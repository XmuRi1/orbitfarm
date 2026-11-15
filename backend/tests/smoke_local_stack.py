"""Opt-in HTTP integration test: build frontend first, run with backend's venv.

Starts real FastAPI and production Next.js processes with explicitly mocked NASA.
Uses no live NASA requests,
does not overwrite .env files, and requires no activation or PYTHONPATH.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
HTTP = build_opener(ProxyHandler({}))
EXAMPLE_IDS = ['wheat_continuous', 'wheat_chickpea_wheat', 'wheat_chickpea_sorghum']


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def request(url: str, body=None, *, raw: bytes | None = None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    try:
        response = HTTP.open(Request(url, data=data, headers=headers), timeout=10)
    except HTTPError as error:
        response = error
    with response:
        content = response.read().decode('utf-8')
        return response.status, json.loads(content) if 'application/json' in response.headers.get('Content-Type', '') else content


def wait_ready(process: subprocess.Popen, url: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Server exited with {process.returncode}: {url}')
        try:
            if request(url)[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f'Server did not become ready: {url}')


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


class TestLocalStack(unittest.TestCase):
    def assert_descriptive(self, payload):
        self.assertEqual(payload['schema_version'], '1.0.0')
        self.assertEqual(payload['pipeline'], 'orbitfarm_rotation_planner_v1')
        self.assertEqual(payload['mode'], 'descriptive_no_score')
        self.assertEqual(payload['climate_context']['future_season_conditions'], 'unknown')
        for plan in payload['plans']:
            self.assertEqual(plan['climate_fit_for_future_seasons']['status'], 'unknown')
            self.assertEqual(plan['season_count'], 3)

        def check_values(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if any(word in key for word in ('score', 'yield', 'nitrogen', 'resilience')):
                        self.assertNotIsInstance(item, (int, float), f'Unexpected quantitative estimate: {key}')
                    check_values(item)
            elif isinstance(value, list):
                for item in value:
                    check_values(item)

        check_values(payload)

    def check_routes(self, backend: str, frontend: str):
        self.assertEqual(request(frontend)[0], 200)
        health_status, health = request(backend + '/health')
        self.assertEqual(health_status, 200)
        self.assertTrue(health['ok'])
        self.assertEqual(health['nasa_reachability'], 'not_checked')
        status, crops = request(backend + '/api/crops')
        self.assertEqual(status, 200)
        self.assertEqual(len(crops['crops']), 10)
        self.assertEqual(request(backend + '/api/nasa/status')[0], 200)

        farm = json.loads((ROOT / 'backend/data/farm_demo.json').read_text(encoding='utf-8'))
        status, assessment = request(backend + '/api/assess', {'farm': farm, 'mode': 'strict'})
        self.assertEqual(status, 200)
        self.assertEqual(len(assessment['crops']), 10)
        self.assertIsNone(assessment['suitability_score_0_100'])

        invalid_nasa = {'latitude': 91, 'longitude': 34.79, 'start': '2025-01-01', 'end': '2025-01-05'}
        direct = request(backend + '/api/nasa/assess', invalid_nasa)
        self.assertEqual(direct[0], 400)
        self.assertEqual(request(frontend + '/api/assess', invalid_nasa), direct)

        options = request(backend + '/api/rotation/options')
        self.assertEqual(options[0], 200)
        self.assertEqual(len(options[1]['available_crops']), 10)
        self.assertEqual([plan['plan_id'] for plan in options[1]['example_plans']], EXAMPLE_IDS)
        self.assertEqual(request(frontend + '/api/rotation/options'), options)

        plans = [
            {'plan_id': 'custom_a', 'crop_ids': ['wheat', 'chickpea', 'wheat']},
            {'plan_id': 'custom_b', 'crop_ids': ['wheat', 'chickpea', 'sorghum']},
        ]
        historical_context = {
            'historical_period': {'start': '2025-01-01', 'end': '2025-03-31'},
            'location': {'latitude': 31.25, 'longitude': 34.79},
            'source_is_synthetic': True,
            'retrieved_from_cache': False,
            'observations': [{'parameter_id': 'CLIM_001', 'value': 12.8, 'unit': '°C'}],
        }
        for body in ({}, {'plans': plans, 'climate_context': None}, {'plans': plans, 'climate_context': historical_context}):
            with self.subTest(body=body):
                direct = request(backend + '/api/rotation/compare', body)
                proxied = request(frontend + '/api/rotation/compare', body)
                self.assertEqual(direct[0], 200)
                self.assertEqual(proxied, direct)
                result = proxied[1]
                self.assert_descriptive(result)
                self.assertEqual([plan['plan_id'] for plan in result['plans']], ['custom_a', 'custom_b'] if 'plans' in body else EXAMPLE_IDS)
                if 'plans' in body:
                    self.assertEqual([[season['crop_id'] for season in plan['seasons']] for plan in result['plans']], [plan['crop_ids'] for plan in plans])
                if body.get('climate_context'):
                    self.assertEqual(result['climate_context']['status'], 'historical_context_only')
                    for key, value in historical_context.items():
                        self.assertEqual(result['climate_context'][key], value)
                else:
                    self.assertEqual(result['climate_context']['status'], 'unknown')
                    self.assertIsNone(result['climate_context']['historical_period'])

        invalid_plans = [dict(plans[0], crop_ids=['wheat', 'unknown_crop', 'wheat']), plans[1]]
        for body in ({'plans': invalid_plans}, {'climate_context': {'historical_period': []}}):
            direct = request(backend + '/api/rotation/compare', body)
            self.assertEqual(direct[0], 400)
            self.assertEqual(direct[1]['error'], 'invalid_input')
            self.assertEqual(request(frontend + '/api/rotation/compare', body), direct)
        for raw in (b'{invalid', b'[]', b'null'):
            status, error = request(frontend + '/api/rotation/compare', raw=raw)
            self.assertEqual(status, 400)
            self.assertEqual(error['error'], 'invalid_input')

        season = {'crop_id': 'wheat', 'latitude': 31.25, 'longitude': 34.79,
                  'sowing_date': '2025-01-01', 'end_date': '2025-01-05'}
        for changes, complete in (({}, True), ({'longitude': 0}, False)):
            status, result = request(frontend + '/api/season/assess', dict(season, **changes))
            self.assertEqual(status, 200)
            self.assertEqual(result['pipeline'], 'orbitfarm_seasonal_climate_v1')
            self.assertEqual(result['season']['duration_days'], 5)
            self.assertEqual(result['metrics']['minimum_temperature']['value'], 11)
            self.assertEqual(result['metrics']['maximum_temperature']['value'], 28)
            self.assertEqual(result['metrics']['total_precipitation']['value'], 18 if complete else None)
            self.assertEqual(result['metrics']['rainy_days']['value'], 3 if complete else None)
            self.assertEqual(result['coverage']['complete_days'], 5 if complete else 4)
            self.assertIsNone(result['suitability_score_0_100'])
            self.assertTrue(all(row['status'] == 'unknown' for row in result['crop_requirements']))
            direct_status, direct = request(backend + '/api/season/assess', dict(season, **changes))
            self.assertEqual(direct_status, 200)
            result.pop('retrieved_from_cache')
            direct.pop('retrieved_from_cache')
            self.assertEqual(direct, result)
        status, error = request(frontend + '/api/season/assess', dict(season, latitude=0))
        self.assertEqual(status, 502)
        self.assertFalse(error['used_synthetic_fallback'])
        for bad in ({}, dict(season, end_date='2024-12-31'), dict(season, crop_id='unknown')):
            self.assertEqual(request(frontend + '/api/season/assess', bad)[0], 400)

        from water_fixtures import water_request, user_scenario
        water = water_request()
        for changes, et0_days, etc_days, rain_complete in (
            ({}, 5, 0, True),
            ({'elevation': None}, 0, 0, True),
            ({'kc_scenario': user_scenario()}, 5, 5, True),
            ({'kc_scenario': user_scenario(), 'longitude': 1}, 4, 4, True),
            ({'kc_scenario': user_scenario(), 'longitude': 0}, 5, 5, False),
        ):
            body = dict(water, **changes)
            status, result = request(frontend + '/api/water/assess', body)
            self.assertEqual(status, 200)
            self.assertEqual(result['pipeline'], 'orbitfarm_water_demand_v1')
            self.assertEqual(result['coverage']['et0_days'], et0_days)
            self.assertEqual(result['coverage']['etc_days'], etc_days)
            self.assertEqual(result['et0']['total_mm'] is not None, et0_days == 5)
            self.assertEqual(result['potential_etc']['total_mm'] is not None, etc_days == 5)
            self.assertEqual(result['precipitation']['total_mm'] is not None, rain_complete)
            self.assertIsNone(result['actual_water_balance'])
            self.assertEqual(len(result['input_parameters']), 9)
            direct_status, direct = request(backend + '/api/water/assess', body)
            self.assertEqual(direct_status, 200)
            direct.pop('retrieved_from_cache')
            result.pop('retrieved_from_cache')
            self.assertEqual(result, direct)
        status, error = request(frontend + '/api/water/assess', dict(water, latitude=0))
        self.assertEqual(status, 502)
        self.assertFalse(error['used_synthetic_fallback'])

        # Numerical regression through actual FastAPI and the built Next proxy,
        # with an explicit test-only replay of the archived real NASA quarter.
        real = json.loads((ROOT / 'backend/tests/fixtures/beersheba_2025_q1_real.json').read_text(encoding='utf-8'))
        direct_status, direct = request(backend + '/api/water/assess', real['request'])
        status, result = request(frontend + '/api/water/assess', real['request'])
        self.assertEqual((direct_status, status), (200, 200))
        for response in (direct, result):
            self.assertEqual(response['method']['policy'], 'fao56_pm_asce2005_cloud_bounds')
            self.assertAlmostEqual(response['et0']['total_mm'], 233.26354978636815, places=9)
            self.assertAlmostEqual(response['potential_etc']['total_mm'], 176.8946371276623, places=9)
            self.assertEqual(response['coverage']['observations']['available_values'], 810)
            self.assertEqual(response['coverage']['et0_days'], 90)
            self.assertEqual(response['coverage']['cloud_ratio_bounded_days'], 1)
            self.assertEqual(response['coverage']['cloud_ratio_bounded_dates'], ['2025-03-07'])
            day = next(row for row in response['daily'] if row['date'] == '2025-03-07')
            self.assertAlmostEqual(day['et0_mm'], 1.6105044280988265, places=10)
            self.assertAlmostEqual(day['etc_mm'], 1.7715548709087094, places=10)
            self.assertEqual(day['quality_flags'], ['cloud_ratio_bounded_asce2005'])
            self.assertEqual(day['etc_quality_flags'], day['quality_flags'])
            self.assertEqual(response['kc']['status'], 'user_assumption')
            self.assertIsNone(response['actual_water_balance'])
            response.pop('retrieved_from_cache')
        self.assertEqual(result, direct)

        from test_root_zone_balance import real_root_request, root_request
        body = real_root_request()
        direct_status, direct = request(backend + '/api/root-zone/compare', body)
        status, result = request(frontend + '/api/root-zone/compare', body)
        self.assertEqual((direct_status, status), (200, 200))
        for response in (direct, result):
            self.assertEqual(response['mode'], 'scenario_not_measured')
            self.assertIsNone(response['actual_water_balance'])
            self.assertEqual(response['scenarios']['rainfed']['summary']['stress_days'], 31)
            self.assertEqual(response['scenarios']['irrigated']['summary']['stress_days'], 8)
            self.assertAlmostEqual(response['scenarios']['rainfed']['summary']['etc_adj']['total_mm'], 140.16457705258284, places=9)
            self.assertAlmostEqual(response['scenarios']['irrigated']['summary']['etc_adj']['total_mm'], 174.21917236826405, places=9)
            self.assertEqual(response['coverage']['root_zone']['irrigated']['computed_days'], 90)
            response.pop('retrieved_from_cache')
        self.assertEqual(result, direct)
        for changes in ({'elevation': None}, {'kc_scenario': None}, {'longitude': 0}, {'longitude': 1}):
            status, error = request(frontend + '/api/root-zone/compare', {**root_request(), **changes})
            self.assertEqual(status, 422)
            self.assertEqual(error['error'], 'root_zone_inputs_incomplete')
        status, error = request(frontend + '/api/root-zone/compare', {**root_request(), 'latitude': 0})
        self.assertEqual(status, 502)
        self.assertFalse(error['used_synthetic_fallback'])

    def test_fastapi_and_next_proxies(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Install Node.js and add it to PATH')
        self.assertTrue((ROOT / 'frontend/.next/BUILD_ID').is_file(), 'Run npm run build in frontend first')
        backend = f'http://127.0.0.1:{free_port()}'
        frontend = f'http://127.0.0.1:{free_port()}'
        while frontend == backend:
            frontend = f'http://127.0.0.1:{free_port()}'
        env = {key: value for key, value in os.environ.items() if key.upper() not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV')}
        env.update(ORBITFARM_BACKEND_URL=backend, NEXT_TELEMETRY_DISABLED='1', PYTHONDONTWRITEBYTECODE='1')
        processes = []
        with tempfile.TemporaryDirectory(prefix='orbitfarm-smoke-') as log_dir:
            with open(Path(log_dir) / 'backend.log', 'w+b') as backend_log, open(Path(log_dir) / 'frontend.log', 'w+b') as frontend_log:
                try:
                    api = subprocess.Popen([sys.executable, '-B', 'backend/tests/serve_smoke_app.py', '--port', backend.rsplit(':', 1)[1]], cwd=ROOT, env=env, stdout=backend_log, stderr=subprocess.STDOUT)
                    processes.append(api)
                    wait_ready(api, backend + '/health')
                    web = subprocess.Popen([node, 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', frontend.rsplit(':', 1)[1]], cwd=ROOT / 'frontend', env=env, stdout=frontend_log, stderr=subprocess.STDOUT)
                    processes.append(web)
                    wait_ready(web, frontend)
                    self.check_routes(backend, frontend)
                    stop(api)
                    for path, body in (('/api/rotation/options', None), ('/api/rotation/compare', {}), ('/api/assess', {}), ('/api/season/assess', {}), ('/api/water/assess', {}), ('/api/root-zone/compare', {})):
                        status, error = request(frontend + path, body)
                        self.assertEqual(status, 502)
                        self.assertEqual(error['error'], 'backend_unavailable')
                    old_api = subprocess.Popen([sys.executable, '-B', 'backend/tests/serve_smoke_app.py', '--port', backend.rsplit(':', 1)[1], '--without-season'], cwd=ROOT, env=env, stdout=backend_log, stderr=subprocess.STDOUT)
                    processes.append(old_api)
                    wait_ready(old_api, backend + '/health')
                    status, error = request(frontend + '/api/season/assess', {})
                    self.assertEqual(status, 404)
                    self.assertEqual(error['error'], 'season_route_not_found')
                    self.assertEqual(error['upstream_status'], 404)
                    status, error = request(frontend + '/api/root-zone/compare', {})
                    self.assertEqual(status, 404)
                    self.assertEqual(error['error'], 'root_zone_route_not_found')
                except Exception:
                    for label, log in (('FastAPI', backend_log), ('Next.js', frontend_log)):
                        log.seek(0)
                        print(f'\n{label} log:\n{log.read().decode("utf-8", errors="replace")}', file=sys.stderr)
                    raise
                finally:
                    for process in reversed(processes):
                        stop(process)


if __name__ == '__main__':
    unittest.main(verbosity=2)
