"""FAO-56 root-zone SCENARIOS, not measured soil moisture or irrigation advice.

Fixed user soil/root/p parameters; single-Kc Eq.81; explicit early-day wetting.
Eq.88 drains the remaining excess AFTER daily ET, not before it.
"""
from datetime import date
import math
from pathlib import Path
from typing import Callable

from water_balance import _number, _period_sum, assess_water, validate_water_request

FAO_CH8 = 'https://www.fao.org/4/x0490e/x0490e0e.htm'
POLICY = 'fao56_root_zone_single_kc_early_wetting_v1'
ASSUMPTIONS = ('runoff_zero', 'capillary_rise_zero', 'full_rain_infiltration',
               'wetting_before_et', 'same_day_drainage')


class IncompleteRootZoneInputs(ValueError):
    def __init__(self, reasons: list[str], coverage: dict):
        super().__init__('A complete valid ET0, potential ETc and precipitation series is required')
        self.reasons = reasons
        self.coverage = coverage


def _finite(value, label: str, minimum: float = 0) -> float:
    if not _number(value) or value < minimum:
        raise ValueError(f'{label} must be a finite number >= {minimum}')
    return value


def validate_root_zone_request(body: dict) -> dict:
    water = validate_water_request(body)
    soil = body.get('soil')
    if not isinstance(soil, dict):
        raise ValueError('soil is required')
    if soil.get('theta_unit') != 'm3/m3':
        raise ValueError('soil.theta_unit must be m3/m3; percentages are not converted')
    fc = _finite(soil.get('theta_fc'), 'soil.theta_fc')
    wp = _finite(soil.get('theta_wp'), 'soil.theta_wp')
    zr = _finite(soil.get('zr_m'), 'soil.zr_m')
    p = _finite(soil.get('p'), 'soil.p')
    if not 0 <= wp < fc <= 1 or zr <= 0 or not 0 <= p < 1:
        raise ValueError('Require 0 <= theta_wp < theta_fc <= 1, zr_m > 0 and 0 <= p < 1 (Eq.84 denominator)')
    if soil.get('acknowledge_assumptions') is not True or not isinstance(soil.get('source'), str) or not soil['source'].strip():
        raise ValueError('soil.source and acknowledge_assumptions=true are required for soil, roots, p and initial state')
    taw = 1000 * (fc - wp) * zr
    if not _number(taw) or taw <= 0 or not _number((1 - p) * taw) or (1 - p) * taw <= 0:
        raise ValueError('Derived TAW and stress denominator must be finite and positive')
    initial = body.get('initial_depletion')
    if not isinstance(initial, dict) or set(initial) not in ({'dr_mm'}, {'fraction_of_taw'}):
        raise ValueError('initial_depletion must contain exactly one of dr_mm or fraction_of_taw')
    key = next(iter(initial))
    value = _finite(initial[key], 'initial_depletion.' + key)
    if value > (1 if key == 'fraction_of_taw' else taw):
        raise ValueError('Initial depletion must be in [0, TAW], or a fraction in [0, 1]')
    dr = value * taw if key == 'fraction_of_taw' else value
    assumptions = body.get('assumptions')
    if not isinstance(assumptions, dict) or set(assumptions) != set(ASSUMPTIONS) or any(assumptions[k] is not True for k in ASSUMPTIONS):
        raise ValueError('Explicitly acknowledge all five supported scenario assumptions as true')
    events = body.get('irrigation')
    if not isinstance(events, list) or len(events) > water['duration_days']:
        raise ValueError('irrigation must be an explicit array with at most one event per season day; [] means zero irrigation')
    schedule = {}
    for event in events:
        if not isinstance(event, dict) or set(event) != {'date', 'net_mm'} or not isinstance(event['date'], str):
            raise ValueError('Each irrigation event requires date (YYYY-MM-DD) and net_mm')
        try:
            day = date.fromisoformat(event['date']).isoformat()
        except ValueError as exc:
            raise ValueError('Invalid irrigation date') from exc
        if day != event['date'] or not water['start'] <= day <= water['end'] or day in schedule:
            raise ValueError('Irrigation dates must be unique ISO dates within the selected season')
        schedule[day] = _finite(event['net_mm'], 'irrigation.net_mm')
    try:
        math.fsum(schedule.values())
    except OverflowError as exc:
        raise ValueError('Total net irrigation must be finite') from exc
    return {'water': water, 'soil': dict(soil), 'initial': dict(initial), 'initial_dr_mm': dr,
            'taw_mm': taw, 'raw_mm': p * taw, 'schedule': schedule, 'assumptions': dict(assumptions)}


def stress_coefficient(dr_mm: float, taw_mm: float, raw_mm: float) -> float:
    """FAO Eq.84; fixed user p is represented by RAW/TAW. No p adjustment."""
    if any(not _number(x) for x in (dr_mm, taw_mm, raw_mm)) or not 0 <= dr_mm <= taw_mm or not 0 <= raw_mm < taw_mm:
        raise ValueError('Require 0 <= Dr <= TAW and 0 <= RAW < TAW')
    return 1.0 if dr_mm <= raw_mm else (taw_mm - dr_mm) / (taw_mm - raw_mm)


def daily_step(dr_mm: float, taw_mm: float, raw_mm: float, rain_mm: float,
               irrigation_mm: float, potential_etc_mm: float) -> dict:
    """Eqs.81,84,85,86,88; rain/irrigation precede Ks; residual DP follows ET.

    Water above FC can supply ET within the day (FAO Eq.88), but is not retained
    in the end-of-day bucket. A marked supply cap prevents daily over-extraction.
    """
    stress_coefficient(dr_mm, taw_mm, raw_mm)  # validate state/capacity
    for label, value in (('rain_mm', rain_mm), ('irrigation_mm', irrigation_mm), ('potential_etc_mm', potential_etc_mm)):
        _finite(value, label)
    inflow = math.fsum((rain_mm, irrigation_mm))
    after_wetting = max(0.0, dr_mm - inflow)
    ks = stress_coefficient(after_wetting, taw_mm, raw_mm)
    demand = ks * potential_etc_mm
    available = math.fsum((taw_mm - dr_mm, inflow))
    adjusted = min(demand, available)
    dp = max(0.0, math.fsum((inflow, -dr_mm, -adjusted)))
    end = max(0.0, math.fsum((dr_mm, -inflow, adjusted)))
    # Roundoff only, not a hidden source/sink of meaningful water.
    if not math.isfinite(end) or end < -1e-9 or end > taw_mm + 1e-9:
        raise ValueError('Non-finite or out-of-bounds root-zone state')
    end = min(taw_mm, max(0.0, end))
    residual = math.fsum((end, -dr_mm, inflow, -adjusted, -dp))
    if abs(residual) > 1e-9:
        raise ValueError('Water balance cannot be represented at this numeric precision')
    return {'dr_after_wetting_mm': after_wetting, 'dr_end_mm': end,
            'available_water_end_mm': taw_mm - end, 'ks': ks,
            'etc_adj_eq81_mm': demand, 'etc_adj_mm': adjusted,
            'available_water_cap_applied': adjusted < demand,
            'deep_percolation_mm': dp, 'mass_balance_residual_mm': residual}


def simulate_scenario(weather: list[dict], params: dict, scenario_id: str) -> dict:
    """Pure kernel supports unknown suffixes. HTTP entry requires complete input."""
    if not weather:
        raise ValueError('Daily weather must not be empty')
    if scenario_id not in ('rainfed', 'irrigated'):
        raise ValueError('Unknown scenario')
    state = params['initial_dr_mm']
    rows = []
    for source in weather:
        irrigation = params['schedule'].get(source['date'], 0.0) if scenario_id == 'irrigated' else 0.0
        rain, etc = source.get('precipitation_mm'), source.get('etc_mm')
        reasons = []
        if state is None:
            reasons.append('previous_root_zone_state_unknown')
        for key, value in (('precipitation_mm', rain), ('potential_etc_mm', etc)):
            if not _number(value) or value < 0:
                reasons.append('missing_or_invalid:' + key)
        row = {'date': source['date'], 'dr_start_mm': state, 'dr_end_mm': None,
               'dr_after_wetting_mm': None, 'available_water_end_mm': None,
               'taw_mm': params['taw_mm'], 'raw_mm': params['raw_mm'],
               'precipitation_mm': rain if _number(rain) and rain >= 0 else None,
               'net_irrigation_mm': irrigation, 'deep_percolation_mm': None,
               'potential_etc_mm': etc if _number(etc) and etc >= 0 else None,
               'ks': None, 'etc_adj_mm': None, 'etc_adj_eq81_mm': None,
               'available_water_cap_applied': None, 'mass_balance_residual_mm': None,
               'status': 'unknown', 'stress_status': 'unknown', 'reason_codes': reasons,
               'quality_flags': list(source.get('etc_quality_flags', source.get('quality_flags', []))),
               'water_diagnostics': {'et0_reason_codes': list(source.get('et0_reason_codes', [])),
                                     'etc_reason_codes': list(source.get('etc_reason_codes', [])),
                                     'cloud_correction': source.get('cloud_correction')},
               'provenance_ref': 'shared_inputs'}
        if not reasons:
            try:
                step = daily_step(state, params['taw_mm'], params['raw_mm'], rain, irrigation, etc)
                row.update(step, status='computed', stress_status='modelled_stress' if step['ks'] < 1 else 'no_modelled_stress')
                if step['available_water_cap_applied']:
                    row['quality_flags'].append('daily_available_water_cap')
            except (ValueError, OverflowError) as exc:
                row['reason_codes'].append('root_zone_numeric_error:' + str(exc))
        state = row['dr_end_mm']
        rows.append(row)
    n = len(rows)
    computed = [r for r in rows if r['status'] == 'computed']
    complete = len(computed) == n
    summary = {'initial_dr_mm': params['initial_dr_mm'], 'final_dr_mm': state,
               'stress_days': sum(r['ks'] < 1 for r in computed) if complete else None,
               'observed_stress_days': sum(r['ks'] < 1 for r in computed),
               'etc_adj': _period_sum([r['etc_adj_mm'] for r in rows], n, ['root_zone_period_incomplete']),
               'deep_percolation': _period_sum([r['deep_percolation_mm'] for r in rows], n, ['root_zone_period_incomplete']),
               'net_irrigation_total_mm': math.fsum(r['net_irrigation_mm'] for r in rows),
               'max_abs_mass_residual_mm': max((abs(r['mass_balance_residual_mm']) for r in computed), default=None)}
    return {'scenario_id': scenario_id, 'daily': rows, 'summary': summary,
            'coverage': {'computed_days': len(computed), 'expected_days': n,
                         'fraction': len(computed) / n if n else 0,
                         'status': 'complete' if complete else 'partial' if computed else 'unknown'}}


def compare_from_water(water: dict, params: dict) -> dict:
    """Server-created water assessment only; HTTP never accepts weather arrays."""
    days = params['water']['duration_days']
    reasons = []
    for key, summary in (('et0', water['et0']), ('potential_etc', water['potential_etc']), ('precipitation', water['precipitation'])):
        if summary['days_available'] != days or summary['total_mm'] is None:
            reasons.append('complete_' + key + '_series_required')
    if len(water['daily']) != days:
        reasons.append('complete_daily_calendar_required')
    if reasons:
        raise IncompleteRootZoneInputs(reasons, {'weather_and_et': water['coverage'], 'root_zone_modelled_days': 0,
                                               'expected_days': days})
    scenarios = {key: simulate_scenario(water['daily'], params, key) for key in ('rainfed', 'irrigated')}
    a, b = (scenarios[key]['summary'] for key in ('rainfed', 'irrigated'))
    def difference(x, y):
        return y - x if x is not None and y is not None else None
    return {'schema_version': '1.0.0', 'pipeline': 'orbitfarm_root_zone_scenario_v1',
            'mode': 'scenario_not_measured', 'not_a_forecast': True,
            'crop_id': water['crop_id'], 'location': water['location'],
            'historical_period': water['historical_period'], 'duration_days': days, 'time_standard': water['time_standard'],
            'soil': {**params['soil'], 'taw_mm': params['taw_mm'], 'raw_mm': params['raw_mm'], 'status': 'user_assumption'},
            'initial_depletion': {**params['initial'], 'dr_mm_used': params['initial_dr_mm'], 'status': 'user_assumption'},
            'irrigation': [{'date': d, 'net_mm': v} for d, v in sorted(params['schedule'].items())],
            'assumptions': params['assumptions'], 'scenarios': scenarios,
            'differences': {'direction': 'irrigated_minus_rainfed',
                            'stress_days': difference(a['stress_days'], b['stress_days']),
                            'etc_adj_total_mm': difference(a['etc_adj']['total_mm'], b['etc_adj']['total_mm']),
                            'final_dr_mm': difference(a['final_dr_mm'], b['final_dr_mm']),
                            'net_irrigation_total_mm': difference(a['net_irrigation_total_mm'], b['net_irrigation_total_mm']),
                            'deep_percolation_total_mm': difference(a['deep_percolation']['total_mm'], b['deep_percolation']['total_mm'])},
            'coverage': {'nasa': water['coverage'],
                         'et0': water['et0'], 'potential_etc': water['potential_etc'], 'precipitation': water['precipitation'],
                         'root_zone': {key: value['coverage'] for key, value in scenarios.items()}},
            'provenance': {'shared_inputs': {'source': water['source'], 'water_method': water['method'],
                                           'weather_parameters': water['input_parameters'], 'time_standard': water['time_standard'],
                                           'kc': water['kc'], 'elevation': water['elevation'], 'soil_and_initial_state': params['soil']['source'],
                                           'irrigation_origin': 'explicit_user_net_root_zone_schedule'}},
            'source_is_synthetic': water['source_is_synthetic'], 'retrieved_from_cache': water['retrieved_from_cache'],
            'method': {'policy': POLICY, 'reference': FAO_CH8, 'equations': [81, 82, 83, 84, 85, 86, 88],
                       'initial_state_reference_equation': 87,
                       'timing': 'wetting -> Ks from max(0, Dr_start-P-I) -> ETc_adj -> residual DP (Eq.88) -> end state',
                       'p_and_zr': 'fixed user values; no crop defaults or daily p adjustment',
                       'initial_state': 'explicit Dr or fraction of TAW; Eq.87 is not used to invent a measured theta',
                       'daily_supply_cap': 'ETc_adj=min(Ks*potential_ETc, TAW-Dr_start+P+I); flagged if active'},
            'actual_water_balance': None,
            'limitations': [
                'Модельный сценарий, не измеренная влажность участка, прогноз или рекомендация нормы полива.',
                'Единый Kc: уравнение 81 приближённо уменьшает всю ETc; физически стресс прежде всего ограничивает транспирацию. Разделение Kcb/Ke не реализовано.',
                'Почва, фиксированные корни, p и начальное состояние заданы пользователем; независимой проверки нет.',
                'RO=0, CR=0, все осадки инфильтрируются. Это допущения, не установленные характеристики участка; малые осадки не отбрасываются.',
                'Дождь и чистый полив предшествуют Ks/ET; остаточное DP после ET выводится в тот же день по ур.88. Внутрисуточная динамика не моделируется.',
                'ETc_adj ограничена доступной водой на суточном шаге; это дополнительное численное ограничение, отмечаемое флагом daily_available_water_cap.',
                'Не оценены засоление, неоднородность почвы, динамика корней, эффективность системы полива, урожайность и экономика.',
                'actual_water_balance=null; результаты A/B являются сценарными, а не фактическим балансом поля.',
            ]}


def compare_root_zone(body: dict, *, fetcher: Callable | None = None, cache_dir: Path | None = None) -> dict:
    params = validate_root_zone_request(body)
    water = assess_water(body, fetcher=fetcher, cache_dir=cache_dir)
    return compare_from_water(water, params)
