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


if __name__ == '__main__':
    unittest.main()
