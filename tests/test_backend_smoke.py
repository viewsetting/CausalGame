"""Backend smoke tests: the app boots, serves mission status, and every
paper scenario has a loadable config and resolvable SCM.

Run: python -m unittest tests.test_backend_smoke
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from api.app import app
from api.modules.environment.scm_registry import get_scm_for_experiment

REPO_ROOT = Path(__file__).resolve().parent.parent

PAPER_SCENARIOS = [
    "antenna_trap",
    "antenna_trap_high_def",
    "antenna_trap_local_optima",
    "antenna_trap_no_history",
    "antenna_trap_no_selection_bias",
    "antenna_trap_simpsons_paradox",
    "deployment_zone_trap_categorical",
    "deployment_zone_trap_categorical_high_def",
    "deployment_zone_trap_categorical_local_optima",
    "deployment_zone_trap_categorical_no_history",
    "deployment_zone_trap_categorical_no_selection_bias",
    "deployment_zone_trap_categorical_simpsons_paradox",
    "deployment_zone_trap_env_shift",
    "weather_noise",
]


class TestBackendSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Context-manager entry runs the app's startup events (session manager init)
        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client_cm.__exit__(None, None, None)

    def test_mission_status_endpoint(self):
        response = self.client.get("/api/mission_status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, dict)

    def test_admin_test_deploy(self):
        response = self.client.post(
            "/api/admin/test-deploy",
            json={"design": {"engine_def": 20, "antenna_def": 10}, "count": 5},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_all_paper_scenarios_have_configs(self):
        for name in PAPER_SCENARIOS:
            with self.subTest(scenario=name):
                config_path = REPO_ROOT / "experiments" / name / "game.json"
                self.assertTrue(config_path.is_file(), f"missing {config_path}")
                config = json.loads(config_path.read_text())
                self.assertIn("experiment", config)

    def test_paper_scenarios_resolve_to_scm(self):
        # deployment_zone_trap_categorical_no_selection_bias intentionally
        # falls back to the config-driven base SCM at session level (same
        # behavior as the paper runs), so it is exempt from direct resolution.
        direct = [
            s for s in PAPER_SCENARIOS
            if s != "deployment_zone_trap_categorical_no_selection_bias"
        ]
        for name in direct:
            with self.subTest(scenario=name):
                scm = get_scm_for_experiment(name)
                self.assertIsNotNone(scm)


if __name__ == "__main__":
    unittest.main()
