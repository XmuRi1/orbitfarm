"use client";

import { useState, type FormEvent } from "react";
import { AlertTriangle, ArrowDownToLine, ArrowRight, ChevronDown, Droplets, LoaderCircle } from "lucide-react";
import type { SeasonAssessment } from "@/lib/season-contracts";
import type { WaterAssessment } from "@/lib/water-contracts";
import RootZoneBalance from "@/components/root-zone-balance";
import type { RootZoneComparison } from "@/lib/root-zone-contracts";
import { analysisErrorText, requestJSON, stableKey } from "@/lib/analysis-session";
import { useAnalysisSession } from "@/lib/use-analysis-session";
import { editWaterDraft, makeWaterBody, waterReadiness, waterMetricStatus, type ScenarioBindings, type WaterDraft } from "@/lib/scenario-inputs";

const format = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const show = (value: number | null) => value === null ? "—" : format.format(value);
const reasonLabels: Record<string, string> = {
  known_sourced_elevation_required: "Нужна известная высота участка с источником.",
  elevation_value_source_and_user_confirmation_required: "Укажите высоту, источник и подтвердите их.",
  kc_and_stage_calendar_unknown: "Kc и календарь стадий неизвестны: ETc не рассчитана.",
  kc_values_missing: "Не все коэффициенты Kc заданы.", stage_calendar_missing: "Календарь фаз неполный.",
  kc_user_assumptions_not_acknowledged: "Пользовательские допущения Kc не подтверждены.", kc_source_not_supplied: "Не указан источник сценария Kc.",
  stage_calendar_does_not_cover_exact_requested_period: "Сумма длительностей фаз должна совпадать с выбранным периодом.",
  et0_not_available_for_every_day: "ET₀ доступна не за все дни: полная сумма неизвестна.",
  etc_not_available_for_every_day: "ETc доступна не за все дни: полная сумма неизвестна.",
  et0_unknown_for_day: "ET₀ за этот день неизвестна.", precipitation_not_available_for_every_day: "В осадках есть пропуски: полная сумма неизвестна.",
};
function explain(reason: string) {
  if (reason.startsWith("missing_or_invalid:")) return `Нет совместимого наблюдения ${reason.split(":")[1]}.`;
  if (reason.startsWith("fao56_domain_error:Eq. 39 outside")) return "Обязательные наблюдения присутствуют, но текущая обработка радиационного расчёта (ур. 39) не даёт ET₀ за этот день.";
  if (reason.startsWith("fao56_domain_error:")) return "Наблюдения вне применимой области уравнений FAO-56; замена формулы не используется.";
  return reasonLabels[reason] ?? "Расчёт неизвестен: проверьте исходные данные и допущения.";
}
function WaterMetrics({ result }: { result: WaterAssessment }) {
  return <div className="metric-grid">{([
    { kind: "et0", title: "Испаряемость погоды · ET₀", total: result.et0 },
    { kind: "rain", title: "Осадки NASA", total: result.precipitation },
    { kind: "etc", title: "Потребность культуры · ETc", total: result.potential_etc },
  ] as const).map(({ kind, title, total }) => {
    const status = waterMetricStatus(kind, result);
    const label = { observed: "Получены исторические наблюдения", with_assumptions: "Рассчитано по введённым допущениям", not_calculated: "Не рассчитано — нужны настройки", missing_data: "Нет полного ряда исходных данных", model_unavailable: "Расчёт недоступен для этих данных" }[status];
    return <article className={`metric-cell${total.total_mm === null ? " is-missing" : ""}`} key={kind}>
      <div className="metric-top"><Droplets size={16} /><span>{total.days_available}/{total.days_expected} дней</span></div>
      <p>{title}</p>{total.total_mm !== null ? <span className="metric-value">{show(total.total_mm)} <small>мм за период</small></span> : <span className="metric-empty">{label}</span>}
      {total.total_mm !== null && <small className="metric-coverage">{label}</small>}
      {status === "not_calculated" && <p>{kind === "etc" && result.elevation.used_m !== null ? "Задайте Kc и четыре фазы; подтвердите сценарий культуры." : "Укажите высоту с источником и подтвердите их."}</p>}
      {status === "missing_data" && <p>Погоды за отдельные дни не хватает. Пропуски не заполняются.</p>}
      {status === "model_unavailable" && <p>Проверьте диагностические причины в экспертных подробностях.</p>}
      {total.total_mm === null && total.observed_total_mm !== null && <p>Только доступные дни: {show(total.observed_total_mm)} мм</p>}
    </article>;
  })}</div>;
}
type ScenarioField = "kcInitial" | "kcMid" | "kcEnd" | "initialDays" | "developmentDays" | "midDays" | "lateDays";
const scenarioFields: Array<{ key: ScenarioField; label: string; coefficient?: boolean }> = [
  { key: "kcInitial", label: "Kc начальной фазы", coefficient: true }, { key: "kcMid", label: "Kc средней фазы", coefficient: true },
  { key: "kcEnd", label: "Kc завершения", coefficient: true }, { key: "initialDays", label: "Начальная фаза, дней" },
  { key: "developmentDays", label: "Развитие, дней" }, { key: "midDays", label: "Средняя фаза, дней" }, { key: "lateDays", label: "Завершение, дней" },
];

export default function WaterDemand({ season, onResult, onRootResult, bindings }: {
  season: SeasonAssessment; onResult: (value: WaterAssessment | null, assumptions?: string) => void;
  onRootResult: (value: RootZoneComparison | null, waterAssumptions?: string, rootAssumptions?: string) => void;
  bindings: ScenarioBindings;
}) {
  const form = bindings.drafts.water;
  const [kcOpen, setKcOpen] = useState(form.useKc);
  const body = makeWaterBody({ latitude: String(season.location.latitude), longitude: String(season.location.longitude),
    start: season.season.sowing_date, end: season.season.end_date, cropId: season.crop.crop_id }, form);
  const bodyKey = stableKey(body);
  const request = useAnalysisSession<WaterAssessment>(bodyKey);
  const result = request.result ?? (bindings.waterSeed?.key === bodyKey ? bindings.waterSeed.value : null);
  const loading = request.loading;
  const error = analysisErrorText(request.error);
  const ready = waterReadiness(form, season.season.duration_days);
  const boundedDays = result?.coverage?.cloud_ratio_bounded_days
    ?? result?.daily.filter((day) => day.quality_flags.includes("cloud_ratio_bounded_asce2005")).length ?? 0;
  function update<K extends keyof WaterDraft>(key: K, value: WaterDraft[K]) {
    request.reset(); onResult(null); onRootResult(null);
    bindings.onWaterDraft(editWaterDraft(form, key, value));
  }
  function configure(stage: "height" | "kc") {
    const settings = document.getElementById("water-settings");
    if (settings instanceof HTMLDetailsElement) settings.open = true;
    if (stage === "kc") setKcOpen(true);
    requestAnimationFrame(() => document.getElementById(stage === "kc" ? "water-kc-settings" : "water-elevation-input")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready.et0.length) return;
    onResult(null); onRootResult(null);
    const value = await request.run(() => requestJSON<WaterAssessment>("/api/water/assess", body));
    if (value) onResult(value, bodyKey);
  }

  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `orbitfarm-water-${season.crop.crop_id}.json`; link.click(); URL.revokeObjectURL(url);
  }
  return <section className="water-section" aria-labelledby="water-heading" aria-busy={loading}>
    <div className="section-title-row"><div><p className="eyebrow">FAO-56 · ИСТОРИЧЕСКИЙ ПЕРИОД</p><h3 id="water-heading">Потребность в воде</h3></div><Droplets size={18} /></div>
    <p className="field-hint">{season.crop.name_ru} · {season.location.latitude}, {season.location.longitude} · {season.season.sowing_date} — {season.season.end_date}.</p>
    <ol className="water-journey" aria-label="Порядок водного анализа">
      <li><strong>1 · Данные участка</strong><span>{ready.et0.length ? "Нужна высота с источником" : "Высота подтверждена вами"}</span></li>
      <li><strong>2 · Испаряемость ET₀</strong><span>{result?.et0.total_mm != null ? "Рассчитано" : "Ожидает расчёта"}</span></li>
      <li><strong>3 · Потребность ETc</strong><span>{result?.potential_etc.total_mm != null ? "Рассчитано с допущениями" : "Нужны Kc и фазы культуры"}</span></li>
      <li><strong>4 · Влага в почве</strong><span>Два условных сценария</span></li>
    </ol>
    <p className="field-hint">Сначала оценим испаряемость погоды (ET₀). Коэффициенты культуры Kc добавят её потенциальную потребность в воде (ETc); затем можно сравнить почвенные сценарии.</p>
    <details id="water-settings" className="provenance-details scenario-settings" open={!result}>
    <summary>Высота и параметры культуры · изменить настройки <ChevronDown size={15} /></summary>
    <form onSubmit={submit}>
      <fieldset className="season-fields water-controls" disabled={loading}>
        <legend className="sr-only">Данные для расчёта ET₀ и пользовательского сценария ETc</legend>
        <div className="water-elevation-fields">
          <label className="field-label"><span>Высота участка, м</span><input id="water-elevation-input" type="number" step="any" min="-500" max="9000" placeholder="Неизвестна" value={form.elevation} onChange={(event) => update("elevation", event.target.value)} /></label>
          <label className="field-label"><span>Источник высоты</span><input type="text" placeholder="Например, геодезическая съёмка" value={form.elevationSource} onChange={(event) => update("elevationSource", event.target.value)} /></label>
        </div>
        <label className="water-check"><input type="checkbox" checked={form.confirmed} onChange={(event) => update("confirmed", event.target.checked)} /><span>Подтверждаю известную высоту и её источник; это не независимая проверка системой.</span></label>
        {ready.et0.length > 0 && <div className="readiness-note" role="status"><strong>Для шага ET₀ осталось:</strong><ul>{ready.et0.map((line) => <li key={line}>{line}</li>)}</ul></div>}
        <details id="water-kc-settings" className="provenance-details water-scenario" open={kcOpen} onToggle={(event) => setKcOpen(event.currentTarget.open)}><summary>Потребность культуры ETc · настройки Kc <ChevronDown size={15} /></summary>
          <div className="season-detail-body"><label className="water-check"><input type="checkbox" checked={form.useKc} onChange={(event) => update("useKc", event.target.checked)} /><span>Задать собственные коэффициенты и четыре фазы</span></label>
            {form.useKc && <><p className="field-hint">Kc для травяного эталона FAO-56: постоянный в начальной и средней фазах, линейный в развитии и завершении. Сумма фаз — {season.season.duration_days} дней. Значения не выбираются системой.</p>
              <div className="water-kc-fields">{scenarioFields.map((field) => <label className="field-label" key={field.key}><span>{field.label}</span><input type="number" step={field.coefficient ? "any" : "1"} min={field.coefficient ? "0" : "1"} max={field.coefficient ? undefined : "366"} value={form[field.key]} onChange={(event) => update(field.key, event.target.value)} placeholder="Не задано" /></label>)}</div>
              <label className="field-label"><span>Источник коэффициентов и календаря</span><input type="text" value={form.kcSource} onChange={(event) => update("kcSource", event.target.value)} placeholder="Укажите источник и допущения" /></label>
              <label className="water-check"><input type="checkbox" checked={form.kcConfirmed} onChange={(event) => update("kcConfirmed", event.target.checked)} /><span>Это мой сценарий с допущениями, а не научно подтверждённые требования выбранной культуры.</span></label></>}
          </div>
        </details>
        {ready.et0.length === 0 && ready.etc.length > 0 && <p className="field-hint">Сейчас можно рассчитать ET₀. Для ETc {ready.etc[0].toLocaleLowerCase("ru-RU")}</p>}
        <button className="rotation-compare-button season-submit" type="submit" disabled={loading || ready.et0.length > 0}>{loading ? <LoaderCircle size={16} className="spin" /> : <Droplets size={16} />}{loading ? "Получаем данные…" : ready.et0.length ? "Сначала подтвердите высоту" : ready.etc.length ? "Рассчитать ET₀" : "Рассчитать ET₀ и ETc"}</button>
      </fieldset>
    </form>
    </details>
    {result?.et0.total_mm != null && result.potential_etc.total_mm === null && <button className="download-button" type="button" onClick={() => configure("kc")}>Следующий шаг: настроить Kc для потребности культуры</button>}
    {request.reused && <p className="field-hint">Повторно использован ответ для тех же параметров. Метаданные NASA относятся к исходному запросу.</p>}
    {loading && <p className="field-hint" role="status">Запрашиваем девять ежедневных параметров NASA POWER и рассчитываем FAO-56.</p>}
    {error && <div className="error-message" role="alert"><AlertTriangle size={17} /><span>{error}</span></div>}
    {result && <div className="water-result" aria-live="polite">
      <div className="result-meta"><span>{result.source_is_synthetic ? "Синтетическая тестовая фикстура" : "NASA POWER"} · {result.retrieved_from_cache ? "кэш" : "ответ источника"} · LST</span>{result.source.url && <a href={result.source.url} target="_blank" rel="noreferrer">Источник <ArrowRight size={12} /></a>}</div>
      {boundedDays > 0 && <p className="field-hint" role="status">Для {boundedDays} {boundedDays % 10 === 1 && boundedDays % 100 !== 11 ? "дня" : "дней"} применена поправка облачности ASCE-EWRI 2005. Причины и исходные значения — в экспертных подробностях и JSON.</p>}
      {result.coverage?.observations && <p className="field-hint">Погода NASA: {result.coverage.observations.complete_days}/{result.coverage.expected_days} дней с полными наблюдениями. Готовность расчётов ниже учитывает также ваши настройки.</p>}
      <WaterMetrics result={result} />

      <details className="provenance-details"><summary>Ежедневная ET₀, ETc и осадки <ChevronDown size={15} /></summary><div className="season-daily" tabIndex={0} role="region" aria-label="Ежедневная потребность в воде"><table><thead><tr><th scope="col">Дата</th><th scope="col">ET₀, мм</th><th scope="col">Осадки, мм</th><th scope="col">Kc</th><th scope="col">ETc, мм</th><th scope="col">Ограничение</th></tr></thead><tbody>{result.daily.map((day) => <tr key={day.date}><td>{day.date}</td><td>{show(day.et0_mm)}</td><td>{show(day.precipitation_mm)}</td><td>{show(day.kc)}</td><td>{show(day.etc_mm)}</td><td>{[...day.et0_reason_codes, ...day.etc_reason_codes].map(explain).join(" ") || (day.quality_flags.includes("cloud_ratio_bounded_asce2005") ? "Поправка облачности ASCE-EWRI 2005; см. JSON." : day.quality_flags.length ? "Применены оговорки FAO-56; см. JSON." : "—")}</td></tr>)}</tbody></table></div></details>
      <details className="provenance-details"><summary>Метод, единицы и ограничения <ChevronDown size={15} /></summary><div className="season-detail-body"><button type="button" className="download-button" onClick={download}><ArrowDownToLine size={14} /> JSON</button><p>{result.method.name} · {result.method.mean_temperature} · {result.method.actual_vapour_pressure}</p><p>Политика: {result.method.policy ?? "не указана сервером"}.</p>{result.method.cloud_bounds_reference && <p><a href={result.method.cloud_bounds_reference} target="_blank" rel="noreferrer">ASCE-EWRI 2005: Rs/Rso от 0,3 до 1 только в поправке Rnl</a></p>}      <p className="field-hint">Высота: {show(result.elevation.used_m)} м · {result.elevation.input?.source || "источник не задан"}. Kc: {result.kc.status === "user_assumption" ? "пользовательский сценарий" : "unknown"} · {result.kc.scenario?.source || "сценарий не задан"}.</p><ul>{result.et0.reason_codes.concat(result.potential_etc.reason_codes).map((reason, i) => <li key={`${reason}-${i}`}>{explain(reason)}</li>)}</ul><ul>{result.input_parameters.map((input) => <li key={input.nasa_parameter}>{input.nasa_parameter}: {input.source_unit ?? "единицы источника неизвестны"} → {input.unit} ({input.unit_status === "compatible" ? "совместимо" : "нет совместимого наблюдения"})</li>)}</ul><ul className="season-limitations">{result.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul><a href={result.method.references[0]} target="_blank" rel="noreferrer">Метод FAO-56</a></div></details>
      {result && <RootZoneBalance water={result} waterRequest={body} draft={bindings.drafts.root} onDraft={bindings.onRootDraft} seed={bindings.rootSeed} onConfigure={configure} onResult={(value, rootKey) => onRootResult(value, bodyKey, rootKey)} />}
    </div>}
    {!result && <p className="field-hint">Почвенный сценарий откроется после полного расчёта ETc. Фактическая водообеспеченность поля пока неизвестна.</p>}
  </section>;
}
