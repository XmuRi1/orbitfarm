export interface SeasonMetric {
  parameter_id: string;
  value: number | null;
  observed_value: number | null;
  unit: string;
  aggregation: string;
  status: "complete" | "partial" | "missing";
  days_available: number;
  days_expected: number;
  reason: string | null;
}

export interface SeasonAssessment {
  schema_version: string;
  pipeline: "orbitfarm_seasonal_climate_v1";
  mode: "historical_daily_description";
  not_a_forecast: true;
  crop: { crop_id: string; name_ru: string; name_en: string };
  location: { latitude: number; longitude: number };
  historical_period: { start: string; end: string };
  season: { sowing_date: string; end_date: string; duration_days: number; day_count_convention: "inclusive"; growth_stages: "unknown" };
  time_standard: "LST";
  metrics: Record<string, SeasonMetric>;
  coverage: {
    expected_days: number;
    complete_days: number;
    available_values: number;
    expected_values: number;
    fraction: number;
    by_parameter: Record<string, { expected_days: number; available_days: number; fraction: number; missing_dates: string[] }>;
  };
  source: { name: string; url: string | null; synthetic: boolean };
  source_is_synthetic: boolean;
  retrieved_from_cache: boolean;
  suitability_score_0_100: null;
  water_balance: null;
  daily: {
    time_standard: "LST";
    time_standard_basis: "response_header" | "explicit_request";
    parameters: Array<{
      parameter_id: string; nasa_parameter: string; unit: string; source_unit: string | null;
      values: Array<{ date: string; value: number | null; missing_reason: string | null }>;
    }>;
  };
  crop_requirements: Array<{
    parameter_id: string; status: "unknown" | "descriptive_comparison";
    reference: { min: number; max: number; unit: string } | null;
    comparison: "within_reference" | "outside_reference" | null;
    reasons: string[];
  }>;
  limitations: string[];
}
