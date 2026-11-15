import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

const { outputText } = ts.transpileModule(readFileSync(new URL('../src/lib/reveal-details.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { revealDetailsFromLink } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

function surface(t, found = true) {
  const calls = [], frames = [];
  const form = { pH: '6.4', activeGrowth: false, elevationConfirmed: true, kcConfirmed: true, soilConfirmed: false };
  class Details {
    open = false; isConnected = true;
    querySelector(selector) {
      assert.equal(selector, ':scope > summary');
      return { focus: options => { assert.equal(this.open, true); calls.push(['focus', options]); } };
    }
    scrollIntoView(options) { calls.push(['scroll', options]); }
  }
  const target = new Details();
  const globals = {
    HTMLDetailsElement: Details,
    document: { getElementById: id => { assert.equal(id, 'site-expert'); return found ? target : null; } },
    window: { location: { hash: '#climate-water' }, history: { pushState: (_state, _title, hash) => { calls.push(['history', hash]); globals.window.location.hash = hash; } } },
    requestAnimationFrame: callback => { frames.push(callback); return frames.length; },
  };
  for (const [key, value] of Object.entries(globals)) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => { if (previous) Object.defineProperty(globalThis, key, previous); else delete globalThis[key]; });
  }
  const activation = overrides => ({ button: 0, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; calls.push(['preventDefault']); }, ...overrides });
  return { target, form, calls, frames, activation };
}

test('expert action opens before focusing, then scrolls after layout without mutating any form draft', t => {
  const { target, form, calls, frames, activation } = surface(t);
  const before = structuredClone(form), event = activation();
  revealDetailsFromLink(event, 'site-expert');
  assert.equal(target.open, true); assert.equal(event.defaultPrevented, true);
  assert.deepEqual(calls, [['preventDefault'], ['history', '#site-expert'], ['focus', { preventScroll: true }]]);
  assert.equal(frames.length, 1); frames.shift()();
  assert.deepEqual(calls.at(-1), ['scroll', { block: 'start', behavior: 'auto' }]);
  assert.deepEqual(form, before);
  revealDetailsFromLink(activation(), 'site-expert');
  assert.equal(target.open, true); assert.equal(calls.filter(call => call[0] === 'history').length, 1);
});

test('modified clicks and missing targets retain native link behaviour', t => {
  const { target, calls, frames, activation } = surface(t);
  for (const modifiers of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }, { defaultPrevented: true }]) {
    revealDetailsFromLink(activation(modifiers), 'site-expert');
  }
  t.mock.method(globalThis.document, 'getElementById', () => null);
  const missing = activation(); revealDetailsFromLink(missing, 'site-expert');
  assert.equal(missing.defaultPrevented, false);
  assert.equal(target.open, false); assert.deepEqual(calls, []); assert.deepEqual(frames, []);
});

test('a detached expert section is not scrolled into view after navigation away', t => {
  const { target, calls, frames, activation } = surface(t);
  revealDetailsFromLink(activation(), 'site-expert'); target.isConnected = false; frames.shift()();
  assert.equal(calls.some(call => call[0] === 'scroll'), false);
});
