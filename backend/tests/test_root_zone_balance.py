import copy
from datetime import date, timedelta
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app, SlidingWindowLimiter
from root_zone_balance import (ASSUMPTIONS, IncompleteRootZoneInputs, compare_root_zone,
                               daily_step, simulate_scenario, stress_coefficient, validate_root_zone_request)
from water_fixtures import make_water_fixture, user_scenario, water_request


def scenario_inputs():
    return {'soil': {'theta_fc': 0.32, 'theta_wp': 0.12, 'theta_unit': 'm3/m3',
                     'zr_m': 0.8, 'p': 0.4, 'source': 'Explicit test soil/root/initial assumptions, not site measurements',
                     'acknowledge_assumptions': True},
            'initial_depletion': {'dr_mm': 55}, 'irrigation': [],
            'assumptions': {key: True for key in ASSUMPTIONS}}


def root_request():
    return {**water_request(), 'kc_scenario': user_scenario(), **scenario_inputs()}


def real_root_request():
    fixture = json.loads((Path(__file__).parent / 'fixtures/beersheba_2025_q1_real.json').read_text(encoding='utf-8'))
    body = {**fixture['request'], **scenario_inputs()}
    body['soil'].update(theta_fc=0.30, theta_wp=0.12, zr_m=0.6, p=0.5,
                        source='TEST SCENARIO ONLY: soil/root/p/initial assumptions, not measured Beersheba properties')
    body['initial_depletion'] = {'fraction_of_taw': 0.25}
    body['irrigation'] = [{'date': d, 'net_mm': 25} for d in ('2025-01-15', '2025-02-15', '2025-03-15')]
    return body


def weather(days=10, rain=0, etc=6):
    return [{'date': (date(2025, 1, 1) + timedelta(days=i)).isoformat(), 'et0_mm': 5,
             'etc_mm': etc, 'precipitation_mm': rain} for i in range(days)]


class TestRootZoneEquations(unittest.TestCase):
    def test_example37_matches_published_ks_etc_and_depletion(self):
        params = validate_root_zone_request(root_request())
        result = simulate_scenario(weather(), params, 'rainfed')
        self.assertAlmostEqual(params['taw_mm'], 160)
        self.assertAlmostEqual(params['raw_mm'], 64)
        expected = [(1, 6, 61), (1, 6, 67), (.97, 5.8, 72.8), (.91, 5.4, 78.3), (.85, 5.1, 83.4),
                    (.80, 4.8, 88.2), (.75, 4.5, 92.6), (.70, 4.2, 96.9), (.66, 3.9, 100.8), (.62, 3.7, 104.5)]
        for row, (ks, et, dr) in zip(result['daily'], expected):
            self.assertAlmostEqual(row['ks'], ks, delta=.005)
            self.assertAlmostEqual(row['etc_adj_mm'], et, delta=.06)
            self.assertAlmostEqual(row['dr_end_mm'], dr, delta=.06)
        self.assertEqual(result['summary']['stress_days'], 8)

    def test_rain_saturation_and_eq88_drainage_after_et(self):
        step = daily_step(80, 100, 50, 150, 0, 6)
        self.assertEqual(step['dr_after_wetting_mm'], 0)
        self.assertEqual(step['ks'], 1)
        self.assertEqual(step['etc_adj_mm'], 6)
        self.assertEqual(step['deep_percolation_mm'], 64)  # 150 - 80 - 6, not 70
        self.assertEqual(step['dr_end_mm'], 0)
        self.assertEqual(step['available_water_end_mm'], 100)

    def test_irrigation_precedes_stress_and_is_net_depth(self):
        dry = daily_step(90, 100, 50, 0, 0, 6)
        wet = daily_step(90, 100, 50, 0, 50, 6)
        self.assertAlmostEqual(dry['ks'], .2)
        self.assertEqual(wet['ks'], 1)
        self.assertEqual(wet['dr_end_mm'], 46)
        self.assertEqual(wet['deep_percolation_mm'], 0)

    def test_reaches_wilting_point_without_negative_water(self):
        first = daily_step(0, 10, 5, 0, 0, 1000)
        self.assertEqual(first['dr_end_mm'], 10)
        self.assertEqual(first['etc_adj_mm'], 10)
        self.assertTrue(first['available_water_cap_applied'])
        second = daily_step(10, 10, 5, 0, 0, 6)
        self.assertEqual(second['ks'], 0)
        self.assertEqual(second['etc_adj_mm'], 0)
        self.assertEqual(second['dr_end_mm'], 10)

    def test_ks_boundaries_zero_p_and_raw(self):
        self.assertEqual(stress_coefficient(50, 100, 50), 1)
        self.assertAlmostEqual(stress_coefficient(75, 100, 50), .5)
        self.assertEqual(stress_coefficient(100, 100, 50), 0)
        self.assertEqual(stress_coefficient(0, 100, 0), 1)
        self.assertAlmostEqual(stress_coefficient(50, 100, 0), .5)
        for values in ((-1, 100, 50), (101, 100, 50), (0, 0, 0), (0, 100, 100)):
            with self.assertRaises(ValueError):
                stress_coefficient(*values)

    def test_random_daily_and_period_mass_conservation(self):
        rng = random.Random(56)
        for p in (0, .4, .999):
            state = initial = 55.0
            rain_total = irrigation_total = et_total = dp_total = 0
            for _ in range(366):
                rain = rng.choice([0, 0, 0, rng.uniform(0, 200)])
                irrigation = rng.choice([0, 0, rng.uniform(0, 80)])
                step = daily_step(state, 160, p * 160, rain, irrigation, rng.uniform(0, 30))
                state = step['dr_end_mm']
                self.assertTrue(0 <= state <= 160)
                self.assertTrue(0 <= step['ks'] <= 1)
                self.assertLess(abs(step['mass_balance_residual_mm']), 1e-10)
                rain_total += rain; irrigation_total += irrigation
                et_total += step['etc_adj_mm']; dp_total += step['deep_percolation_mm']
            self.assertAlmostEqual(rain_total + irrigation_total, et_total + dp_total + initial - state, places=8)

    def test_unknown_day_propagates_even_after_heavy_rain(self):
        params = validate_root_zone_request(root_request())
        for key in ('precipitation_mm', 'etc_mm'):
            rows = weather(5)
            rows[1][key] = None
            rows[2]['precipitation_mm'] = 500
            result = simulate_scenario(rows, params, 'rainfed')
            self.assertEqual(result['coverage']['computed_days'], 1)
            self.assertIsNone(result['summary']['etc_adj']['total_mm'])
            self.assertIsNone(result['summary']['deep_percolation']['total_mm'])
            self.assertIsNone(result['summary']['stress_days'])
            self.assertIsNone(result['summary']['final_dr_mm'])
            self.assertIsNone(result['daily'][2]['dr_start_mm'])
            self.assertIn('previous_root_zone_state_unknown', result['daily'][2]['reason_codes'])

    def test_zero_irrigation_scenarios_are_identical(self):
        params = validate_root_zone_request(root_request())
        a = simulate_scenario(weather(), params, 'rainfed')
        b = simulate_scenario(weather(), params, 'irrigated')
        self.assertEqual(a['daily'], b['daily'])
        self.assertEqual(a['summary'], b['summary'])

    def test_numeric_overflow_propagates_unknown_without_nonfinite_json(self):
        params = validate_root_zone_request(root_request())
        rows = weather(3); rows[0]['precipitation_mm'] = 1e308
        result = simulate_scenario(rows, params, 'rainfed')
        self.assertEqual(result['coverage']['computed_days'], 0)
        self.assertIsNone(result['summary']['final_dr_mm'])
        self.assertTrue(result['daily'][0]['reason_codes'][0].startswith('root_zone_numeric_error:'))
        json.dumps(result, allow_nan=False)


class TestRootZoneValidation(unittest.TestCase):
    def test_units_and_physical_bounds_are_strict(self):
        for field, value in (('theta_fc', .12), ('theta_fc', 1.1), ('theta_wp', -.1), ('theta_wp', .5),
                             ('theta_unit', '%'), ('zr_m', 0), ('p', 1), ('p', -.1), ('p', True),
                             ('theta_fc', float('nan')), ('zr_m', 1e308), ('source', ''), ('acknowledge_assumptions', False)):
            body = root_request(); body['soil'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_root_zone_request(body)

    def test_initial_state_exactly_one_finite_mm_or_fraction(self):
        for initial in ({}, {'dr_mm': None}, {'fraction_of_taw': 1.1}, {'dr_mm': -1}, {'dr_mm': 161},
                        {'dr_mm': 0, 'fraction_of_taw': 0}, {'dr_mm': True}):
            with self.subTest(initial=initial), self.assertRaises(ValueError):
                validate_root_zone_request({**root_request(), 'initial_depletion': initial})
        for fraction in (0, .5, 1):
            p = validate_root_zone_request({**root_request(), 'initial_depletion': {'fraction_of_taw': fraction}})
            self.assertAlmostEqual(p['initial_dr_mm'], fraction * 160)

    def test_irrigation_dates_values_and_assumptions(self):
        for events in (None, [{'date': '2025-02-01', 'net_mm': 10}], [{'date': '20250101', 'net_mm': 1}],
                       [{'date': '2025-01-01', 'net_mm': -1}], [{'date': '2025-01-01', 'net_mm': True}],
                       [{'date': '2025-01-01', 'net_mm': 1}] * 2):
            with self.subTest(events=events), self.assertRaises(ValueError):
                validate_root_zone_request({**root_request(), 'irrigation': events})
        for key in ASSUMPTIONS:
            body = root_request(); body['assumptions'][key] = False
            with self.assertRaises(ValueError): validate_root_zone_request(body)


class TestRootZoneAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app); self.addCleanup(self.client.close)
        limiter = patch('app.nasa_rate_limiter', SlidingWindowLimiter(120)); limiter.start(); self.addCleanup(limiter.stop)

    def post_fixture(self, body, payload=None):
        payload = copy.deepcopy(payload or make_water_fixture()); payload.pop('_synthetic_test_fixture', None)
        with tempfile.TemporaryDirectory() as directory, patch('water_balance.fetch_power_daily', return_value=(payload, 'https://example.test/nasa-test')), patch('live_pipeline.CACHE_DIR', Path(directory)):
            return self.client.post('/api/root-zone/compare', json=body)

    def test_success_contract_and_openapi(self):
        response = self.post_fixture(root_request())
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['mode'], 'scenario_not_measured')
        self.assertIsNone(result['actual_water_balance'])
        self.assertEqual(result['scenarios']['rainfed']['daily'], result['scenarios']['irrigated']['daily'])
        self.assertEqual(result['differences']['etc_adj_total_mm'], 0)
        self.assertEqual(result['coverage']['root_zone']['rainfed']['computed_days'], 5)
        self.assertIn('post', app.openapi()['paths']['/api/root-zone/compare'])

    def test_missing_kc_height_rain_or_wind_prevents_http_modelling(self):
        for change in ({'kc_scenario': None}, {'elevation': None}):
            response = self.post_fixture({**root_request(), **change})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()['error'], 'root_zone_inputs_incomplete')
            self.assertEqual(response.json()['coverage']['root_zone_modelled_days'], 0)
        for key in ('WS2M', 'PRECTOTCORR'):
            payload = make_water_fixture(); del payload['properties']['parameter'][key]['20250102']
            self.assertEqual(self.post_fixture(root_request(), payload).status_code, 422)

    def test_bad_inputs_rejected_before_nasa_and_errors_are_distinct(self):
        with patch('app.compare_root_zone') as compare:
            for body in (None, [], {}, {**root_request(), 'soil': {}}):
                self.assertEqual(self.client.post('/api/root-zone/compare', content=json.dumps(body), headers={'Content-Type': 'application/json'}).status_code, 400)
            compare.assert_not_called()
        with patch('app.compare_root_zone', side_effect=URLError('offline')):
            response = self.client.post('/api/root-zone/compare', json=root_request())
            self.assertEqual(response.status_code, 502)
            self.assertFalse(response.json()['used_synthetic_fallback'])

    def test_quota_shared_with_water(self):
        with patch('app.nasa_rate_limiter', SlidingWindowLimiter(1)), patch('app.compare_root_zone', return_value={'test': True}):
            self.assertEqual(self.client.post('/api/root-zone/compare', json=root_request()).status_code, 200)
            self.assertEqual(self.client.post('/api/water/assess', json=water_request()).status_code, 429)

    def test_real_beersheba_quarter_is_scenario_not_measurement(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/beersheba_2025_q1_real.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            result = compare_root_zone(real_root_request(), fetcher=Mock(return_value=(fixture['nasa']['payload'], fixture['nasa']['requested_url'])), cache_dir=Path(directory))
        self.assertFalse(result['source_is_synthetic'])
        self.assertEqual(result['soil']['status'], 'user_assumption')
        self.assertAlmostEqual(result['soil']['taw_mm'], 108)
        self.assertAlmostEqual(result['soil']['raw_mm'], 54)
        self.assertEqual(result['scenarios']['irrigated']['summary']['net_irrigation_total_mm'], 75)
        self.assertEqual(result['coverage']['potential_etc']['days_available'], 90)
        self.assertAlmostEqual(result['coverage']['potential_etc']['total_mm'], 176.8946371276623)
        self.assertEqual(result['coverage']['nasa']['cloud_ratio_bounded_days'], 1)
        for scenario in result['scenarios'].values():
            self.assertEqual(scenario['coverage']['computed_days'], 90)
            s = scenario['summary']
            self.assertAlmostEqual(76.18 + s['net_irrigation_total_mm'],
                                   s['etc_adj']['total_mm'] + s['deep_percolation']['total_mm'] + 27 - s['final_dr_mm'], places=9)
            self.assertIsNone(result['actual_water_balance'])
        for key, expected in (('rainfed', (31, 140.16457705258284, 90.98457705258282, 0)),
                              ('irrigated', (8, 174.21917236826405, 69.88808690242729, 19.848914534163242))):
            s = result['scenarios'][key]['summary']
            self.assertEqual(s['stress_days'], expected[0])
            self.assertAlmostEqual(s['etc_adj']['total_mm'], expected[1], places=9)
            self.assertAlmostEqual(s['final_dr_mm'], expected[2], places=9)
            self.assertAlmostEqual(s['deep_percolation']['total_mm'], expected[3], places=9)
        self.assertLessEqual(result['scenarios']['rainfed']['summary']['etc_adj']['total_mm'], 176.8946371276623)
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
