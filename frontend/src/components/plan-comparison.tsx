import type { RotationPlan } from "@/lib/contracts";
import { differentPlanMetrics, planMetrics, resultNumber } from "@/lib/result-presentation";

export default function PlanComparison({ plans }: { plans: RotationPlan[] }) {
  const different = differentPlanMetrics(plans);
  return <div className="plan-comparison">
    <p className="field-hint">Выделены только известные структурные различия. Они не определяют лучший план.</p>
    <div className="summary-plan-table" tabIndex={0} role="region" aria-label="Структурное сравнение планов"><table>
      <thead><tr><th scope="col">План</th>{plans[0] && planMetrics(plans[0]).map(metric => <th scope="col" key={metric.key}>{metric.label}</th>)}</tr></thead>
      <tbody>{plans.map(plan => <tr key={plan.plan_id}><th scope="row">{plan.name_ru}</th>{planMetrics(plan).map(metric => <td key={metric.key} data-different={different.includes(metric.key) || undefined}>
        {typeof metric.value === "boolean" ? metric.value ? "Есть" : "Нет" : resultNumber(metric.value)}{metric.key === "diversity" && metric.value !== null ? ` из ${plan.season_count}` : ""}
      </td>)}</tr>)}</tbody>
    </table></div>
  </div>;
}
