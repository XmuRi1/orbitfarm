import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/app/api/water/assess/route.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { POST } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const body = { crop_id: 'wheat', latitude: 31.25, longitude: 34.79, sowing_date: '2025-01-01', end_date: '2025-01-05', elevation: null, kc_scenario: null };
const request = () => new Request('http://localhost/api/water/assess', { method: 'POST', body: JSON.stringify(body) });
function configure(t) {
  const previous = process.env.ORBITFARM_BACKEND_URL;
  process.env.ORBITFARM_BACKEND_URL = 'http://127.0.0.1:8000/';
  t.after(() => { if (previous === undefined) delete process.env.ORBITFARM_BACKEND_URL; else process.env.ORBITFARM_BACKEND_URL = previous; });
}

test('forwards unknown height/Kc unchanged, never inventing water estimates', async (t) => {
  configure(t);
  const expected = { et0: { total_mm: null }, potential_etc: { total_mm: null }, actual_water_balance: null };
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8000/api/water/assess');
    assert.deepEqual(JSON.parse(options.body), body);
    return Response.json(expected);
  });
  const response = await POST(request());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expected);
});

test('preserves cloud bounds diagnostics, completeness and user Kc metadata', async (t) => {
  configure(t);
  const expected = {
    method: { policy: 'fao56_pm_asce2005_cloud_bounds' },
    coverage: { cloud_ratio_bounded_days: 1, observations: { available_values: 810, expected_values: 810 } },
    kc: { status: 'user_assumption' },
    daily: [{ date: '2025-03-07', et0_mm: 1.6105044280988265, etc_mm: 1.7715548709087094,
      quality_flags: ['cloud_ratio_bounded_asce2005'], etc_quality_flags: ['cloud_ratio_bounded_asce2005'],
      cloud_correction: { rs_rso_raw: 0.22589915952401016, rs_rso_used: 0.3, bounded: true, reason: 'rs_rso_below_0_3' } }],
    actual_water_balance: null,
  };
  t.mock.method(globalThis, 'fetch', async () => Response.json(expected));
  const response = await POST(request());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expected);
});

for (const text of ['{"detail":"Not Found"}', '<html>Not Found</html>']) {
  test(`keeps old-backend HTTP 404 separate from NASA errors: ${text}`, async (t) => {
    configure(t);
    t.mock.method(globalThis, 'fetch', async () => new Response(text, { status: 404 }));
    const response = await POST(request());
    assert.equal(response.status, 404);
    assert.equal((await response.json()).error, 'water_route_not_found');
  });
}

test('preserves NASA failure and shared Retry-After', async (t) => {
  configure(t);
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ error: 'rate_limited' }, { status: 429, headers: { 'Retry-After': '15' } }));
  const limited = await POST(request());
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('retry-after'), '15');
  const expected = { error: 'nasa_upstream_unavailable', used_synthetic_fallback: false };
  fetch.mock.mockImplementation(async () => Response.json(expected, { status: 502 }));
  const unavailable = await POST(request());
  assert.equal(unavailable.status, 502);
  assert.deepEqual(await unavailable.json(), expected);
});

test('invalid requests and missing configuration do not contact upstream', async (t) => {
  configure(t);
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw new Error('must not call'); });
  for (const raw of ['[]', 'null', '{invalid']) {
    assert.equal((await POST(new Request('http://localhost/api/water/assess', { method: 'POST', body: raw }))).status, 400);
  }
  delete process.env.ORBITFARM_BACKEND_URL;
  assert.equal((await POST(request())).status, 503);
  assert.equal(fetch.mock.callCount(), 0);
});
