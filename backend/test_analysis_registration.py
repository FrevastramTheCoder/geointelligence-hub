import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RegistrationRegressionTests(unittest.TestCase):
    def test_new_spatial_and_drone_methods_are_rule_registered_and_routed(self):
        planner = (ROOT / 'frontend/src/services/geoaiPlanner.js').read_text(encoding='utf-8')
        api = (ROOT / 'frontend/src/config/api.js').read_text(encoding='utf-8')
        server = (ROOT / 'backend/server.py').read_text(encoding='utf-8')
        methods = ('global_moran', 'local_moran', 'getis_ord_gi_star', 'kde', 'nearest_neighbor',
                   'point_pattern', 'idw', 'kriging', 'spatial_sampling', 'spatial_regression',
                   'surface_metrics', 'dsm_dtm', 'dem_difference', 'cut_fill', 'stockpile_volume',
                   'excavation_volume', 'point_cloud_inspection', 'orthomosaic_analysis')
        for method in methods:
            with self.subTest(method=method):
                self.assertRegex(planner, rf"\b{re.escape(method)}:\s*\{{[^}}]*local: '(?:spatial_statistics|drone_analysis)'")
        self.assertIn("SPATIAL_STATISTICS: `${API_BASE}/spatial-statistics`", api)
        self.assertIn("DRONE_ANALYSIS: `${API_BASE}/drone-analysis`", api)
        self.assertIn("path == '/api/spatial-statistics'", server)
        self.assertIn("path == '/api/drone-analysis'", server)
        self.assertRegex(planner, r"\bterrain:\s*\{[^}]*backend: 'terrain'")

    def test_old_and_new_sample_upload_formats_remain_advertised(self):
        upload = (ROOT / 'frontend/src/components/upload/UploadPanel.jsx').read_text(encoding='utf-8')
        for layer_type in ('drone-grid', 'drone-pointcloud', 'drone-orthomosaic'):
            self.assertIn(layer_type, upload)
        self.assertIn('parseBoundaryFile(file)', upload)


if __name__ == '__main__':
    unittest.main()
