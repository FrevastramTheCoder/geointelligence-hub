import unittest

from drone_mining import _utm_to_lonlat, run_drone_analysis


def grid(values, transform=None, crs='EPSG:32736'):
    return {'values': values, 'crs': crs, 'horizontalUnits': 'm', 'verticalUnits': 'm',
            'verticalDatum': 'EGM96', 'transform': transform or [500000, 2, 0, 10000000, 0, -2]}


class DroneMiningTests(unittest.TestCase):
    def test_utm_fallback_known_coordinate(self):
        lon, lat = _utm_to_lonlat(500000, 10000000, 36, True)
        self.assertAlmostEqual(lon, 33.0, places=7)
        self.assertAlmostEqual(lat, 0.0, places=7)

    def test_stockpile_requires_reference_and_mask_then_computes_volume(self):
        surface = grid([[12, 11], [9, 8]])
        with self.assertRaisesRegex(ValueError, 'basePlane'):
            run_drone_analysis({'method': 'stockpile_volume', 'surface': surface, 'mask': [[True, True], [True, True]]})
        result = run_drone_analysis({'method': 'stockpile_volume', 'surface': surface,
            'basePlane': {'type': 'horizontal', 'elevationM': 10, 'verticalDatum': 'EGM96'}, 'mask': [[True, True], [True, True]], 'verticalAccuracyM': 0.1})
        self.assertEqual(result['stats']['Fill volume'], '12 m³')
        self.assertEqual(result['stats']['Cut volume'], '12 m³')
        self.assertEqual(len(result['geometry']['features']), 4)
        self.assertIn('Conservative absolute volume uncertainty bound', result['stats'])

    def test_dem_difference_volume_and_alignment_validation(self):
        before = grid([[10, 10], [10, 10]])
        after = grid([[12, 9], [8, 11]])
        result = run_drone_analysis({'method': 'dem_difference', 'before': before, 'after': after})
        self.assertEqual(result['stats']['Fill volume'], '12 m³')
        self.assertEqual(result['stats']['Cut volume'], '12 m³')
        shifted = grid([[10, 10], [10, 10]], [500001, 2, 0, 10000000, 0, -2])
        with self.assertRaisesRegex(ValueError, 'aligned pixel transforms'):
            run_drone_analysis({'method': 'dem_difference', 'before': before, 'after': shifted})

    def test_web_mercator_rejected_for_volume_area_distortion(self):
        surface = grid([[12]], crs='EPSG:3857')
        with self.assertRaisesRegex(ValueError, 'area distortion'):
            run_drone_analysis({'method': 'stockpile_volume', 'surface': surface,
                'basePlane': {'type': 'horizontal', 'elevationM': 10, 'verticalDatum': 'EGM96'}, 'mask': [[True]]})

    def test_surface_metrics_and_slope_from_plane(self):
        values = [[0, 2, 4], [0, 2, 4], [0, 2, 4]]
        result = run_drone_analysis({'method': 'surface_metrics', 'surface': grid(values)})
        slopes = [f['properties']['slope_degrees'] for f in result['geometry']['features'] if f['properties']['slope_degrees'] is not None]
        self.assertEqual(len(slopes), 1)
        self.assertAlmostEqual(slopes[0], 45, places=7)

    def test_point_cloud_inspection_is_descriptive_and_validates_xyz(self):
        cloud = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [500000, 10000000, z]}, 'properties': {}}
            for z in (10, 12, 11)]}
        result = run_drone_analysis({'method': 'point_cloud_inspection', 'pointCloud': cloud, 'crs': 'EPSG:32736', 'units': 'm'})
        self.assertEqual(result['stats']['Input points'], 3)
        self.assertEqual(result['stats']['Z min/max'], '10 / 12 m')
        self.assertIn('no classification', result['interpretation'])
        cloud['features'][0]['geometry']['coordinates'] = [1, 2]
        with self.assertRaisesRegex(ValueError, 'needs a Point with'):
            run_drone_analysis({'method': 'point_cloud_inspection', 'pointCloud': cloud, 'crs': 'EPSG:32736', 'units': 'm'})

    def test_orthomosaic_ndvi_uses_reflectance_and_rejects_raw_dn(self):
        red = grid([[0.2, 0.1]])
        nir = grid([[0.6, 0.3]])
        red['units'] = nir['units'] = 'reflectance'
        result = run_drone_analysis({'method': 'orthomosaic_ndvi', 'bands': {'red': red, 'nir': nir}})
        values = [f['properties']['NDVI'] for f in result['geometry']['features']]
        self.assertAlmostEqual(values[0], 0.5)
        self.assertAlmostEqual(values[1], 0.5)
        self.assertEqual(result['stats']['Valid pixels'], 2)
        red['units'] = 'digital_number'
        with self.assertRaisesRegex(ValueError, 'calibrated unitless reflectance'):
            run_drone_analysis({'method': 'orthomosaic_ndvi', 'bands': {'red': red, 'nir': nir}})


if __name__ == '__main__':
    unittest.main()
