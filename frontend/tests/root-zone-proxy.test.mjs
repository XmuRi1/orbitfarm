import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/app/api/root-zone/compare/route.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { POST } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const body = { crop_id: 'wheat', soil: { theta_fc: .3, theta_wp: .12, theta_unit: 'm3/m3', zr_m: .6, p: .5 }, irrigation: [{ date: '2025-01-15', net_mm: 25 }] };
const request = () => new Request('http://localhost/api/root-zone/compare', { method: 'POST', body: JSON.stringify(body) });
function configure(t) {
  const previous = process.env.ORBITFARM_BACKEND_URL;
  process.env.ORBITFARM_BACKEND_URL = 'http://127.0.0.1:8000/';
  t.after(() => { if (previous === undefined) delete process.env.ORBITFARM_BACKEND_URL; else process.env.ORBITFARM_BACKEND_URL = previous; });
}

test('forwards explicit scenario unchanged without computing soil estimates in proxy', async (t) => {
  configure(t);
  const expected = { mode: 'scenario_not_measured', scenarios: { rainfed: { daily: [{ dr_end_mm: null, reason_codes: ['previous_root_zone_state_unknown'] }] } }, actual_water_balance: null };
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8000/api/root-zone/compare');
    assert.deepEqual(JSON.parse(options.body), body);
    assert.equal(options.cache, 'no-store');
    return Response.json(expected);
  });
  const response = await POST(request());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expected);
});

for (const status of [400, 422, 429, 502]) {
  test(`preserves upstream ${status} and completeness/error diagnostics`, async (t) => {
    configure(t);
    const expected = { error: status === 422 ? 'root_zone_inputs_incomplete' : 'upstream_error', missing_requirements: ['complete_potential_etc_series_required'], used_synthetic_fallback: false };
    t.mock.method(globalThis, 'fetch', async () => Response.json(expected, { status, headers: { 'Retry-After': '15' } }));
    const response = await POST(request());
    assert.equal(response.status, status);
    assert.equal(response.headers.get('retry-after'), '15');
    assert.deepEqual(await response.json(), expected);
  });
}

test('404 is a routing error, not a NASA outage', async (t) => {
  configure(t);
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>Not Found</html>', { status: 404 }));
  const response = await POST(request());
  assert.equal(response.status, 404);
  assert.equal((await response.json()).error, 'root_zone_route_not_found');
});

test('invalid JSON, unavailable backend and invalid upstream JSON remain distinct', async (t) => {
  configure(t);
  for (const raw of ['[]', 'null', '{invalid']) {
    assert.equal((await POST(new Request('http://localhost/api/root-zone/compare', { method: 'POST', body: raw }))).status, 400);
  }
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw Error('offline'); });
  assert.equal((await (await POST(request())).json()).error, 'backend_unavailable');
  fetch.mock.mockImplementation(async () => new Response('invalid json'));
  assert.equal((await (await POST(request())).json()).error, 'invalid_backend_response');
  delete process.env.ORBITFARM_BACKEND_URL;
  assert.equal((await POST(request())).status, 503);
});
