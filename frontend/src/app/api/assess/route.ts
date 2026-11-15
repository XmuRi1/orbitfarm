function errorResponse(error: string, detail: string, status: number) {
  return Response.json({ error, detail }, { status });
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return errorResponse("invalid_input", "Request body must be valid JSON.", 400);
  }

  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return errorResponse("invalid_input", "Request body must be a JSON object.", 400);
  }

  const backendUrl = process.env.ORBITFARM_BACKEND_URL?.trim().replace(/\/+$/, "");
  if (!backendUrl) {
    return errorResponse(
      "backend_not_configured",
      "Set ORBITFARM_BACKEND_URL for the Next.js server.",
      503,
    );
  }

  let upstream: Response;
  let text: string;
  try {
    upstream = await fetch(`${backendUrl}/api/nasa/assess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(55_000),
    });
    text = await upstream.text();
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unable to reach the backend.";
    return errorResponse("backend_unavailable", detail, 502);
  }

  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return errorResponse("invalid_backend_response", "Backend returned invalid JSON.", 502);
  }

  return Response.json(payload, { status: upstream.status });
}