"""Offline regression tests for optical formulas, band maps and trend statistics."""
import math
import unittest

from remote_sensing import (compute_index, sensor_bands, trend_statistics,
                            validate_training_geojson, classification_metrics)


class SensorBandTests(unittest.TestCase):
    def test_supported_product_mappings(self):
        self.assertEqual(sensor_bands('sentinel2')['NIR'], 'B8')
        self.assertEqual(sensor_bands('sentinel2')['RE2'], 'B6')
        self.assertIsNone(sensor_bands('landsat8')['RE2'])
        self.assertEqual(sensor_bands('landsat7')['NIR'], 'SR_B4')
        self.assertEqual(sensor_bands('landsat8')['THERMAL'], 'ST_B10')
        self.assertEqual(sensor_bands('landsat9')['SWIR2'], 'SR_B7')

    def test_unknown_sensor_rejected(self):
        with self.assertRaises(ValueError):
            sensor_bands('modis')


class SpectralFormulaTests(unittest.TestCase):
    def setUp(self):
        self.bands = {'BLUE': .1, 'GREEN': .2, 'RED': .15, 'RE': .25,
                      'NIR': .6, 'SWIR1': .3, 'SWIR2': .2}

    def test_requested_index_formulas(self):
        expected = {
            'EVI': 2.5 * (.6 - .15) / (.6 + 6 * .15 - 7.5 * .1 + 1),
            'EVI2': 2.5 * (.6 - .15) / (.6 + 2.4 * .15 + 1),
            'SAVI': 1.5 * (.6 - .15) / (.6 + .15 + .5),
            'MSAVI': (2 * .6 + 1 - math.sqrt((2 * .6 + 1) ** 2 - 8 * (.6 - .15))) / 2,
            'GNDVI': (.6 - .2) / (.6 + .2),
            'NDMI': (.6 - .3) / (.6 + .3),
            'NBR': (.6 - .2) / (.6 + .2),
            'MNDWI': (.2 - .3) / (.2 + .3),
            'NDBI': (.3 - .6) / (.3 + .6),
            'BSI': ((.3 + .15) - (.6 + .1)) / ((.3 + .15) + (.6 + .1)),
            'NDSI': (.2 - .3) / (.2 + .3),
        }
        for index, value in expected.items():
            with self.subTest(index=index):
                self.assertAlmostEqual(compute_index(index, self.bands), value, places=10)
        self.assertAlmostEqual(compute_index('dNBR', {'NBR_PRE': .5, 'NBR_POST': .1}), .4)

    def test_bad_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            compute_index('NDRE', {'NIR': .3})
        with self.assertRaises(ValueError):
            compute_index('NDVI', {'NIR': .2, 'RED': -.2})


class TrendTests(unittest.TestCase):
    def test_mann_kendall_and_sen_slope(self):
        result = trend_statistics(list(range(2011, 2021)), list(range(10)))
        self.assertEqual(result['mk_s'], 45)
        self.assertAlmostEqual(result['sen_slope'], 1)
        self.assertAlmostEqual(result['ols_slope'], 1)
        self.assertLess(result['mk_p'], .05)

    def test_ties_have_finite_statistics(self):
        result = trend_statistics([1, 2, 3, 4], [2, 2, 2, 2])
        self.assertEqual(result['sen_slope'], 0)
        self.assertEqual(result['mk_p'], 1)

    def test_requires_three_observations(self):
        with self.assertRaises(ValueError):
            trend_statistics([2020, 2021], [1, 2])


class ClassificationInputTests(unittest.TestCase):
    def test_geojson_sample_labels_are_normalized_and_validation_codes_reused(self):
        def feature(x, label):
            return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [x, 0]},
                    'properties': {'class': label}}
        training, class_map = validate_training_geojson(
            {'type': 'FeatureCollection', 'features': [feature(0, 'forest'), feature(1, 'water')]})
        validation, _ = validate_training_geojson(
            {'type': 'FeatureCollection', 'features': [feature(2, 'water')]}, class_mapping=class_map)
        self.assertEqual(class_map, {0: 'forest', 1: 'water'})
        self.assertEqual(training['features'][0]['properties']['class'], 0)
        self.assertEqual(validation['features'][0]['properties']['class'], 1)

    def test_samples_reject_missing_labels_and_unseen_validation_class(self):
        fc = {'type': 'FeatureCollection', 'features': [{'type': 'Feature',
              'geometry': {'type': 'Point', 'coordinates': [0, 0]}, 'properties': {}}]}
        with self.assertRaises(ValueError):
            validate_training_geojson(fc)
        _, class_map = validate_training_geojson({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [0, 0]}, 'properties': {'class': 1}},
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [1, 0]}, 'properties': {'class': 2}}]})
        unseen = {'type': 'FeatureCollection', 'features': [{'type': 'Feature',
                  'geometry': {'type': 'Point', 'coordinates': [2, 0]}, 'properties': {'class': 3}}]}
        with self.assertRaises(ValueError):
            validate_training_geojson(unseen, class_mapping=class_map)

    def test_sample_coordinates_must_be_wgs84_longitude_latitude(self):
        invalid = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [500000, 1000000]},
             'properties': {'class': 1}},
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [1, 1]},
             'properties': {'class': 2}}]}
        with self.assertRaisesRegex(ValueError, 'WGS84'):
            validate_training_geojson(invalid)

    def test_classification_metrics_from_reference_rows(self):
        result = classification_metrics([[8, 2], [1, 9]])
        self.assertAlmostEqual(result['overall_accuracy'], .85)
        self.assertAlmostEqual(result['classes'][0]['producer_accuracy'], .8)
        self.assertAlmostEqual(result['classes'][0]['user_accuracy'], 8 / 9)
        self.assertAlmostEqual(result['classes'][0]['f1'], 16 / 19)
        self.assertGreater(result['kappa'], .69)


if __name__ == '__main__':
    unittest.main()
