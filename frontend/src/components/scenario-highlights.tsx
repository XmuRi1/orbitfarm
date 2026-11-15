import type { RootZoneComparison } from "@/lib/root-zone-contracts";
import { resultNumber as show, stressDifference } from "@/lib/result-presentation";

export default function ScenarioHighlights({ result, compact = false }: { result: RootZoneComparison; compact?: boolean }) {
  const a = result.scenarios.rainfed.coverage, b = result.scenarios.irrigated.coverage;
  const commonCoverage = a.computed_days === b.computed_days && a.expected_days === b.expected_days;
  return <div className={`scenario-highlights${compact ? " is-compact" : ""}`}>
    <div className="scenario-comparison-heading"><div><p className="eyebrow">УСЛОВНЫЕ СЦЕНАРИИ · ОДНА ПОГОДА И ПОЧВА</p><h4>Дни модельного водного стресса</h4></div><span className="assumption-tag">С пользовательскими допущениями</span></div>
    <div className="scenario-scorecards">{(["rainfed", "irrigated"] as const).map((key, index) => {
      const scenario = result.scenarios[key], s = scenario.summary;
      return <article className={`scenario-scorecard scenario-${key}`} key={key}>
        <h5><span>{index === 0 ? "A" : "B"}</span>{index === 0 ? "Без орошения" : "С орошением"}</h5>
        <p className={`stress-value${s.stress_days === null ? " is-unknown" : ""}`}>{show(s.stress_days)}<span>{s.stress_days === null ? "число дней неизвестно" : "дн. модельного стресса"}</span></p>
        <p className="irrigation-value">Заданный чистый полив <strong>{show(s.net_irrigation_total_mm)} мм</strong></p>
        {!compact && <details className="scenario-details"><summary>Другие показатели сценария</summary><dl className="scenario-secondary">
          <div><dt>Модельная эвапотранспирация</dt><dd>{show(s.etc_adj.total_mm)} мм</dd></div>
          <div><dt>Истощение к концу периода</dt><dd>{show(s.final_dr_mm)} мм</dd></div>
          <div><dt>Глубокое просачивание</dt><dd>{show(s.deep_percolation.total_mm)} мм</dd></div>
        </dl></details>}
        {!commonCoverage && <small>Модель: {scenario.coverage.computed_days}/{scenario.coverage.expected_days} дней</small>}
      </article>;
    })}</div>
    <p className="scenario-difference">{stressDifference(result)}.</p>
    <p className="field-hint">{commonCoverage && <>Полнота моделирования обоих сценариев: {a.computed_days}/{a.expected_days} дней. </>}Стресс — модельный (Ks &lt; 1), не измеренное состояние растений. Сравнение не задаёт рекомендованную норму полива и не оценивает урожайность.</p>
  </div>;
}
