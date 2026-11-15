"use client";

import { ArrowDownToLine } from "lucide-react";
import type { RotationCompareResponse } from "@/lib/contracts";
import type { AnalysisContext } from "@/lib/analysis-session";
import type { SeasonAssessment } from "@/lib/season-contracts";
import type { WaterAssessment } from "@/lib/water-contracts";
import type { RootZoneComparison } from "@/lib/root-zone-contracts";
import { buildExperienceSummary } from "@/lib/experience-summary";
import { resultNumber as show, sourceCaption, stressDifference } from "@/lib/result-presentation";
import PlanComparison from "@/components/plan-comparison";

interface Props {
  context: AnalysisContext; cropName: string; season: SeasonAssessment | null;
  water: WaterAssessment | null; root: RootZoneComparison | null; rotation: RotationCompareResponse | null;
}
export default function AnalysisSummary(props: Props) {
  const { context, cropName, season, water, root, rotation } = props;
  const summary = buildExperienceSummary(props);
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ context, summary, season, water, root_zone: root, rotation,
      limitation: "Historical observations and explicit scenarios; no future-season ranking or suitability score." }, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "orbitfarm-analysis-summary.json"; link.click(); URL.revokeObjectURL(url);
  }
  return <section id="analysis-summary" className="experience-summary" aria-labelledby="analysis-summary-heading">
    <header className="summary-heading"><p className="eyebrow">04 · РЕЗУЛЬТАТ</p><h2 id="analysis-summary-heading">Что показал анализ</h2>
      <div className="summary-context"><span>{context.latitude || "—"}, {context.longitude || "—"}</span><span>{context.start || "—"} — {context.end || "—"}</span><span>{cropName || "Культура не выбрана"}</span></div>
    </header>
    <section className="summary-chapter" aria-labelledby="summary-history"><div className="chapter-heading"><span className="result-category">НАБЛЮДЕНИЯ</span><h3 id="summary-history">Историческая погода</h3></div>
      {season ? <><div className="summary-observed-values">
        <div><span>Средняя температура{season.metrics.mean_temperature?.status === "partial" ? " · доступные дни" : ""}</span><strong>{show(season.metrics.mean_temperature?.value)}<small> °C</small></strong></div>
        <div><span>Осадки за весь период</span><strong>{show(season.metrics.total_precipitation?.value)}<small> мм</small></strong></div>
        <div><span>Полных дней наблюдений</span><strong>{season.coverage.complete_days}<small> / {season.coverage.expected_days}</small></strong></div>
      </div><p className="field-hint">{season.source_is_synthetic ? "Синтетическая тестовая фикстура" : "NASA POWER"} · {season.retrieved_from_cache ? "серверный кэш" : "ответ источника"}. Региональные наблюдения, не измерения на поле. Пропуски не заполняются. <a href="#seasonal-analysis">Наблюдения и дневные данные →</a></p></> : <p className="summary-empty">Наблюдения ещё не получены. <a href="#site">Выберите участок, культуру и период →</a></p>}
    </section>
    <section className="summary-chapter" aria-labelledby="summary-water"><div className="chapter-heading"><span className="result-category">МОДЕЛЬ С ДОПУЩЕНИЯМИ</span><h3 id="summary-water">Вода в историческом сценарии</h3></div>
      {water && <div className="summary-water-totals"><p>Эталонная испаряемость ET₀ <strong>{show(water.et0.total_mm)} мм</strong></p><p>Потенциальная потребность ETc <strong>{show(water.potential_etc.total_mm)} мм</strong></p></div>}
      {root ? <div className="summary-water-outcome">
        <p className="scenario-difference">{stressDifference(root)}.</p>
        <dl className="summary-scenario-lines">{(["rainfed", "irrigated"] as const).map((key, index) => {
          const scenario = root.scenarios[key], s = scenario.summary;
          return <div key={key}><dt>{index === 0 ? "A · Без орошения" : "B · С орошением"}</dt><dd><strong>{show(s.stress_days)}</strong> дн. модельного стресса · <strong>{show(s.net_irrigation_total_mm)} мм</strong> полива<small>Модель: {scenario.coverage.computed_days}/{scenario.coverage.expected_days} дней</small></dd></div>;
        })}</dl>
        <p className="field-hint">Условная модель с пользовательскими допущениями, не измеренное состояние поля и не рекомендация полива. <a href="#root-zone-results">Сценарии, настройки и график →</a></p>
      </div> : <p className="summary-empty">Почвенные сценарии ещё не рассчитаны. <a href="#climate-water">Проверить настройки и полноту данных →</a></p>}
      {(water || root) && <p className="assumption-caption">Высота: {sourceCaption(water?.elevation.input?.source)} · Kc: {water?.kc.status === "user_assumption" ? "пользовательский сценарий" : "не подтверждён"}{root ? ` · Почва: ${sourceCaption(root.soil.source)}` : ""}. Исходные записи сохранены в деталях.</p>}
    </section>
    <section className="summary-chapter" aria-labelledby="summary-plans"><div className="chapter-heading"><span className="result-category">СТРУКТУРА ПЛАНОВ</span><h3 id="summary-plans">Что различается в севооборотах</h3></div>
      {rotation ? <><PlanComparison plans={rotation.plans} /><a className="field-hint" href="#rotation-planner">Планы и полные объяснения →</a></> : <p className="summary-empty">Сравнение ещё не выполнено. <a href="#rotation-planner">Составить и сравнить два плана →</a></p>}
    </section>
    <section className="summary-chapter summary-unknown" aria-labelledby="summary-unknown"><div className="chapter-heading"><span className="result-category">ГРАНИЦЫ АНАЛИЗА</span><h3 id="summary-unknown">Что остаётся неизвестным</h3></div>
      <p>Фактическая влажность и водный баланс поля не определены. Урожайность и пригодность трёх будущих сезонов не оценены; научного рейтинга планов нет.</p>
      <p>Один исторический водный сценарий не является прогнозом следующих сезонов. Почва, Kc и поливы в примере — тестовые допущения.</p>
      {(season || water || rotation) && summary.unknown.length > 3 && <details className="provenance-details"><summary>Каких данных или расчётов ещё не хватает</summary><ul>{[...new Set(summary.unknown.slice(3))].map(line => <li key={line}>{line}</li>)}</ul></details>}
    </section>
    <details className="provenance-details summary-export"><summary>Исходные данные, источники, объяснения и JSON</summary><div className="season-detail-body">
      <button className="download-button" type="button" onClick={download}><ArrowDownToLine size={16} /> Экспорт JSON</button>
      {water && <><p>Высота: {show(water.elevation.used_m)} м. Исходный источник: {water.elevation.input?.source || "не задан"}. Независимая проверка системой не выполнялась.</p><p>Kc: {water.kc.status} · {water.kc.scenario?.source || "Коэффициенты и календарь неизвестны"}.</p></>}
      {root && <p>Почва: {root.soil.source}. TAW={show(root.soil.taw_mm)} мм, RAW={show(root.soil.raw_mm)} мм. Начальное Dr={show(root.scenarios.rainfed.summary.initial_dr_mm)} мм. Полный календарь поливов и ежедневные значения — в разделе 02 и JSON.</p>}
      <ul className="season-limitations">{summary.observations.concat(summary.scenarios, summary.plans, summary.unknown.slice(0, 3)).map(line => <li key={line}>{line}</li>)}</ul>
    </div></details>
  </section>;
}
