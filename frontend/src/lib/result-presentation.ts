import type { AnalysisContext } from "./analysis-session";
import type { RotationPlan } from "./contracts";
import type { RootZoneComparison } from "./root-zone-contracts";

const format = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
export const resultNumber = (value: number | null | undefined) => value == null ? "Нет данных" : format.format(value);
export function sourceCaption(source: string | null | undefined) {
  if (!source?.trim()) return "Источник не указан";
  if (/SRTM/i.test(source)) return "SRTM · пользовательская оценка высоты";
  if (/USER ASSUMPTIONS|TEST SCENARIO|DEMO/i.test(source)) return "Тестовые пользовательские допущения";
  return source.length > 64 || /https?:\/\//i.test(source) ? "Источник указан пользователем" : source;
}
/** Display of an existing API difference; no comparison/model is recalculated here. */
export function stressDifference(result: RootZoneComparison) {
  const difference = result.differences.stress_days;
  if (difference === null) return "Разница дней модельного стресса неизвестна";
  if (difference === 0) return "Одинаковое число дней модельного стресса";
  return `В сценарии B на ${resultNumber(Math.abs(difference))} дн. ${difference < 0 ? "меньше" : "больше"} модельного стресса`;
}
export function planMetrics(plan: RotationPlan) {
  const i = plan.indicators;
  return [
    { key: "repeats", label: "Повторы подряд", value: i.crop_repetition.status === "known" ? i.crop_repetition.adjacent_repeats?.length ?? null : null },
    { key: "returns", label: "Возвраты культуры", value: i.crop_repetition.status === "known" ? i.crop_repetition.return_after_intermediate?.length ?? null : null },
    { key: "diversity", label: "Разных культур", value: i.sequence_diversity.status === "known" ? i.sequence_diversity.distinct_crop_count : null },
    { key: "legumes", label: "Бобовое звено", value: i.legume_presence.status === "known" ? i.legume_presence.present : null },
  ];
}
export function differentPlanMetrics(plans: RotationPlan[]) {
  const rows = plans.map(planMetrics);
  return rows[0]?.filter((_, index) => {
    const values = rows.map(row => row[index].value);
    return values.every(v => v != null) && new Set(values).size > 1;
  }).map(row => row.key) ?? [];
}
/** Deduplicate identical server explanations while retaining their parameter provenance. */
export function groupRequirementReasons(requirements: Array<{ parameter_id: string; reasons: string[] }>) {
  const groups = new Map<string, Set<string>>();
  for (const requirement of requirements) for (const reason of requirement.reasons) {
    const parameters = groups.get(reason) ?? new Set<string>();
    parameters.add(requirement.parameter_id); groups.set(reason, parameters);
  }
  return [...groups].map(([reason, parameters]) => ({ reason, parameters: [...parameters] }));
}
export function siteReadiness(context: AnalysisContext, catalogueReady: boolean) {
  const validNumber = (text: string, limit: number) => text.trim() !== "" && Number.isFinite(Number(text)) && Math.abs(Number(text)) <= limit;
  const validDate = (text: string) => /^\d{4}-\d{2}-\d{2}$/.test(text) && Number.isFinite(Date.parse(text)) && new Date(text).toISOString().slice(0, 10) === text;
  return [!catalogueReady ? "Дождитесь загрузки каталога культур." : !context.cropId ? "Выберите культуру." : "",
    !validNumber(context.latitude, 90) || !validNumber(context.longitude, 180) ? "Укажите корректные координаты или выберите точку на карте." : "",
    !validDate(context.start) || !validDate(context.end) ? "Укажите корректные даты начала и окончания." : context.start > context.end ? "Дата окончания должна быть не раньше даты начала." : "",
  ].filter(Boolean);
}
export const journeyStages = [
  { id: "site", label: "Участок" }, { id: "climate-water", label: "Климат и вода" },
  { id: "rotation-planner", label: "Севооборот" }, { id: "analysis-summary", label: "Итоги" },
] as const;
export function currentJourneyStage(positions: Array<{ id: string; top: number }>, offset: number, atBottom = false) {
  if (atBottom && positions.length) return positions.at(-1)!.id;
  return positions.filter(position => position.top <= offset + 2).at(-1)?.id ?? "site";
}
