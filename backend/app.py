from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from math import ceil
from typing import Any
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api_server import CROPS, _validate_assess_body
from live_pipeline import NASAUpstreamError, assess_nasa
from scoring import score_all_crops

MAX_REQUEST_BYTES = 500_000
RATE_WINDOW_SECONDS = 60.0
MAX_RATE_LIMIT_KEYS = 2048


def _configured_rate_limit() -> int:
    try:
        value = int(os.environ.get("ORBITFARM_RATE_LIMIT_PER_MINUTE", "8"))
    except ValueError:
        return 8
    return min(max(value, 1), 120)


class RequestInputError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class SlidingWindowLimiter:
    """Best-effort per-instance request limit; not a shared serverless store."""

    def __init__(self, limit: int, window_seconds: float = RATE_WINDOW_SECONDS):
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def consume(self, client_key: str) -> int | None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            if len(self._requests) >= MAX_RATE_LIMIT_KEYS:
                for key, timestamps in list(self._requests.items()):
                    while timestamps and timestamps[0] <= cutoff:
                        timestamps.popleft()
                    if not timestamps:
                        del self._requests[key]
                if len(self._requests) >= MAX_RATE_LIMIT_KEYS:
                    oldest_key = min(self._requests, key=lambda key: self._requests[key][0])
                    del self._requests[oldest_key]

            timestamps = self._requests.setdefault(client_key, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                return max(1, ceil(timestamps[0] + self.window_seconds - now))
            timestamps.append(now)
            return None


nasa_rate_limiter = SlidingWindowLimiter(_configured_rate_limit())
app = FastAPI(
    title="OrbitFarm API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _error(code: str, detail: str, status_code: int, headers: dict[str, str] | None = None):
    return JSONResponse(
        {"error": code, "detail": detail},
        status_code=status_code,
        headers=headers,
    )


async def _json_object(request: Request) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise RequestInputError(400, "invalid_content_length", "Content-Length must be an integer") from exc
        if declared_length <= 0 or declared_length > MAX_REQUEST_BYTES:
            raise RequestInputError(413, "invalid_payload_size", "Request body size is invalid")

    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_REQUEST_BYTES:
            raise RequestInputError(413, "invalid_payload_size", "Request body exceeds 500000 bytes")
        chunks.append(chunk)

    if body_size == 0:
        raise RequestInputError(413, "invalid_payload_size", "Request body is empty")
    try:
        body = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestInputError(400, "invalid_input", "Request body must contain valid UTF-8 JSON") from exc
    if not isinstance(body, dict):
        raise RequestInputError(400, "invalid_input", "Request body must be a JSON object")
    return body


def _client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:128] or "unknown"
    if request.client and request.client.host:
        return request.client.host[:128]
    return "unknown"


@app.get("/health")
async def health():
    return {"ok": True, "mode": "vercel_serverless", "nasa_reachability": "not_checked"}


@app.get("/api/crops")
async def crops():
    return {
        "crops": [
            {"crop_id": crop["crop_id"], "name_ru": crop["name_ru"], "name_en": crop["name_en"]}
            for crop in CROPS["crops"]
        ]
    }


@app.get("/api/nasa/status")
async def nasa_status():
    return {
        "integration": "NASA POWER daily point",
        "route": "POST /api/nasa/assess",
        "history_only": True,
        "cache_days": 14,
        "cache_persistence": "best_effort_ephemeral",
        "nasa_reachability": "not_checked",
    }


@app.post("/api/assess")
async def assess(request: Request):
    try:
        body = await _json_object(request)
        _validate_assess_body(body)
        return await run_in_threadpool(
            score_all_crops,
            body["farm"],
            CROPS,
            mode=body.get("mode", "strict"),
        )
    except RequestInputError as exc:
        return _error(exc.code, exc.detail, exc.status_code)
    except (ValueError, KeyError, TypeError) as exc:
        return _error("invalid_input", str(exc), 400)


@app.post("/api/nasa/assess")
async def nasa_assess(request: Request):
    try:
        body = await _json_object(request)
    except RequestInputError as exc:
        return _error(exc.code, exc.detail, exc.status_code)

    retry_after = nasa_rate_limiter.consume(_client_key(request))
    if retry_after is not None:
        return _error(
            "rate_limited",
            "Too many NASA requests. Try again after the rate limit window.",
            429,
            {"Retry-After": str(retry_after)},
        )

    try:
        return await run_in_threadpool(assess_nasa, body)
    except (NASAUpstreamError, URLError, HTTPError, TimeoutError, OSError, RuntimeError) as exc:
        return JSONResponse(
            {
                "error": "nasa_upstream_unavailable",
                "detail": str(exc),
                "used_synthetic_fallback": False,
            },
            status_code=502,
        )
    except (ValueError, KeyError, TypeError) as exc:
        return _error("invalid_input", str(exc), 400)
