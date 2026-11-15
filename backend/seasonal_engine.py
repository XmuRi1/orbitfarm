"""Historical, daily-data seasonal description. No suitability or yield model."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from api_contracts import CROPS
from live_pipeline import get_daily_climate, validate_request
from nasa_power import fetch_power_daily

METRICS = {
    'mean_temperature': ('CLIM_001', '°C', 'mean_daily_mean_over_period', 'mean'),
    'minimum_temperature': ('CLIM_002', '°C', 'minimum_daily_minimum_over_period', 'min'),
    'maximum_temperature': ('CLIM_003', '°C', 'maximum_daily_maximum_over_period', 'max'),
    'total_precipitation': ('CLIM_007', 'mm per period', 'sum_daily_precipitation_over_period', 'sum'),
    'rainy_days': ('CLIM_007', 'days', 'count_daily_precipitation_gt_0_mm', 'count'),
    'mean_solar_radiation': ('CLIM_009', 'MJ/m²/day', 'mean_daily_total_over_period', 'mean'),
    'mean_relative_humidity': ('CLIM_008', '%', 'mean_daily_mean_over_period', 'mean'),
}


def validate_season_request(body: dict, dataset: dict = CROPS) -> dict:
    if not isinstance(body, dict):
        raise ValueError('Request body must be a JSON object')
    crop_id = body.get('crop_id')
    if not isinstance(crop_id, str) or not any(crop['crop_id'] == crop_id for crop in dataset['crops']):
        raise ValueError('crop_id must be an existing catalogue crop ID')
    for field in ('sowing_date', 'end_date'):
        value = body.get(field)
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{field} must be a valid YYYY-MM-DD date') from exc
    params = validate_request({
        'latitude': body.get('latitude'), 'longitude': body.get('longitude'),
        'start': body['sowing_date'], 'end': body['end_date'], 'mode': 'strict',
    })
    expected = {'start': params['start'], 'end': params['end']}
    if 'historical_period' in body and body['historical_period'] != expected:
        raise ValueError('historical_period must exactly match sowing_date and end_date')
    return {**params, 'crop_id': crop_id}


def _metric(series: dict, unit: str, aggregation: str, method: str) -> dict:
    values = [row['value'] for row in series['values'] if row['value'] is not None]
    available, expected = len(values), len(series['values'])
    complete = available == expected
    observed = None
    if values:
        if method == 'sum':
            observed = sum(values)
        elif method == 'count':
            observed = sum(value > 0 for value in values)
        elif method == 'min':
            observed = min(values)
        elif method == 'max':
            observed = max(values)
        else:
            observed = sum(values) / available
        observed = round(observed, 4)
    value = observed if complete or method not in ('sum', 'count') else None
    return {
        'parameter_id': series['parameter_id'], 'value': value, 'unit': unit,
        'aggregation': aggregation, 'status': 'complete' if complete else 'partial' if available else 'missing',
        'days_available': available, 'days_expected': expected,
        'observed_value': observed,
        'reason': None if complete else (
            'Наблюдений нет; пропуски не заполнены.' if not available else
            'Полное сезонное значение неизвестно; observed_value относится только к доступным дням.'
        ),
    }


def _requirements(crop: dict, metrics: dict) -> list[dict]:
    by_parameter = {metric['parameter_id']: metric for name, metric in metrics.items() if name != 'rainy_days'}
    results = []
    for parameter_id in (*by_parameter, 'WATER_007'):
        requirement = crop.get('requirements', {}).get(parameter_id)
        observation = by_parameter.get(parameter_id)
        reasons = []
        reference = None
        if requirement is None:
            reasons.append('Требование культуры отсутствует в каталоге.')
        elif parameter_id == 'WATER_007':
            reasons.append('Водный баланс не реализован; осадки не равны доступной культуре воде.')
        else:
            context = requirement.get('context') or {}
            verification = requirement.get('verification') or {}
            if not (verification.get('agronomic_verified') and verification.get('approved_for_production_scoring')):
                reasons.append('Требование — непроверенный черновик, не подтверждённая критическая граница.')
            if observation['unit'] != requirement.get('unit'):
                reasons.append('Несовместимые единицы наблюдения и требования.')
            if context.get('growth_stages'):
                reasons.append('Даты стадий роста неизвестны; весь сезон нельзя приравнять к отдельной фазе.')
            if context.get('time_window') != 'whole_crop_cycle' or context.get('aggregation') != observation['aggregation']:
                reasons.append('Временной контекст или агрегация требования не совпадают с сезонным наблюдением.')
            if observation['status'] != 'complete':
                reasons.append('Наблюдения за сезон неполные или отсутствуют.')
            if requirement.get('kind') == 'reference_range':
                data = requirement.get('data') or {}
                low, high = data.get('min'), data.get('max')
                if type(low) in (int, float) and type(high) in (int, float) and low <= high:
                    reference = {'min': low, 'max': high, 'unit': requirement.get('unit')}
            if reference is None:
                reasons.append('Нет совместимого численного диапазона для сравнения.')
        comparison = None
        if not reasons:
            comparison = 'within_reference' if reference['min'] <= observation['value'] <= reference['max'] else 'outside_reference'
        results.append({
            'parameter_id': parameter_id, 'status': 'unknown' if reasons else 'descriptive_comparison',
            'observed_value': observation['value'] if observation else None,
            'reference': reference, 'comparison': comparison, 'reasons': reasons,
            'requirement': requirement,
        })
    return results


def summarize_season(params: dict, daily: dict, *, dataset: dict = CROPS) -> dict:
    """Use daily means/minima/maxima separately; never derive extremes from means."""
    period = {'start': params['start'], 'end': params['end']}
    location = {'latitude': params['latitude'], 'longitude': params['longitude']}
    if daily['period'] != period or daily['location'] != location or daily['time_standard'] != 'LST':
        raise ValueError('Daily data must match the requested period, location and LST standard')
    crop = next(crop for crop in dataset['crops'] if crop['crop_id'] == params['crop_id'])
    series = {item['parameter_id']: item for item in daily['parameters']}
    metrics = {name: _metric(series[pid], unit, aggregation, method)
               for name, (pid, unit, aggregation, method) in METRICS.items()}
    days = (date.fromisoformat(params['end']) - date.fromisoformat(params['start'])).days + 1
    coverages = {pid: item['coverage'] for pid, item in series.items()}
    complete_days = sum(all(item['values'][index]['value'] is not None for item in series.values()) for index in range(days))
    available = sum(item['available_days'] for item in coverages.values())
    return {
        'schema_version': '1.0.0', 'pipeline': 'orbitfarm_seasonal_climate_v1',
        'mode': 'historical_daily_description', 'not_a_forecast': True,
        'crop': {'crop_id': crop['crop_id'], 'name_ru': crop['name_ru'], 'name_en': crop['name_en']},
        'location': location, 'historical_period': period,
        'season': {'sowing_date': params['start'], 'end_date': params['end'],
                   'duration_days': days, 'day_count_convention': 'inclusive', 'growth_stages': 'unknown'},
        'time_standard': daily['time_standard'], 'metrics': metrics,
        'coverage': {'expected_days': days, 'complete_days': complete_days,
                     'available_values': available, 'expected_values': days * len(series),
                     'fraction': round(available / (days * len(series)), 6),
                     'by_parameter': coverages},
        'daily': daily, 'source': daily['source'],
        'source_is_synthetic': daily['source']['synthetic'],
        'suitability_score_0_100': None, 'water_balance': None,
        'crop_requirements': _requirements(crop, metrics),
        'limitations': [
            'Исторические данные NASA POWER описывают регион, а не измерения на поле; это не прогноз.',
            'Даты задаёт пользователь: длительность окна не подтверждает зрелость культуры или стадии роста.',
            'Средние и экстремумы при пропусках относятся только к доступным дням; интерполяции нет.',
            'Сумма осадков и число дождливых дней за весь сезон неизвестны при пропущенных осадках.',
            'Дождливый день определён как PRECTOTCORR > 0 мм; это не порог агрономического стресса.',
            'Черновые требования не являются критическими границами; пригодность, урожайность и водный баланс не рассчитаны.',
        ],
    }


def assess_season(body: dict, *, dataset: dict = CROPS, fetcher: Callable | None = None,
                  cache_dir: Path | None = None) -> dict:
    params = validate_season_request(body, dataset)
    daily, cached = get_daily_climate(params, fetcher=fetcher or fetch_power_daily, cache_dir=cache_dir)
    result = summarize_season(params, daily, dataset=dataset)
    result['retrieved_from_cache'] = cached
    return result
