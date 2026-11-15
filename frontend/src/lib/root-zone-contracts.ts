import type { WaterTotal } from "./water-contracts";

export interface RootZoneDay {
  date: string;
  dr_start_mm: number | null;
  dr_after_wetting_mm: number | null;
  dr_end_mm: number | null;
  raw_mm: number;
  taw_mm: number;
  precipitation_mm: number | null;
  net_irrigation_mm: number;
  deep_percolation_mm: number | null;
  potential_etc_mm: number | null;
  ks: number | null;
  etc_adj_mm: number | null;
  stress_status: string;
  reason_codes: string[];
  quality_flags: string[];
}
export interface RootZoneScenario {
  daily: RootZoneDay[];
  summary: {
    initial_dr_mm: number;
    final_dr_mm: number | null;
    stress_days: number | null;
    etc_adj: WaterTotal;
    deep_percolation: WaterTotal;
    net_irrigation_total_mm: number;
  };
  coverage: { computed_days: number; expected_days: number; fraction: number; status: string };
}
export interface RootZoneComparison {
  mode: "scenario_not_measured";
  soil: { taw_mm: number; raw_mm: number; source: string };
  scenarios: { rainfed: RootZoneScenario; irrigated: RootZoneScenario };
  differences: {
    direction: "irrigated_minus_rainfed";
    stress_days: number | null;
    etc_adj_total_mm: number | null;
    final_dr_mm: number | null;
    net_irrigation_total_mm: number | null;
    deep_percolation_total_mm: number | null;
  };
  coverage: { nasa: { observations: { available_values: number; expected_values: number } }; et0: WaterTotal; potential_etc: WaterTotal };
  method: { policy: string; reference: string; timing: string };
  limitations: string[];
  actual_water_balance: null;
}
