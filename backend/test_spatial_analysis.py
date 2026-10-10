import unittest

from spatial_analysis import ahp_weights, normalize_values, validate_weights


class SpatialAnalysisMathTests(unittest.TestCase):
    def test_weights_require_nonzero_sum_and_normalize(self):
        self.assertEqual(validate_weights({'slope': 40, 'ndvi': 60}), {'slope': 0.4, 'ndvi': 0.6})
        with self.assertRaisesRegex(ValueError, 'greater than zero'):
            validate_weights({'slope': 0})

    def test_weights_reject_unknown_factor(self):
        with self.assertRaisesRegex(ValueError, 'Unknown criteria'):
            validate_weights({'roads': 1}, {'slope', 'ndvi'})

    def test_ahp_consistent_reciprocal_matrix(self):
        weights, cr, lam = ahp_weights([[1, 2], [0.5, 1]], ['slope', 'rainfall'])
        self.assertAlmostEqual(weights['slope'], 2 / 3, places=6)
        self.assertAlmostEqual(weights['rainfall'], 1 / 3, places=6)
        self.assertAlmostEqual(cr, 0)
        self.assertAlmostEqual(lam, 2)

    def test_ahp_rejects_inconsistent_matrix_shape_and_reciprocity(self):
        with self.assertRaisesRegex(ValueError, 'square'):
            ahp_weights([[1, 2], [0.5]], ['a', 'b'])
        with self.assertRaisesRegex(ValueError, 'reciprocal'):
            ahp_weights([[1, 2], [0.2, 1]], ['a', 'b'])

    def test_minmax_normalization_and_cost_polarity(self):
        self.assertEqual(normalize_values([0, 5, 10]), [0, 0.5, 1])
        self.assertEqual(normalize_values([0, 5, 10], 'cost'), [1, 0.5, 0])
        self.assertEqual(normalize_values([-1, 0, 2], scale=(0, 1)), [0, 0, 1])

    def test_normalization_rejects_missing_or_bad_scale(self):
        with self.assertRaisesRegex(ValueError, 'no finite'):
            normalize_values([None, float('nan')])
        with self.assertRaisesRegex(ValueError, 'minimum < maximum'):
            normalize_values([1], scale=(3, 3))


if __name__ == '__main__':
    unittest.main()
