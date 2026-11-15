"""Explicit synthetic weather for tests only, never imported by production code."""
import json
from pathlib import Path


def make_water_fixture():
    payload = json.loads((Path(__file__).resolve().parents[1] / 'data/power_fixture_synthetic.json').read_text(encoding='utf-8'))
    dates = payload['properties']['parameter']['T2M'].keys()
    for key, unit, value in (('WS2M', 'm/s', 2.0), ('T2MDEW', 'C', 7.0), ('PS', 'kPa', 100.0)):
        payload['parameters'][key] = {'units': unit}
        payload['properties']['parameter'][key] = {day: value for day in dates}
    payload['header'] = {'time_standard': 'LST', 'fill_value': -999}
    return payload


def user_scenario():
    return {'type': 'user_defined', 'crop_id': 'wheat', 'source': 'Synthetic five-day test scenario; not agronomic guidance',
            'acknowledge_assumptions': True, 'kc_initial': 0.3, 'kc_mid': 1.1, 'kc_end': 0.4,
            'stage_lengths_days': {'initial': 1, 'development': 1, 'mid': 2, 'late': 1}}


def water_request():
    return {'crop_id': 'wheat', 'latitude': 31.25, 'longitude': 34.79,
            'sowing_date': '2025-01-01', 'end_date': '2025-01-05',
            'elevation': {'value_m': 100, 'source': 'Synthetic test elevation, not a verified height of this location', 'confirmed': True}}
