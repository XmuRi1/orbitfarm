import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

async function load(path) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const { confirmedDemoDrafts, DEMO_CONTEXT, runGuidedDemo } = await load('../src/lib/guided-demo.ts');
const { reconcileDrafts, editWaterDraft, makeWaterBody, makeRootBody, waterReadiness, waterMetricStatus } = await load('../src/lib/scenario-inputs.ts');
const preset = () => confirmedDemoDrafts(true);
const bodies = () => { const p = preset(); const water = makeWaterBody(DEMO_CONTEXT, p.water); return { water, root: makeRootBody(water, p.root) }; };

test('demo requires explicit grouped acceptance before any API call', async () => {
  assert.throws(() => confirmedDemoDrafts(false), /подтвердите/);
  let calls = 0;
  await assert.rejects(runGuidedDemo(false, bodies(), async () => { calls++; }, () => true, () => {}), /not accepted/);
  assert.equal(calls, 0);
});

test('demo contains inputs only, with exact sourced height, user Kc, soil and irrigation', () => {
  const { water, root } = bodies();
  assert.deepEqual(DEMO_CONTEXT, { latitude: '31.25', longitude: '34.79', cropId: 'wheat', start: '2025-01-01', end: '2025-03-31' });
  assert.equal(water.elevation.value_m, 288);
  assert.match(water.elevation.source, /SRTM v3.*not a site survey/);
  assert.equal(water.elevation.confirmed, true);
  assert.deepEqual([water.kc_scenario.kc_initial, water.kc_scenario.kc_mid, water.kc_scenario.kc_end], [.3, 1.1, .4]);
  assert.deepEqual(water.kc_scenario.stage_lengths_days, { initial: 20, development: 25, mid: 25, late: 20 });
  assert.equal(water.kc_scenario.acknowledge_assumptions, true);
  assert.match(water.kc_scenario.source, /USER ASSUMPTIONS/);
  assert.deepEqual([root.soil.theta_fc, root.soil.theta_wp, root.soil.zr_m, root.soil.p], [.3, .12, .6, .5]);
  assert.match(root.soil.source, /not measured/);
  assert.deepEqual(root.initial_depletion, { dr_mm: 27 });
  assert.deepEqual(root.irrigation, ['2025-01-15', '2025-02-15', '2025-03-15'].map(date => ({ date, net_mm: 25 })));
  assert.equal(Object.values(root.assumptions).every(v => v === true), true);
  assert.deepEqual(waterReadiness(preset().water, 90), { et0: [], etc: [] });
  for (const name of ['et0', 'daily', 'scenarios', 'actual_water_balance']) assert.equal(name in root, false);
});

test('demo publishes actual responses sequentially through existing routes', async () => {
  const calls = [], published = [], responses = [1, 2, 3].map(n => ({ server_value: n, source_is_synthetic: false }));
  const input = bodies();
  const ok = await runGuidedDemo(true, input, async (url, body) => {
    calls.push({ url, body }); return { value: responses[calls.length - 1], reused: false };
  }, () => true, (stage, value) => published.push({ stage, value }));
  assert.equal(ok, true);
  assert.deepEqual(calls.map(c => c.url), ['/api/season/assess', '/api/water/assess', '/api/root-zone/compare']);
  assert.deepEqual(calls[0].body, { crop_id: 'wheat', latitude: 31.25, longitude: 34.79, sowing_date: '2025-01-01', end_date: '2025-03-31' });
  assert.equal(calls[1].body, input.water); assert.equal(calls[2].body, input.root);
  assert.deepEqual(published.map(p => p.stage), ['season', 'water', 'root']);
  published.forEach((p, i) => assert.equal(p.value, responses[i]));
});

test('demo never falls back after an API failure or synthetic/unknown source', async () => {
  for (const source of [true, undefined]) {
    let calls = 0, published = 0;
    await assert.rejects(runGuidedDemo(true, bodies(), async () => { calls++; return { value: { source_is_synthetic: source } }; }, () => true, () => published++), /NASA/);
    assert.equal(calls, 1); assert.equal(published, 0);
  }
  let calls = 0;
  await assert.rejects(runGuidedDemo(true, bodies(), async () => { calls++; throw new Error('HTTP 404 route_not_found'); }, () => true, () => {}), /HTTP 404/);
  assert.equal(calls, 1);
});

test('context or assumption edit during demo fences late response and later stages', async () => {
  for (const cancelAfterStage of [0, 1, 2]) {
    let current = true, calls = 0, published = 0;
    await assert.rejects(runGuidedDemo(true, bodies(), async () => {
      calls++; if (calls === cancelAfterStage + 1) current = false;
      return { value: { source_is_synthetic: false } };
    }, () => current, () => published++), /cancelled/);
    assert.equal(calls, cancelAfterStage + 1); assert.equal(published, cancelAfterStage);
  }
});

test('compatible rerun and equivalent coordinate formatting preserve drafts', () => {
  const draft = preset();
  assert.equal(reconcileDrafts(DEMO_CONTEXT, { ...DEMO_CONTEXT }, draft), draft);
  assert.equal(reconcileDrafts(DEMO_CONTEXT, { ...DEMO_CONTEXT, latitude: '31.2500' }, draft), draft);
  assert.notEqual(preset().root.events, preset().root.events);
});

test('new point removes all site assumptions and confirmations', () => {
  for (const field of ['latitude', 'longitude']) {
    const next = reconcileDrafts(DEMO_CONTEXT, { ...DEMO_CONTEXT, [field]: '32' }, preset());
    assert.equal(next.water.elevation, ''); assert.equal(next.water.confirmed, false);
    assert.equal(next.water.kcConfirmed, false); assert.equal(next.root.form.fc, '');
    assert.equal(next.root.form.confirmed, false); assert.deepEqual(next.root.events, []);
  }
});

test('crop change keeps unconfirmed site drafts but clears crop and root calendar; returning cannot resurrect them', () => {
  const nextContext = { ...DEMO_CONTEXT, cropId: 'chickpea' };
  const next = reconcileDrafts(DEMO_CONTEXT, nextContext, preset());
  assert.equal(next.water.elevation, '288'); assert.equal(next.water.confirmed, false);
  assert.equal(next.water.kcInitial, ''); assert.equal(next.water.useKc, false); assert.equal(next.water.kcConfirmed, false);
  assert.equal(next.root.form.fc, '0.30'); assert.equal(next.root.form.wp, '0.12'); assert.equal(next.root.form.zr, '');
  assert.equal(next.root.form.confirmed, false); assert.deepEqual(next.root.events, []);
  const back = reconcileDrafts(nextContext, DEMO_CONTEXT, next);
  assert.equal(back.water.kcConfirmed, false); assert.equal(back.water.kcMid, '');
  assert.equal(back.root.form.depletion, '');
});

test('period edits retain drafts and out-of-period events, revoke season confirmations and flag mismatched phases', () => {
  const draft = preset(), nextContext = { ...DEMO_CONTEXT, start: '2025-02-01' };
  const next = reconcileDrafts(DEMO_CONTEXT, nextContext, draft);
  assert.equal(next.water.elevation, '288'); assert.equal(next.water.confirmed, true);
  assert.equal(next.water.kcMid, '1.1'); assert.equal(next.water.kcConfirmed, false);
  assert.equal(next.root.form.depletion, '27'); assert.equal(next.root.form.confirmed, false);
  assert.deepEqual(next.root.events, draft.root.events);
  assert.ok(waterReadiness(next.water, 59).etc.some(reason => reason.includes('59')));
  const back = reconcileDrafts(nextContext, DEMO_CONTEXT, next);
  assert.equal(back.water.kcConfirmed, false); assert.equal(back.root.form.confirmed, false);
  assert.equal(waterReadiness(back.water, 90).etc.length, 1);
});

test('editing height or Kc revokes only its explicit acknowledgement', () => {
  for (const key of ['elevation', 'elevationSource']) {
    const next = editWaterDraft(preset().water, key, 'changed');
    assert.equal(next.confirmed, false); assert.equal(next.kcConfirmed, true);
  }
  for (const key of ['kcMid', 'midDays', 'kcSource', 'useKc']) {
    const next = editWaterDraft(preset().water, key, key === 'useKc' ? false : '1');
    assert.equal(next.confirmed, true); assert.equal(next.kcConfirmed, false);
  }
});

const water = JSON.parse(readFileSync(new URL('../../backend/examples/water_assessment_fixture.json', import.meta.url), 'utf8'));
test('UI statuses separate absent settings, absent NASA, model limitations, real zero and scenario results', () => {
  assert.equal(waterMetricStatus('et0', null), 'not_calculated');
  const missingHeight = structuredClone(water); missingHeight.elevation.used_m = null; missingHeight.et0.total_mm = null;
  assert.equal(waterMetricStatus('et0', missingHeight), 'not_calculated');
  const missingKc = structuredClone(water); missingKc.kc.status = 'unknown'; missingKc.potential_etc.total_mm = null;
  assert.equal(waterMetricStatus('etc', missingKc), 'not_calculated');
  const missing = structuredClone(water); missing.et0.total_mm = null; missing.daily[0].et0_reason_codes = ['missing_or_invalid:WS2M'];
  assert.equal(waterMetricStatus('et0', missing), 'missing_data');
  const domain = structuredClone(water); domain.et0.total_mm = null; domain.daily.forEach(d => { d.et0_reason_codes = ['fao56_domain_error:polar']; });
  assert.equal(waterMetricStatus('et0', domain), 'model_unavailable');
  const zero = structuredClone(water); zero.et0.total_mm = 0; zero.precipitation.total_mm = 0;
  assert.equal(waterMetricStatus('et0', zero), 'with_assumptions');
  assert.equal(waterMetricStatus('rain', zero), 'observed');
  zero.precipitation.total_mm = null; assert.equal(waterMetricStatus('rain', zero), 'missing_data');
});
