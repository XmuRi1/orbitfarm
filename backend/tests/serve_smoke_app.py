"""Test-only FastAPI launcher with explicit NASA mocks. Never used by production.

The existing synthetic fixture models a network response inside a mock. Removing
its marker here is confined to the mock, as in the unit tests; the real NASA
pipeline still rejects synthetic responses and has no synthetic fallback.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from app import app, SlidingWindowLimiter
from nasa_power import PARAMETERS
from water_fixtures import make_water_fixture


def fixture_fetcher(latitude, longitude, start, end, *, parameters=PARAMETERS):
    if latitude == 0:
        raise URLError('NASA offline (explicit integration-test mock)')
    if (latitude, longitude, start, end) == (31.25, 34.79, '2025-01-01', '2025-03-31'):
        # Replay archived REAL observations through the HTTP stack, no synthetic
        # replacement. This branch is test-only and never imported by production.
        fixture = json.loads((Path(__file__).parent / 'fixtures/beersheba_2025_q1_real.json').read_text(encoding='utf-8'))
        return copy.deepcopy(fixture['nasa']['payload']), fixture['nasa']['requested_url']
    payload = make_water_fixture()
    payload.pop('_synthetic_test_fixture')
    payload['header'] = {'time_standard': 'LST', 'fill_value': -999}
    if longitude == 0:
        del payload['properties']['parameter']['PRECTOTCORR']['20250102']
    if longitude == 1:
        del payload['properties']['parameter']['WS2M']['20250102']
    payload['properties']['parameter'] = {key: value for key, value in payload['properties']['parameter'].items() if key in parameters}
    payload['parameters'] = {key: value for key, value in payload['parameters'].items() if key in parameters}
    return copy.deepcopy(payload), 'https://example.test/mock-nasa-daily'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--without-season', action='store_true', help='Simulate an outdated backend for the 404 regression check')
    args = parser.parse_args()
    if args.without_season:
        app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'path', None) not in ('/api/season/assess', '/api/root-zone/compare')]
    with tempfile.TemporaryDirectory(prefix='orbitfarm-mock-nasa-') as directory, \
         patch('seasonal_engine.fetch_power_daily', fixture_fetcher), \
         patch('water_balance.fetch_power_daily', fixture_fetcher), \
         patch('live_pipeline.CACHE_DIR', Path(directory)), \
         patch('app.nasa_rate_limiter', SlidingWindowLimiter(120)):
        print('TEST ONLY: NASA daily responses are explicitly mocked.', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port)
