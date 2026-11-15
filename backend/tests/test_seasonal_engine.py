import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from api_contracts import CROPS
from app import app, SlidingWindowLimiter
from live_pipeline import NASAUpstreamError, assess_nasa
from nasa_power import normalize_power_daily, convert_power
from seasonal_engine import assess_season, summarize_season, validate_season_request

ROOT = Path(__file__).resolve().parents[1]


class TestSeasonalEngine(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / 'data/power_fixture_synthetic.json').read_text(encoding='utf-8'))
        self.body = {'crop_id': 'wheat', 'latitude': 31.25, 'longitude': 34.79,
                     'sowing_date': '2025-01-01', 'end_date': '2025-01-05'}

    def normalize(self, body=None):
        body = body or self.body
        return normalize_power_daily(self.payload, lat=body['latitude'], lon=body['longitude'],
                                     start=body['sowing_date'], end=body['end_date'], source_url='https://example.test/fixture')

    def summary(self, body=None, dataset=CROPS):
        body = body or self.body
        return summarize_season(validate_season_request(body, dataset), self.normalize(body), dataset=dataset)

    def fetcher(self):
        # Simulate an upstream response only in tests. Production rejects fixture flags.
        payload = copy.deepcopy(self.payload)
        payload.pop('_synthetic_test_fixture')
        return Mock(return_value=(payload, 'https://example.test/mock-nasa'))

    def test_daily_values_and_exact_season_statistics(self):
        result = self.summary()
        expected = {'mean_temperature': 19.4, 'minimum_temperature': 11, 'maximum_temperature': 28,
                    'total_precipitation': 18, 'rainy_days': 3, 'mean_solar_radiation': 17.6,
                    'mean_relative_humidity': 54.6}
        self.assertEqual(result['season']['duration_days'], 5)
        self.assertEqual(result['coverage']['complete_days'], 5)
        self.assertEqual(result['coverage']['fraction'], 1)
        for key, value in expected.items():
            self.assertEqual(result['metrics'][key]['value'], value, key)
        self.assertEqual(len(result['daily']['parameters']), 6)
        self.assertTrue(result['source_is_synthetic'])
        self.assertEqual(result['daily']['parameters'][0]['values'][0]['date'], '2025-01-01')
        self.assertEqual(result['time_standard'], 'LST')
        self.assertIsNone(result['suitability_score_0_100'])
        self.assertIsNone(result['water_balance'])

    def test_missing_precipitation_never_becomes_a_full_season_sum_or_count(self):
        del self.payload['properties']['parameter']['PRECTOTCORR']['20250102']
        result = self.summary()
        self.assertIsNone(result['metrics']['total_precipitation']['value'])
        self.assertIsNone(result['metrics']['rainy_days']['value'])
        self.assertEqual(result['metrics']['total_precipitation']['observed_value'], 14)
        self.assertEqual(result['metrics']['rainy_days']['observed_value'], 2)
        self.assertEqual(result['coverage']['by_parameter']['CLIM_007']['missing_dates'], ['2025-01-02'])
        self.assertEqual(result['coverage']['complete_days'], 4)

    def test_partial_temperature_mean_is_labelled_and_uses_only_available_days(self):
        self.payload['properties']['parameter']['T2M']['20250101'] = -999
        result = self.summary()
        self.assertEqual(result['metrics']['mean_temperature']['value'], 19.475)
        self.assertEqual(result['metrics']['mean_temperature']['status'], 'partial')
        self.assertEqual(result['metrics']['mean_temperature']['days_available'], 4)

    def test_extremes_are_not_inferred_from_daily_means(self):
        self.payload['properties']['parameter'].pop('T2M_MIN')
        self.payload['properties']['parameter'].pop('T2M_MAX')
        result = self.summary()
        self.assertIsNone(result['metrics']['minimum_temperature']['value'])
        self.assertIsNone(result['metrics']['maximum_temperature']['value'])
        self.assertEqual(result['metrics']['mean_temperature']['value'], 19.4)

    def test_zero_rainfall_is_observed_and_not_missing(self):
        self.payload['properties']['parameter']['PRECTOTCORR'] = {f'2025010{day}': 0 for day in range(1, 6)}
        self.assertEqual(self.summary()['metrics']['rainy_days']['value'], 0)
        self.assertEqual(self.summary()['metrics']['total_precipitation']['value'], 0)

    def test_non_finite_sentinels_booleans_and_physical_ranges_are_missing(self):
        for value in (None, float('nan'), float('inf'), True, '12', -999, -9999, -1):
            with self.subTest(value=value):
                self.payload['properties']['parameter']['PRECTOTCORR']['20250101'] = value
                self.assertIsNone(self.summary()['metrics']['total_precipitation']['value'])
        self.payload['properties']['parameter']['RH2M']['20250101'] = 101
        self.assertEqual(self.summary()['metrics']['mean_relative_humidity']['days_available'], 4)

    def test_header_fill_value_and_time_standard_are_preserved(self):
        self.payload['header'] = {'fill_value': -888, 'time_standard': 'LST'}
        self.payload['properties']['parameter']['T2M']['20250101'] = -888
        daily = self.normalize()
        self.assertEqual(daily['time_standard_basis'], 'response_header')
        self.assertEqual(daily['parameters'][0]['values'][0]['missing_reason'], 'fill_value')
        self.payload['header']['time_standard'] = 'UTC'
        with self.assertRaisesRegex(ValueError, 'LST'):
            self.normalize()

    def test_explicit_solar_unit_conversion_and_wrong_units(self):
        self.payload['parameters']['ALLSKY_SFC_SW_DWN']['units'] = 'kW-hr/m^2/day'
        result = self.summary()
        self.assertEqual(result['metrics']['mean_solar_radiation']['value'], 63.36)
        self.assertEqual(result['daily']['parameters'][-1]['conversion_factor'], 3.6)
        self.payload['parameters']['T2M']['units'] = 'F'
        result = self.summary()
        self.assertIsNone(result['metrics']['mean_temperature']['value'])
        self.assertEqual(result['coverage']['by_parameter']['CLIM_001']['available_days'], 0)

    def test_season_subinterval_does_not_use_outside_days(self):
        body = dict(self.body, sowing_date='2025-01-02', end_date='2025-01-03')
        result = self.summary(body)
        self.assertEqual(result['season']['duration_days'], 2)
        self.assertEqual(result['metrics']['mean_temperature']['value'], 18.9)
        self.assertEqual(result['metrics']['maximum_temperature']['value'], 27)
        self.assertEqual(result['metrics']['total_precipitation']['value'], 4)
        self.assertIn('20250101', result['daily']['parameters'][0]['ignored_date_keys'])

    def test_single_day_leap_day_and_cross_year_windows(self):
        for start, end, count in (('2025-01-01', '2025-01-01', 1), ('2024-02-28', '2024-03-01', 3),
                                  ('2024-12-30', '2025-01-02', 4)):
            with self.subTest(start=start):
                result = self.summary(dict(self.body, sowing_date=start, end_date=end))
                self.assertEqual(result['season']['duration_days'], count)
                self.assertEqual(len(result['daily']['parameters'][0]['values']), count)

    def test_invalid_dates_coordinate_and_crop_rejected_before_fetch(self):
        updates = ({'sowing_date': '2025-02-30'}, {'sowing_date': '20250101'}, {'sowing_date': None},
                   {'end_date': '2024-12-31'}, {'end_date': date.today().isoformat()},
                   {'sowing_date': '1980-01-01'}, {'sowing_date': '2023-01-01'},
                   {'latitude': float('nan')}, {'longitude': True}, {'crop_id': 'unknown'},
                   {'historical_period': {'start': '2025-01-02', 'end': '2025-01-05'}})
        for update in updates:
            fetcher = Mock()
            with self.subTest(update=update), self.assertRaises(ValueError):
                assess_season(dict(self.body, **update), fetcher=fetcher)
            fetcher.assert_not_called()

    def test_missing_and_unverified_requirements_never_produce_a_score(self):
        dataset = copy.deepcopy(CROPS)
        next(crop for crop in dataset['crops'] if crop['crop_id'] == 'wheat')['requirements']['CLIM_001'] = None
        result = self.summary(dataset=dataset)
        rows = {row['parameter_id']: row for row in result['crop_requirements']}
        self.assertIsNone(rows['CLIM_001']['requirement'])
        self.assertIsNone(rows['CLIM_001']['reference'])
        self.assertTrue(rows['CLIM_001']['reasons'])
        self.assertTrue(all(row['status'] == 'unknown' and row['comparison'] is None for row in rows.values()))
        self.assertIsNone(result['suitability_score_0_100'])
        self.assertIsNone(result['water_balance'])

    def test_verified_reference_still_requires_compatible_units_and_season_context(self):
        dataset = copy.deepcopy(CROPS)
        crop = next(crop for crop in dataset['crops'] if crop['crop_id'] == 'wheat')
        req = crop['requirements']['CLIM_001']
        req['verification'] = {'agronomic_verified': True, 'approved_for_production_scoring': True}
        req['context'] = {'growth_stages': None, 'time_window': 'whole_crop_cycle', 'aggregation': 'mean_daily_mean_over_period'}
        row = self.summary(dataset=dataset)['crop_requirements'][0]
        self.assertEqual(row['comparison'], 'within_reference')
        req['unit'] = 'F'
        self.assertIsNone(self.summary(dataset=dataset)['crop_requirements'][0]['comparison'])
        req['unit'] = '°C'
        req['context']['growth_stages'] = ['flowering']
        self.assertIsNone(self.summary(dataset=dataset)['crop_requirements'][0]['comparison'])

    def test_daily_period_and_location_must_match_requested_season(self):
        daily = self.normalize()
        for changes in ({'start': '2025-01-02'}, {'latitude': 0}):
            with self.assertRaises(ValueError):
                summarize_season({**validate_season_request(self.body), **changes}, daily)

    def test_raw_and_normalized_cache_are_saved_and_reused(self):
        fetcher = self.fetcher()
        with tempfile.TemporaryDirectory() as directory:
            first = assess_season(self.body, fetcher=fetcher, cache_dir=Path(directory))
            second = assess_season(self.body, fetcher=fetcher, cache_dir=Path(directory))
            normalized = list(Path(directory).glob('*.daily.json'))
            self.assertEqual(len(normalized), 1)
            saved = json.loads(normalized[0].read_text(encoding='utf-8'))
            self.assertEqual(saved, first['daily'])
        self.assertFalse(first['retrieved_from_cache'])
        self.assertTrue(second['retrieved_from_cache'])
        self.assertEqual(first['daily'], second['daily'])
        fetcher.assert_called_once()

    def test_cache_write_failure_does_not_break_daily_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / 'file'
            blocked.write_text('not a directory')
            result = assess_season(self.body, fetcher=self.fetcher(), cache_dir=blocked)
        self.assertEqual(result['coverage']['fraction'], 1)

    def test_nasa_errors_and_synthetic_responses_never_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            for fetcher, error in ((Mock(side_effect=URLError('offline')), URLError),
                                   (Mock(return_value=(self.payload, 'fixture')), NASAUpstreamError),
                                   (Mock(return_value=({'properties': {}}, 'fixture')), NASAUpstreamError)):
                with self.subTest(error=error), self.assertRaises(error):
                    assess_season(self.body, fetcher=fetcher, cache_dir=Path(directory))
            self.payload.pop('_synthetic_test_fixture')
            self.payload['header'] = {'time_standard': 'UTC'}
            with self.assertRaises(NASAUpstreamError):
                assess_season(self.body, fetcher=Mock(return_value=(self.payload, 'mock')), cache_dir=Path(directory))

    def test_legacy_aggregate_contract_is_unchanged_by_daily_normalization(self):
        before = convert_power(self.payload, lat=31.25, lon=34.79, start='2025-01-01', end='2025-01-05')
        self.normalize()
        self.assertEqual(convert_power(self.payload, lat=31.25, lon=34.79, start='2025-01-01', end='2025-01-05'), before)
        with tempfile.TemporaryDirectory() as directory:
            legacy = assess_nasa({'latitude': 31.25, 'longitude': 34.79, 'start': '2025-01-01', 'end': '2025-01-05'}, fetcher=self.fetcher(), cache_dir=Path(directory))
        self.assertNotIn('daily', legacy)
        self.assertNotIn('daily', legacy['farm'])


class TestSeasonAPI(unittest.TestCase):
    setUp = TestSeasonalEngine.setUp
    fetcher = TestSeasonalEngine.fetcher

    def test_season_route_is_present_in_programmatic_openapi(self):
        self.assertIn('post', app.openapi()['paths']['/api/season/assess'])
    def test_route_success_calls_real_engine_with_mock_nasa(self):
        with tempfile.TemporaryDirectory() as directory, patch('seasonal_engine.fetch_power_daily', self.fetcher()), \
             patch('live_pipeline.CACHE_DIR', Path(directory)), patch('app.nasa_rate_limiter', SlidingWindowLimiter(120)):
            response = TestClient(app).post('/api/season/assess', json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['metrics']['maximum_temperature']['value'], 28)
        self.assertIsNone(response.json()['suitability_score_0_100'])

    def test_invalid_route_requests_are_rejected_without_nasa(self):
        with patch('app.assess_season') as assess:
            for raw in ('null', '[]', '{bad', '{}'):
                self.assertEqual(TestClient(app).post('/api/season/assess', content=raw).status_code, 400)
            assess.assert_not_called()
        self.assertEqual(TestClient(app).post('/api/season/assess', content=b'x' * 500_001).status_code, 413)

    def test_route_nasa_error_and_shared_quota(self):
        with patch('app.nasa_rate_limiter', SlidingWindowLimiter(1)), patch('app.assess_season', side_effect=NASAUpstreamError('offline')):
            response = TestClient(app).post('/api/season/assess', json=self.body)
            self.assertEqual(response.status_code, 502)
            self.assertFalse(response.json()['used_synthetic_fallback'])
            response = TestClient(app).post('/api/nasa/assess', json={})
            self.assertEqual(response.status_code, 429)
            self.assertIn('retry-after', response.headers)


if __name__ == '__main__':
    unittest.main()
