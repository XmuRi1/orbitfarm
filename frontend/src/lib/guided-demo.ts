import type { AnalysisContext } from "./analysis-session";
import type { ScenarioDrafts } from "./scenario-inputs";
import type { SeasonAssessment } from "./season-contracts";
import type { WaterAssessment } from "./water-contracts";
import type { RootZoneComparison } from "./root-zone-contracts";

export const DEMO_CONTEXT: AnalysisContext = { latitude: "31.25", longitude: "34.79", start: "2025-01-01", end: "2025-03-31", cropId: "wheat" };
export const DEMO_HEIGHT_SOURCE = "DEMO: SRTM v3 30m, EGM96, bilinear DEM estimate, not a site survey. https://api.opentopodata.org/v1/srtm30m?locations=31.25,34.79&interpolation=bilinear";
export function confirmedDemoDrafts(accepted: boolean): ScenarioDrafts {
  if (!accepted) throw new Error("Сначала подтвердите источники и тестовые допущения примера.");
  return { water: { elevation: "288", elevationSource: DEMO_HEIGHT_SOURCE, confirmed: true, useKc: true,
    kcInitial: "0.3", kcMid: "1.1", kcEnd: "0.4", initialDays: "20", developmentDays: "25", midDays: "25", lateDays: "20",
    kcSource: "DEMO USER ASSUMPTIONS: Kc and 20/25/25/20-day calendar, not validated wheat guidance", kcConfirmed: true },
    root: { form: { fc: "0.30", wp: "0.12", zr: "0.6", p: "0.5", depletion: "27", initialMode: "mm",
      source: "DEMO USER ASSUMPTIONS: soil, fixed roots/p and initial state; not measured Beersheba properties", confirmed: true },
      events: ["2025-01-15", "2025-02-15", "2025-03-15"].map((date) => ({ date, net: "25" })) }, notice: "Тестовый пример: SRTM — оценка высоты; Kc, почва и поливы — тестовые допущения, не измерения или рекомендации." };
}
export type DemoStage = "season" | "water" | "root";
/** Existing APIs only; values above are inputs. All outcomes come from the server. */
export async function runGuidedDemo(accepted: boolean, bodies: { water: Record<string, unknown>; root: Record<string, unknown> },
  post: (url: string, body: unknown) => Promise<{ value: unknown }>, isCurrent: () => boolean,
  onStage: (stage: DemoStage, value: SeasonAssessment | WaterAssessment | RootZoneComparison) => void) {
  if (!accepted) throw new Error("Demo assumptions not accepted");
  const steps: Array<[DemoStage, string, unknown]> = [
    ["season", "/api/season/assess", { crop_id: DEMO_CONTEXT.cropId, latitude: Number(DEMO_CONTEXT.latitude), longitude: Number(DEMO_CONTEXT.longitude), sowing_date: DEMO_CONTEXT.start, end_date: DEMO_CONTEXT.end }],
    ["water", "/api/water/assess", bodies.water], ["root", "/api/root-zone/compare", bodies.root],
  ];
  for (const [stage, url, body] of steps) {
    if (!isCurrent()) throw new Error("Demo cancelled after context change");
    const { value } = await post(url, body);
    if (!isCurrent()) throw new Error("Demo cancelled after context change");
    const result = value as (SeasonAssessment | WaterAssessment | RootZoneComparison) & { source_is_synthetic: boolean };
    if (result.source_is_synthetic !== false) throw new Error("Пример требует реальных исторических данных NASA; синтетическая замена запрещена.");
    onStage(stage, result);
  }
  return true;
}
