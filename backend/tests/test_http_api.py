import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api_server import Handler
from live_pipeline import NASAUpstreamError

class TestLocalHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_address[1]}'

    def post(self, path, body):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')
        request = Request(self.url + path, data=payload,
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            try:
                return response.code, json.load(response)
            finally:
                response.close()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_root_is_html_dashboard(self):
        with urlopen(self.url+'/') as res:
            body=res.read().decode('utf-8')
            self.assertEqual(res.status,200)
            self.assertIn('text/html',res.headers['Content-Type'])
            self.assertIn('NASA Climate Lab',body)
            self.assertIn('/api/nasa/assess',body)

    def test_previous_routes(self):
        for endpoint in ('/health','/api/crops','/api/nasa/status'):
            with self.subTest(endpoint=endpoint),urlopen(self.url+endpoint) as res:
                payload=json.loads(res.read())
                self.assertEqual(res.status,200)
                self.assertIsInstance(payload,dict)

    def test_nasa_endpoint_returns_mocked_result(self):
        body={'latitude':31.25,'longitude':34.79,'start':'2025-01-01','end':'2025-01-31'}
        payload=json.dumps(body).encode('utf-8')
        request=Request(self.url+'/api/nasa/assess',data=payload,
                        headers={'Content-Type':'application/json'},method='POST')
        with patch('api_server.assess_nasa',return_value={'status':'test_live_route_works'}) as mock:
            with urlopen(request) as res:
                self.assertEqual(res.status,200)
                self.assertEqual(json.load(res)['status'],'test_live_route_works')
            mock.assert_called_once_with(body)

    def test_invalid_json_rejected(self):
        for endpoint in ('/api/assess', '/api/nasa/assess'):
            status, payload = self.post(endpoint, b'{invalid')
            self.assertEqual(status, 400)
            self.assertEqual(payload['error'], 'invalid_input')

    def test_non_object_json_bodies_are_rejected(self):
        for endpoint in ('/api/assess', '/api/nasa/assess'):
            for body in (None, [], 'text'):
                with self.subTest(endpoint=endpoint, body=body):
                    status, payload = self.post(endpoint, body)
                    self.assertEqual(status, 400)
                    self.assertIn('JSON object', payload['detail'])

    def test_malformed_farm_and_nested_fields_are_rejected(self):
        bad_bodies = (
            {'farm': None},
            {'farm': []},
            {'farm': {'farm_id': 'x', 'location': [], 'observations': []}},
            {'farm': {'farm_id': 'x', 'location': {}, 'observations': [None]}},
            {'farm': {'farm_id': 'x', 'location': {}, 'observations': [
                {'parameter_id': 'CLIM_001', 'context': [], 'source': {}}]}},
        )
        for body in bad_bodies:
            with self.subTest(body=body):
                status, payload = self.post('/api/assess', body)
                self.assertEqual(status, 400)
                self.assertEqual(payload['error'], 'invalid_input')

    def test_nasa_upstream_errors_are_502_not_input_errors(self):
        for error in (NASAUpstreamError('invalid NASA response'), URLError('network unavailable')):
            with self.subTest(error=type(error).__name__), patch('api_server.assess_nasa', side_effect=error):
                status, payload = self.post('/api/nasa/assess', {
                    'latitude': 31.25, 'longitude': 34.79,
                    'start': '2025-01-01', 'end': '2025-01-05'
                })
                self.assertEqual(status, 502)
                self.assertEqual(payload['error'], 'nasa_upstream_unavailable')
                self.assertFalse(payload['used_synthetic_fallback'])

if __name__ == '__main__':unittest.main()
