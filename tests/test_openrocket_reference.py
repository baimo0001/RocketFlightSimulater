import json
import unittest
from pathlib import Path
from rocket.project import default_project
from rocket.pipeline import run_project


class InstalledOpenRocketReference(unittest.TestCase):
    def test_same_assumption_ascent_matches_installed_openrocket_23_09(self):
        # Independent engine output generated locally; no OpenRocket installation needed for regression.
        ref=json.loads((Path(__file__).parent/'fixtures/openrocket_23_09_baseline.json').read_text())
        p=default_project();p['recovery']['mode']='none'
        result=run_project(p)
        self.assertLess(abs(result['flight']['summary']['apogee_m']/ref['openrocket_apogee_m']-1),.001)
        self.assertLess(abs(result['flight']['summary']['max_speed_m_s']/ref['openrocket_max_ascent_speed_m_s']-1),.001)
        self.assertAlmostEqual(result['analysis']['initial_mass_kg'],ref['openrocket_initial_mass_kg'],delta=1e-6)
        self.assertAlmostEqual(result['analysis']['cg_initial_m'],ref['openrocket_initial_cg_m'],delta=1e-6)
        self.assertAlmostEqual(result['analysis']['cp_m'],ref['openrocket_cp_at_mach0_m'],delta=.0001)
        self.assertAlmostEqual(result['motor']['total_impulse_ns'],ref['openrocket_total_impulse_ns'],places=8)
