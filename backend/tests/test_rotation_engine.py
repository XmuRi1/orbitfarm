import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rotation_engine import compare_rotation_plans
from scoring import read_json

ROOT = Path(__file__).resolve().parents[1]


class TestRotationEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = read_json(ROOT / 'data' / 'crops.json')
        cls.result = compare_rotation_plans(cls.dataset)
        cls.plans = {plan['plan_id']: plan for plan in cls.result['plans']}

    def test_returns_exactly_three_requested_demo_sequences(self):
        self.assertEqual(self.result['mode'], 'descriptive_no_score')
        self.assertEqual(
            [plan['plan_id'] for plan in self.result['plans']],
            ['wheat_continuous', 'wheat_chickpea_wheat', 'wheat_chickpea_sorghum'],
        )
        self.assertEqual(self.result['example_plans'][1]['crop_ids'], ['wheat', 'chickpea', 'wheat'])
        self.assertTrue(all(plan['season_count'] == 3 for plan in self.result['plans']))
        self.assertNotIn('score', self.result)

    def test_continuous_wheat_reports_crop_family_and_catalogue_repeats(self):
        plan = self.plans['wheat_continuous']
        self.assertEqual(len(plan['indicators']['crop_repetition']['adjacent_repeats']), 2)
        self.assertEqual(
            plan['indicators']['family_repetition']['repeated_families'],
            [{'family': 'Poaceae', 'seasons': [1, 2, 3]}],
        )
        self.assertFalse(plan['indicators']['legume_presence']['present'])
        self.assertEqual(plan['indicators']['sequence_diversity']['distinct_crop_count'], 1)
        self.assertEqual(len(plan['potential_risks'][0]['used_data']), 2)
        self.assertTrue(any(item['basis'] == 'catalogue_ROT_001_advice' for item in plan['potential_risks']))

    def test_mixed_plans_report_legume_diversity_and_repeated_family(self):
        wheat_chickpea = self.plans['wheat_chickpea_wheat']
        wheat_chickpea_sorghum = self.plans['wheat_chickpea_sorghum']
        for plan in (wheat_chickpea, wheat_chickpea_sorghum):
            self.assertTrue(plan['indicators']['legume_presence']['present'])
            self.assertEqual(plan['indicators']['legume_presence']['seasons'], [2])
            self.assertEqual(
                plan['indicators']['family_repetition']['repeated_families'],
                [{'family': 'Poaceae', 'seasons': [1, 3]}],
            )
            self.assertEqual(wheat_chickpea['indicators']['crop_repetition']['adjacent_repeats'], [])
            self.assertEqual(wheat_chickpea['indicators']['crop_repetition']['return_after_intermediate'][0]['crop_id'], 'wheat')
            self.assertEqual(wheat_chickpea['indicators']['family_repetition']['adjacent_repeats'], [])
            self.assertEqual(wheat_chickpea['indicators']['family_repetition']['return_after_intermediate'][0]['family'], 'Poaceae')
        self.assertEqual(wheat_chickpea['indicators']['sequence_diversity']['distinct_crop_count'], 2)
        self.assertEqual(wheat_chickpea_sorghum['indicators']['sequence_diversity']['distinct_crop_count'], 3)
        self.assertTrue(any(
            item['basis'] == 'catalogue_ROT_001_preferred_predecessor'
            for item in wheat_chickpea['potential_benefits']
        ))
        self.assertTrue(any(
            item['basis'] == 'catalogue_ROT_001_preferred_predecessor'
            for item in wheat_chickpea_sorghum['potential_benefits']
        ))

    def test_future_climate_is_unknown_with_or_without_historical_context(self):
        no_context = self.result['climate_context']
        self.assertEqual(no_context['status'], 'unknown')
        self.assertEqual(no_context['future_season_conditions'], 'unknown')

        context = {
            'historical_period': {'start': '2025-01-01', 'end': '2025-03-31'},
            'location': {'latitude': 31.25, 'longitude': 34.79},
            'source_is_synthetic': False,
            'retrieved_from_cache': True,
            'observations': [{'parameter_id': 'CLIM_001', 'value': 12.8, 'unit': '°C'}],
        }
        result = compare_rotation_plans(self.dataset, context)
        self.assertEqual(result['climate_context']['status'], 'historical_context_only')
        self.assertEqual(result['climate_context']['observations'][0]['value'], 12.8)
        self.assertEqual(result['climate_context']['future_season_conditions'], 'unknown')
        self.assertTrue(all(plan['climate_fit_for_future_seasons']['status'] == 'unknown' for plan in result['plans']))

    def test_missing_taxonomy_is_unknown_not_inferred(self):
        dataset = copy.deepcopy(self.dataset)
        chickpea = next(crop for crop in dataset['crops'] if crop['crop_id'] == 'chickpea')
        chickpea['requirements']['CROP_007'] = None
        result = compare_rotation_plans(dataset)
        plan = next(item for item in result['plans'] if item['plan_id'] == 'wheat_chickpea_wheat')
        self.assertEqual(plan['indicators']['family_repetition']['status'], 'unknown')
        self.assertIsNone(plan['indicators']['family_repetition']['repeated_families'])
        self.assertEqual(plan['seasons'][1]['family_status'], 'unknown')

    def test_invalid_climate_context_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'historical_period'):
            compare_rotation_plans(self.dataset, {'historical_period': []})


if __name__ == '__main__':
    unittest.main()
