import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

async function moduleFrom(path) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const { AnalysisSession, AnalysisError, contextKey, currentPublication, stableKey, requestJSON, analysisErrorText } = await moduleFrom('../src/lib/analysis-session.ts');
const { buildExperienceSummary, describePlan, displayKnown, seasonClimateContext } = await moduleFrom('../src/lib/experience-summary.ts');
const context = { latitude: '31.25', longitude: '34.79', start: '2025-01-01', end: '2025-03-31', cropId: 'wheat' };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

for (const [field, value] of [['latitude', '32'], ['longitude', '35'], ['start', '2025-01-02'], ['end', '2025-03-30'], ['cropId', 'chickpea']]) {
  test(`changing ${field} cannot expose a previous result or late publication`, async () => {
    const oldScope = contextKey(context), nextScope = contextKey({ ...context, [field]: value });
    assert.notEqual(oldScope, nextScope);
    const old = new AnalysisSession(oldScope), pending = deferred();
    const running = old.run(() => pending.promise);
    old.reset();
    const current = new AnalysisSession(nextScope);
    pending.resolve({ value: { et0: 233 }, reused: false });
    assert.equal(await running, null);
    assert.equal(current.getSnapshot().result, null);
    assert.equal(old.getSnapshot().result, null);
    assert.equal(currentPublication({ scope: oldScope, value: { et0: 233 } }, nextScope), null);
  });
}

test('water and root assumptions are part of the actual request scope', async () => {
  const body = { elevation: { value_m: 288, source: 'DEM assumption', confirmed: true }, kc: { mid: 1.1 }, soil: { p: .5 }, irrigation: [{ date: '2025-01-15', net_mm: 25 }] };
  for (const changed of [
    { ...body, elevation: { ...body.elevation, value_m: 281 } },
    { ...body, elevation: { ...body.elevation, confirmed: false } },
    { ...body, kc: { mid: 1.2 } }, { ...body, soil: { p: .4 } },
    { ...body, irrigation: [{ date: '2025-01-16', net_mm: 25 }] },
    { ...body, irrigation: [{ date: '2025-01-15', net_mm: 30 }] },
  ]) {
    assert.notEqual(stableKey(body), stableKey(changed));
    const session = new AnalysisSession(stableKey(body));
    await session.run(async () => ({ value: { total_mm: 100 }, reused: false }));
    session.reset();
    assert.equal(session.getSnapshot().result, null);
  }
  const scope = contextKey(context);
  assert.equal(currentPublication({ scope, assumptions: stableKey(body), value: 'old root' }, scope, stableKey({ ...body, kc: { mid: 1.2 } })), null);
});

test('late failure cannot overwrite a newer success; cancellation fences callbacks', async () => {
  const session = new AnalysisSession('same scope'), old = deferred();
  const first = session.run(() => old.promise);
  await session.run(async () => ({ value: { current: true }, reused: false }));
  old.reject(new AnalysisError(502, 'nasa_upstream_unavailable', 'offline'));
  assert.equal(await first, null);
  assert.deepEqual(session.getSnapshot().result, { current: true });
  assert.equal(session.getSnapshot().error, null);
  const next = deferred(); const running = session.run(() => next.promise);
  session.cancel(); next.resolve({ value: 'retired component', reused: false });
  assert.equal(await running, null);
});

test('same request reuses success and coalesces in-flight work; changed inputs fetch again', async (t) => {
  let calls = 0; const response = deferred();
  t.mock.method(globalThis, 'fetch', async () => { calls++; await response.promise; return Response.json({ total_mm: null, actual_water_balance: null }); });
  const body = { point: context, kc: { mid: null } };
  const first = requestJSON('/test/experience-cache', body), second = requestJSON('/test/experience-cache', body);
  response.resolve();
  const [a, b] = await Promise.all([first, second]);
  assert.equal(calls, 1); assert.equal(a.reused, false); assert.equal(b.reused, true);
  assert.equal((await requestJSON('/test/experience-cache', body)).reused, true);
  assert.equal(calls, 1);
  assert.deepEqual(a.value, { total_mm: null, actual_water_balance: null });
  await requestJSON('/test/experience-cache', { ...body, kc: { mid: 1.1 } });
  assert.equal(calls, 2);
});

test('expired responses fetch again, and returning to old inputs does not auto-restore results', async (t) => {
  let time = 1000, calls = 0;
  t.mock.method(Date, 'now', () => time);
  t.mock.method(globalThis, 'fetch', async () => { calls++; return Response.json({ ok: true }); });
  await requestJSON('/test/experience-ttl', context);
  const fresh = new AnalysisSession(contextKey(context));
  assert.equal(fresh.getSnapshot().result, null);
  time += 5 * 60_000 + 1;
  assert.equal((await requestJSON('/test/experience-ttl', context)).reused, false);
  assert.equal(calls, 2);
});

test('errors clear current output, retain HTTP status and are never cached', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return Response.json({ error: 'root_zone_inputs_incomplete', detail: 'no ETc' }, { status: 422 }); });
  const session = new AnalysisSession('error');
  for (let i = 0; i < 2; i++) assert.equal(await session.run(() => requestJSON('/test/experience-errors', {})), null);
  assert.equal(calls, 2); assert.equal(session.getSnapshot().error.status, 422);
  assert.equal(session.getSnapshot().result, null);
  assert.match(analysisErrorText(session.getSnapshot().error), /HTTP 422/);
  assert.match(analysisErrorText(new AnalysisError(404, 'route_not_found', 'Not Found')), /HTTP 404/);
  t.mock.method(globalThis, 'fetch', async () => new Response('invalid json'));
  assert.equal(await session.run(() => requestJSON('/test/experience-invalid', {})), null);
  assert.equal(session.getSnapshot().error.code, 'invalid_backend_response');
});

const season = JSON.parse(readFileSync(new URL('../../backend/examples/season_assessment_fixture.json', import.meta.url), 'utf8'));
const water = JSON.parse(readFileSync(new URL('../../backend/examples/water_assessment_fixture.json', import.meta.url), 'utf8'));

test('summary preserves unknown/null and genuine zero, without a plan recommendation', () => {
  const empty = buildExperienceSummary({ season: null, water: null, root: null, rotation: null });
  assert.equal(empty.observations.length, 0); assert.equal(empty.scenarios.length, 0);
  assert.match(empty.unknown.join(' '), /неизвестны/);
  assert.equal(displayKnown(0, 'мм'), '0 мм'); assert.match(displayKnown(null), /unknown/);
  const missing = structuredClone(water); missing.et0.total_mm = null; missing.elevation.used_m = null;
  missing.potential_etc.total_mm = null; missing.kc.status = 'unknown';
  const summary = buildExperienceSummary({ season, water: missing, root: null, rotation: null });
  assert.match(summary.scenarios.join(' '), /unknown/);
  assert.match(summary.unknown.join(' '), /Kc/);
  assert.match(summary.observations.join(' '), /Синтетическая/);
  assert.doesNotMatch(JSON.stringify(summary), /рекомендуем выбрать|лучший план|прогноз урожая/i);
});

test('rotation adapter copies server-computed historical values, skipping unknown full-period metrics', () => {
  const input = structuredClone(season);
  input.metrics.total_precipitation.value = null;
  const context = seasonClimateContext(input);
  assert.deepEqual(context.historical_period, input.historical_period);
  assert.deepEqual(context.location, input.location);
  assert.equal(context.observations.some((row) => row.parameter_id === 'CLIM_007'), false);
  assert.equal(context.observations.find((row) => row.parameter_id === 'CLIM_001').value, input.metrics.mean_temperature.value);
});

test('plan explanation distinguishes unknown indicators from zero repeats and keeps evidence limits', () => {
  const plan = { name_ru: 'План A', season_count: 3, indicators: {
    crop_repetition: { status: 'known', adjacent_repeats: [] },
    family_repetition: { status: 'unknown', adjacent_repeats: null },
    legume_presence: { status: 'known', present: false },
    sequence_diversity: { status: 'known', distinct_crop_count: 3 },
  } };
  const text = describePlan(plan);
  assert.match(text, /подряд — 0/); assert.match(text, /семейства подряд — неизвестно/);
  assert.match(text, /бобовое звено — нет/); assert.match(text, /3 из 3/);
});
