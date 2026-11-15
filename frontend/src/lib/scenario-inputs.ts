import type { AnalysisContext } from "./analysis-session";
import type { WaterAssessment } from "./water-contracts";
import type { RootZoneComparison } from "./root-zone-contracts";

export interface WaterDraft {
  elevation: string; elevationSource: string; confirmed: boolean; useKc: boolean; kcSource: string; kcConfirmed: boolean;
  kcInitial: string; kcMid: string; kcEnd: string; initialDays: string; developmentDays: string; midDays: string; lateDays: string;
}
export interface RootFormDraft {
  fc: string; wp: string; zr: string; p: string; depletion: string; initialMode: string; source: string; confirmed: boolean;
}
export interface IrrigationDraft { date: string; net: string }
export interface RootDraft { form: RootFormDraft; events: IrrigationDraft[] }
export interface ScenarioDrafts { water: WaterDraft; root: RootDraft; notice: string }
export interface ScenarioBindings {
  drafts: ScenarioDrafts; onWaterDraft: (draft: WaterDraft) => void; onRootDraft: (draft: RootDraft) => void;
  waterSeed: { key: string; value: WaterAssessment } | null;
  rootSeed: { key: string; value: RootZoneComparison } | null;
}
export const emptyWaterDraft = (): WaterDraft => ({ elevation: "", elevationSource: "", confirmed: false, useKc: false,
  kcSource: "", kcConfirmed: false, kcInitial: "", kcMid: "", kcEnd: "", initialDays: "", developmentDays: "", midDays: "", lateDays: "" });
export const emptyRootDraft = (): RootDraft => ({ form: { fc: "", wp: "", zr: "", p: "", depletion: "", initialMode: "mm", source: "", confirmed: false }, events: [] });
export const emptyScenarioDrafts = (): ScenarioDrafts => ({ water: emptyWaterDraft(), root: emptyRootDraft(), notice: "" });
const number = (text: string) => text.trim() === "" ? null : Number(text);
export function editWaterDraft<K extends keyof WaterDraft>(draft: WaterDraft, key: K, value: WaterDraft[K]): WaterDraft {
  return { ...draft, [key]: value,
    confirmed: key === "elevation" || key === "elevationSource" ? false : key === "confirmed" ? Boolean(value) : draft.confirmed,
    kcConfirmed: key !== "kcConfirmed" && key !== "confirmed" && key !== "elevation" && key !== "elevationSource" ? false : key === "kcConfirmed" ? Boolean(value) : draft.kcConfirmed };
}

/** Compatibility of user inputs only. No agronomic defaults or calculated outcomes. */
export function reconcileDrafts(previous: AnalysisContext, next: AnalysisContext, draft: ScenarioDrafts): ScenarioDrafts {
  const sameCoordinate = (a: string, b: string) => a === b || (a.trim() !== "" && b.trim() !== "" && Number.isFinite(Number(a)) && Number(a) === Number(b));
  if (!sameCoordinate(previous.latitude, next.latitude) || !sameCoordinate(previous.longitude, next.longitude)) {
    return { ...emptyScenarioDrafts(), notice: "Участок изменён. Высоту и почвенные допущения нужно задать для новой точки." };
  }
  if (previous.cropId !== next.cropId) {
    const fresh = emptyScenarioDrafts();
    fresh.water = { ...fresh.water, elevation: draft.water.elevation, elevationSource: draft.water.elevationSource, confirmed: false };
    fresh.root.form = { ...fresh.root.form, fc: draft.root.form.fc, wp: draft.root.form.wp, source: draft.root.form.source, confirmed: false };
    fresh.notice = "Культура изменена. Kc, корни и календарь сброшены; сохранённые черновики высоты и почвы требуют подтверждения.";
    return fresh;
  }
  if (previous.start !== next.start || previous.end !== next.end) {
    return { water: { ...draft.water, kcConfirmed: false },
      root: { form: { ...draft.root.form, confirmed: false }, events: draft.root.events.map((event) => ({ ...event })) },
      notice: "Период изменён. Черновики сохранены: проверьте фазы, начальное состояние и даты поливов и подтвердите их заново." };
  }
  return draft;
}

export function makeWaterBody(context: AnalysisContext, draft: WaterDraft) {
  return { crop_id: context.cropId, latitude: Number(context.latitude), longitude: Number(context.longitude),
    sowing_date: context.start, end_date: context.end,
    elevation: draft.elevation.trim() ? { value_m: number(draft.elevation), source: draft.elevationSource, confirmed: draft.confirmed } : null,
    kc_scenario: draft.useKc ? { type: "user_defined", reference_surface: "grass", crop_id: context.cropId,
      source: draft.kcSource, acknowledge_assumptions: draft.kcConfirmed,
      kc_initial: number(draft.kcInitial), kc_mid: number(draft.kcMid), kc_end: number(draft.kcEnd),
      stage_lengths_days: { initial: number(draft.initialDays), development: number(draft.developmentDays), mid: number(draft.midDays), late: number(draft.lateDays) } } : null };
}
export function makeRootBody(waterBody: Record<string, unknown>, draft: RootDraft) {
  const f = draft.form;
  return { ...waterBody,
    soil: { theta_fc: number(f.fc), theta_wp: number(f.wp), theta_unit: "m3/m3", zr_m: number(f.zr), p: number(f.p), source: f.source, acknowledge_assumptions: f.confirmed },
    initial_depletion: f.initialMode === "mm" ? { dr_mm: number(f.depletion) } : { fraction_of_taw: number(f.depletion) },
    irrigation: draft.events.map((entry) => ({ date: entry.date, net_mm: number(entry.net) })),
    assumptions: { runoff_zero: true, capillary_rise_zero: true, full_rain_infiltration: true, wetting_before_et: true, same_day_drainage: true } };
}

export function waterReadiness(draft: WaterDraft, days: number) {
  const height = number(draft.elevation);
  const et0 = [height === null || !Number.isFinite(height) || height < -500 || height > 9000 ? "Укажите высоту участка в метрах." : "",
    !draft.elevationSource.trim() ? "Добавьте источник высоты." : "", !draft.confirmed ? "Подтвердите высоту и её источник." : ""].filter(Boolean);
  const coefficients = [draft.kcInitial, draft.kcMid, draft.kcEnd].map(number);
  const lengths = [draft.initialDays, draft.developmentDays, draft.midDays, draft.lateDays].map(number);
  const etc = [!draft.useKc ? "Включите пользовательский сценарий культуры Kc." : "",
    coefficients.some((v) => v === null || !Number.isFinite(v) || v < 0) ? "Задайте три коэффициента Kc." : "",
    lengths.some((v) => v === null || !Number.isInteger(v) || v < 1 || v > 366) || lengths.reduce<number>((sum, v) => sum + (v ?? 0), 0) !== days ? `Задайте четыре фазы общей длительностью ${days} дней.` : "",
    !draft.kcSource.trim() ? "Укажите источник или описание сценария Kc." : "",
    !draft.kcConfirmed ? "Подтвердите допущения Kc и календаря." : ""].filter(Boolean);
  return { et0, etc };
}
export function waterMetricStatus(kind: "et0" | "etc" | "rain", water: WaterAssessment | null) {
  if (!water) return "not_calculated";
  const total = kind === "et0" ? water.et0 : kind === "etc" ? water.potential_etc : water.precipitation;
  if (total.total_mm !== null) return kind === "rain" ? "observed" : "with_assumptions";
  if (kind !== "rain" && (water.elevation.used_m === null || (kind === "etc" && water.kc.status === "unknown"))) return "not_calculated";
  if (kind === "rain" || water.daily.some((day) => day.et0_reason_codes.some((r) => r.startsWith("missing_or_invalid:")))) return "missing_data";
  return "model_unavailable";
}
