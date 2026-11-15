"""OrbitFarm local development service (stdlib; not production-secure).

GET /                         small local interface for manual NASA tests
GET /health                   local service availability (not NASA health)
GET /api/crops                all 10 crops
GET /api/nasa/status          supported NASA integration routes
POST /api/assess              existing Farm Observations -> scoring
POST /api/nasa/assess         coordinates + historic dates -> NASA -> scoring
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from scoring import read_json, score_all_crops
from live_pipeline import NASAUpstreamError, assess_nasa

HERE = Path(__file__).resolve().parent
CROPS = read_json(HERE / 'data/crops.json')
ALLOWED_ORIGINS = {'http://localhost:3000', 'http://127.0.0.1:3000'}


def _validate_assess_body(body: dict) -> None:
    farm = body.get('farm')
    if not isinstance(farm, dict):
        raise ValueError('farm must be a JSON object')
    if not isinstance(farm.get('farm_id'), str) or not farm['farm_id'].strip():
        raise ValueError('farm.farm_id must be a nonempty string')
    if not isinstance(farm.get('location'), dict):
        raise ValueError('farm.location must be a JSON object')
    observations = farm.get('observations')
    if not isinstance(observations, list):
        raise ValueError('farm.observations must be an array')
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f'farm.observations[{index}] must be a JSON object')
        if not isinstance(observation.get('parameter_id'), str):
            raise ValueError(f'farm.observations[{index}].parameter_id must be a string')
        for field in ('context', 'source'):
            if field in observation and observation[field] is not None and not isinstance(observation[field], dict):
                raise ValueError(f'farm.observations[{index}].{field} must be a JSON object')


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get('Origin')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def _reply(self, status: int, obj: dict):
        encoded = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self._cors()
        self.end_headers()
        self.wfile.write(encoded)

    def _static(self, file: Path, mime: str):
        content = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        if self.path not in ('/api/assess', '/api/nasa/assess'):
            self._reply(404, {'error': 'not_found'})
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in ('/', '/index.html'):
            self._static(HERE / 'web' / 'index.html', 'text/html; charset=utf-8')
        elif path == '/health':
            self._reply(200, {'ok': True, 'mode': 'local_development_only',
                              'nasa_reachability': 'not_checked'})
        elif path == '/api/crops':
            self._reply(200, {'crops': [{'crop_id': c['crop_id'], 'name_ru': c['name_ru'],
                                        'name_en': c['name_en']} for c in CROPS['crops']]})
        elif path == '/api/nasa/status':
            self._reply(200, {'integration': 'NASA POWER daily point',
                              'route': 'POST /api/nasa/assess',
                              'history_only': True, 'cache_days': 14,
                              'nasa_reachability': 'not_checked'})
        else:
            self._reply(404, {'error': 'not_found'})

    def do_POST(self):
        if self.path not in ('/api/assess', '/api/nasa/assess'):
            self._reply(404, {'error': 'not_found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self._reply(400, {'error': 'invalid_content_length'}); return
        if length <= 0 or length > 500_000:
            self._reply(413, {'error': 'invalid_payload_size'}); return
        try:
            try:
                body = json.loads(self.rfile.read(length).decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('request body must contain valid UTF-8 JSON') from exc
            if not isinstance(body, dict):
                raise ValueError('request body must be a JSON object')
            if self.path == '/api/nasa/assess':
                result = assess_nasa(body)
            else:
                _validate_assess_body(body)
                result = score_all_crops(body['farm'], CROPS, mode=body.get('mode', 'strict'))
            self._reply(200, result)
        except NASAUpstreamError as exc:
            self._reply(502, {'error': 'nasa_upstream_unavailable',
                              'detail': str(exc), 'used_synthetic_fallback': False})
        except (ValueError, KeyError, TypeError) as exc:
            self._reply(400, {'error': 'invalid_input', 'detail': str(exc)})
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            self._reply(502, {'error': 'nasa_upstream_unavailable',
                              'detail': str(exc), 'used_synthetic_fallback': False})

if __name__ == '__main__':
    print('OrbitFarm local dashboard: http://127.0.0.1:8765/')
    print('NASA requests need internet; historical data only. CTRL+C to stop.')
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
