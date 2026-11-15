export interface AssessRequest {
  latitude: number;
  longitude: number;
  start: string;
  end: string;
  farm_id: string;
  mode: "demo" | "strict";
  growth_stage: "active_growth" | null;
  soil_observations: SoilObservation[];
}

export interface SoilObservation {
  parameter_id: "SOIL_001" | "SOIL_005";
  value: number | string;
  unit: "pH" | "USDA / FAO texture class";
  context: { soil_depth_cm: null };
  source: { name: "user_entered_unverified"; synthetic: false };
}

export interface Observation {
  parameter_id: string;
  value: number | string;
  unit: string;
  aggregation?: string;
  context?: {
    start_date?: string;
    end_date?: string;
    growth_stage?: string | null;
    time_standard?: string;
    days_available?: number;
    days_requested?: number;
    [key: string]: unknown;
  };
  source: {
    name: string;
    url: string | null;
    synthetic: boolean;
  };
}

export interface CropFactor {
  parameter_id: string;
  weight: number;
  status: string;
  observed_value: number | string | null;
  observed_unit: string | null;
  reference: {
    min?: number | null;
    max?: number | null;
    unit?: string;
    preferred_categories?: string[] | null;
    exhaustive?: boolean;
  } | null;
  demo_factor_score_0_100: number | null;
  warning: string | null;
}

export interface CropAssessment {
  crop_id: string;
  name_en: string;
  name_ru: string;
  suitability_score_0_100: number | null;
  demo_partial_score_0_100: number | null;
  demo_weight_coverage: number;
  factor_count_scored: number;
  total_demo_factors: number;
  factors: CropFactor[];
  status: string;
  data_confidence: string;
  warnings: string[];
}

export interface NasaAssessResponse {
  pipeline: string;
  status: string;
  is_live_source: boolean;
  source_is_synthetic: boolean;
  retrieved_from_cache: boolean;
  source_url: string;
  historical_period: { start: string; end: string };
  not_a_forecast: boolean;
  farm: {
    farm_id: string;
    demo_only: boolean;
    location: { latitude: number; longitude: number };
    scenario: {
      date_start: string;
      date_end: string;
      stage_assigned_by_user: string | null;
      kind: string;
    };
    observations: Observation[];
    water_balance: unknown;
    data_gaps: string[];
    warnings: string[];
  };
  assessment: {
    mode: "demo" | "strict";
    farm_id: string;
    demo_only: boolean;
    observations_received: number;
    suitability_score_0_100: number | null;
    scores_are_agronomically_validated: boolean;
    ranking_is_only_exploratory: boolean;
    warnings: string[];
    crops: CropAssessment[];
  };
  warnings: string[];
}

export interface ApiError {
  error?: string;
  detail?: string;
}

export interface RotationClimateContext {
  historical_period: { start: string; end: string };
  location: { latitude: number; longitude: number };
  source_is_synthetic: boolean;
  retrieved_from_cache: boolean;
  observations: Observation[];
}

export interface RotationFinding {
  status: "known" | "unknown";
  basis: string;
  explanation: string;
  used_data: unknown;
  limitation: string;
}

export interface RotationPlan {
  plan_id: string;
  name_ru: string;
  season_count: number;
  seasons: Array<{
    season: number;
    crop_id: string;
    name_ru: string;
    crop_group: string | null;
    crop_group_status: "known" | "unknown";
    botanical_family: string | null;
    family_status: "known" | "unknown";
  }>;
  indicators: {
    crop_repetition: {
      status: "known" | "unknown";
      repeated_crop_ids: Record<string, number[]> | null;
      adjacent_repeats: Array<{ from_season: number; to_season: number; crop_id: string }> | null;
      return_after_intermediate: Array<{
        crop_id: string;
        from_season: number;
        to_season: number;
        intervening_seasons: number[];
        intervening_crop_ids: string[];
      }> | null;
    };
    family_repetition: {
      status: "known" | "unknown";
      repeated_families: Array<{ family: string; seasons: number[] }> | null;
      adjacent_repeats: Array<{ from_season: number; to_season: number; family: string }> | null;
      return_after_intermediate: Array<{
        family: string;
        from_season: number;
        to_season: number;
        intervening_seasons: number[];
        intervening_crop_ids: string[];
      }> | null;
      source_status: string;
    };
    legume_presence: {
      status: "known" | "unknown";
      present: boolean | null;
      seasons: number[] | null;
      used_data: string;
    };
    sequence_diversity: {
      status: "known" | "unknown";
      distinct_crop_count: number | null;
      season_count: number;
      distinct_crop_groups: string[] | null;
    };
  };
  potential_benefits: RotationFinding[];
  potential_risks: RotationFinding[];
  sequence_notes: RotationFinding[];
  climate_fit_for_future_seasons: { status: "unknown"; explanation: string };
  limitations: string[];
}

export interface RotationCompareResponse {
  schema_version: string;
  pipeline: string;
  mode: "descriptive_no_score";
  example_plans: Array<{ plan_id: string; name_ru: string; crop_ids: string[] }>;
  plans: RotationPlan[];
  climate_context: {
    status: "unknown" | "historical_context_only";
    historical_period: { start: string; end: string } | null;
    location: { latitude: number; longitude: number } | null;
    source_is_synthetic: boolean | null;
    retrieved_from_cache: boolean | null;
    observations: Array<{ parameter_id?: string; value?: number | string; unit?: string }>;
    future_season_conditions: "unknown";
    explanation: string;
  };
  comparison_limitations: string[];
}

export interface RotationOptionsResponse {
  available_crops: Array<{
    crop_id: string;
    name_ru: string;
    name_en: string;
    crop_group: string | null;
    botanical_family: string | null;
  }>;
  example_plans: Array<{ plan_id: string; name_ru: string; crop_ids: string[] }>;
}