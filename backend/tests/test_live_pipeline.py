import copy
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live_pipeline import NASAUpstreamError, assess_nasa, validate_request, get_nasa_data
from nasa_power import convert_power

ROOT = Path(__file__).resolve().parents[1]

class TestNASAIntegration(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT/'data/power_fixture_synthetic.json').read_text(encoding='utf-8'))
        # Mock payload models NASA response format, never claim it's a live API result in tests.
        self.payload.pop('_synthetic_test_fixture', None)
        self.args = {'latitude':31.25,'longitude':34.79,'start':'2025-01-01',
                     'end':'2025-01-05','growth_stage':'active_growth',
                     'farm_id':'test_farm','mode':'demo'}
        self.fetcher = Mock(side_effect=lambda lat,lon,start,end:(copy.deepcopy(self.payload), 'https://power.larc.nasa.gov/mock'))

    def test_live_pipeline_scoring_ten_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            out=assess_nasa(self.args,fetcher=self.fetcher,cache_dir=Path(d))
        self.assertEqual(len(out['assessment']['crops']),10)
        self.assertEqual(out['farm']['farm_id'],'test_farm')
        self.assertEqual(out['farm']['demo_only'],False)
        self.assertEqual(out['farm']['observations'][0]['source']['synthetic'],False)
        self.assertTrue(out['not_a_forecast'])
        self.assertEqual(out['assessment']['suitability_score_0_100'],None)
        self.assertTrue(any(c['demo_partial_score_0_100'] is not None for c in out['assessment']['crops']))
        self.assertTrue(all(next(f for f in c['factors'] if f['parameter_id']=='WATER_007')['status']=='WATER_BALANCE_REQUIRED' for c in out['assessment']['crops']))
        self.assertFalse(out['retrieved_from_cache'])

    def test_cache_does_not_refetch_same_point_and_dates(self):
        with tempfile.TemporaryDirectory() as d:
            first=assess_nasa(self.args,fetcher=self.fetcher,cache_dir=Path(d))
            second=assess_nasa(self.args,fetcher=self.fetcher,cache_dir=Path(d))
        self.assertEqual(self.fetcher.call_count,1)
        self.assertFalse(first['retrieved_from_cache'])
        self.assertTrue(second['retrieved_from_cache'])

    def test_strict_mode_reports_no_unverified_scores(self):
        args={**self.args,'mode':'strict'}
        with tempfile.TemporaryDirectory() as d:
            out=assess_nasa(args,fetcher=self.fetcher,cache_dir=Path(d))
        self.assertTrue(all(c['demo_partial_score_0_100'] is None for c in out['assessment']['crops']))

    def test_unassigned_growth_stage_remains_unscored(self):
        args={**self.args,'growth_stage':None}
        with tempfile.TemporaryDirectory() as d:
            out=assess_nasa(args,fetcher=self.fetcher,cache_dir=Path(d))
        wheat=next(c for c in out['assessment']['crops'] if c['crop_id']=='wheat')
        temp=next(f for f in wheat['factors'] if f['parameter_id']=='CLIM_001')
        self.assertEqual(temp['status'],'GROWTH_STAGE_MISMATCH_OR_MISSING')

    def test_optional_soil_reaches_score(self):
        args={**self.args,'soil_observations':[{'parameter_id':'SOIL_001','value':7.1,'unit':'pH',
                         'context':{'soil_depth_cm':[0,30]},'source':{'name':'field_lab'}}]}
        with tempfile.TemporaryDirectory() as d:
            out=assess_nasa(args,fetcher=self.fetcher,cache_dir=Path(d))
        self.assertEqual(len(out['farm']['observations']),7)
        wheat=next(c for c in out['assessment']['crops'] if c['crop_id']=='wheat')
        ph=next(f for f in wheat['factors'] if f['parameter_id']=='SOIL_001')
        self.assertEqual(ph['demo_factor_score_0_100'],100.0)

    def test_inappropriate_fields_rejected_before_fetch(self):
        for modification in ({'latitude':91},{'start':'2025-03-01','end':'2025-01-01'},
                             {'start':'2024-01-01','end':'2025-03-01'},
                             {'end':(date.today()+timedelta(days=1)).isoformat()},
                             {'soil_observations':[{'parameter_id':'CLIM_001'}]}):
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                validate_request({**self.args,**modification})

    def test_no_synthetic_fallback(self):
        raw=copy.deepcopy(self.payload)
        raw['_synthetic_test_fixture']=True
        bad=Mock(return_value=(raw,'https://power.larc.nasa.gov/mock'))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'synthetic'):
                assess_nasa(self.args,fetcher=bad,cache_dir=Path(d))

    def test_invalid_nasa_payload_is_classified_as_upstream_error(self):
        bad = Mock(return_value=({'properties': []}, 'https://power.larc.nasa.gov/mock'))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(NASAUpstreamError):
                assess_nasa(self.args, fetcher=bad, cache_dir=Path(d))

    def test_invalid_soil_observation_is_rejected_before_fetch(self):
        args = {**self.args, 'soil_observations': [{'parameter_id': 'SOIL_001', 'value': 7.0,
                'unit': 'pH', 'source': [], 'context': {}}]}
        with self.assertRaises(ValueError):
            validate_request(args)
        self.fetcher.assert_not_called()

    def test_cache_write_failure_does_not_break_assessment(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / 'not_a_directory'
            cache_path.write_text('occupied', encoding='utf-8')
            out = assess_nasa(self.args, fetcher=self.fetcher, cache_dir=cache_path)
        self.assertEqual(len(out['assessment']['crops']), 10)
        self.assertFalse(out['retrieved_from_cache'])

    def test_solar_conversion_units(self):
        fake=copy.deepcopy(self.payload)
        fake['parameters']['ALLSKY_SFC_SW_DWN']['units']='kW-hr/m^2/day'
        fake['properties']['parameter']['ALLSKY_SFC_SW_DWN']={k:2 for k in fake['properties']['parameter']['ALLSKY_SFC_SW_DWN']}
        out=convert_power(fake,lat=31.25,lon=34.79,start='2025-01-01',end='2025-01-05')
        solar=next(x for x in out['observations'] if x['parameter_id']=='CLIM_009')
        self.assertEqual(solar['value'],7.2)
        self.assertEqual(solar['unit'],'MJ/m²/day')

if __name__=='__main__':unittest.main()
