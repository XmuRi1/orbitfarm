/** Opt-in real HTTP verification of the same demo orchestration/builders used by Home.
 * Start production Next connected to actual FastAPI. No mock NASA or result fixture.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import ts from 'typescript';

async function load(path) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const { DEMO_CONTEXT, confirmedDemoDrafts, runGuidedDemo } = await load('../src/lib/guided-demo.ts');
const { makeWaterBody, makeRootBody, reconcileDrafts, waterReadiness } = await load('../src/lib/scenario-inputs.ts');
const base = process.env.ORBITFARM_HTTP_TEST_BASE_URL;
assert.ok(base, 'Set ORBITFARM_HTTP_TEST_BASE_URL');
const preset = confirmedDemoDrafts(true), waterBody = makeWaterBody(DEMO_CONTEXT, preset.water);
const rootBody = makeRootBody(waterBody, preset.root), stages = {};
const html = await (await fetch(base)).text();
assert.ok(html.includes('Попробовать на примере Беэр-Шевы'));
assert.ok(html.includes('id="first-run"'));
// Acceptance is false on first render; the launch button must initially be disabled.
const launchLabel = html.indexOf('Запустить подтверждённый пример');
assert.ok(launchLabel > 0);
assert.match(html.slice(html.lastIndexOf('<button', launchLabel), launchLabel).split('>')[0], /disabled=""/);
const post = async (url, body) => {
  const response = await fetch(base + url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const value = await response.json(); assert.equal(response.status, 200, JSON.stringify(value));
  return { value };
};
await runGuidedDemo(true, { water: waterBody, root: rootBody }, post, () => true, (stage, value) => { stages[stage] = value; });
const { season, water, root } = stages;
assert.equal(season.source_is_synthetic, false); assert.equal(water.source_is_synthetic, false); assert.equal(root.source_is_synthetic, false);
assert.equal(season.coverage.available_values, 540);
assert.equal(water.coverage.observations.available_values, 810);
assert.equal(water.et0.days_available, 90); assert.equal(water.potential_etc.days_available, 90);
assert.ok(Math.abs(water.et0.total_mm - 233.26354978636815) < 1e-9);
assert.ok(Math.abs(water.potential_etc.total_mm - 176.8946371276623) < 1e-9);
assert.ok(Math.abs(water.precipitation.total_mm - 76.18) < 1e-9);
assert.equal(water.coverage.cloud_ratio_bounded_days, 1);
assert.equal(root.actual_water_balance, null);
assert.equal(root.scenarios.rainfed.summary.stress_days, 31);
assert.equal(root.scenarios.irrigated.summary.stress_days, 8);
assert.equal(root.scenarios.irrigated.summary.net_irrigation_total_mm, 75);
assert.equal(root.scenarios.rainfed.coverage.computed_days, 90);
assert.equal(root.scenarios.irrigated.coverage.computed_days, 90);
assert.match(water.kc.scenario.source, /USER ASSUMPTIONS/);
assert.match(root.soil.source, /not measured/);
// A repeated seasonal run keeps compatible drafts and obtains a server response again.
assert.equal(reconcileDrafts(DEMO_CONTEXT, DEMO_CONTEXT, preset), preset);
await post('/api/season/assess', { crop_id: 'wheat', latitude: 31.25, longitude: 34.79, sowing_date: '2025-01-01', end_date: '2025-03-31' });
// Crop/period changes retain no scenario confirmation. ET0 can still be requested independently.
const changedContext = { ...DEMO_CONTEXT, cropId: 'chickpea' };
const changed = reconcileDrafts(DEMO_CONTEXT, changedContext, preset);
const independent = (await post('/api/water/assess', makeWaterBody(changedContext, changed.water))).value;
assert.equal(independent.et0.total_mm, null); assert.equal(independent.potential_etc.total_mm, null);
const shorter = { ...DEMO_CONTEXT, end: '2025-03-30' };
assert.ok(waterReadiness(reconcileDrafts(DEMO_CONTEXT, shorter, preset).water, 89).etc.length > 0);
if (process.env.ORBITFARM_HTTP_TEST_OUTPUT) writeFileSync(process.env.ORBITFARM_HTTP_TEST_OUTPUT, JSON.stringify({ inputs: { waterBody, rootBody }, ...stages, changed_crop: independent }, null, 2));
console.log(JSON.stringify({ ok: true, source: 'real NASA POWER via existing cache/API', et0: water.et0.total_mm, etc: water.potential_etc.total_mm,
  precipitation: water.precipitation.total_mm, stress_days_A_B: [31, 8], nasa_cache: [season.retrieved_from_cache, water.retrieved_from_cache, root.retrieved_from_cache] }));
