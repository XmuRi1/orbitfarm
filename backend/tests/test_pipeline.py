import sys
import copy
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scoring import read_json,score_all_crops
from nasa_power import convert_power,merge_farm,power_url

ROOT=Path(__file__).resolve().parents[1]

class TestOrbitFarm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crops=read_json(ROOT/'data/crops.json')
        cls.farm=read_json(ROOT/'data/farm_demo.json')
    def test_all_ten(self):
        result=score_all_crops(self.farm,self.crops,mode='demo')
        self.assertEqual(len(result['crops']),10)
        self.assertTrue(all(x['suitability_score_0_100'] is None for x in result['crops']))
        self.assertTrue(all(x['demo_partial_score_0_100'] is not None for x in result['crops']))
    def test_strict_scores_null_due_to_unverified_profiles(self):
        result=score_all_crops(self.farm,self.crops,mode='strict')
        self.assertTrue(all(x['demo_partial_score_0_100'] is None for x in result['crops']))
    def test_water_balance_not_assumed_from_precipitation(self):
        r=score_all_crops(self.farm,self.crops,mode='demo')
        self.assertTrue(all(next(x for x in c['factors'] if x['parameter_id']=='WATER_007')['status']=='WATER_BALANCE_REQUIRED' for c in r['crops']))
        self.assertTrue(all(c['demo_weight_coverage'] <= 0.7 for c in r['crops']))
    def test_duplicate_parameter_rejected(self):
        bad=copy.deepcopy(self.farm)
        bad['observations'].append(copy.deepcopy(bad['observations'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            score_all_crops(bad,self.crops)
    def test_unit_mismatch_rejected(self):
        bad=copy.deepcopy(self.farm)
        bad['observations'][0]['unit']='kelvin'
        with self.assertRaisesRegex(ValueError,'Unit mismatch'):
            score_all_crops(bad,self.crops)
    def test_stage_mismatch_does_not_score_temperature(self):
        bad=copy.deepcopy(self.farm)
        bad['observations'][0]['context']['growth_stage']='flowering'
        r=score_all_crops(bad,self.crops)
        w=next(c for c in r['crops'] if c['crop_id']=='wheat')
        t=next(x for x in w['factors'] if x['parameter_id']=='CLIM_001')
        self.assertEqual(t['status'],'GROWTH_STAGE_MISMATCH_OR_MISSING')
    def test_nasa_fixture(self):
        raw=read_json(ROOT/'data/power_fixture_synthetic.json')
        obj=convert_power(raw,lat=31.25,lon=34.79,start='2025-01-01',end='2025-01-05',stage='active_growth')
        self.assertTrue(obj['demo_only'])
        self.assertEqual(len(obj['observations']),6)
        rain=next(o for o in obj['observations'] if o['parameter_id']=='CLIM_007')
        self.assertEqual(rain['value'],18)
        self.assertEqual(rain['unit'],'mm per period')
        self.assertTrue(all(o['source']['synthetic'] for o in obj['observations']))
        self.assertIsNone(obj['water_balance'])
    def test_nasa_missing_daily_rain_not_summed(self):
        raw=read_json(ROOT/'data/power_fixture_synthetic.json')
        del raw['properties']['parameter']['PRECTOTCORR']['20250103']
        obj=convert_power(raw,lat=31.25,lon=34.79,start='2025-01-01',end='2025-01-05')
        self.assertNotIn('CLIM_007',[x['parameter_id'] for x in obj['observations']])
    def test_merge_rejects_duplicates(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            merge_farm(self.farm,self.farm)
    def test_nasa_url(self):
        u=power_url(31.25,34.79,'2025-01-01','2025-01-05')
        self.assertIn('power.larc.nasa.gov',u)
        self.assertIn('time-standard=LST',u)

if __name__=='__main__':unittest.main()
