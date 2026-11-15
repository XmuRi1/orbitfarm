import copy
from datetime import date
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app, SlidingWindowLimiter
from live_pipeline import NASAUpstreamError, get_daily_climate
from nasa_power import PARAMETERS, WATER_PARAMETERS, normalize_power_daily, power_url
from water_balance import (RADIATION_POLICY, assess_water, crop_coefficient_curve, radiation_balance, reference_et0,
                           saturation_pressure, solar_geometry, summarize_water, validate_water_request, _period_sum)
from water_fixtures import make_water_fixture, user_scenario, water_request


class TestFAO56(unittest.TestCase):
    def setUp(self):
        # FAO-56 Ch.4 Example 18, Uccle, 6 July, J=187, site elevation 100 m.
        # The book supplies ea=1.409 via RHmax/min. Its EXACT equivalent dewpoint
        # exercises Eq.14 without changing the book's vapour pressure input.
        x = math.log(1.409 / 0.6108)
        self.inputs = {'T2M_MIN': 12.3, 'T2M_MAX': 21.5, 'T2MDEW': 237.3 * x / (17.27 - x),
                       'WS2M': 2.078, 'PS': 100.1, 'ALLSKY_SFC_SW_DWN': 22.07}

    def calculate(self, **changes):
        return reference_et0(date(2025, 7, 6), 50.8, 100, {**self.inputs, **changes})

    def test_fao56_example18_et0_and_intermediates(self):
        result = self.calculate()
        self.assertAlmostEqual(result['value'], 3.88, delta=0.01)
        for key, expected, tolerance in (
            ('ra_mj_m2_day', 41.09, 0.02), ('rso_mj_m2_day', 30.90, 0.02),
            ('rns_mj_m2_day', 17.00, 0.02), ('rnl_mj_m2_day', 3.71, 0.02),
            ('rn_mj_m2_day', 13.28, 0.02), ('es_kpa', 1.997, 0.001), ('ea_kpa', 1.409, 0.0001),
            ('delta_kpa_per_c', 0.122, 0.001), ('gamma_kpa_per_c', 0.0666, 0.0001),
        ):
            self.assertAlmostEqual(result['intermediates'][key], expected, delta=tolerance, msg=key)
        self.assertEqual(result['intermediates']['tmean_c'], 16.9)
        self.assertEqual(result['intermediates']['g_mj_m2_day'], 0)
        self.assertFalse(result['cloud_correction']['bounded'])
        self.assertIsNone(result['cloud_correction']['reason'])
        self.assertEqual(result['cloud_correction']['rs_rso_raw'], result['cloud_correction']['rs_rso_used'])
        self.assertNotIn('cloud_ratio_bounded_asce2005', result['quality_flags'])

    def test_saturation_pressure_book_values(self):
        self.assertAlmostEqual(saturation_pressure(21.5), 2.564, delta=0.001)
        self.assertAlmostEqual(saturation_pressure(12.3), 1.431, delta=0.001)

    def test_no_elevation_default_even_when_pressure_is_present(self):
        result = reference_et0(date(2025, 7, 6), 50.8, None, self.inputs)
        self.assertIsNone(result['value'])
        self.assertIn('known_sourced_elevation_required', result['reason_codes'])

    def test_each_required_weather_input_is_indispensable(self):
        for key in self.inputs:
            with self.subTest(key=key):
                result = self.calculate(**{key: None})
                self.assertIsNone(result['value'])
                self.assertIn('missing_or_invalid:' + key, result['reason_codes'])
                self.assertIsNone(result['cloud_correction']['bounded'])
                self.assertEqual(result['cloud_correction']['reason'], 'not_evaluated')
                self.assertNotIn('cloud_ratio_bounded_asce2005', result['quality_flags'])

    def test_invalid_physical_and_non_finite_values(self):
        for update in ({'T2M_MIN': 30}, {'T2MDEW': 40}, {'T2M_MIN': -273.16}, {'WS2M': -1},
                       {'PS': 0}, {'ALLSKY_SFC_SW_DWN': -1}, {'WS2M': True}, {'PS': float('nan')}, {'PS': float('inf')}):
            with self.subTest(update=update):
                self.assertIsNone(self.calculate(**update)['value'])

    def test_fao_low_wind_rule_uses_an_observed_value_only(self):
        result = self.calculate(WS2M=0)
        self.assertIsNotNone(result['value'])
        self.assertEqual(result['intermediates']['u2_used_m_s'], 0.5)
        self.assertTrue(result['quality_flags'])
        self.assertIsNone(self.calculate(WS2M=None)['value'])

    def test_shortwave_ratio_is_capped_per_equation39(self):
        result = self.calculate(ALLSKY_SFC_SW_DWN=40)
        self.assertEqual(result['intermediates']['rs_rso_used'], 1)
        self.assertIn('rs_rso_capped_at_1_per_equation_39', result['quality_flags'])
        self.assertIn('cloud_ratio_bounded_asce2005', result['quality_flags'])
        self.assertEqual(result['cloud_correction']['reason'], 'rs_rso_above_1_0')
        self.assertEqual(result['intermediates']['rns_mj_m2_day'], 0.77 * 40)

    def test_polar_night_does_not_trigger_another_formula(self):
        result = reference_et0(date(2025, 12, 21), 90, 100, self.inputs)
        self.assertIsNone(result['value'])
        self.assertTrue(result['reason_codes'][0].startswith('fao56_domain_error:'))

    def test_zero_observed_solar_uses_cloud_bounds_without_inventing_rs(self):
        result = self.calculate(ALLSKY_SFC_SW_DWN=0)
        self.assertIsNotNone(result['value'])
        self.assertEqual(result['intermediates']['rns_mj_m2_day'], 0)
        self.assertEqual(result['cloud_correction']['rs_rso_raw'], 0)
        self.assertEqual(result['cloud_correction']['rs_rso_used'], 0.3)
        self.assertEqual(result['cloud_correction']['reason'], 'rs_rso_below_0_3')

    def test_cloud_bounds_do_not_remove_the_humidity_domain_guard(self):
        result = self.calculate(T2M_MIN=45, T2M_MAX=50, T2MDEW=40)
        self.assertIsNone(result['value'])
        self.assertIn('Eq. 39 outside its empirical domain', result['reason_codes'][0])

    def test_exact_bounds_are_not_marked_as_adjusted(self):
        rso = solar_geometry(date(2025, 7, 6), 50.8)['ra_mj_m2_day'] * (0.75 + 2e-5 * 100)
        for ratio in (0.3, 0.5, 1.0):
            with self.subTest(ratio=ratio):
                result = radiation_balance(date(2025, 7, 6), 50.8, 100, 12.3, 21.5, ratio * rso, 1.409)
                self.assertFalse(result['cloud_correction']['bounded'])
                self.assertIsNone(result['cloud_correction']['reason'])
                self.assertAlmostEqual(result['rs_rso_used'], ratio)

    def test_overflowing_diagnostics_cannot_serialize_infinity(self):
        result = reference_et0(date(2025, 12, 21), 66.5, 288,
                               {**self.inputs, 'ALLSKY_SFC_SW_DWN': 1e308})
        self.assertIsNone(result['value'])
        self.assertIn('Non-finite cloud ratio or factor', result['reason_codes'][0])
        self.assertIsNone(result['cloud_correction']['rs_rso_raw'])
        json.dumps(result, allow_nan=False)

    def test_calendar_and_hemisphere_affect_extraterrestrial_radiation(self):
        july = solar_geometry(date(2025, 7, 6), 50.8)['ra_mj_m2_day']
        january = solar_geometry(date(2025, 1, 6), 50.8)['ra_mj_m2_day']
        self.assertGreater(july, january)
        self.assertLess(solar_geometry(date(2025, 7, 6), -50.8)['ra_mj_m2_day'], july)
        self.assertEqual(solar_geometry(date(2024, 2, 29), 0)['day_of_year'], 60)

    def test_fao56_example28_four_phase_curve(self):
        scenario = {'type': 'user_defined', 'crop_id': 'dry_bean', 'source': 'FAO56 Example 28 numerical benchmark',
                    'acknowledge_assumptions': True, 'kc_initial': 0.15, 'kc_mid': 1.19, 'kc_end': 0.35,
                    'stage_lengths_days': {'initial': 25, 'development': 25, 'mid': 30, 'late': 20}}
        curve, reasons = crop_coefficient_curve(scenario, 100, 'dry_bean')
        self.assertEqual(reasons, [])
        for day, expected in ((20, 0.15), (40, 0.774), (70, 1.19), (95, 0.56), (100, 0.35)):
            self.assertAlmostEqual(curve[day - 1]['kc'], expected)
        self.assertEqual(curve[25]['stage'], 'development')
        self.assertEqual(curve[50]['stage'], 'mid')
        self.assertEqual(curve[80]['stage'], 'late')

    def test_does_not_silently_mix_alfalfa_and_grass_kc(self):
        with self.assertRaisesRegex(ValueError, 'grass'):
            crop_coefficient_curve({**user_scenario(), 'reference_surface': 'alfalfa'}, 5, 'wheat')

    def test_numeric_overflow_is_unknown_not_invalid_json(self):
        result = _period_sum([1e308, 1e308], 2, [])
        self.assertIsNone(result['total_mm'])
        self.assertIn('non_finite_period_sum', result['reason_codes'])


class TestWaterEngine(unittest.TestCase):
    def setUp(self):
        self.payload = make_water_fixture()
        self.body = water_request()

    def daily(self):
        return normalize_power_daily(self.payload, lat=31.25, lon=34.79, start='2025-01-01', end='2025-01-05',
                                      source_url='https://example.test/explicit-synthetic-fixture', parameters=WATER_PARAMETERS)

    def summary(self, body=None):
        return summarize_water(validate_water_request(body or self.body), self.daily())

    def test_full_et0_rain_and_no_kc(self):
        result = self.summary()
        self.assertEqual(result['coverage']['et0_days'], 5)
        self.assertAlmostEqual(result['et0']['total_mm'], sum(row['et0_mm'] for row in result['daily']))
        self.assertEqual(result['precipitation']['total_mm'], 18)
        self.assertIsNone(result['potential_etc']['total_mm'])
        self.assertEqual(result['kc']['status'], 'unknown')
        self.assertTrue(all(row['etc_mm'] is None for row in result['daily']))
        self.assertIsNone(result['actual_water_balance'])
        self.assertTrue(result['source_is_synthetic'])
        self.assertNotIn('deficit', result)

    def test_explicit_scenario_etc_is_et0_times_daily_kc(self):
        result = self.summary(dict(self.body, kc_scenario=user_scenario()))
        self.assertEqual(result['kc']['status'], 'user_assumption')
        self.assertEqual([row['stage'] for row in result['daily']], ['initial', 'development', 'mid', 'mid', 'late'])
        for row in result['daily']:
            self.assertAlmostEqual(row['etc_mm'], row['et0_mm'] * row['kc'])
        self.assertAlmostEqual(result['potential_etc']['total_mm'], sum(row['etc_mm'] for row in result['daily']))
        self.assertIsNone(result['actual_water_balance'])

    def test_missing_weather_day_makes_full_sum_null_not_partial_sum(self):
        del self.payload['properties']['parameter']['WS2M']['20250102']
        result = self.summary(dict(self.body, kc_scenario=user_scenario()))
        self.assertIsNone(result['et0']['total_mm'])
        self.assertIsNone(result['potential_etc']['total_mm'])
        self.assertIsNotNone(result['et0']['observed_total_mm'])
        self.assertEqual(result['coverage']['et0_days'], 4)
        self.assertEqual(result['coverage']['observations']['available_values'], 44)
        self.assertEqual(result['coverage']['observations']['expected_values'], 45)
        self.assertEqual(result['coverage']['observations']['complete_days'], 4)
        self.assertIn('missing_or_invalid:WS2M', result['daily'][1]['et0_reason_codes'])

    def test_low_solar_with_missing_wind_is_unknown_not_synthetic_computation(self):
        self.payload['properties']['parameter']['ALLSKY_SFC_SW_DWN']['20250102'] = 1
        del self.payload['properties']['parameter']['WS2M']['20250102']
        result = self.summary(dict(self.body, kc_scenario=user_scenario()))
        day = result['daily'][1]
        self.assertIsNone(day['et0_mm'])
        self.assertIsNone(day['etc_mm'])
        self.assertIsNone(day['cloud_correction']['bounded'])
        self.assertEqual(day['quality_flags'], [])
        self.assertEqual(day['etc_quality_flags'], [])
        self.assertIsNone(result['et0']['total_mm'])

    def test_missing_rain_does_not_block_et0_or_etc(self):
        del self.payload['properties']['parameter']['PRECTOTCORR']['20250102']
        result = self.summary(dict(self.body, kc_scenario=user_scenario()))
        self.assertIsNotNone(result['et0']['total_mm'])
        self.assertIsNotNone(result['potential_etc']['total_mm'])
        self.assertIsNone(result['precipitation']['total_mm'])
        self.assertEqual(result['precipitation']['observed_total_mm'], 14)

    def test_missing_dewpoint_is_not_replaced_by_humidity_or_tmin(self):
        self.payload['properties']['parameter'].pop('T2MDEW')
        result = self.summary()
        self.assertIsNone(result['et0']['total_mm'])
        self.assertEqual(result['coverage']['et0_days'], 0)

    def test_missing_pressure_is_not_estimated_from_elevation(self):
        self.payload['properties']['parameter'].pop('PS')
        self.assertIsNone(self.summary()['et0']['total_mm'])

    def test_fao_tmean_uses_extremes_and_not_nasa_t2m_or_rh(self):
        expected = self.summary()['et0']['total_mm']
        self.payload['properties']['parameter'].pop('T2M')
        self.payload['properties']['parameter'].pop('RH2M')
        self.assertEqual(self.summary()['et0']['total_mm'], expected)

    def test_pressure_metadata_conversions_have_identical_results(self):
        expected = self.summary()['et0']['total_mm']
        for unit, value in (('Pa', 100000), ('hPa', 1000), ('mb', 1000), ('kPa', 100)):
            with self.subTest(unit=unit):
                self.payload['parameters']['PS']['units'] = unit
                self.payload['properties']['parameter']['PS'] = {f'2025010{i}': value for i in range(1, 6)}
                self.assertAlmostEqual(self.summary()['et0']['total_mm'], expected)

    def test_unsupported_or_missing_units_never_assume_correct_magnitude(self):
        for key, wrong_unit in (('PS', 'bar'), ('WS2M', 'km/h'), ('T2MDEW', 'F'), ('PS', None)):
            with self.subTest(key=key, unit=wrong_unit):
                self.payload = make_water_fixture()
                self.payload['parameters'][key]['units'] = wrong_unit
                result = self.summary()
                self.assertIsNone(result['et0']['total_mm'])
                self.assertEqual(result['coverage']['et0_days'], 0)

    def test_solar_kwh_conversion_preserves_result(self):
        expected = self.summary()['et0']['total_mm']
        self.payload['parameters']['ALLSKY_SFC_SW_DWN']['units'] = 'kWh/m²/day'
        self.payload['properties']['parameter']['ALLSKY_SFC_SW_DWN'] = {key: value / 3.6 for key, value in self.payload['properties']['parameter']['ALLSKY_SFC_SW_DWN'].items()}
        self.assertAlmostEqual(self.summary()['et0']['total_mm'], expected)

    def test_overflow_in_source_number_becomes_explicit_missing(self):
        self.payload['properties']['parameter']['PS']['20250101'] = 10 ** 1000
        result = self.summary()
        self.assertIsNone(result['daily'][0]['et0_mm'])
        json.dumps(result, allow_nan=False)

    def test_unit_conversion_overflow_never_serializes_infinity(self):
        self.payload['parameters']['ALLSKY_SFC_SW_DWN']['units'] = 'kWh/m²/day'
        self.payload['properties']['parameter']['ALLSKY_SFC_SW_DWN']['20250101'] = 1e308
        result = self.summary()
        self.assertIsNone(result['daily'][0]['et0_mm'])
        json.dumps(result, allow_nan=False)

    def test_height_requires_source_and_confirmation(self):
        for elevation in (None, {'value_m': 100}, {'value_m': 100, 'source': 'survey', 'confirmed': False}):
            with self.subTest(elevation=elevation):
                result = self.summary(dict(self.body, elevation=elevation))
                self.assertIsNone(result['et0']['total_mm'])
                self.assertEqual(result['precipitation']['total_mm'], 18)
        result = self.summary(dict(self.body, elevation={'value_m': 0, 'source': 'explicit survey at sea level (test)', 'confirmed': True}))
        self.assertIsNotNone(result['et0']['total_mm'])

    def test_missing_or_unacknowledged_kc_does_not_block_et0(self):
        for updates in ({'kc_mid': None}, {'stage_lengths_days': None}, {'source': ''}, {'acknowledge_assumptions': False},
                        {'stage_lengths_days': {'initial': 1, 'development': 1, 'mid': 1, 'late': 1}}):
            with self.subTest(updates=updates):
                result = self.summary(dict(self.body, kc_scenario={**user_scenario(), **updates}))
                self.assertIsNotNone(result['et0']['total_mm'])
                self.assertIsNone(result['potential_etc']['total_mm'])
                self.assertTrue(result['kc']['reason_codes'])

    def test_invalid_user_numbers_and_crop_mismatch_are_rejected(self):
        for update in ({'kc_mid': -0.1}, {'kc_mid': True}, {'kc_mid': float('nan')}, {'crop_id': 'barley'},
                       {'stage_lengths_days': {'initial': 0}}, {'stage_lengths_days': {'mid': 1.5}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_water_request(dict(self.body, kc_scenario={**user_scenario(), **update}))
        for value in (float('inf'), True, 100000):
            with self.assertRaises(ValueError):
                validate_water_request(dict(self.body, elevation={'value_m': value, 'source': 'test', 'confirmed': True}))

    def test_water_and_six_parameter_cache_profiles_are_separate(self):
        payload = copy.deepcopy(self.payload)
        payload.pop('_synthetic_test_fixture')
        fetcher = Mock(return_value=(payload, 'https://example.test/mock-nasa'))
        params = validate_water_request(self.body)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            old, cached = get_daily_climate(params, fetcher=fetcher, cache_dir=path)
            self.assertFalse(cached)
            self.assertEqual(len(old['parameters']), 6)
            extended, cached = get_daily_climate(params, fetcher=fetcher, cache_dir=path, parameters=WATER_PARAMETERS)
            self.assertFalse(cached)
            self.assertEqual(len(extended['parameters']), 9)
            self.assertTrue(get_daily_climate(params, fetcher=fetcher, cache_dir=path)[1])
            self.assertTrue(get_daily_climate(params, fetcher=fetcher, cache_dir=path, parameters=WATER_PARAMETERS)[1])
            self.assertEqual(len(list(path.glob('*.daily.json'))), 2)
            raw = [json.loads(file.read_text(encoding='utf-8')) for file in path.glob('*.json') if not file.name.endswith('.daily.json')]
            self.assertEqual(sorted(len(doc['parameters']) for doc in raw), [6, 9])
            self.assertTrue(all(doc['cache_schema_version'] == 2 for doc in raw))
        self.assertEqual(fetcher.call_count, 2)
        self.assertEqual(fetcher.call_args_list[0].kwargs, {})
        self.assertEqual(fetcher.call_args_list[1].kwargs['parameters'], WATER_PARAMETERS)

    def test_original_nasa_url_and_daily_contract_remain_six_by_default(self):
        original = normalize_power_daily(self.payload, lat=31.25, lon=34.79, start='2025-01-01', end='2025-01-05')
        self.assertEqual(tuple(item['nasa_parameter'] for item in original['parameters']), PARAMETERS)
        self.assertNotIn('WS2M', power_url(31.25, 34.79, '2025-01-01', '2025-01-05'))
        self.assertIn('WS2M', power_url(31.25, 34.79, '2025-01-01', '2025-01-05', parameters=WATER_PARAMETERS))
        self.assertEqual(next(item for item in self.daily()['parameters'] if item['nasa_parameter'] == 'WS2M')['parameter_id'], 'CLIM_011')
        self.assertIsNone(next(item for item in self.daily()['parameters'] if item['nasa_parameter'] == 'PS')['parameter_id'])

    def test_live_pipeline_rejects_synthetic_content_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(NASAUpstreamError):
            assess_water(self.body, fetcher=Mock(return_value=(self.payload, 'fixture')), cache_dir=Path(directory))

    def test_full_absent_season_and_wrong_period(self):
        self.payload['properties']['parameter'] = {}
        result = self.summary(dict(self.body, kc_scenario=user_scenario()))
        self.assertIsNone(result['et0']['total_mm'])
        self.assertIsNone(result['et0']['observed_total_mm'])
        self.assertIsNone(result['potential_etc']['total_mm'])
        self.assertIsNone(result['precipitation']['total_mm'])
        daily = self.daily()
        daily['period']['start'] = '2025-01-02'
        with self.assertRaises(ValueError):
            summarize_water(validate_water_request(self.body), daily)


class TestWaterAPI(unittest.TestCase):
    def setUp(self):
        self.body = water_request()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.limiter = patch('app.nasa_rate_limiter', SlidingWindowLimiter(120))
        self.limiter.start()
        self.addCleanup(self.limiter.stop)

    def test_route_and_openapi_success_with_explicit_mock_nasa(self):
        payload = make_water_fixture()
        payload.pop('_synthetic_test_fixture')
        fetcher = Mock(return_value=(payload, 'https://example.test/mock-nasa'))
        with tempfile.TemporaryDirectory() as directory, patch('water_balance.fetch_power_daily', fetcher), patch('live_pipeline.CACHE_DIR', Path(directory)):
            response = self.client.post('/api/water/assess', json=dict(self.body, kc_scenario=user_scenario()))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()['et0']['total_mm'])
        self.assertIsNotNone(response.json()['potential_etc']['total_mm'])
        self.assertIsNone(response.json()['actual_water_balance'])
        self.assertIn('post', app.openapi()['paths']['/api/water/assess'])
        result = response.json()
        self.assertEqual(result['schema_version'], '1.0.0')
        self.assertEqual(result['method']['policy'], RADIATION_POLICY)
        self.assertEqual(result['coverage']['observations']['available_values'], 45)
        self.assertTrue(all(key in result['et0'] for key in (
            'total_mm', 'observed_total_mm', 'unit', 'days_available', 'days_expected',
            'coverage_fraction', 'status', 'reason_codes')))
        for row in result['daily']:
            self.assertEqual(row['etc_quality_flags'], row['quality_flags'])
            self.assertEqual(row['cloud_correction']['policy'], RADIATION_POLICY)

    def test_bad_dates_and_malformed_bodies_rejected_before_fetch(self):
        with patch('app.assess_water') as assess:
            for raw in ('null', '[]', '{invalid', '{}', json.dumps(dict(self.body, end_date='2024-12-31'))):
                self.assertEqual(self.client.post('/api/water/assess', content=raw).status_code, 400)
            assess.assert_not_called()
        self.assertEqual(self.client.post('/api/water/assess', content=b'x' * 500_001).status_code, 413)

    def test_nasa_error_is_502_without_synthetic_fallback(self):
        with patch('app.assess_water', side_effect=URLError('offline')):
            response = self.client.post('/api/water/assess', json=self.body)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'nasa_upstream_unavailable')
        self.assertFalse(response.json()['used_synthetic_fallback'])

    def test_nasa_quota_is_shared_with_seasonal_route(self):
        with patch('app.nasa_rate_limiter', SlidingWindowLimiter(1)), patch('app.assess_water', return_value={'test': True}):
            self.assertEqual(self.client.post('/api/water/assess', json=self.body).status_code, 200)
            response = self.client.post('/api/season/assess', json=self.body)
            self.assertEqual(response.status_code, 429)
            self.assertIn('retry-after', response.headers)


class TestBeershebaRealRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((Path(__file__).parent / 'fixtures/beersheba_2025_q1_real.json').read_text(encoding='utf-8'))

    def assess(self, **changes):
        nasa = self.fixture['nasa']
        with tempfile.TemporaryDirectory() as directory:
            return assess_water({**self.fixture['request'], **changes},
                                fetcher=Mock(return_value=(nasa['payload'], nasa['requested_url'])),
                                cache_dir=Path(directory))

    def test_archived_real_quarter_matches_approved_cloud_policy(self):
        result = self.assess()
        day = next(row for row in result['daily'] if row['date'] == '2025-03-07')
        self.assertEqual(result['method']['policy'], 'fao56_pm_asce2005_cloud_bounds')
        self.assertFalse(result['source_is_synthetic'])
        self.assertEqual(result['elevation']['used_m'], 288)
        self.assertEqual(result['kc']['status'], 'user_assumption')
        self.assertAlmostEqual(day['et0_mm'], 1.6105044280988265, places=10)
        self.assertAlmostEqual(day['etc_mm'], 1.7715548709087094, places=10)
        self.assertAlmostEqual(result['et0']['total_mm'], 233.26354978636815, places=9)
        self.assertAlmostEqual(result['potential_etc']['total_mm'], 176.8946371276623, places=9)
        self.assertEqual(result['precipitation']['total_mm'], 76.18)
        self.assertEqual(result['coverage']['et0_days'], 90)
        self.assertEqual(result['coverage']['etc_days'], 90)
        self.assertEqual(result['coverage']['observations'], {
            'available_values': 810, 'expected_values': 810, 'complete_days': 90, 'coverage_fraction': 1.0})
        self.assertEqual(result['coverage']['cloud_ratio_bounded_days'], 1)
        self.assertEqual(result['coverage']['cloud_ratio_bounded_dates'], ['2025-03-07'])
        self.assertAlmostEqual(day['cloud_correction']['rs_rso_raw'], 0.22589915952401016)
        self.assertEqual(day['cloud_correction']['rs_rso_used'], 0.3)
        self.assertEqual(day['cloud_correction']['reason'], 'rs_rso_below_0_3')
        self.assertEqual(day['quality_flags'], ['cloud_ratio_bounded_asce2005'])
        self.assertEqual(day['etc_quality_flags'], day['quality_flags'])
        self.assertAlmostEqual(day['cloud_correction']['cloud_factor_used'], 0.055)
        self.assertEqual(day['inputs']['ALLSKY_SFC_SW_DWN'], 5.0)
        self.assertAlmostEqual(day['intermediates']['rso_mj_m2_day'], 22.133769822497126)
        self.assertEqual(day['intermediates']['rns_mj_m2_day'], 3.85)
        self.assertAlmostEqual(day['intermediates']['rnl_mj_m2_day'], 0.34773033391262165)
        self.assertIsNone(result['actual_water_balance'])
        self.assertTrue(all(math.isfinite(row['et0_mm']) and row['et0_mm'] >= 0 for row in result['daily']))
        json.dumps(result, allow_nan=False)

    def test_cloud_bounds_do_not_invent_height_or_kc(self):
        no_height = self.assess(elevation=None)
        self.assertIsNone(no_height['et0']['total_mm'])
        self.assertIsNone(no_height['potential_etc']['total_mm'])
        self.assertEqual(no_height['coverage']['cloud_ratio_bounded_days'], 0)
        self.assertEqual(no_height['coverage']['observations']['complete_days'], 90)
        self.assertEqual(no_height['coverage']['et0_days'], 0)
        no_kc = self.assess(kc_scenario=None)
        self.assertAlmostEqual(no_kc['et0']['total_mm'], 233.26354978636815, places=9)
        self.assertIsNone(no_kc['potential_etc']['total_mm'])
        self.assertEqual(no_kc['kc']['status'], 'unknown')
        self.assertEqual(no_kc['coverage']['cloud_ratio_bounded_days'], 1)


if __name__ == '__main__':
    unittest.main()
