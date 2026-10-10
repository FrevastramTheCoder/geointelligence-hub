"""Mocked coordinate-adapter tests; numeric computation remains the real backend function."""
import unittest
from unittest.mock import patch

from drone_mining import run_drone_analysis


class MockedMapIntegrationTests(unittest.TestCase):
    def test_volume_result_flows_through_geojson_feature_adapter(self):
        surface = {'crs': 'EPSG:32736', 'horizontalUnits': 'm', 'verticalUnits': 'm', 'verticalDatum': 'EGM96',
                   'transform': [500000, 2, 0, 10000000, 0, -2], 'values': [[12]]}
        with patch('drone_mining._transformer', return_value=lambda x, y: (33 + (x-500000)/100000, (y-10000000)/100000)) as project:
            result = run_drone_analysis({'method': 'stockpile_volume', 'surface': surface,
                'basePlane': {'type': 'horizontal', 'elevationM': 10, 'verticalDatum': 'EGM96'}, 'mask': [[True]]})
        project.assert_called_once_with('EPSG:32736')
        self.assertTrue(result['stats']['Stockpile volume'].startswith('8 m'))
        self.assertEqual(result['geometry']['features'][0]['properties']['fill_volume_m3'], 8)
        self.assertEqual(result['geometry']['features'][0]['geometry']['type'], 'Polygon')


if __name__ == '__main__':
    unittest.main()
