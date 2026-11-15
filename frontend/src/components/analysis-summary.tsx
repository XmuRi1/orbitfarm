"use client";

import { ArrowDownToLine } from "lucide-react";
import type { RotationCompareResponse } from "@/lib/contracts";
import type { AnalysisContext } from "@/lib/analysis-session";
import type { SeasonAssessment } from "@/lib/season-contracts";
import type { WaterAssessment } from "@/lib/water-contracts";
import type { RootZoneComparison } from "@/lib/root-zone-contracts";
import { buildExperienceSummary, displayKnown } from "@/lib/experience-summary";

interface Props {
  context: AnalysisContext; cropName: string; season: SeasonAssessment | null;
  water: WaterAssessment | null; root: RootZoneComparison | null; rotation: RotationCompareResponse | null;
}
export default function AnalysisSummary(props: Props) {
  const { context, cropName, season, water, root, rotation } = props;
  const summary = buildExperienceSummary(props);
  const human = (line: string) => line.replaceAll("неизвестно (unknown)", "не рассчитано").replaceAll("unknown", "нет данных");
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ context, summary, season, water, root_zone: root, rotation,
      limitation: "Historical observations and explicit scenarios; no future-season ranking or suitability score." }, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "orbitfarm-analysis-summary.json"; link.click(); URL.revokeObjectURL(url);
  }
  return <section id="analysis-summary" className="experience-summary" aria-labelledby="analysis-summary-heading">
    <div className="section-title-row"><div><p className="eyebrow">04 · РЕЗУЛЬТАТ</p><h2 id="analysis-summary-heading">Итоги анализа</h2></div></div>
    <p className="field-hint">Участок {context.latitude || "—"}, {context.longitude || "—"} · {context.start || "—"} — {context.end || "—"} · культура исторического сценария: {cropName || "не выбрана"}.</p>
    <div className="experience-summary-grid">
      {([
        ["Исторические наблюдения", summary.observations, "Запустите сезонный анализ для текущих параметров."],
        ["Условные водные сценарии", summary.scenarios, "Расчёты ещё не выполнены; значения не подставляются."],
      ] as const).map(([title, lines, empty]) => <article key={title}><h3>{title}</h3>{lines.length ? <ul>{lines.map((line) => <li key={line}>{human(line)}</li>)}</ul> : <p>{empty}</p>}</article>)}
    </div>
    {rotation ? <div className="summary-plan-table" tabIndex={0} role="region" aria-label="Структурное сравнение планов"><table><thead><tr><th>План</th><th>Повторы культуры подряд</th><th>Возвраты культуры</th><th>Разных культур</th><th>Бобовое звено</th></tr></thead><tbody>{rotation.plans.map((plan) => <tr key={plan.plan_id}><th scope="row">{plan.name_ru}</th><td>{human(displayKnown(plan.indicators.crop_repetition.status === "known" ? plan.indicators.crop_repetition.adjacent_repeats?.length : null))}</td><td>{human(displayKnown(plan.indicators.crop_repetition.status === "known" ? plan.indicators.crop_repetition.return_after_intermediate?.length : null))}</td><td>{human(displayKnown(plan.indicators.sequence_diversity.status === "known" ? plan.indicators.sequence_diversity.distinct_crop_count : null))} из {plan.season_count}</td><td>{plan.indicators.legume_presence.status !== "known" || plan.indicators.legume_presence.present === null ? "Нет данных" : plan.indicators.legume_presence.present ? "Есть" : "Нет"}</td></tr>)}</tbody></table></div> : <p className="field-hint">Сравните два плана в разделе «Севооборот». Водный пример не выбирает план-победитель.</p>}
    {(water || root) && <details className="provenance-details"><summary>Для каких допущений получен водный результат</summary><div className="season-detail-body">
      {water && <><p>Высота: {displayKnown(water.elevation.used_m, "м")}. Источник: {water.elevation.input?.source || "не задан"}; независимая проверка высоты не выполнялась.</p><p>Kc: {water.kc.status === "user_assumption" ? "пользовательский сценарий" : "unknown"}. {water.kc.scenario?.source || "Коэффициенты и календарь неизвестны."}</p></>}
      {root && <p>Почвенный сценарий: {root.soil.source}. TAW={displayKnown(root.soil.taw_mm, "мм")}, RAW={displayKnown(root.soil.raw_mm, "мм")}. Начальное Dr={displayKnown(root.scenarios.rainfed.summary.initial_dr_mm, "мм")}. Параметры и даты поливов доступны в разделе 02 и JSON.</p>}
    </div></details>}
    {summary.unknown.length > 3 && <div className="readiness-note"><strong>Что ещё не рассчитано или требует настройки</strong><ul>{summary.unknown.slice(3).map((line) => <li key={line}>{human(line)}</li>)}</ul></div>}
    <p className="field-hint">Это исторические наблюдения и условные сценарии. Фактическая влажность поля, урожайность и научный рейтинг планов не определены.</p>
    <details className="provenance-details"><summary>Экспертные ограничения, структура семейств и JSON</summary><div className="season-detail-body"><button className="download-button" type="button" onClick={download}><ArrowDownToLine size={15} /> JSON</button><ul className="season-limitations">{summary.unknown.slice(0, 3).concat(summary.plans).map((line) => <li key={line}>{line}</li>)}</ul></div></details>
  </section>;
}
