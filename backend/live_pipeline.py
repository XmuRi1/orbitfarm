"""NASA POWER -> OrbitFarm farm profile -> ten-crop exploratory assessment.

Pure standard library. An actual NASA network request is made when cache is absent.
We never silently substitute a synthetic fixture if the upstream API is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

from nasa_power import fetch_power_daily, convert_power, merge_farm, power_url
from scoring import score_all_crops, read_json, validate_farm

ROOT = Path(__file__).resolve().parent
CROPS = read_json(ROOT / "data" / "crops.json")
CACHE_DIR = ROOT / "cache" / "nasa_power"
MAX_PERIOD_DAYS = 366
CACHE_TTL_DAYS = 14
FIRST_POWER_DATE = date(1981, 1, 1)


class NASAUpstreamError(RuntimeError):
    """The NASA service returned content that cannot be used by the pipeline."""


def _valid_float(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be a number between {minimum} and {maximum}")
    number = float(value)
    if not math.isfinite(number) or not (minimum <= number <= maximum):
        raise ValueError(f"{label} must be a finite number between {minimum} and {maximum}")
    return number


def validate_request(body: dict) -> dict:
    """Bound all inputs before making a potentially expensive upstream call."""
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    lat = _valid_float(body.get("latitude"), "latitude", -90, 90)
    lon = _valid_float(body.get("longitude"), "longitude", -180, 180)
    try:
        start = date.fromisoformat(body["start"])
        end = date.fromisoformat(body["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("start and end must be valid YYYY-MM-DD dates") from exc
    if start < FIRST_POWER_DATE or end >= date.today() or end < start:
        raise ValueError("Choose a historical range between 1981-01-01 and yesterday, start <= end")
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError(f"Maximum period is {MAX_PERIOD_DAYS} days per request")

    mode = body.get("mode", "demo")
    if mode not in ("demo", "strict"):
        raise ValueError("mode must be demo or strict")
    stage = body.get("growth_stage", None)
    if stage not in (None, "active_growth"):
        raise ValueError("growth_stage must be null or active_growth")
    farm_id = body.get("farm_id", "nasa_selected_point")
    if not isinstance(farm_id, str) or not (1 <= len(farm_id) <= 80):
        raise ValueError("farm_id must be a nonempty string, at most 80 characters")
    soil = body.get("soil_observations", [])
    if not isinstance(soil, list) or len(soil) > 30:
        raise ValueError("soil_observations must be an array with at most 30 entries")
    if any(not isinstance(row, dict) or not str(row.get("parameter_id", "")).startswith("SOIL_") for row in soil):
        raise ValueError("soil_observations can contain only SOIL_* observation objects")
    validate_farm({"farm_id": farm_id, "location": {"latitude": lat, "longitude": lon},
                   "observations": soil}, CROPS)
    return {"latitude": lat, "longitude": lon, "start": start.isoformat(),
            "end": end.isoformat(), "mode": mode, "growth_stage": stage,
            "farm_id": farm_id, "soil_observations": soil}


def _cache_path(params: dict, cache_dir: Path) -> Path:
    # Exact point and date range, not approximate grid cells, to avoid confusing source locations.
    fields = {k: params[k] for k in ("latitude", "longitude", "start", "end")}
    key = hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()[:28]
    return cache_dir / f"power_{key}.json"


def get_nasa_data(params: dict, *, fetcher: Callable = fetch_power_daily,
                  cache_dir: Path | None = None) -> tuple[dict, str, bool]:
    """Fetch from official API, or reuse recent earlier genuine response."""
    cache_dir = CACHE_DIR if cache_dir is None else Path(cache_dir)
    path = _cache_path(params, cache_dir)
    url = power_url(params["latitude"], params["longitude"], params["start"], params["end"])
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            fetched_on = datetime.fromisoformat(saved["fetched_at"])
            fresh = datetime.now(timezone.utc) - fetched_on <= timedelta(days=CACHE_TTL_DAYS)
            if fresh and saved.get("request_url") == url and isinstance(saved.get("payload"), dict):
                payload = saved["payload"]
                if payload.get("_synthetic_test_fixture"):
                    raise ValueError("synthetic data cannot be reused as live cache")
                return payload, url, True
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    try:
        payload, response_url = fetcher(params["latitude"], params["longitude"], params["start"], params["end"])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise NASAUpstreamError("NASA returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("_synthetic_test_fixture"):
        raise NASAUpstreamError("Live NASA request returned invalid or synthetic content")
    properties = payload.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("parameter"), dict):
        raise NASAUpstreamError("NASA response had no usable daily observations")
    cache_doc = {"fetched_at": datetime.now(timezone.utc).isoformat(),
                 "request_url": url, "payload": payload}
    # Failure to persist cache must not prevent using fetched real data.
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache_doc), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return payload, response_url, False


def assess_nasa(body: dict, *, fetcher: Callable = fetch_power_daily,
                cache_dir: Path | None = None) -> dict:
    params = validate_request(body)
    nasa, url, cached = get_nasa_data(params, fetcher=fetcher, cache_dir=cache_dir)
    try:
        farm = convert_power(nasa, lat=params["latitude"], lon=params["longitude"],
                             start=params["start"], end=params["end"],
                             stage=params["growth_stage"], farm_id=params["farm_id"], source_url=url)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise NASAUpstreamError("NASA response has an invalid structure or unsupported data") from exc
    if not farm["observations"]:
        raise NASAUpstreamError("NASA did not provide parameters with recognizable units/coverage")
    if params["soil_observations"]:
        addition = {"farm_id": params["farm_id"], "demo_only": False,
                    "location": farm["location"], "observations": params["soil_observations"]}
        farm = merge_farm(farm, addition)
    try:
        assessment = score_all_crops(farm, CROPS, mode=params["mode"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise NASAUpstreamError("NASA observations could not be validated for assessment") from exc
    warnings = list(farm.get("warnings", []))
    if params["growth_stage"]:
        warnings.append("Growth stage is user-assigned; a single period/stage cannot be assumed valid for all crops.")
    else:
        warnings.append("No crop growth stage assigned: stage-dependent crop factors remain unscored.")
    if not params["soil_observations"]:
        warnings.append("No soil observations supplied. NASA POWER does not measure the farm's soil pH or texture.")
    warnings.extend(farm.get("data_gaps", []))
    return {
        "pipeline": "orbitfarm_nasa_power_to_10_crop_assessment",
        "status": "historical_climate_processed",
        "is_live_source": True,
        "source_is_synthetic": False,
        "retrieved_from_cache": cached,
        "source_url": url,
        "historical_period": {"start":params["start"], "end":params["end"]},
        "not_a_forecast": True,
        "farm": farm,
        "assessment": assessment,
        "warnings": warnings,
    }
