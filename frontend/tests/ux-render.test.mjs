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
