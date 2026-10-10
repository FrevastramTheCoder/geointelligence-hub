import math
import unittest

from spatial_statistics import _moran_i, _neighbors, run_spatial_statistics

M_PER_DEG = 6371008.8 * math.pi / 180


def point_collection(coords, **properties):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": i, "geometry": {"type": "Point", "coordinates": [x / M_PER_DEG, y / M_PER_DEG]},
         "properties": {key: values[i] for key, values in properties.items()}}
        for i, (x, y) in enumerate(coords)
    ]}


def square(size=100):
    ring = [[0, 0], [size / M_PER_DEG, 0], [size / M_PER_DEG, size / M_PER_DEG],
            [0, size / M_PER_DEG], [0, 0]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}}


class SpatialStatisticsTests(unittest.TestCase):
    def test_global_moran_chain_matches_known_value(self):
        coords = [(i, 0) for i in range(4)]
        points = point_collection(coords, value=[1, 2, 3, 4])
        weights = _neighbors(__import__('spatial_statistics').read_points(points, 'value'), 1.01)
        self.assertAlmostEqual(_moran_i([1, 2, 3, 4], weights), 1 / 3)
        result = run_spatial_statistics({"method": "global_moran", "points": points, "valueField": "value",
                                         "distanceThreshold": 1.01, "permutations": 99})
        self.assertGreaterEqual(result['stats']["Permutation p-value (two-sided)"], 0.01)
        self.assertLessEqual(result['stats']["Permutation p-value (two-sided)"], 1)

    def test_local_moran_and_gi_star_report_adjusted_significance(self):
        coords = [(i, 0) for i in range(12)]
        points = point_collection(coords, value=[0, 0, 0, 8, 10, 9, 0, 0, 0, 1, 2, 1])
        for method in ('local_moran', 'getis_ord_gi_star'):
            result = run_spatial_statistics({"method": method, "points": points, "valueField": "value", "k": 3})
            props = [f['properties'] for f in result['geometry']['features']]
            self.assertEqual(len(props), len(coords))
            self.assertTrue(all(0 <= p.get('q_value_bh', 0) <= 1 for p in props))
            self.assertIn('Multiple testing', result['stats'])

    def test_nearest_neighbor_and_ripley_are_descriptive_with_caveat(self):
        coords = [(10, 10), (20, 10), (80, 80), (90, 80), (50, 50)]
        points = point_collection(coords)
        result = run_spatial_statistics({"method": "nearest_neighbor", "points": points, "studyArea": square(100)})
        self.assertGreater(result['stats']['Clark–Evans R'], 0)
        pattern = run_spatial_statistics({"method": "point_pattern", "points": points, "studyArea": square(100), "distances": [20]})
        self.assertIn('no significance claim', pattern['interpretation'])

    def test_kde_idw_and_kriging_produce_grid_features(self):
        coords = [(20, 20), (80, 20), (20, 80), (80, 80), (50, 20), (20, 50), (80, 50), (50, 80)]
        points = point_collection(coords, value=[1, 3, 2, 4, 2, 1, 4, 3], predictor=[x for x, _ in coords])
        kde = run_spatial_statistics({"method": "kde", "points": points, "studyArea": square(), "bandwidth": 25, "cellSize": 25})
        self.assertTrue(kde['geometry']['features'])
        self.assertTrue(all(f['properties']['density_points_per_m2'] >= 0 for f in kde['geometry']['features']))
        idw = run_spatial_statistics({"method": "idw", "points": points, "studyArea": square(), "valueField": "value", "cellSize": 50})
        self.assertTrue(all(math.isfinite(f['properties']['predicted']) for f in idw['geometry']['features']))
        kriging = run_spatial_statistics({"method": "kriging", "points": points, "studyArea": square(), "valueField": "value",
                                          "cellSize": 50, "sill": 3, "range": 150, "nugget": 0.1})
        self.assertTrue(all(math.isfinite(f['properties']['predicted']) for f in kriging['geometry']['features']))
        self.assertTrue(all(f['properties']['kriging_variance'] >= 0 for f in kriging['geometry']['features']))

    def test_spatial_sampling_respects_polygon_and_seed(self):
        args = {"method": "spatial_sampling", "studyArea": square(), "sampleSize": 25, "seed": 21}
        first = run_spatial_statistics(args)['geometry']
        second = run_spatial_statistics(args)['geometry']
        self.assertEqual(first, second)
        self.assertEqual(len(first['features']), 25)
        self.assertTrue(all(0 <= f['geometry']['coordinates'][0] <= 100 / M_PER_DEG for f in first['features']))

    def test_gwr_recovers_known_linear_relationship(self):
        coords = [(x * 10, y * 10) for y in range(3) for x in range(4)]
        xv = [x for x, _ in coords]
        yv = [2 + 3 * x for x in xv]
        points = point_collection(coords, response=yv, predictor=xv)
        result = run_spatial_statistics({"method": "spatial_regression", "points": points, "valueField": "response",
                                         "predictors": ["predictor"], "bandwidth": 1000, "permutations": 99})
        self.assertGreater(result['stats']['R² (local fitted)'], 0.999999)
        self.assertEqual(len(result['geometry']['features']), len(coords))

    def test_invalid_crs_and_missing_spatial_weights_rejected(self):
        points = point_collection([(0, 0), (1, 0), (2, 0), (3, 0)], value=[1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, 'EPSG:4326'):
            run_spatial_statistics({"method": "global_moran", "points": points, "valueField": "value", "crs": "EPSG:3857", "k": 2})
        with self.assertRaisesRegex(ValueError, 'distanceThreshold'):
            run_spatial_statistics({"method": "global_moran", "points": points, "valueField": "value"})

    def test_invalid_polygon_and_inverse_distance_duplicate_rejected(self):
        invalid = square(100)
        invalid['geometry']['coordinates'] = [[[0,0], [100/M_PER_DEG,100/M_PER_DEG], [0,100/M_PER_DEG],
                                                [100/M_PER_DEG,0], [0,0]]]
        with self.assertRaisesRegex(ValueError, 'self-intersect'):
            run_spatial_statistics({"method": "spatial_sampling", "studyArea": invalid, "sampleSize": 2})
        points = point_collection([(0,0),(0,0),(1,0),(2,0)], value=[1,2,3,4])
        with self.assertRaisesRegex(ValueError, 'duplicate point coordinates'):
            run_spatial_statistics({"method": "global_moran", "points": points, "valueField": "value",
                                    "distanceThreshold": 3, "weightMode": "inverse_distance"})


if __name__ == '__main__':
    unittest.main()
