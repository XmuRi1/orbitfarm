import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

// Test the actual route handler without adding a frontend test framework.
const source = readFileSync(new URL('../src/app/api/season/assess/route.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { POST } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const body = { crop_id: 'wheat', latitude: 31.25, longitude: 34.79, sowing_date: '2025-01-01', end_date: '2025-01-05' };
const request = () => new Request('http://localhost/api/season/assess', { method: 'POST', body: JSON.stringify(body) });

function configure(t) {
  const previous = process.env.ORBITFARM_BACKEND_URL;
  process.env.ORBITFARM_BACKEND_URL = 'http://127.0.0.1:8000/';
  t.after(() => {
    if (previous === undefined) delete process.env.ORBITFARM_BACKEND_URL;
    else process.env.ORBITFARM_BACKEND_URL = previous;
  });
}

for (const upstreamBody of ['{"detail":"Not Found"}', '<html>Not Found</html>']) {
  test(`outdated backend 404 remains a routing error: ${upstreamBody}`, async (t) => {
    configure(t);
    t.mock.method(globalThis, 'fetch', async () => new Response(upstreamBody, { status: 404 }));
    const response = await POST(request());
    assert.equal(response.status, 404);
    const error = await response.json();
    assert.equal(error.error, 'season_route_not_found');
    assert.equal(error.upstream_status, 404);
    assert.match(error.detail, /FastAPI/);
  });
}

test('forwards the exact season request and successful response', async (t) => {
  configure(t);
  const expected = { pipeline: 'orbitfarm_seasonal_climate_v1', suitability_score_0_100: null };
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8000/api/season/assess');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), body);
    return Response.json(expected);
  });
  const response = await POST(request());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expected);
});

test('preserves NASA errors and rate-limit Retry-After', async (t) => {
  configure(t);
  const expected = { error: 'nasa_upstream_unavailable', used_synthetic_fallback: false };
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(expected, { status: 502 }));
  const failure = await POST(request());
  assert.equal(failure.status, 502);
  assert.deepEqual(await failure.json(), expected);
  fetch.mock.mockImplementation(async () => Response.json({ error: 'rate_limited' }, { status: 429, headers: { 'Retry-After': '23' } }));
  const limited = await POST(request());
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('retry-after'), '23');
});

test('network failure and invalid backend JSON have separate errors', async (t) => {
  configure(t);
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw new Error('offline'); });
  const unavailable = await POST(request());
  assert.equal(unavailable.status, 502);
  assert.equal((await unavailable.json()).error, 'backend_unavailable');
  fetch.mock.mockImplementation(async () => new Response('not json'));
  const malformed = await POST(request());
  assert.equal(malformed.status, 502);
  assert.equal((await malformed.json()).error, 'invalid_backend_response');
});
