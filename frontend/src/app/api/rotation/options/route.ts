export async function GET() {
  const backendUrl = process.env.ORBITFARM_BACKEND_URL?.trim().replace(/\/+$/, "");
  if (!backendUrl) {
    return Response.json(
      { error: "backend_not_configured", detail: "Set ORBITFARM_BACKEND_URL for the Next.js server." },
      { status: 503 },
    );
  }

  let upstream: Response;
  let text: string;
  try {
    upstream = await fetch(`${backendUrl}/api/rotation/options`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    text = await upstream.text();
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unable to reach the backend.";
    return Response.json({ error: "backend_unavailable", detail }, { status: 502 });
  }

  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return Response.json(
      { error: "invalid_backend_response", detail: "Backend returned invalid JSON." },
      { status: 502 },
    );
  }
  return Response.json(payload, { status: upstream.status });
}
