import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Render actual production components and their TS dependencies, without a browser
// or a second implementation of their readiness/status conditions.
const require = createRequire(import.meta.url), src = fileURLToPath(new URL('../src/', import.meta.url)), modules = new Map();
function load(path) {
  if (modules.has(path)) return modules.get(path).exports;
  const compiled = { exports: {} }; modules.set(path, compiled);
  const { outputText } = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } });
  const localRequire = name => {
    if (!name.startsWith('@/') && !name.startsWith('.')) return require(name);
    const base = name.startsWith('@/') ? resolve(src, name.slice(2)) : resolve(dirname(path), name);
    const target = [base, base + '.tsx', base + '.ts'].find(existsSync);
    assert.ok(target, `Cannot resolve ${name}`); return load(target);
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, compiled, compiled.exports);
  return compiled.exports;
}
const { default: FirstRun } = load(resolve(src, 'components/first-run-experience.tsx'));
const { default: WaterDemand } = load(resolve(src, 'components/water-demand.tsx'));
const { default: RootZone } = load(resolve(src, 'components/root-zone-balance.tsx'));
const { emptyScenarioDrafts, makeWaterBody } = load(resolve(src, 'lib/scenario-inputs.ts'));
const { confirmedDemoDrafts, DEMO_CONTEXT } = load(resolve(src, 'lib/guided-demo.ts'));
const noop = () => {};
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const fixture = name => JSON.parse(readFileSync(new URL(`../../backend/examples/${name}_assessment_fixture.json`, import.meta.url), 'utf8'));

test('first-run presents explicit assumptions with unchecked consent and disabled launch', () => {
  const props = { open: true, onOpen: noop, onAccepted: noop, onStart: noop, loading: false, progress: '', error: '' };
  for (const accepted of [false, true]) {
    const html = render(FirstRun, { ...props, accepted });
    const label = html.indexOf('Запустить подтверждённый пример');
    const button = html.slice(html.lastIndexOf('<button', label), label).split('>')[0];
    assert.equal(button.includes('disabled'), !accepted);
    assert.equal(/type="checkbox"[^>]*checked=""/.test(html), accepted);
    for (const text of ['SRTM v3', '288 м', 'тестовые предположения', '0.3 / 1.1 / 0.4', '27 мм', '25 мм']) assert.ok(html.includes(text), text);
  }
});

test('loading and API errors stay explicit in the demo, without substituting results', () => {
  const props = { open: true, onOpen: noop, accepted: true, onAccepted: noop, onStart: noop, progress: 'Получаем погоду' };
  const loading = render(FirstRun, { ...props, loading: true, error: '' });
  assert.match(loading, /role="status"/); assert.match(loading, /Получаем погоду/);
  const error = render(FirstRun, { ...props, loading: false, error: 'HTTP 404: route_not_found' });
  assert.match(error, /role="alert"/); assert.match(error, /HTTP 404: route_not_found/);
  assert.doesNotMatch(error, /Пример рассчитан/);
});

test('incomplete ETc produces a short root readiness gate instead of a disabled soil form', () => {
  const water = fixture('water'); water.potential_etc.total_mm = null; water.kc.status = 'unknown';
  const html = render(RootZone, { water, waterRequest: {}, draft: emptyScenarioDrafts().root, onDraft: noop,
    seed: null, onConfigure: noop, onResult: noop });
  assert.match(html, /пока не рассчитано/); assert.match(html, /Настроить культуру Kc/);
  assert.doesNotMatch(html, /<form/); assert.doesNotMatch(html, /Добавить полив/);
});

test('water without height explains the exact missing settings before calling any API', () => {
  const html = render(WaterDemand, { season: fixture('season'), onResult: noop, onRootResult: noop,
    bindings: { drafts: emptyScenarioDrafts(), onWaterDraft: noop, onRootDraft: noop, waterSeed: null, rootSeed: null } });
  for (const text of ['Укажите высоту участка', 'Добавьте источник высоты', 'Подтвердите высоту', 'Сначала подтвердите высоту']) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /<input[^>]*checked=""/);
});

test('nullable water totals distinguish missing weather from missing settings and preserve zero rain', () => {
  const season = fixture('season'), water = fixture('water'), drafts = confirmedDemoDrafts(true);
  const context = { ...DEMO_CONTEXT, start: season.season.sowing_date, end: season.season.end_date };
  const waterRequest = makeWaterBody(context, drafts.water);
  // Synthetic test fixture remains visibly labelled. No fake live-NASA claim.
  water.et0.total_mm = null; water.potential_etc.total_mm = null; water.kc.status = 'unknown';
  water.precipitation.total_mm = 0; water.daily[0].et0_reason_codes = ['missing_or_invalid:WS2M'];
  const { stableKey } = load(resolve(src, 'lib/analysis-session.ts'));
  const html = render(WaterDemand, { season, onResult: noop, onRootResult: noop,
    bindings: { drafts, onWaterDraft: noop, onRootDraft: noop, waterSeed: { key: stableKey(waterRequest), value: water }, rootSeed: null } });
  for (const text of ['Нет полного ряда исходных данных', 'Не рассчитано — нужны настройки', 'Синтетическая тестовая фикстура', '0 <small>мм за период']) assert.ok(html.includes(text), text);
  assert.match(html, /Метод, единицы и ограничения/); assert.match(html, /JSON/);
  assert.doesNotMatch(html, /NaN|undefined/);
});

const { default: ScenarioHighlights } = load(resolve(src, 'components/scenario-highlights.tsx'));
const { default: PlanComparison } = load(resolve(src, 'components/plan-comparison.tsx'));
const { default: Summary } = load(resolve(src, 'components/analysis-summary.tsx'));
const { default: JourneyNavigation } = load(resolve(src, 'components/journey-navigation.tsx'));
const { DepletionChart } = load(resolve(src, 'components/root-zone-balance.tsx'));
const { default: SeasonalAnalysis } = load(resolve(src, 'components/seasonal-analysis.tsx'));
const { default: SourceField } = load(resolve(src, 'components/source-field.tsx'));
const { siteReadiness, currentJourneyStage, groupRequirementReasons, differentPlanMetrics } = load(resolve(src, 'lib/result-presentation.ts'));
function scenarioResult() {
  const scenario = (stress, irrigation) => ({ summary: { stress_days: stress, net_irrigation_total_mm: irrigation,
    initial_dr_mm: 7, final_dr_mm: 12, etc_adj: { total_mm: 32 }, deep_percolation: { total_mm: 0 } },
    coverage: { computed_days: 90, expected_days: 90 } });
  return { scenarios: { rainfed: scenario(17, 0), irrigated: scenario(4, 45) }, differences: { stress_days: -13 },
    soil: { taw_mm: 108, raw_mm: 54, source: 'UI TEST ASSUMPTIONS' } };
}
test('completed demo prioritises result navigation and keeps recalculation secondary', () => {
  const html = render(FirstRun, { open: true, onOpen: noop, accepted: true, onAccepted: noop, onStart: noop,
    loading: false, progress: 'Пример рассчитан', error: '' });
  assert.match(html, /class="rotation-compare-button" href="#climate-water"/);
  assert.match(html, /Повторно рассчитать подтверждённый пример/);
  assert.doesNotMatch(html, /<button class="rotation-compare-button"/);
  assert.match(html, /Все параметры, источники и допущения примера/);
});
test('scenario hierarchy uses arbitrary API counts/difference, preserves zero and unknown', () => {
  const result = scenarioResult(), html = render(ScenarioHighlights, { result });
  for (const text of ['Без орошения', 'С орошением', '17', '4', '45 мм', '0 мм', 'на 13 дн. меньше', 'не измеренное состояние']) assert.ok(html.includes(text), text);
  result.scenarios.rainfed.summary.stress_days = null; result.differences.stress_days = null;
  const missing = render(ScenarioHighlights, { result });
  assert.match(missing, /число дней неизвестно/); assert.match(missing, /Разница дней модельного стресса неизвестна/);
  assert.doesNotMatch(missing, /на 13/); assert.doesNotMatch(missing, /NaN|undefined/);
});
test('chart orientation is explicit and unknown daily values split the line', () => {
  const daily = [0, null, 108].map((dr_end_mm, i) => ({ date: `2025-01-0${i + 1}`, dr_end_mm }));
  const html = render(DepletionChart, { result: { soil: { taw_mm: 108, raw_mm: 54 }, scenarios: { rainfed: { daily }, irrigated: { daily } } } });
  assert.match(html, /Выше линия → больше истощение/); assert.match(html, /RAW — порог начала модельного стресса/);
  assert.match(html, /до дневной ET/); assert.match(html, /мм на конец дня/);
  const path = html.match(/d="([^"]+)" class="root-zone-rainfed"/)[1];
  assert.match(path, /^M65,180\s+M885,25$/); assert.doesNotMatch(path, /L/);
});
test('site action readiness rejects missing/invalid mandatory inputs with a local explanation', () => {
  assert.deepEqual(siteReadiness(DEMO_CONTEXT, true), []);
  for (const [key, value] of [['cropId', ''], ['latitude', ''], ['longitude', '181'], ['start', '2025-02-30'], ['end', '2024-12-31']]) {
    assert.ok(siteReadiness({ ...DEMO_CONTEXT, [key]: value }, true).length, key);
  }
  assert.ok(siteReadiness(DEMO_CONTEXT, false).length);
});
test('navigation keeps native keyboard anchors and chooses the section below its measured offset', () => {
  const html = render(JourneyNavigation, {});
  assert.match(html, /href="#site" aria-current="step"/);
  assert.equal((html.match(/href="#/g) ?? []).length, 4);
  const positions = [{ id: 'site', top: -300 }, { id: 'climate-water', top: 110 }, { id: 'rotation-planner', top: 700 }, { id: 'analysis-summary', top: 1100 }];
  assert.equal(currentJourneyStage(positions, 100), 'site');
  assert.equal(currentJourneyStage(positions, 120), 'climate-water');
  assert.equal(currentJourneyStage(positions, 760), 'rotation-planner');
  assert.equal(currentJourneyStage(positions, 120, true), 'analysis-summary');
});
test('repeated unknown reasons are grouped without losing parameter provenance', () => {
  assert.deepEqual(groupRequirementReasons([{ parameter_id: 'A', reasons: ['unverified', 'missing'] }, { parameter_id: 'B', reasons: ['unverified', 'unverified'] }]),
    [{ reason: 'unverified', parameters: ['A', 'B'] }, { reason: 'missing', parameters: ['A'] }]);
});
const plan = (id, returns, diversity) => ({ plan_id: id, name_ru: id, season_count: 3, indicators: {
  crop_repetition: { status: 'known', adjacent_repeats: [], return_after_intermediate: Array(returns).fill({}) },
  family_repetition: { status: 'unknown', adjacent_repeats: null },
  sequence_diversity: { status: 'known', distinct_crop_count: diversity }, legume_presence: { status: 'known', present: false },
} });
test('plan accents show descriptive known differences only, never an unknown value as zero', () => {
  const plans = [plan('A', 1, 2), plan('B', 0, 3)];
  assert.deepEqual(differentPlanMetrics(plans), ['returns', 'diversity']);
  let html = render(PlanComparison, { plans });
  assert.equal((html.match(/data-different="true"/g) ?? []).length, 4);
  assert.match(html, /не определяют лучший план/);
  plans[1].indicators.sequence_diversity.status = 'unknown';
  html = render(PlanComparison, { plans });
  assert.deepEqual(differentPlanMetrics(plans), ['returns']); assert.match(html, /Нет данных/);
});
test('summary separates observations, conditional scenarios, plan structure and unknowns with full JSON retained', () => {
  const html = render(Summary, { context: DEMO_CONTEXT, cropName: 'Пшеница', season: fixture('season'), water: null, root: null, rotation: null });
  for (const id of ['summary-history', 'summary-water', 'summary-plans', 'summary-unknown']) assert.ok(html.includes(`id="${id}"`));
  assert.match(html, /Экспорт JSON/); assert.match(html, /не является прогнозом/); assert.match(html, /Синтетическая тестовая фикстура/);
});
test('climate highlights two observations with grouped coverage and retains five secondary metrics/daily data', () => {
  const html = render(SeasonalAnalysis, { result: fixture('season'), loading: false, error: null, reused: false, onWaterResult: noop, onRootResult: noop,
    bindings: { drafts: emptyScenarioDrafts(), onWaterDraft: noop, onRootDraft: noop, waterSeed: null, rootSeed: null } });
  assert.equal((html.match(/climate-key-metric/g) ?? []).length, 2);
  for (const text of ['Полнота наблюдений NASA', 'Ещё пять климатических показателей', 'Минимальная температура', 'Ежедневные наблюдения и пропуски']) assert.ok(html.includes(text), text);
});
test('short source caption retains the original editable provenance and URL verbatim', () => {
  const source = 'DEMO: SRTM v3, bilinear DEM estimate, not a site survey https://example.test/?point=31.25,34.79';
  const html = render(SourceField, { label: 'Источник высоты', value: source, onChange: noop, placeholder: '' });
  assert.match(html, /SRTM · пользовательская оценка высоты/); assert.ok(html.includes(source));
  assert.match(html, /<input type="text"/);
});

test('core text tokens meet 4.5:1 contrast for their actual light/dark surfaces', () => {
  const css = readFileSync(resolve(src, 'app/globals.css'), 'utf8');
  const colour = name => css.match(new RegExp('--' + name + ': (#[a-fA-F0-9]{6})'))[1];
  const luminance = hex => {
    const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
    return rgb.reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
  };
  for (const [text, background] of [['ink', 'paper'], ['muted', 'paper'], ['muted', 'surface'], ['surface', 'forest'], ['rust', 'surface']]) {
    const [high, low] = [luminance(colour(text)), luminance(colour(background))].sort((a, b) => b - a);
    assert.ok((high + .05) / (low + .05) >= 4.5, `${text} on ${background}`);
  }
});

test('summary water result is a compact API-driven comparison with links, no large cards or graph', () => {
  const root = scenarioResult();
  const props = { context: DEMO_CONTEXT, cropName: 'Пшеница', season: fixture('season'), water: null, root,
    rotation: { plans: [plan('A', 1, 2), plan('B', 0, 3)] } };
  const html = render(Summary, props);
  for (const text of ['на 13 дн. меньше', '17', '4', '45 мм', '0 мм', '90/90', 'Что остаётся неизвестным', 'Экспорт JSON']) assert.ok(html.includes(text), text);
  for (const anchor of ['#root-zone-results', '#rotation-planner', '#seasonal-analysis']) assert.ok(html.includes(`href="${anchor}"`));
  assert.doesNotMatch(html, /scenario-scorecard|root-zone-chart|class="stress-value/);
  root.scenarios.rainfed.summary.stress_days = null; root.differences.stress_days = null;
  const missing = render(Summary, props);
  assert.match(missing, /Разница дней модельного стресса неизвестна/); assert.match(missing, /Нет данных/);
  assert.doesNotMatch(missing, /NaN|undefined|на 13 дн/);
});

test('root coverage is grouped only when both scenarios have exactly the same coverage', () => {
  const result = scenarioResult();
  let html = render(ScenarioHighlights, { result });
  assert.equal((html.match(/90\/90/g) ?? []).length, 1);
  assert.match(html, /Полнота моделирования обоих сценариев/);
  result.scenarios.irrigated.coverage.computed_days = 87;
  html = render(ScenarioHighlights, { result });
  assert.match(html, /Модель: 87\/90/); assert.match(html, /Модель: 90\/90/);
  assert.doesNotMatch(html, /Полнота моделирования обоих сценариев/);
});

test('dark scenario disclosure declares readable normal/hover/focus text colours on its existing surface', () => {
  const styles = readFileSync(resolve(src, 'app/design-v1.css'), 'utf8');
  const tokens = readFileSync(resolve(src, 'app/globals.css'), 'utf8');
  const declaration = selector => {
    const start = styles.indexOf(selector + ' {'); assert.ok(start >= 0, selector);
    return styles.slice(start, styles.indexOf('}', start));
  };
  const resolveColour = text => {
    const raw = text.match(/(?:^|[;{])\s*(?:background|color):\s*([^;]+)/)[1].trim();
    const variable = raw.match(/^var\(--([\w-]+)\)$/);
    return variable ? tokens.match(new RegExp('--' + variable[1] + ': (#[a-fA-F0-9]{6})'))[1] : raw;
  };
  const luminance = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
    .reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
  const background = resolveColour(declaration('.design-v1.ux-polish .scenario-irrigated'));
  for (const selector of ['.design-v1.ux-polish .scenario-irrigated .scenario-details > summary', '.design-v1.ux-polish .scenario-irrigated .scenario-details > summary:is(:hover, :focus)']) {
    const colour = resolveColour(declaration(selector));
    const [high, low] = [luminance(colour), luminance(background)].sort((a, b) => b - a);
    assert.ok((high + .05) / (low + .05) >= 4.5, selector);
  }
});
