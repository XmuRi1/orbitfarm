/** Opt-in HTTP workflow against a production Next server and actual FastAPI.
 * Uses the agreed Beersheba historical scenario, not synthetic replacements.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import ts from 'typescript';

const base = process.env.ORBITFARM_HTTP_TEST_BASE_URL;
assert.ok(base, 'Set ORBITFARM_HTTP_TEST_BASE_URL to the local Next server');
const source = readFileSync(new URL('../src/lib/experience-summary.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { seasonClimateContext, buildExperienceSummary } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const fixture = JSON.parse(readFileSync(new URL('../../backend/tests/fixtures/beersheba_2025_q1_real.json', import.meta.url), 'utf8'));
const rootBody = JSON.parse(readFileSync(new URL('../../backend/examples/root_zone_beersheba_scenario.json', import.meta.url), 'utf8'));
async function post(path, body, status = 200) {
  const response = await fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const payload = await response.json();
  assert.equal(response.status, status, JSON.stringify(payload));
  return payload;
}
const html = await (await fetch(base)).text();
for (const id of ['site', 'climate-water', 'rotation-planner', 'analysis-summary']) assert.ok(html.includes(`id="${id}"`), `Missing section ${id}`);
assert.equal((html.match(/aria-label="Дата начала"/g) ?? []).length, 1);
assert.equal((html.match(/aria-label="Дата окончания"/g) ?? []).length, 1);
const season = await post('/api/season/assess', fixture.request);
assert.equal(season.coverage.available_values, 540);
const climate = seasonClimateContext(season);
assert.equal(new Set(climate.observations.map((o) => o.parameter_id)).size, climate.observations.length);
const rotation = await post('/api/rotation/compare', { climate_context: climate, plans: [
  { plan_id: 'custom_a', crop_ids: ['wheat', 'chickpea', 'wheat'] },
  { plan_id: 'custom_b', crop_ids: ['wheat', 'chickpea', 'sorghum'] },
] });
assert.equal(rotation.climate_context.status, 'historical_context_only');
assert.equal(rotation.climate_context.future_season_conditions, 'unknown');
assert.equal(rotation.plans[0].indicators.sequence_diversity.distinct_crop_count, 2);
assert.equal(rotation.plans[1].indicators.sequence_diversity.distinct_crop_count, 3);
const water = await post('/api/water/assess', fixture.request);
assert.ok(Math.abs(water.et0.total_mm - 233.26354978636815) < 1e-9);
const root = await post('/api/root-zone/compare', rootBody);
assert.equal(root.actual_water_balance, null);
assert.equal(root.scenarios.rainfed.summary.stress_days, 31);
assert.equal(root.scenarios.irrigated.summary.stress_days, 8);
const summary = buildExperienceSummary({ season, water, root, rotation });
assert.equal(summary.plans.length, 2);
assert.equal(summary.scenarios.length, 3);
assert.match(summary.unknown.join(' '), /не является прогнозом/);
assert.doesNotMatch(JSON.stringify(summary), /рекомендуем выбрать|лучший план/i);
await post('/api/root-zone/compare', { ...rootBody, kc_scenario: null }, 422);
await post('/api/season/assess', { ...fixture.request, end_date: '2024-12-31' }, 400);
if (process.env.ORBITFARM_HTTP_TEST_OUTPUT) writeFileSync(process.env.ORBITFARM_HTTP_TEST_OUTPUT, JSON.stringify({ season, water, root, rotation, summary }, null, 2));
console.log('PASS: four SSR sections, one shared period, season -> rotation context, water/root scenarios, deterministic summary, HTTP 400/422.');
