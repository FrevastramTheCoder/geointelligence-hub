"""Live-service checks intentionally remain opt-in; no user's EE account is used by unit tests."""
import unittest


@unittest.skip('Requires a real Earth Engine test project, credentials, registered datasets and a safe test AOI.')
class LiveEarthEngineIntegrationTests(unittest.TestCase):
    def test_live_earth_engine_job_and_export(self):
        self.fail('Enable only after adding an explicitly provisioned live EE fixture.')


if __name__ == '__main__':
    unittest.main()
