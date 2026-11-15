"""FAO-56 daily grass-reference ET0 and explicit scenario ETc, not a soil balance.

No missing weather, height, crop coefficient or stage length is invented here.
"""
from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
from typing import Callable

from live_pipeline import get_daily_climate
from nasa_power import WATER_PARAMETERS, fetch_power_daily
from seasonal_engine import validate_season_request

FAO_CH2 = 'https://www.fao.org/4/x0490e/x0490e06.htm'
FAO_CH3 = 'https://www.fao.org/4/x0490e/x0490e07.htm'
FAO_CH4 = 'https://www.fao.org/4/x0490e/x0490e08.htm'
FAO_CH6 = 'https://www.fao.org/4/x0490e/x0490e0b.htm'
ASCE_2005 = 'https://content.mesonet.org/mesonet/site_files/ASCE_Evapotranspiration_Formula.pdf#page=30'
RADIATION_POLICY = 'fao56_pm_asce2005_cloud_bounds'
ET0_INPUTS = {
    'T2M_MIN': '°C', 'T2M_MAX': '°C', 'ALLSKY_SFC_SW_DWN': 'MJ/m²/day',
    'WS2M': 'm/s', 'T2MDEW': '°C', 'PS': 'kPa',
}


def _number(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def saturation_pressure(temperature_c: float) -> float:
    """FAO-56 Eq. 11, kPa. The empirical expression is undefined at -237.3 C."""
    if not _number(temperature_c) or temperature_c <= -237.3:
        raise ValueError('Temperature outside the saturation-pressure formula domain')
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def solar_geometry(day: date, latitude: float) -> dict:
    """FAO-56 Eqs. 21-25; 365-day astronomical convention, including leap years."""
    if not _number(latitude) or not -90 <= latitude <= 90:
        raise ValueError('Invalid latitude')
    j = day.timetuple().tm_yday
    phi = math.radians(latitude)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    declination = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    sunset = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(declination))))
    ra = 24 * 60 / math.pi * 0.0820 * dr * (
        sunset * math.sin(phi) * math.sin(declination) + math.cos(phi) * math.cos(declination) * math.sin(sunset))
    return {'day_of_year': j, 'ra_mj_m2_day': max(0.0, ra), 'daylight_hours': 24 / math.pi * sunset}


def radiation_balance(day: date, latitude: float, elevation_m: float, tmin_c: float,
                      tmax_c: float, solar_mj_m2_day: float, ea_kpa: float) -> dict:
    """FAO-56 Eqs. 37-40 with ASCE-EWRI 2005 Eq.18 cloud-ratio bounds.

    Only the cloud factor uses the bounded ratio; measured Rs and Rns stay intact.
    FAO constants, including sigma=4.903e-9, are retained.
    """
    if not _number(elevation_m):
        raise ValueError('A known site elevation is required for clear-sky radiation')
    geometry = solar_geometry(day, latitude)
    rso = (0.75 + 2e-5 * elevation_m) * geometry['ra_mj_m2_day']
    if rso <= 0:
        raise ValueError('Clear-sky radiation is zero; polar-night cloudiness is not modelled')
    ratio_raw = solar_mj_m2_day / rso
    cloud_factor_raw = 1.35 * ratio_raw - 0.35
    if not _number(ratio_raw) or not _number(cloud_factor_raw):
        raise ValueError('Non-finite cloud ratio or factor')
    ratio = max(0.3, min(ratio_raw, 1.0))
    bounded_reason = 'rs_rso_below_0_3' if ratio_raw < 0.3 else 'rs_rso_above_1_0' if ratio_raw > 1 else None
    humidity_factor = 0.34 - 0.14 * math.sqrt(ea_kpa)
    cloud_factor = 1.35 * ratio - 0.35
    if humidity_factor < 0:
        raise ValueError('Eq. 39 outside its empirical domain; no assumed cloudiness or fallback')
    rns = (1 - 0.23) * solar_mj_m2_day
    rnl = 4.903e-9 * ((tmax_c + 273.16) ** 4 + (tmin_c + 273.16) ** 4) / 2 * humidity_factor * cloud_factor
    return {**geometry, 'rso_mj_m2_day': rso, 'rs_rso_raw': ratio_raw, 'rs_rso_used': ratio,
            'cloud_correction': {'policy': RADIATION_POLICY, 'rs_rso_raw': ratio_raw,
                                 'rs_rso_used': ratio, 'bounded': bounded_reason is not None,
                                 'reason': bounded_reason, 'cloud_factor_raw': cloud_factor_raw,
                                 'cloud_factor_used': cloud_factor},
            'rns_mj_m2_day': rns, 'rnl_mj_m2_day': rnl, 'rn_mj_m2_day': rns - rnl}


def reference_et0(day: date, latitude: float, elevation_m: float | None, inputs: dict) -> dict:
    """FAO-56 Eq. 6, daily grass reference; all inputs are normalized SI units.

    Tmean=(Tmax+Tmin)/2 (Eq. 9), G=0 (Eq. 42), ea from dewpoint (Eq. 14).
    Missing dewpoint/pressure/wind are NOT estimated from other variables.
    """
    missing = [key for key in ET0_INPUTS if not _number(inputs.get(key))]
    reasons = [f'missing_or_invalid:{key}' for key in missing]
    if not _number(elevation_m):
        reasons.append('known_sourced_elevation_required')
    result = {'value': None, 'unit': 'mm/day', 'status': 'unknown', 'reason_codes': reasons,
              'quality_flags': [], 'intermediates': None,
              'cloud_correction': {'policy': RADIATION_POLICY, 'rs_rso_raw': None,
                                   'rs_rso_used': None, 'bounded': None, 'reason': 'not_evaluated',
                                   'cloud_factor_raw': None, 'cloud_factor_used': None}}
    if reasons:
        return result
    tmin, tmax = inputs['T2M_MIN'], inputs['T2M_MAX']
    dew, wind, pressure, solar = (inputs[key] for key in ('T2MDEW', 'WS2M', 'PS', 'ALLSKY_SFC_SW_DWN'))
    if tmin > tmax or min(tmin, tmax, dew) <= -237.3 or wind < 0 or pressure <= 0 or solar < 0:
        result['reason_codes'] = ['inconsistent_or_outside_physical_domain']
        return result
    try:
        tmean = (tmin + tmax) / 2
        es = (saturation_pressure(tmin) + saturation_pressure(tmax)) / 2
        ea = saturation_pressure(dew)
        if ea > es + 1e-9 or es >= pressure:
            raise ValueError('Vapour pressure inconsistent with temperature/pressure')
        delta = 4098 * saturation_pressure(tmean) / (tmean + 237.3) ** 2  # Eq. 13
        gamma = 0.000665 * pressure  # Eq. 8; PS is measured/modelled, not inferred from height.
        radiation = radiation_balance(day, latitude, elevation_m, tmin, tmax, solar, ea)
        result['cloud_correction'] = radiation['cloud_correction']
        if radiation['cloud_correction']['bounded']:
            result['quality_flags'].append('cloud_ratio_bounded_asce2005')
        u2 = max(0.5, wind)  # FAO-56 Ch.3 low-wind guidance, only for an OBSERVED value.
        numerator = 0.408 * delta * radiation['rn_mj_m2_day'] + gamma * 900 / (tmean + 273) * u2 * (es - ea)
        value = numerator / (delta + gamma * (1 + 0.34 * u2))
        if not math.isfinite(value) or value < 0:
            raise ValueError('Negative/non-finite ET0; condensation is not modelled')
        if wind < 0.5:
            result['quality_flags'].append('observed_wind_raised_to_fao56_minimum_0_5_m_s')
        if radiation['rs_rso_raw'] > 1:
            result['quality_flags'].append('rs_rso_capped_at_1_per_equation_39')
        result.update(value=value, status='computed', intermediates={
            **radiation, 'tmean_c': tmean, 'es_kpa': es, 'ea_kpa': ea, 'vpd_kpa': es - ea,
            'delta_kpa_per_c': delta, 'gamma_kpa_per_c': gamma, 'u2_used_m_s': u2, 'g_mj_m2_day': 0.0,
        })
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        result['reason_codes'] = ['fao56_domain_error:' + str(exc)]
    return result


STAGES = ('initial', 'development', 'mid', 'late')


def crop_coefficient_curve(scenario: dict | None, days: int, crop_id: str) -> tuple[list | None, list[str]]:
    """FAO-56 Eq. 66, 1-based days; user-supplied single Kc, not a catalogue default."""
    if scenario is None:
        return None, ['kc_and_stage_calendar_unknown']
    if not isinstance(scenario, dict) or scenario.get('type') != 'user_defined':
        raise ValueError('kc_scenario must be null or an explicit type=user_defined object')
    if scenario.get('crop_id') != crop_id:
        raise ValueError('kc_scenario.crop_id must match the requested crop')
    if scenario.get('reference_surface', 'grass') != 'grass':
        raise ValueError('Kc must use the FAO-56 grass reference; alfalfa coefficients are not automatically converted')
    reasons = []
    if scenario.get('acknowledge_assumptions') is not True:
        reasons.append('kc_user_assumptions_not_acknowledged')
    if not isinstance(scenario.get('source'), str) or not scenario['source'].strip():
        reasons.append('kc_source_not_supplied')
    coefficients = [scenario.get(key) for key in ('kc_initial', 'kc_mid', 'kc_end')]
    for value in coefficients:
        if value is not None and (not _number(value) or value < 0):
            raise ValueError('Kc values must be finite non-negative numbers or null')
    if any(value is None for value in coefficients):
        reasons.append('kc_values_missing')
    lengths = scenario.get('stage_lengths_days')
    if lengths is not None and not isinstance(lengths, dict):
        raise ValueError('stage_lengths_days must be an object or null')
    lengths = [lengths.get(stage) for stage in STAGES] if lengths else [None] * 4
    for length in lengths:
        if length is not None and (type(length) is not int or not 1 <= length <= 366):
            raise ValueError('Stage lengths must be integer days in 1..366 or null')
    if any(length is None for length in lengths):
        reasons.append('stage_calendar_missing')
    elif sum(lengths) != days:
        reasons.append('stage_calendar_does_not_cover_exact_requested_period')
    if reasons:
        return None, reasons
    initial, mid, end = coefficients
    previous = 0
    curve = []
    for stage, length in zip(STAGES, lengths):
        start_kc, end_kc = {'initial': (initial, initial), 'development': (initial, mid),
                            'mid': (mid, mid), 'late': (mid, end)}[stage]
        for i in range(1, length + 1):
            curve.append({'day_number': previous + i, 'stage': stage,
                          'kc': start_kc + i / length * (end_kc - start_kc)})
        previous += length
    return curve, []


def validate_water_request(body: dict) -> dict:
    params = validate_season_request(body)
    days = (date.fromisoformat(params['end']) - date.fromisoformat(params['start'])).days + 1
    elevation = body.get('elevation')
    elevation_reasons = []
    height = None
    if elevation is None:
        elevation_reasons.append('known_sourced_elevation_required')
    else:
        if not isinstance(elevation, dict):
            raise ValueError('elevation must be an object or null')
        value = elevation.get('value_m')
        if value is not None and (not _number(value) or not -500 <= value <= 9000):
            raise ValueError('Elevation must be finite metres in the supported land range -500..9000')
        if value is None or not isinstance(elevation.get('source'), str) or not elevation['source'].strip() or elevation.get('confirmed') is not True:
            elevation_reasons.append('elevation_value_source_and_user_confirmation_required')
        else:
            height = value
    scenario = body.get('kc_scenario')
    curve, kc_reasons = crop_coefficient_curve(scenario, days, params['crop_id'])
    return {**params, 'duration_days': days, 'elevation': elevation, 'elevation_used_m': height,
            'elevation_reason_codes': elevation_reasons, 'kc_scenario': scenario,
            'kc_curve': curve, 'kc_reason_codes': kc_reasons}


def _period_sum(values: list, days: int, unknown_reasons: list[str]) -> dict:
    available = [value for value in values if value is not None]
    complete = len(available) == days
    try:
        observed = math.fsum(available) if available else None
    except OverflowError:
        return {'total_mm': None, 'observed_total_mm': None, 'unit': 'mm per period',
                'days_available': len(available), 'days_expected': days,
                'coverage_fraction': len(available) / days, 'status': 'unknown',
                'reason_codes': ['non_finite_period_sum']}
    return {'total_mm': observed if complete else None,
            'observed_total_mm': observed,
            'unit': 'mm per period', 'days_available': len(available), 'days_expected': days,
            'coverage_fraction': len(available) / days,
            'status': 'complete' if complete else 'partial' if available else 'unknown',
            'reason_codes': [] if complete else unknown_reasons}


def summarize_water(params: dict, daily: dict) -> dict:
    period = {'start': params['start'], 'end': params['end']}
    location = {'latitude': params['latitude'], 'longitude': params['longitude']}
    if daily['period'] != period or daily['location'] != location or daily['time_standard'] != 'LST':
        raise ValueError('Daily data must match requested dates, location and LST')
    series = {item['nasa_parameter']: item for item in daily['parameters']}
    indexed = {key: {row['date']: row['value'] for row in item['values']}
               for key, item in series.items()}

    def observation(key, day, unit):
        item = series.get(key)
        if not item or item['unit'] != unit or item['unit_status'] != 'compatible':
            return None
        return indexed[key].get(day)

    rows = []
    observation_values = complete_observation_days = 0
    for offset in range(params['duration_days']):
        day = date.fromisoformat(params['start']) + timedelta(days=offset)
        day_key = day.isoformat()
        available = sum(series.get(key, {}).get('unit_status') == 'compatible'
                        and _number(indexed.get(key, {}).get(day_key)) for key in WATER_PARAMETERS)
        observation_values += available
        complete_observation_days += available == len(WATER_PARAMETERS)
        inputs = {key: observation(key, day_key, unit) for key, unit in ET0_INPUTS.items()}
        et0 = reference_et0(day, params['latitude'], params['elevation_used_m'], inputs)
        coefficient = params['kc_curve'][offset] if params['kc_curve'] is not None else None
        etc = et0['value'] * coefficient['kc'] if coefficient is not None and et0['value'] is not None else None
        etc_reasons = list(params['kc_reason_codes'])
        if et0['value'] is None:
            etc_reasons.append('et0_unknown_for_day')
        if etc is not None and not math.isfinite(etc):
            etc, etc_reasons = None, ['non_finite_etc']
        rows.append({'date': day_key, 'et0_mm': et0['value'], 'et0_status': et0['status'],
                     'et0_reason_codes': et0['reason_codes'], 'quality_flags': et0['quality_flags'],
                     'cloud_correction': et0['cloud_correction'],
                     'inputs': inputs, 'intermediates': et0['intermediates'],
                     'precipitation_mm': observation('PRECTOTCORR', day_key, 'mm/day'),
                     'stage': coefficient['stage'] if coefficient else 'unknown',
                     'kc': coefficient['kc'] if coefficient else None,
                     'etc_mm': etc, 'etc_reason_codes': etc_reasons,
                     'etc_quality_flags': list(et0['quality_flags']) if etc is not None else []})
    days = params['duration_days']
    et0 = _period_sum([row['et0_mm'] for row in rows], days, ['et0_not_available_for_every_day'] + params['elevation_reason_codes'])
    etc = _period_sum([row['etc_mm'] for row in rows], days, params['kc_reason_codes'] or ['etc_not_available_for_every_day'])
    precipitation = _period_sum([row['precipitation_mm'] for row in rows], days, ['precipitation_not_available_for_every_day'])
    bounded_dates = [row['date'] for row in rows if row['cloud_correction']['bounded'] is True]
    return {
        'schema_version': '1.0.0', 'pipeline': 'orbitfarm_water_demand_v1',
        'mode': 'historical_reference_et0_and_potential_etc', 'not_a_forecast': True,
        'crop_id': params['crop_id'], 'location': location, 'historical_period': period,
        'duration_days': days, 'time_standard': 'LST', 'daily': rows,
        'et0': et0, 'potential_etc': etc, 'precipitation': precipitation,
        'coverage': {'expected_days': days, 'et0_days': et0['days_available'],
                     'etc_days': etc['days_available'], 'precipitation_days': precipitation['days_available'],
                     'observations': {'available_values': observation_values, 'expected_values': days * len(WATER_PARAMETERS),
                                      'complete_days': complete_observation_days,
                                      'coverage_fraction': observation_values / (days * len(WATER_PARAMETERS))},
                     'cloud_ratio_bounded_days': len(bounded_dates), 'cloud_ratio_bounded_dates': bounded_dates,
                     'inputs': {key: item['coverage'] for key, item in series.items()}},
        'elevation': {'input': params['elevation'], 'used_m': params['elevation_used_m'],
                      'verification': 'user_asserted_not_independently_verified',
                      'reason_codes': params['elevation_reason_codes']},
        'kc': {'status': 'user_assumption' if params['kc_curve'] is not None else 'unknown',
               'reference_surface': 'grass',
               'scenario': params['kc_scenario'], 'reason_codes': params['kc_reason_codes'],
               'curve_method': 'FAO56_equation_66_single_grass_reference_kc'},
        'method': {'name': 'FAO-56 Penman-Monteith', 'equation': 6, 'timestep': 'daily',
                   'policy': RADIATION_POLICY, 'cloud_bounds_reference': ASCE_2005,
                   'cloud_bounds_scope': 'Rs/Rso in Rnl cloud factor only; original Rs, Rso and Rns unchanged',
                   'reference_surface': 'hypothetical_well_watered_short_grass',
                   'reference_height_m': 0.12, 'albedo': 0.23, 'surface_resistance_s_m': 70,
                   'mean_temperature': '(T2M_MAX + T2M_MIN) / 2; FAO-56 Eq.9',
                   'actual_vapour_pressure': 'from T2MDEW; Eq.14', 'pressure': 'observed NASA PS; no altitude fallback',
                   'soil_heat_flux_mj_m2_day': 0, 'soil_heat_flux_basis': 'FAO56_Eq42_daily_reference_surface',
                   'low_observed_wind_floor_m_s': 0.5, 'rs_rso_lower_limit': 0.3, 'rs_rso_upper_limit': 1.0,
                   'unsupported_cases': 'null for negative ET0, polar night or invalid Eq.39 factors',
                   'references': [FAO_CH2, FAO_CH3, FAO_CH4, FAO_CH6, ASCE_2005]},
        'input_parameters': [{**{field: item[field] for field in ('nasa_parameter', 'parameter_id', 'unit', 'source_unit', 'unit_status', 'conversion_factor', 'aggregation')},
                              'role': 'et0_required' if key in ET0_INPUTS else 'precipitation' if key == 'PRECTOTCORR' else 'context_only'}
                             for key, item in series.items()],
        'nasa_daily': daily, 'source': daily['source'], 'source_is_synthetic': daily['source']['synthetic'],
        'actual_water_balance': None,
        'limitations': [
            'ET0 — эталонная испаряемость с условной хорошо увлажнённой травы; не измерение испарения на поле.',
            'NASA POWER — региональные исторические данные; давление и высота источника могут отличаться от участка.',
            'Высота с источником подтверждается пользователем, но не проверяется независимо; высоты по умолчанию нет.',
            'Нет замены пропущенных наблюдений и нет автоматического перехода на другие формулы ET0.',
            'Отношение Rs/Rso ограничивается до [0.3, 1.0] только в поправке облачности Rnl по ASCE-EWRI 2005; остальные коэффициенты FAO-56 сохранены. Это эмпирическая оценка, не измерение длинноволнового потока.',
            'Kc и длины фаз — явный пользовательский сценарий, без автоматических дат, коэффициентов или климатических поправок.',
            'Потенциальная ETc предполагает стандартные условия без водного стресса; это не фактическое водопотребление.',
            'Осадки показаны отдельно: они не считаются полностью доступными растениям, разность осадков и ETc не является дефицитом поля.',
            'Эффективные осадки, орошение, запасы воды, сток, просачивание и водный стресс не рассчитаны; actual_water_balance=null.',
        ],
    }


def assess_water(body: dict, *, fetcher: Callable | None = None, cache_dir: Path | None = None) -> dict:
    params = validate_water_request(body)
    daily, cached = get_daily_climate(params, fetcher=fetcher or fetch_power_daily,
                                      cache_dir=cache_dir, parameters=WATER_PARAMETERS)
    result = summarize_water(params, daily)
    result['retrieved_from_cache'] = cached
    return result
