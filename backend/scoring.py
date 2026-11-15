"""OrbitFarm exploratory matching engine, standard-library only.

Important: scores are NEVER scientifically validated suitability scores with the
supplied draft dataset. For unverified requirements, strict mode exposes only
checks/statuses and never computes a numeric suitability score.
"""
from __future__ import annotations
import json
from datetime import date
from typing import Any

# Explicit DEMONSTRATION weights. They are not agronomic evidence.
DEMO_WEIGHTS = {
    "CLIM_001": 0.25,  # temperature, active growth
    "SOIL_001": 0.20,  # pH
    "SOIL_005": 0.10,  # texture (only positive evidence for listed preferences)
    "CLIM_009": 0.10,  # incident shortwave radiation, active growth
    "CLIM_008": 0.05,  # relative humidity, unspecified source stage
    "WATER_007": 0.30,  # seasonal crop-available water: disabled pending water balance
}
NUMERIC_IDS = {"CLIM_001", "SOIL_001", "CLIM_009", "CLIM_008"}
CLIMATE_IDS = {"CLIM_001", "CLIM_008", "CLIM_009"}


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and float('-inf') < float(value) < float('inf')


def _validate_observation(obs: dict, registry: dict) -> None:
    pid = obs.get("parameter_id")
    if pid not in registry:
        raise ValueError(f"Unknown parameter_id: {pid!r}")
    expected_unit = registry[pid].get("canonical_unit")
    if obs.get("unit") != expected_unit:
        raise ValueError(f"Unit mismatch for {pid}: expected {expected_unit!r}, got {obs.get('unit')!r}")
    value = obs.get("value")
    if value is None or isinstance(value, bool):
        raise ValueError(f"Observation {pid} must have non-null value (omit it if missing)")
    if pid in NUMERIC_IDS and not _is_number(value):
        raise ValueError(f"Observation {pid} must have a numeric value")
    if not isinstance(obs.get("source"), dict) or not obs["source"].get("name"):
        raise ValueError(f"Observation {pid} must include source.name")
    if pid in CLIMATE_IDS:
        ctx = obs.get("context") or {}
        if not ctx.get("start_date") or not ctx.get("end_date"):
            raise ValueError(f"Climate observation {pid} needs context.start_date/end_date")
        try:
            if date.fromisoformat(ctx["start_date"]) > date.fromisoformat(ctx["end_date"]):
                raise ValueError("start_date later than end_date")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid time context for {pid}: {e}") from e
    if pid == "SOIL_001":
        if not (0 <= value <= 14):
            raise ValueError("Soil pH outside 0..14")
    if pid == "CLIM_008" and not (0 <= value <= 100):
        raise ValueError("Relative humidity outside 0..100%")


def validate_farm(farm: dict, dataset: dict) -> dict[str, dict]:
    if not farm.get("farm_id"):
        raise ValueError("farm_id is mandatory")
    if not isinstance(farm.get("observations"), list):
        raise ValueError("farm.observations must be a list")
    loc = farm.get("location") or {}
    if not (_is_number(loc.get("latitude")) and -90 <= loc["latitude"] <= 90):
        raise ValueError("Valid location.latitude is mandatory")
    if not (_is_number(loc.get("longitude")) and -180 <= loc["longitude"] <= 180):
        raise ValueError("Valid location.longitude is mandatory")
    registry = dataset["parameter_registry"]
    result = {}
    for obs in farm["observations"]:
        _validate_observation(obs, registry)
        pid = obs["parameter_id"]
        if pid in result:
            raise ValueError(f"Duplicate {pid}: aggregate to one scenario value before scoring")
        result[pid] = obs
    return result


def _compatible(obs: dict, req: dict) -> tuple[bool, str]:
    if obs["unit"] != req["unit"]:
        return False, "incompatible_units"
    context = req.get("context") or {}
    stage_req = context.get("growth_stages")
    if stage_req:
        stage_observed = (obs.get("context") or {}).get("growth_stage")
        if stage_observed not in stage_req:
            return False, "growth_stage_mismatch_or_missing"
    # We deliberately refuse to match a generic climate aggregate with unknown season.
    if obs["parameter_id"] in CLIMATE_IDS:
        agg = obs.get("aggregation")
        needed = {"CLIM_001": "mean_daily_mean_over_period",
                  "CLIM_009": "mean_daily_total_over_period",
                  "CLIM_008": "mean_daily_mean_over_period"}[obs["parameter_id"]]
        if agg != needed:
            return False, "aggregation_mismatch"
    return True, "ok"


def _demo_range_score(value: float, minimum: float, maximum: float) -> float:
    """Demo policy: 100 in reported reference interval; declines outside.

    No claim that the source interval is a verified optimum or that the decline
    describes real yield loss. The denominator is a chosen UI-only heuristic.
    """
    if minimum <= value <= maximum:
        return 100.0
    span = maximum - minimum
    if span <= 0:
        return 100.0 if value == minimum else 0.0
    distance = (minimum - value) if value < minimum else (value - maximum)
    return round(max(0.0, 100.0 - 50.0 * distance / span), 1)


def _evaluate_parameter(pid: str, crop: dict, observations: dict[str,dict], *, mode: str) -> dict:
    req = crop["requirements"].get(pid)
    obs = observations.get(pid)
    result = {"parameter_id":pid, "weight": DEMO_WEIGHTS[pid],
              "status": None, "observed_value":obs["value"] if obs else None,
              "observed_unit":obs["unit"] if obs else None,
              "reference": None, "demo_factor_score_0_100":None,
              "warning":None}
    if req is None:
        result["status"] = "CROP_REQUIREMENT_MISSING"
        return result
    if req["kind"] == "reference_range":
        result["reference"] = {"min":req["data"].get("min"),"max":req["data"].get("max"),"unit":req["unit"]}
    elif req["kind"] == "category_preference":
        result["reference"] = {"preferred_categories":req["data"].get("preferred_categories"),"exhaustive":req["data"].get("exhaustive")}
    if pid == "WATER_007":
        result["status"] = "WATER_BALANCE_REQUIRED"
        result["warning"] = "Precipitation alone cannot be compared with crop water demand. Calculate crop-cycle available water/ETc."
        return result
    if obs is None:
        result["status"] = "FARM_OBSERVATION_MISSING"
        return result
    compatible, reason = _compatible(obs, req)
    if not compatible:
        result["status"] = reason.upper()
        return result
    verified = bool(req.get("verification",{}).get("approved_for_production_scoring"))
    if mode == "strict" and not verified:
        result["status"] = "REQUIREMENT_UNVERIFIED"
        result["warning"] = "No production score from team-draft thresholds."
        return result
    if pid in NUMERIC_IDS and req["kind"] == "reference_range":
        low, high = req["data"].get("min"), req["data"].get("max")
        if not (_is_number(low) and _is_number(high) and low <= high):
            result["status"] = "REFERENCE_INVALID"
            return result
        result["demo_factor_score_0_100"] = _demo_range_score(obs["value"],low,high)
        result["status"] = "DEMO_REFERENCE_MATCH" if low <= obs["value"] <= high else "DEMO_OUTSIDE_REFERENCE"
        result["warning"] = "Unverified source range and illustrative linear penalty, not agronomic yield prediction."
        return result
    if pid == "SOIL_005" and req["kind"] == "category_preference":
        preferred = req["data"].get("preferred_categories") or []
        if obs["value"] in preferred:
            result["status"] = "DEMO_LISTED_PREFERRED_TEXTURE"
            result["demo_factor_score_0_100"] = 100.0
        else:
            result["status"] = "TEXTURE_NOT_LISTED_UNKNOWN_COMPATIBILITY"
            result["warning"] = "Preference list is non-exhaustive; do not assign a penalty for unlisted textures."
        return result
    result["status"] = "UNSUPPORTED_COMPARISON_TYPE"
    return result


def score_all_crops(farm: dict, dataset: dict, *, mode: str = "demo") -> dict:
    if mode not in ("demo", "strict"):
        raise ValueError("mode must be 'demo' or 'strict'")
    observations = validate_farm(farm,dataset)
    results = []
    total_weight = sum(DEMO_WEIGHTS.values())
    for crop in dataset["crops"]:
        factors = [_evaluate_parameter(pid,crop,observations,mode=mode) for pid in DEMO_WEIGHTS]
        available = [x for x in factors if x["demo_factor_score_0_100"] is not None]
        used_weight = sum(x["weight"] for x in available)
        partial = (round(sum(x["weight"]*x["demo_factor_score_0_100"] for x in available)/used_weight,1)
                   if used_weight else None)
        results.append({
            "crop_id":crop["crop_id"], "name_en":crop["name_en"],"name_ru":crop["name_ru"],
            "suitability_score_0_100":None,
            "demo_partial_score_0_100":partial,
            "demo_weight_coverage":round(used_weight/total_weight,2),
            "factor_count_scored":len(available),"total_demo_factors":len(DEMO_WEIGHTS),
            "factors":factors,
            "status":"DEMO_PARTIAL_ONLY" if mode=="demo" and partial is not None else "NOT_SCORABLE",
            "data_confidence":"LOW" if partial is not None else "INSUFFICIENT",
            "warnings":["Crop requirements are unverified team draft.",
                        "Seasonal water balance is not implemented; cannot give an overall suitability score.",
                        "The same scenario period is not necessarily a valid crop growing season for every crop."]
        })
    if mode == "demo":
        results.sort(key=lambda x: (x["demo_partial_score_0_100"] is not None,
                                    x["demo_partial_score_0_100"] if x["demo_partial_score_0_100"] is not None else -1),reverse=True)
    return {
        "schema_version":"1.0.0", "pipeline":"orbitfarm_scoring_mvp",
        "mode":mode, "farm_id":farm["farm_id"],"demo_only": bool(farm.get("demo_only",False) or mode=="demo"),
        "source_dataset_id":dataset["dataset"]["dataset_id"],
        "observations_received":len(observations),
        "suitability_score_0_100":None,
        "scores_are_agronomically_validated":False,
        "ranking_is_only_exploratory":mode=="demo",
        "warnings":["No scientific validation of the crop requirement dataset.",
                    "Demo partial score uses arbitrary weights and linear penalties; not a forecast, yield estimate or farming recommendation.",
                    "NASA POWER is weather/climate context, not field-measured soil information.",
                    "Water balance must use effective rainfall, ET0/Kc, storage, irrigation and losses for each crop's planting window."],
        "crops":results
    }
