export const maxDuration = 60;

export async function POST(request: Request) {
  let body: unknown;
  try { body = await request.json(); }
  catch { return Response.json({ error: "invalid_input", detail: "Request body must be valid JSON." }, { status: 400 }); }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return Response.json({ error: "invalid_input", detail: "Request body must be a JSON object." }, { status: 400 });
  }
  const backendUrl = process.env.ORBITFARM_BACKEND_URL?.trim().replace(/\/+$/, "");
  if (!backendUrl) return Response.json({ error: "backend_not_configured", detail: "Set ORBITFARM_BACKEND_URL." }, { status: 503 });
  let upstream: Response;
  let text: string;
  try {
    upstream = await fetch(`${backendUrl}/api/water/assess`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      cache: "no-store", signal: AbortSignal.timeout(55_000),
    });
    text = await upstream.text();
  } catch {
    return Response.json({ error: "backend_unavailable", detail: "Unable to reach the backend." }, { status: 502 });
  }
  if (upstream.status === 404) {
    return Response.json({ error: "water_route_not_found", detail: "Backend не содержит /api/water/assess. Перезапустите актуальный FastAPI.", upstream_status: 404 }, { status: 404 });
  }
  try {
    const headers: HeadersInit = {};
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) headers["Retry-After"] = retryAfter;
    return Response.json(JSON.parse(text), { status: upstream.status, headers });
  } catch {
    return Response.json({ error: "invalid_backend_response", detail: "Backend returned invalid JSON." }, { status: 502 });
  }
}
