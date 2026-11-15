"use client";

import type { FormEvent } from "react";
import { AlertTriangle, ArrowDownToLine, ChevronDown, Droplets, LoaderCircle, Plus, X } from "lucide-react";
import type { WaterAssessment } from "@/lib/water-contracts";
import type { RootZoneComparison, RootZoneDay } from "@/lib/root-zone-contracts";
import { analysisErrorText, requestJSON, stableKey } from "@/lib/analysis-session";
import { useAnalysisSession } from "@/lib/use-analysis-session";
import { makeRootBody, type RootDraft, type RootFormDraft, type IrrigationDraft } from "@/lib/scenario-inputs";

const format = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const show = (value: number | null) => value === null ? "—" : format.format(value);
const fields = [
  { key: "fc", label: "θFC · полевая влагоёмкость, м³/м³" },
  { key: "wp", label: "θWP · влажность завядания, м³/м³" },
  { key: "zr", label: "Эффективная глубина корней Zr, м" },
  { key: "p", label: "Допустимое истощение p, доля < 1" },
] as const;

function DepletionChart({ result }: { result: RootZoneComparison }) {
  const a = result.scenarios.rainfed.daily;
  const b = result.scenarios.irrigated.daily;
  const { taw_mm: taw, raw_mm: raw } = result.soil;
  const x = (i: number) => 54 + i / Math.max(1, a.length - 1) * 610;
  const y = (dr: number) => 25 + dr / taw * 180;
  function path(rows: RootZoneDay[]) {
    let active = false;
    return rows.map((row, i) => {
      if (row.dr_end_mm === null) { active = false; return ""; }
      const command = active ? "L" : "M"; active = true;
      return `${command}${x(i)},${y(row.dr_end_mm)}`;
    }).join(" ");
  }
  return <figure className="root-zone-figure">
    <figcaption>Ежедневное истощение Dr · конец дня, мм</figcaption>
    <div className="root-zone-chart" tabIndex={0} role="region" aria-label="График истощения корневой зоны">
      <svg viewBox="0 0 720 250" role="img" aria-label="Модельные Dr сценариев A и B и линия RAW">
        <title>Истощение влаги: Rainfed и Irrigated</title>
        <desc>Ноль соответствует полевой влагоёмкости, TAW — исчерпанию доступной воды. Стресс оценивается после поступления воды, до дневной ET; его дни указаны в карточках.</desc>
        {[0, taw].map((v) => <g key={v}><line x1="54" x2="664" y1={y(v)} y2={y(v)} className="root-zone-grid" /><text x="47" y={y(v) + 4} textAnchor="end">{show(v)}</text></g>)}
        <line x1="54" x2="664" y1={y(raw)} y2={y(raw)} className="root-zone-raw" />
        <text x="670" y={y(raw) + 4}>RAW</text>
        <path d={path(a)} className="root-zone-rainfed" />
        <path d={path(b)} className="root-zone-irrigated" />
        {a.length === 1 && a[0].dr_end_mm !== null && <circle cx={x(0)} cy={y(a[0].dr_end_mm)} r="3" fill="var(--rust)" />}
        {b.length === 1 && b[0].dr_end_mm !== null && <circle cx={x(0)} cy={y(b[0].dr_end_mm)} r="3" fill="var(--forest)" />}
        <text x="54" y="229">{a[0]?.date}</text><text x="664" y="229" textAnchor="end">{a.at(-1)?.date}</text>
      </svg>
    </div>
    <p className="field-hint"><span className="root-zone-key-a">A · без полива</span> · <span className="root-zone-key-b">B · заданный полив</span> · пунктир: RAW = {show(raw)} мм. TAW = {show(taw)} мм.</p>
  </figure>;
}

export default function RootZoneBalance({ water, waterRequest, onResult, draft, onDraft, seed, onConfigure }: {
  water: WaterAssessment; waterRequest: Record<string, unknown>; onResult: (value: RootZoneComparison | null, key?: string) => void;
  draft: RootDraft; onDraft: (draft: RootDraft) => void;
  seed: { key: string; value: RootZoneComparison } | null; onConfigure: (stage: "height" | "kc") => void;
}) {
  const { form, events } = draft;
  const body = makeRootBody(waterRequest, draft), bodyKey = stableKey(body);
  const request = useAnalysisSession<RootZoneComparison>(bodyKey);
  const result = request.result ?? (seed?.key === bodyKey ? seed.value : null);
  const loading = request.loading;
  const error = analysisErrorText(request.error);
  const missing = [
    water.et0.days_available !== water.et0.days_expected || water.et0.total_mm === null ? "Нужен полный ряд ET₀: проверьте высоту и наблюдения." : "",
    water.potential_etc.days_available !== water.potential_etc.days_expected || water.potential_etc.total_mm === null ? "Нужна потенциальная ETc за каждый день: задайте Kc и календарь фаз в форме выше." : "",
    water.precipitation.days_available !== water.precipitation.days_expected || water.precipitation.total_mm === null ? "Нужны осадки за каждый день; пропуски не заполняются." : "",
  ].filter(Boolean);
  const number = (text: string) => text.trim() === "" ? NaN : Number(text);
  const fc = number(form.fc), wp = number(form.wp), zr = number(form.zr), p = number(form.p), depletion = number(form.depletion);
  const taw = 1000 * (fc - wp) * zr;
  const validSoil = [fc, wp, zr, p, depletion, taw].every(Number.isFinite) && 0 <= wp && wp < fc && fc <= 1 && zr > 0 && 0 <= p && p < 1
    && depletion >= 0 && depletion <= (form.initialMode === "mm" ? taw : 1);
  const validEvents = events.every((event) => event.date >= water.historical_period.start && event.date <= water.historical_period.end && Number.isFinite(number(event.net)) && number(event.net) >= 0)
    && new Set(events.map((event) => event.date)).size === events.length;
  const canRun = missing.length === 0 && validSoil && validEvents && form.source.trim() !== "" && form.confirmed;
  function clear() { request.reset(); onResult(null); }
  function update<K extends keyof RootFormDraft>(key: K, value: RootFormDraft[K]) {
    onDraft({ form: { ...form, [key]: value, confirmed: key === "confirmed" ? Boolean(value) : false }, events }); clear();
  }
  function setEvents(change: (current: IrrigationDraft[]) => IrrigationDraft[]) {
    onDraft({ form: { ...form, confirmed: false }, events: change(events) });
  }
  function changeEvent(i: number, key: keyof IrrigationDraft, value: string) {
    setEvents((current) => current.map((event, index) => index === i ? { ...event, [key]: value } : event)); clear();
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canRun) return;
    onResult(null);
    const value = await request.run(() => requestJSON<RootZoneComparison>("/api/root-zone/compare", body));
    if (value) onResult(value, bodyKey);
  }

  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "orbitfarm-root-zone-scenarios.json"; link.click(); URL.revokeObjectURL(url);
  }
  if (missing.length) return <aside className="readiness-note root-zone-gate" aria-label="Готовность почвенного сценария">
    <strong>Шаг 4 · Влага в почве — пока не рассчитано</strong>
    <ul>{missing.map((line) => <li key={line}>{line}</li>)}</ul>
    {water.elevation.used_m === null && <button className="download-button" type="button" onClick={() => onConfigure("height")}>Указать высоту и источник</button>}
    {water.kc.status === "unknown" && <button className="download-button" type="button" onClick={() => onConfigure("kc")}>Настроить культуру Kc</button>}
    <a href="#climate-water">Проверить полноту погоды</a>
  </aside>;
  return <details className="provenance-details season-details root-zone-section" open>
    <summary>Шаг 4 · Баланс влаги в почве <ChevronDown size={15} /></summary>
    <div className="season-detail-body">
      <p className="field-hint">Сравним один участок без полива (A) и с вашим чистым поливом (B). Погода и культура одинаковы. Параметры ниже — ваши допущения, не измеренная влажность поля.</p>
      {missing.length > 0 && <div className="score-honesty"><AlertTriangle size={16} /><p><strong>Сравнение пока недоступно</strong>{missing.map((reason) => <span key={reason}>{reason}</span>)}</p></div>}
      <details className="provenance-details scenario-settings" open={!result}><summary>Почва, начальное состояние и поливы · изменить настройки <ChevronDown size={15} /></summary>
      <form onSubmit={submit}>
        <fieldset className="season-fields water-controls" disabled={loading || missing.length > 0}>
          <legend className="sr-only">Пользовательские параметры почвы и сценария полива</legend>
          <div className="water-kc-fields">{fields.map((field) => <label key={field.key} className="field-label"><span>{field.label}</span><input type="number" min="0" max={field.key === "zr" ? undefined : "1"} step="any" required value={form[field.key]} onChange={(event) => update(field.key, event.target.value)} placeholder="Не задано" /></label>)}</div>
          {Number.isFinite(taw) && taw > 0 && p >= 0 && p < 1 && <p className="field-hint">Для введённых параметров: TAW = {show(taw)} мм, RAW = {show(p * taw)} мм. Начальное Dr задаётся относительно полевой влагоёмкости.</p>}
          <div className="water-elevation-fields">
            <label className="field-label"><span>Начальное истощение Dr</span><input type="number" min="0" step="any" required value={form.depletion} onChange={(event) => update("depletion", event.target.value)} placeholder="Не задано" /></label>
            <label className="field-label"><span>Единица начального состояния</span><select value={form.initialMode} onChange={(event) => update("initialMode", event.target.value)}><option value="mm">мм истощения</option><option value="fraction">Доля TAW, от 0 до 1</option></select></label>
          </div>
          <label className="field-label"><span>Источник почвы, корней, p и начального состояния</span><input type="text" required value={form.source} onChange={(event) => update("source", event.target.value)} placeholder="Замеры или явно условный пользовательский сценарий" /></label>
          <p className="field-hint">Полив B — чистая глубина в мм, поступающая в корневую зону, без пересчёта КПД. Пустой график явно означает нулевой полив.</p>
          {events.map((entry, i) => <div className="root-zone-event" key={i}>
            <label className="field-label"><span>Дата полива {i + 1}</span><input type="date" required min={water.historical_period.start} max={water.historical_period.end} value={entry.date} onChange={(event) => changeEvent(i, "date", event.target.value)} /></label>
            <label className="field-label"><span>Чистая глубина, мм</span><input type="number" required min="0" step="any" value={entry.net} onChange={(event) => changeEvent(i, "net", event.target.value)} /></label>
            <button className="download-button" type="button" aria-label={`Удалить полив ${i + 1}`} onClick={() => { setEvents((current) => current.filter((_, index) => index !== i)); clear(); }}><X size={16} /></button>
          </div>)}
          <button className="download-button root-zone-add" type="button" disabled={events.length >= water.et0.days_expected} onClick={() => { setEvents((current) => [...current, { date: "", net: "" }]); clear(); }}><Plus size={14} /> Добавить полив</button>
          <p className="field-hint">Допущения: RO=0, CR=0; все осадки инфильтрируются. Дождь и полив — до расчёта Ks/ET, оставшийся избыток — DP в тот же день после ET. Zr и p фиксированы на весь период.</p>
          <label className="water-check"><input type="checkbox" checked={form.confirmed} onChange={(event) => update("confirmed", event.target.checked)} /><span>Подтверждаю пользовательские параметры, начальное состояние, график полива и перечисленные допущения сценария.</span></label>
          {!validSoil && <p className="field-hint">Требуется 0 ≤ θWP &lt; θFC ≤ 1, Zr &gt; 0, 0 ≤ p &lt; 1 и начальное Dr от 0 до TAW (либо доля от 0 до 1).</p>}
          {!validEvents && <p className="field-hint">Заполните даты и глубины полива. Даты должны быть уникальными и внутри периода; глубины — неотрицательными.</p>}
          <button className="rotation-compare-button season-submit" type="submit" disabled={loading || !canRun}>{loading ? <LoaderCircle size={16} className="spin" /> : <Droplets size={16} />}{loading ? "Моделируем…" : "Сравнить сценарии"}</button>
        </fieldset>
      </form>
      </details>
      {loading && <p className="field-hint" role="status">Проверяем исходный ряд и рассчитываем два ежедневных баланса.</p>}
      {error && <div className="error-message" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>}
      {result && <div className="root-zone-result" aria-live="polite">
        <p className="calculation-state">Рассчитано с пользовательскими допущениями · фактическая влажность поля неизвестна</p>
        <div className="root-zone-cards">{(["rainfed", "irrigated"] as const).map((key) => {
          const scenario = result.scenarios[key], s = scenario.summary;
          return <article className="metric-cell" key={key}><h4>{key === "rainfed" ? "A · Rainfed" : "B · Irrigated"}</h4><p>Дни с Ks &lt; 1: <strong>{show(s.stress_days)}</strong></p><p>Модельная ETc_adj: <strong>{show(s.etc_adj.total_mm)} мм</strong></p><p>Dr: {show(s.initial_dr_mm)} → {show(s.final_dr_mm)} мм</p><p>Чистый полив: {show(s.net_irrigation_total_mm)} мм</p><p>Глубокое просачивание: {show(s.deep_percolation.total_mm)} мм</p><small className="metric-coverage">Модель: {scenario.coverage.computed_days}/{scenario.coverage.expected_days} дней</small></article>;
        })}</div>
        <p className="field-hint">B − A: ETc_adj {show(result.differences.etc_adj_total_mm)} мм; дней стресса {show(result.differences.stress_days)}; конечное Dr {show(result.differences.final_dr_mm)} мм; полив {show(result.differences.net_irrigation_total_mm)} мм; DP {show(result.differences.deep_percolation_total_mm)} мм.</p>
        <p className="field-hint">NASA: {result.coverage.nasa.observations.available_values}/{result.coverage.nasa.observations.expected_values} наблюдений. ET₀: {result.coverage.et0.days_available}/{result.coverage.et0.days_expected} дней. Потенциальная ETc: {result.coverage.potential_etc.days_available}/{result.coverage.potential_etc.days_expected} дней.</p>
        <DepletionChart result={result} />
        <details className="provenance-details"><summary>Ежедневные значения и метод <ChevronDown size={15} /></summary><div className="season-detail-body">
          <p className="field-hint">{result.method.policy} · {result.soil.source}</p>
          {(["rainfed", "irrigated"] as const).map((key) => <div key={key}><h4>{key === "rainfed" ? "A · Rainfed" : "B · Irrigated"}</h4><div className="season-daily" role="region" tabIndex={0} aria-label={`Ежедневный баланс ${key}`}><table><thead><tr>{["Дата", "Dr начало, мм", "Dr конец, мм", "Дождь, мм", "Полив, мм", "DP, мм", "ETc, мм", "Ks", "ETc_adj, мм", "Статус"].map((heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead><tbody>{result.scenarios[key].daily.map((day) => <tr key={day.date}><td>{day.date}</td><td>{show(day.dr_start_mm)}</td><td>{show(day.dr_end_mm)}</td><td>{show(day.precipitation_mm)}</td><td>{show(day.net_irrigation_mm)}</td><td>{show(day.deep_percolation_mm)}</td><td>{show(day.potential_etc_mm)}</td><td>{show(day.ks)}</td><td>{show(day.etc_adj_mm)}</td><td>{day.stress_status === "unknown" ? "Неизвестно: см. JSON" : day.stress_status === "modelled_stress" ? "Модельный стресс" : "Без модельного стресса"}</td></tr>)}</tbody></table></div></div>)}
          <ul className="season-limitations">{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul><a href={result.method.reference} target="_blank" rel="noreferrer">FAO-56, глава 8</a><button className="download-button" type="button" onClick={download}><ArrowDownToLine size={14} /> JSON сценариев</button>
        </div></details>
      </div>}
      <details className="provenance-details"><summary>Ограничения почвенной модели</summary><p className="field-hint">Уравнение 81 приближённо корректирует всю ETc единым Ks, хотя физически стресс прежде всего ограничивает транспирацию. Это не оценка урожайности или гарантированная норма полива. Фактический баланс участка остаётся неизвестным.</p></details>
    </div>
  </details>;
}
