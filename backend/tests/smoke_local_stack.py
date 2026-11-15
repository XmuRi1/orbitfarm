"""Opt-in HTTP integration test: build frontend first, run with backend's venv.

Starts real FastAPI and production Next.js processes. Uses no live NASA requests,
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
                    api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', backend.rsplit(':', 1)[1]], cwd=ROOT, env=env, stdout=backend_log, stderr=subprocess.STDOUT)
                    processes.append(api)
                    wait_ready(api, backend + '/health')
                    web = subprocess.Popen([node, 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', frontend.rsplit(':', 1)[1]], cwd=ROOT / 'frontend', env=env, stdout=frontend_log, stderr=subprocess.STDOUT)
                    processes.append(web)
                    wait_ready(web, frontend)
                    self.check_routes(backend, frontend)
                    stop(api)
                    for path, body in (('/api/rotation/options', None), ('/api/rotation/compare', {}), ('/api/assess', {})):
                        status, error = request(frontend + path, body)
                        self.assertEqual(status, 502)
                        self.assertEqual(error['error'], 'backend_unavailable')
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
