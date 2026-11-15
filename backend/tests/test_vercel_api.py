import json
import sys
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import SlidingWindowLimiter, app
from scoring import read_json

ROOT = Path(__file__).resolve().parents[1]


class TestVercelASGI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_existing_read_routes_keep_their_contract(self):
        health = self.client.get('/health')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(set(health.json()), {'ok', 'mode', 'nasa_reachability'})

        crops = self.client.get('/api/crops')
        self.assertEqual(crops.status_code, 200)
        self.assertEqual(len(crops.json()['crops']), 10)
        self.assertEqual(set(crops.json()['crops'][0]), {'crop_id', 'name_ru', 'name_en'})

        status = self.client.get('/api/nasa/status')
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()['route'], 'POST /api/nasa/assess')

    def test_assess_route_reuses_existing_scoring_contract(self):
        farm = read_json(ROOT / 'data' / 'farm_demo.json')
        response = self.client.post('/api/assess', json={'farm': farm, 'mode': 'strict'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['farm_id'], farm['farm_id'])
        self.assertEqual(len(payload['crops']), 10)
        self.assertIsNone(payload['suitability_score_0_100'])

    def test_assess_rejects_malformed_farm_fields_through_shared_validation(self):
        for farm in (None, [], {'farm_id': 'x', 'location': [], 'observations': []},
                     {'farm_id': 'x', 'location': {}, 'observations': [None]},
                     {'farm_id': 'x', 'location': {}, 'observations': [
                         {'parameter_id': 'CLIM_001', 'context': []}]}):
            with self.subTest(farm=farm):
                response = self.client.post('/api/assess', json={'farm': farm})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error'], 'invalid_input')

    def test_malformed_bodies_return_400_or_413(self):
        for body in (None, [], 'text'):
            with self.subTest(body=body):
                response = (
                    self.client.post('/api/nasa/assess', content='null', headers={'content-type': 'application/json'})
                    if body is None else self.client.post('/api/nasa/assess', json=body)
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error'], 'invalid_input')

        oversized = b'{"payload":"' + (b'x' * 500_100) + b'"}'
        response = self.client.post(
            '/api/nasa/assess',
            content=oversized,
            headers={'content-type': 'application/json'},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['error'], 'invalid_payload_size')

    def test_nasa_route_preserves_success_json(self):
        expected = {
            'pipeline': 'orbitfarm_nasa_power_to_10_crop_assessment',
            'source_is_synthetic': False,
            'retrieved_from_cache': True,
            'farm': {'observations': []},
            'assessment': {'suitability_score_0_100': None, 'crops': []},
        }
        request = {
            'latitude': 31.25,
            'longitude': 34.79,
            'start': '2025-01-01',
            'end': '2025-01-05',
        }
        with patch('app.assess_nasa', return_value=expected) as assess_nasa:
            response = self.client.post('/api/nasa/assess', json=request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        assess_nasa.assert_called_once_with(request)

    def test_upstream_network_error_returns_502(self):
        with patch('app.assess_nasa', side_effect=URLError('network unavailable')):
            response = self.client.post('/api/nasa/assess', json={
                'latitude': 31.25,
                'longitude': 34.79,
                'start': '2025-01-01',
                'end': '2025-01-05',
            })
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'nasa_upstream_unavailable')
        self.assertFalse(response.json()['used_synthetic_fallback'])

    def test_nasa_rate_limit_returns_retry_after(self):
        with patch('app.nasa_rate_limiter', SlidingWindowLimiter(limit=1)), \
             patch('app.assess_nasa', return_value={'status': 'ok'}):
            request = {
                'latitude': 31.25,
                'longitude': 34.79,
                'start': '2025-01-01',
                'end': '2025-01-05',
            }
            first = self.client.post('/api/nasa/assess', json=request)
            second = self.client.post('/api/nasa/assess', json=request)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertGreaterEqual(int(second.headers['retry-after']), 1)

    def test_rotation_compare_route_returns_three_descriptive_plans(self):
        response = self.client.post('/api/rotation/compare', json={})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['mode'], 'descriptive_no_score')
        self.assertEqual(len(payload['plans']), 3)
        self.assertEqual(payload['climate_context']['status'], 'unknown')
        self.assertEqual(payload['plans'][0]['plan_id'], 'wheat_continuous')
        self.assertEqual(payload['plans'][1]['plan_id'], 'wheat_chickpea_wheat')
        self.assertEqual(payload['plans'][2]['plan_id'], 'wheat_chickpea_sorghum')
        self.assertNotIn('score', payload)

    def test_rotation_route_rejects_malformed_climate_context(self):
        response = self.client.post('/api/rotation/compare', json={
            'climate_context': {'historical_period': []}
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'invalid_input')

    def test_rotation_options_route_lists_all_catalogue_crops_and_examples(self):
        response = self.client.get('/api/rotation/options')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['available_crops']), 10)
        self.assertEqual(
            [plan['plan_id'] for plan in payload['example_plans']],
            ['wheat_continuous', 'wheat_chickpea_wheat', 'wheat_chickpea_sorghum'],
        )

    def test_rotation_compare_accepts_two_custom_plans(self):
        response = self.client.post('/api/rotation/compare', json={
            'plans': [
                {'plan_id': 'my_a', 'crop_ids': ['wheat', 'wheat', 'chickpea']},
                {'plan_id': 'my_b', 'crop_ids': ['wheat', 'chickpea', 'wheat']},
            ],
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([plan['plan_id'] for plan in payload['plans']], ['my_a', 'my_b'])
        plan_a, plan_b = payload['plans']
        self.assertEqual(len(plan_a['indicators']['crop_repetition']['adjacent_repeats']), 1)
        self.assertEqual(plan_a['indicators']['crop_repetition']['return_after_intermediate'], [])
        self.assertEqual(plan_b['indicators']['crop_repetition']['adjacent_repeats'], [])
        self.assertEqual(plan_b['indicators']['crop_repetition']['return_after_intermediate'][0]['crop_id'], 'wheat')
        self.assertEqual(plan_b['indicators']['family_repetition']['adjacent_repeats'], [])
        self.assertEqual(plan_b['indicators']['family_repetition']['return_after_intermediate'][0]['family'], 'Poaceae')
        self.assertEqual(len(payload['example_plans']), 3)
        self.assertEqual(payload['plans'][1]['climate_fit_for_future_seasons']['status'], 'unknown')
        advice_finding = next(
            finding
            for finding in plan_a['potential_risks']
            if finding['basis'] == 'catalogue_ROT_001_advice'
        )
        self.assertNotIn('ROT_001', advice_finding['explanation'])
        self.assertNotIn('ROT_001', advice_finding['limitation'])
        self.assertEqual(advice_finding['used_data'][0]['parameter_id'], 'ROT_001')
        self.assertEqual(
            advice_finding['used_data'][0]['source_status'],
            'team_draft_not_independently_verified',
        )

    def test_rotation_compare_rejects_unknown_crop_id_and_invalid_plan_length(self):
        for plans in (
            [
                {'plan_id': 'my_a', 'crop_ids': ['wheat', 'unknown_crop', 'chickpea']},
                {'plan_id': 'my_b', 'crop_ids': ['wheat', 'chickpea', 'sorghum']},
            ],
            [
                {'plan_id': 'my_a', 'crop_ids': ['wheat', 'chickpea']},
                {'plan_id': 'my_b', 'crop_ids': ['wheat', 'chickpea', 'sorghum']},
            ],
            [
                {'plan_id': 'same', 'crop_ids': ['wheat', 'chickpea', 'wheat']},
                {'plan_id': 'same', 'crop_ids': ['wheat', 'chickpea', 'sorghum']},
            ],
        ):
            with self.subTest(plans=plans):
                response = self.client.post('/api/rotation/compare', json={'plans': plans})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error'], 'invalid_input')


if __name__ == '__main__':
    unittest.main()
