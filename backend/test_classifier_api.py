"""Offline contract checks against the installed Earth Engine Python client."""
import inspect
import unittest

import ee


class EarthEngineClassifierApiTests(unittest.TestCase):
    def test_supported_real_classifier_methods(self):
        self.assertTrue(hasattr(ee.Classifier, 'smileRandomForest'))
        self.assertTrue(hasattr(ee.Classifier, 'smileCart'))
        self.assertTrue(hasattr(ee.Classifier, 'libsvm'))
        self.assertTrue(hasattr(ee.Clusterer, 'wekaKMeans'))
        self.assertFalse(hasattr(ee.Classifier, 'cart'))

    def test_configurable_parameter_names_exist_in_client_signatures(self):
        rf = inspect.signature(ee.Classifier.smileRandomForest).parameters
        cart = inspect.signature(ee.Classifier.smileCart).parameters
        svm = inspect.signature(ee.Classifier.libsvm).parameters
        self.assertTrue({'numberOfTrees', 'variablesPerSplit', 'minLeafPopulation', 'bagFraction', 'seed'} <= set(rf))
        self.assertTrue({'maxNodes', 'minLeafPopulation'} <= set(cart))
        self.assertTrue({'kernelType', 'gamma', 'cost'} <= set(svm))


if __name__ == '__main__':
    unittest.main()
