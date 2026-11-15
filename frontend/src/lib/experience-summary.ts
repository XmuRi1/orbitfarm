import type { RotationClimateContext, RotationCompareResponse, RotationPlan } from "./contracts";
import type { SeasonAssessment } from "./season-contracts";
import type { WaterAssessment } from "./water-contracts";
import type { RootZoneComparison } from "./root-zone-contracts";

const format = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
export const displayKnown = (value: number | null | undefined, unit = "") => value === null || value === undefined
  ? "неизвестно (unknown)" : `${format.format(value)}${unit ? ` ${unit}` : ""}`;

export function seasonClimateContext(season: SeasonAssessment): RotationClimateContext {
  // Copy server-computed values only; no daily aggregation or future-season inference.
  return { historical_period: season.historical_period, location: season.location,
    source_is_synthetic: season.source_is_synthetic, retrieved_from_cache: season.retrieved_from_cache,
    // Rainy-day count shares CLIM_007 with precipitation in the seasonal report;
    // it is not a second precipitation-depth observation in the rotation contract.
    observations: Object.entries(season.metrics).flatMap(([key, metric]) => key === "rainy_days" || metric.value === null ? [] : [{
      parameter_id: metric.parameter_id, value: metric.value, unit: metric.unit, aggregation: metric.aggregation,
      context: { start_date: season.historical_period.start, end_date: season.historical_period.end, time_standard: season.time_standard,
        days_available: metric.days_available, days_requested: metric.days_expected },
      source: { name: season.source.name, url: season.source.url, synthetic: season.source_is_synthetic },
    }]) };
}

export function describePlan(plan: RotationPlan): string {
  const i = plan.indicators;
  const cropRepeats = i.crop_repetition.status === "unknown" || i.crop_repetition.adjacent_repeats === null ? null : i.crop_repetition.adjacent_repeats.length;
  const familyRepeats = i.family_repetition.status === "unknown" || i.family_repetition.adjacent_repeats === null ? null : i.family_repetition.adjacent_repeats.length;
  const legumes = i.legume_presence.status === "unknown" || i.legume_presence.present === null ? "unknown" : i.legume_presence.present ? "есть" : "нет";
  const diversity = i.sequence_diversity.status === "unknown" ? null : i.sequence_diversity.distinct_crop_count;
  const cropReturns = i.crop_repetition.status === "unknown" ? null : i.crop_repetition.return_after_intermediate?.length;
  const familyReturns = i.family_repetition.status === "unknown" ? null : i.family_repetition.return_after_intermediate?.length;
  return `${plan.name_ru}: повторов культуры подряд — ${displayKnown(cropRepeats)}; семейства подряд — ${displayKnown(familyRepeats)}; возвратов культуры после промежуточного сезона — ${displayKnown(cropReturns)}; семейства — ${displayKnown(familyReturns)}; бобовое звено — ${legumes}; разных культур — ${displayKnown(diversity)} из ${plan.season_count}.`;
}

export function buildExperienceSummary({ season, water, root, rotation }: {
  season: SeasonAssessment | null; water: WaterAssessment | null;
  root: RootZoneComparison | null; rotation: RotationCompareResponse | null;
}) {
  const observations: string[] = [];
  const scenarios: string[] = [];
  const unknown = ["Фактическая влажность и водный баланс поля неизвестны.", "Исторический водный сценарий не является прогнозом трёх будущих сезонов.", "Требования культур и дополнительная таксономия требуют проверки; научное ранжирование планов не выполняется."];
  if (season) {
    observations.push(`${season.source_is_synthetic ? "Синтетическая фикстура" : "NASA POWER"}: ${season.coverage.available_values}/${season.coverage.expected_values} ежедневных значений, ${season.coverage.complete_days}/${season.coverage.expected_days} полных дней. Это региональный источник, не измерения на поле.`);
    observations.push(`Средняя температура${season.metrics.mean_temperature?.status === "partial" ? " по доступным дням" : ""}: ${displayKnown(season.metrics.mean_temperature?.value, "°C")}. Осадки за весь период: ${displayKnown(season.metrics.total_precipitation?.value, "мм")}.`);
    if (season.metrics.total_precipitation?.value === null) unknown.push("Полная сумма осадков неизвестна из-за неполного ряда.");
  } else unknown.push("Сезонные наблюдения для текущих участка, периода и культуры ещё не получены.");
  if (water) {
    scenarios.push(`ET₀: ${displayKnown(water.et0.total_mm, "мм")}; потенциальная ETc: ${displayKnown(water.potential_etc.total_mm, "мм")}. Полнота расчёта ET₀ ${water.et0.days_available}/${water.et0.days_expected}, ETc ${water.potential_etc.days_available}/${water.potential_etc.days_expected} дней.`);
    if (water.kc.status === "unknown") unknown.push("Kc или календарь стадий неизвестны: потенциальная ETc не определена.");
    if (water.elevation.used_m === null) unknown.push("Без пригодной высоты участка ET₀ неизвестна.");
  } else unknown.push("ET₀/ETc для текущих параметров ещё не рассчитаны.");
  if (root) {
    for (const [label, key] of [["A · без полива", "rainfed"], ["B · заданный полив", "irrigated"]] as const) {
      const s = root.scenarios[key].summary;
      scenarios.push(`${label}: модельная ETc_adj ${displayKnown(s.etc_adj.total_mm, "мм")}; дней с Ks < 1 — ${displayKnown(s.stress_days)}; конечное Dr ${displayKnown(s.final_dr_mm, "мм")}; чистый полив ${displayKnown(s.net_irrigation_total_mm, "мм")}; DP ${displayKnown(s.deep_percolation.total_mm, "мм")}.`);
    }
  } else unknown.push("Сценарий корневой зоны для текущих допущений не рассчитан.");
  if (!rotation) unknown.push("Текущие планы севооборота ещё не сравнены.");
  return { observations, scenarios, plans: rotation?.plans.map(describePlan) ?? [], unknown };
}
