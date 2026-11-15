"""Descriptive comparison of three illustrative crop sequences.

This module reports catalogue facts and draft rotation advice only. It does not
estimate yield, soil nitrogen, disease pressure, or future climate suitability.
"""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Any


DEFAULT_PLANS = (
    {"plan_id": "wheat_continuous", "crop_ids": ("wheat", "wheat", "wheat")},
    {"plan_id": "wheat_chickpea_wheat", "crop_ids": ("wheat", "chickpea", "wheat")},
    {"plan_id": "wheat_chickpea_sorghum", "crop_ids": ("wheat", "chickpea", "sorghum")},
)

PLAN_NAMES_RU = {
    "wheat_continuous": "Пшеница → пшеница → пшеница",
    "wheat_chickpea_wheat": "Пшеница → нут → пшеница",
    "wheat_chickpea_sorghum": "Пшеница → нут → сорго",
}

TAXONOMY_SOURCE = "supplemental_general_botanical_knowledge_not_from_team_sheet"
PLAN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")


def _crop_traits(crop: dict[str, Any]) -> dict[str, Any]:
    requirements = crop.get("requirements") or {}
    taxonomy = requirements.get("CROP_007")
    taxonomy_data = taxonomy.get("data") if isinstance(taxonomy, dict) else None
    taxonomy_data = taxonomy_data if isinstance(taxonomy_data, dict) else {}
    provenance = taxonomy.get("provenance") if isinstance(taxonomy, dict) else None
    provenance = provenance if isinstance(provenance, dict) else {}

    rotation = requirements.get("ROT_001")
    rotation_data = rotation.get("data") if isinstance(rotation, dict) else None
    rotation_data = rotation_data if isinstance(rotation_data, dict) else {}
    rotation_provenance = rotation.get("provenance") if isinstance(rotation, dict) else None
    rotation_provenance = rotation_provenance if isinstance(rotation_provenance, dict) else {}

    family = taxonomy_data.get("botanical_family")
    crop_group = taxonomy_data.get("crop_group") or crop.get("crop_group")
    return {
        "crop_id": crop.get("crop_id"),
        "name_ru": crop.get("name_ru"),
        "name_en": crop.get("name_en"),
        "crop_group": crop_group,
        "crop_group_status": "known" if isinstance(crop_group, str) else "unknown",
        "botanical_family": family,
        "family_status": "known" if isinstance(family, str) else "unknown",
        "taxonomy_source_status": provenance.get("source_status", "unknown"),
        "rotation_advice": rotation_data,
        "rotation_advice_source_status": rotation_provenance.get("source_status", "unknown"),
    }


def _normalize_climate_context(context: Any) -> dict[str, Any]:
    if context is None:
        return {
            "status": "unknown",
            "historical_period": None,
            "location": None,
            "source_is_synthetic": None,
            "retrieved_from_cache": None,
            "observations": [],
            "future_season_conditions": "unknown",
            "explanation": "Исторические климатические данные не переданы.",
        }
    if not isinstance(context, dict):
        raise ValueError("climate_context must be a JSON object or null")

    period = context.get("historical_period")
    if period is not None and not isinstance(period, dict):
        raise ValueError("climate_context.historical_period must be an object")
    location = context.get("location")
    if location is not None and not isinstance(location, dict):
        raise ValueError("climate_context.location must be an object")
    observations = context.get("observations", [])
    if not isinstance(observations, list):
        raise ValueError("climate_context.observations must be an array")
    if any(not isinstance(item, dict) for item in observations):
        raise ValueError("climate_context.observations entries must be objects")

    return {
        "status": "historical_context_only",
        "historical_period": period,
        "location": location,
        "source_is_synthetic": context.get("source_is_synthetic"),
        "retrieved_from_cache": context.get("retrieved_from_cache"),
        "observations": [
            {
                "parameter_id": item.get("parameter_id"),
                "value": item.get("value"),
                "unit": item.get("unit"),
            }
            for item in observations
        ],
        "future_season_conditions": "unknown",
        "explanation": (
            "Исторический период показан только как контекст; он не является прогнозом "
            "климата или пригодности для следующих сезонов."
        ),
    }


def _plan_analysis(plan_id: str, crop_ids: tuple[str, ...], traits: dict[str, dict[str, Any]]) -> dict[str, Any]:
    seasons = [traits[crop_id] for crop_id in crop_ids]
    crop_occurrences: dict[str, list[int]] = defaultdict(list)
    family_occurrences: dict[str, list[int]] = defaultdict(list)
    for season_number, crop in enumerate(seasons, start=1):
        crop_occurrences[crop["crop_id"]].append(season_number)
        family = crop["botanical_family"]
        if isinstance(family, str):
            family_occurrences[family].append(season_number)

    repeated_crop_ids = {
        crop_id: season_numbers
        for crop_id, season_numbers in crop_occurrences.items()
        if len(season_numbers) > 1
    }
    repeated_families = {
        family: season_numbers
        for family, season_numbers in family_occurrences.items()
        if len(season_numbers) > 1
    }
    adjacent_crop_repeats = [
        {"from_season": index, "to_season": index + 1, "crop_id": crop_ids[index - 1]}
        for index in range(1, len(crop_ids))
        if crop_ids[index - 1] == crop_ids[index]
    ]
    crop_returns_after_intermediate = [
        {
            "crop_id": crop_id,
            "from_season": from_season,
            "to_season": to_season,
            "intervening_seasons": list(range(from_season + 1, to_season)),
            "intervening_crop_ids": list(crop_ids[from_season:to_season - 1]),
        }
        for crop_id, season_numbers in repeated_crop_ids.items()
        for from_season_index, from_season in enumerate(season_numbers)
        for to_season in season_numbers[from_season_index + 1:]
        if to_season - from_season > 1
    ]
    adjacent_family_repeats = []
    advice_matches = []
    preferred_predecessor_matches = []
    for index in range(1, len(seasons)):
        previous = seasons[index - 1]
        current = seasons[index]
        current_advice = current["rotation_advice"]
        avoided_groups = current_advice.get("avoid_repeat_groups") or []
        preferred_groups = current_advice.get("preferred_predecessor_groups") or []
        if previous["crop_group"] in avoided_groups:
            advice_matches.append({
                "from_season": index,
                "to_season": index + 1,
                "previous_crop_group": previous["crop_group"],
                "next_crop_id": current["crop_id"],
                "rule": "avoid_repeat_groups",
                "parameter_id": "ROT_001",
                "source_status": current["rotation_advice_source_status"],
            })
        if previous["crop_group"] in preferred_groups:
            preferred_predecessor_matches.append({
                "from_season": index,
                "to_season": index + 1,
                "previous_crop_group": previous["crop_group"],
                "next_crop_id": current["crop_id"],
                "rule": "preferred_predecessor_groups",
                "parameter_id": "ROT_001",
                "source_status": current["rotation_advice_source_status"],
            })

        previous_family = previous["botanical_family"]
        current_family = current["botanical_family"]
        if previous_family is not None and previous_family == current_family:
            adjacent_family_repeats.append({
                "from_season": index,
                "to_season": index + 1,
                "family": current_family,
            })

    family_returns_after_intermediate = [
        {
            "family": family,
            "from_season": from_season,
            "to_season": to_season,
            "intervening_seasons": list(range(from_season + 1, to_season)),
            "intervening_crop_ids": list(crop_ids[from_season:to_season - 1]),
        }
        for family, season_numbers in repeated_families.items()
        for from_season_index, from_season in enumerate(season_numbers)
        for to_season in season_numbers[from_season_index + 1:]
        if to_season - from_season > 1
    ]

    all_groups_known = all(crop["crop_group_status"] == "known" for crop in seasons)
    legume_seasons = [
        index for index, crop in enumerate(seasons, start=1)
        if crop["crop_group"] == "legume"
    ]
    legume_value: bool | None = True if legume_seasons else (False if all_groups_known else None)
    unique_count = len(set(crop_ids)) if all(isinstance(item, str) for item in crop_ids) else None
    used_groups = sorted({crop["crop_group"] for crop in seasons if isinstance(crop["crop_group"], str)})

    benefits = []
    if legume_value is True:
        benefits.append({
            "status": "known",
            "basis": "crop_group",
            "explanation": f"В плане есть бобовое звено в сезоне {', '.join(map(str, legume_seasons))}.",
            "used_data": [seasons[index - 1]["crop_id"] for index in legume_seasons],
            "limitation": "Наличие бобовой культуры не используется для расчёта азота, урожайности или эффекта для почвы.",
        })
    if preferred_predecessor_matches:
        benefits.append({
            "status": "known",
            "basis": "catalogue_ROT_001_preferred_predecessor",
            "explanation": "Предшествующая группа совпала с предпочтениями каталога для следующей культуры.",
            "used_data": preferred_predecessor_matches,
            "limitation": "Это непроверенный командный черновик, не количественный бонус и не доказательство эффекта.",
        })
    if unique_count is not None and unique_count > 1:
        benefits.append({
            "status": "known",
            "basis": "distinct_crop_ids",
            "explanation": f"В последовательности {unique_count} разных crop_id из {len(crop_ids)} сезонов.",
            "used_data": sorted(set(crop_ids)),
            "limitation": "Разнообразие названий не является оценкой устойчивости, здоровья почвы или урожайности.",
        })

    risks = []
    if adjacent_crop_repeats:
        risks.append({
            "status": "known",
            "basis": "adjacent_crop_repetition",
            "explanation": f"Одна и та же культура повторяется подряд в {len(adjacent_crop_repeats)} переходах.",
            "used_data": adjacent_crop_repeats,
            "limitation": "Это структурный признак плана; фактическое давление болезней и вредителей не моделируется.",
        })
    if advice_matches:
        risks.append({
            "status": "known",
            "basis": "catalogue_ROT_001_advice",
            "explanation": "Переход совпал с группой предшественников, которую каталог советует избегать.",
            "used_data": advice_matches,
            "limitation": "Совет каталога — непроверенный командный черновик, не валидированное правило или прогноз потерь.",
        })
    if adjacent_family_repeats:
        risks.append({
            "status": "known",
            "basis": "adjacent_botanical_family_repetition",
            "explanation": "Одинаковое ботаническое семейство встречается в соседних сезонах.",
            "used_data": adjacent_family_repeats,
            "rule_id": "CROP_007",
            "limitation": "Это структурное совпадение; агрономический риск или допустимый интервал не оценён. Семейства supplemental и не локально проверены.",
        })

    sequence_notes = []
    if crop_returns_after_intermediate:
        sequence_notes.append({
            "status": "known",
            "basis": "crop_returns_after_intermediate",
            "explanation": "Культура возвращается после промежуточного сезона; это отличается от повторения подряд.",
            "used_data": crop_returns_after_intermediate,
            "limitation": "Без календарных лет нельзя определить фактическую длину перерыва.",
        })
    if family_returns_after_intermediate:
        sequence_notes.append({
            "status": "known",
            "basis": "family_returns_after_intermediate",
            "explanation": "Ботаническое семейство возвращается после промежуточной культуры; этот паттерн не приравнивается к семейному повтору подряд.",
            "used_data": family_returns_after_intermediate,
            "limitation": "Данные не задают календарные интервалы; допустимый перерыв и риск неизвестны.",
        })

    return {
        "plan_id": plan_id,
        "name_ru": PLAN_NAMES_RU.get(plan_id) or " → ".join(crop["name_ru"] for crop in seasons),
        "season_count": len(seasons),
        "seasons": [
            {
                "season": index,
                "crop_id": crop["crop_id"],
                "name_ru": crop["name_ru"],
                "crop_group": crop["crop_group"],
                "crop_group_status": crop["crop_group_status"],
                "botanical_family": crop["botanical_family"],
                "family_status": crop["family_status"],
            }
            for index, crop in enumerate(seasons, start=1)
        ],
        "indicators": {
            "crop_repetition": {
                "status": "known",
                "repeated_crop_ids": repeated_crop_ids,
                "adjacent_repeats": adjacent_crop_repeats,
                "return_after_intermediate": crop_returns_after_intermediate,
            },
            "family_repetition": {
                "status": "known" if all(crop["family_status"] == "known" for crop in seasons) else "unknown",
                "repeated_families": [
                    {"family": family, "seasons": season_numbers}
                    for family, season_numbers in sorted(repeated_families.items())
                ] if all(crop["family_status"] == "known" for crop in seasons) else None,
                "adjacent_repeats": adjacent_family_repeats if all(crop["family_status"] == "known" for crop in seasons) else None,
                "return_after_intermediate": family_returns_after_intermediate if all(crop["family_status"] == "known" for crop in seasons) else None,
                "source_status": TAXONOMY_SOURCE if all(crop["family_status"] == "known" for crop in seasons) else "unknown",
            },
            "legume_presence": {
                "status": "known" if legume_value is not None else "unknown",
                "present": legume_value,
                "seasons": legume_seasons if legume_value is not None else None,
                "used_data": "crop_group",
            },
            "sequence_diversity": {
                "status": "known" if unique_count is not None else "unknown",
                "distinct_crop_count": unique_count,
                "season_count": len(crop_ids),
                "distinct_crop_groups": used_groups if all_groups_known else None,
            },
        },
        "potential_benefits": benefits,
        "potential_risks": risks,
        "sequence_notes": sequence_notes,
        "climate_fit_for_future_seasons": {
            "status": "unknown",
            "explanation": "Данные будущих сезонов и посевные годы плана не заданы.",
        },
        "limitations": [
            "План содержит только порядок культур; конкретные годы, сроки, сорта и история участка не заданы.",
            "Повтор семейства и crop_group — описательные признаки, а не научная оценка риска.",
            "Севооборот не оценивает урожайность, азотный баланс, болезни, вредителей, экономику или пригодность.",
            "Советы по предшественникам являются непроверенным командным черновиком.",
        ],
    }


def compare_rotation_plans(
    dataset: dict,
    climate_context: Any = None,
    plans: Any = None,
) -> dict[str, Any]:
    """Compare demo plans by default or two/three user plans; never return a score."""
    crops_by_id = {crop.get("crop_id"): crop for crop in dataset.get("crops", [])}
    example_plans = _normalize_plans(None, crops_by_id)
    selected_plans = _normalize_plans(plans, crops_by_id)
    missing_ids = sorted({
        crop_id
        for plan in (*example_plans, *selected_plans)
        for crop_id in plan["crop_ids"]
        if crop_id not in crops_by_id
    })
    if missing_ids:
        raise ValueError("Rotation plans reference unknown crop ids: " + ", ".join(missing_ids))
    traits = {crop_id: _crop_traits(crop) for crop_id, crop in crops_by_id.items()}
    return {
        "schema_version": "1.0.0",
        "pipeline": "orbitfarm_rotation_planner_v1",
        "mode": "descriptive_no_score",
        "example_plans": [
            {
                "plan_id": plan["plan_id"],
                "name_ru": PLAN_NAMES_RU[plan["plan_id"]],
                "crop_ids": list(plan["crop_ids"]),
            }
            for plan in example_plans
        ],
        "plans": [
            _plan_analysis(plan["plan_id"], plan["crop_ids"], traits)
            for plan in selected_plans
        ],
        "climate_context": _normalize_climate_context(climate_context),
        "comparison_limitations": [
            "Планы демонстрационные и не задают фактические годы следующих сезонов.",
            "Исторические NASA POWER observations не являются прогнозом будущего климата.",
            "Численные бонусы и общий рейтинг севооборота не рассчитываются.",
        ],
    }


def get_rotation_options(dataset: dict) -> dict[str, Any]:
    """Return catalogue crop choices and the unchanged demonstration examples."""
    return {
        "available_crops": [
            {
                "crop_id": crop.get("crop_id"),
                "name_ru": crop.get("name_ru"),
                "name_en": crop.get("name_en"),
                "crop_group": _crop_traits(crop)["crop_group"],
                "botanical_family": _crop_traits(crop)["botanical_family"],
            }
            for crop in dataset.get("crops", [])
        ],
        "example_plans": [
            {
                "plan_id": plan["plan_id"],
                "name_ru": PLAN_NAMES_RU[plan["plan_id"]],
                "crop_ids": list(plan["crop_ids"]),
            }
            for plan in DEFAULT_PLANS
        ],
    }


def _normalize_plans(plans: Any, crops_by_id: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    if plans is None:
        return DEFAULT_PLANS
    if not isinstance(plans, list) or not 2 <= len(plans) <= 3:
        raise ValueError("plans must contain two or three plan objects")

    normalized = []
    seen_plan_ids = set()
    for index, plan in enumerate(plans, start=1):
        if not isinstance(plan, dict):
            raise ValueError(f"plans[{index - 1}] must be an object")
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or not PLAN_ID_PATTERN.fullmatch(plan_id):
            raise ValueError(f"plans[{index - 1}].plan_id must be 1-40 letters, numbers, underscores, or hyphens")
        if plan_id in seen_plan_ids:
            raise ValueError(f"plan_id must be unique: {plan_id}")
        seen_plan_ids.add(plan_id)

        crop_ids = plan.get("crop_ids")
        if not isinstance(crop_ids, list) or len(crop_ids) != 3:
            raise ValueError(f"plans[{index - 1}].crop_ids must contain exactly three seasons")
        if any(not isinstance(crop_id, str) for crop_id in crop_ids):
            raise ValueError(f"plans[{index - 1}].crop_ids entries must be strings")
        unknown_ids = [crop_id for crop_id in crop_ids if crop_id not in crops_by_id]
        if unknown_ids:
            raise ValueError(f"plans[{index - 1}] contains unknown crop_id: {', '.join(unknown_ids)}")
        normalized.append({"plan_id": plan_id, "crop_ids": tuple(crop_ids)})
    return tuple(normalized)