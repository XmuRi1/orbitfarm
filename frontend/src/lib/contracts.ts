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