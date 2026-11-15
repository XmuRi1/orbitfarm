export interface WaterTotal {
  total_mm: number | null;
  observed_total_mm: number | null;
  days_available: number;
  days_expected: number;
  coverage_fraction: number;
  status: "complete" | "partial" | "unknown";
  reason_codes: string[];
}

export interface WaterAssessment {
  pipeline: "orbitfarm_water_demand_v1";
  historical_period: { start: string; end: string };
  source: { name: string; url: string | null; synthetic: boolean };
  source_is_synthetic: boolean;
  retrieved_from_cache: boolean;
  et0: WaterTotal;
  potential_etc: WaterTotal;
  precipitation: WaterTotal;
  coverage?: {
    expected_days: number;
    observations: { available_values: number; expected_values: number; complete_days: number; coverage_fraction: number };
    cloud_ratio_bounded_days: number;
    cloud_ratio_bounded_dates: string[];
  };
  elevation: { used_m: number | null; verification: string; reason_codes: string[]; input: { value_m: number | null; source?: string } | null };
  kc: { status: "unknown" | "user_assumption"; reason_codes: string[]; scenario: { source?: string } | null };
  daily: Array<{
    date: string; et0_mm: number | null; etc_mm: number | null; precipitation_mm: number | null;
    kc: number | null; stage: string; et0_reason_codes: string[]; etc_reason_codes: string[]; quality_flags: string[];
    cloud_correction?: {
      policy: string; rs_rso_raw: number | null; rs_rso_used: number | null;
      bounded: boolean | null; reason: string | null; cloud_factor_raw: number | null; cloud_factor_used: number | null;
    };
    etc_quality_flags?: string[];
  }>;
  method: { name: string; references: string[]; mean_temperature: string; actual_vapour_pressure: string; policy?: string; cloud_bounds_reference?: string };
  input_parameters: Array<{ nasa_parameter: string; unit: string; source_unit: string | null; role: string; unit_status: string }>;
  actual_water_balance: null;
  limitations: string[];
}
