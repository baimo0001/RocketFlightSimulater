import math
import unittest
from rocket.project import default_project
from rocket.motor import build_motor
from rocket.atmosphere import atmosphere
from rocket.analysis import mass_properties, analyze


class AnalysisTests(unittest.TestCase):
    def test_isa_sea_level_and_tropopause_continuity(self):
        rho, p, t, a = atmosphere(0)
        self.assertAlmostEqual(rho, 1.225, places=3)
        self.assertAlmostEqual(a, 340.294, places=2)
        self.assertLess(abs(atmosphere(11000-.001)[0]-atmosphere(11000+.001)[0]), 1e-6)
        self.assertAlmostEqual(atmosphere(15000)[0], .1937, places=3)

    def test_component_masses_and_cg_no_motor_double_count(self):
        p = default_project()
        p['body']['parts'] = [{'name':'测试部件', 'mass_kg':1., 'position_m':.2}]
        p['motor'].update(dry_mass_kg=.1, position_m=.8, propellant_mass_kg=.1, propellant_position_m=.7)
        m = build_motor(p)
        mass, cg = mass_properties(p, m, 0)
        self.assertAlmostEqual(mass, 1.2)
        self.assertAlmostEqual(cg, .35/1.2)
        self.assertAlmostEqual(mass_properties(p, m, 10)[0], 1.1)

    def test_missing_pressure_is_not_a_structural_pass(self):
        p = default_project()
        a = analyze(p, build_motor(p))
        self.assertEqual(a['structure']['status'], 'missing')
        self.assertIsNone(a['structure']['hoop_stress_pa'])
        self.assertGreater(a['cp_m'], p['body']['nose_length_m'])

    def test_thin_wall_and_bolt_hand_calculation(self):
        p = default_project()
        p['structure'].update(pressure_pa=1e6, diameter_m=.04, thickness_m=.001,
                              bolt_count=4, bolt_effective_area_m2=1e-5)
        s = analyze(p, build_motor(p))['structure']
        self.assertAlmostEqual(s['hoop_stress_pa'], 20e6)
        self.assertAlmostEqual(s['axial_stress_pa'], 10e6)
        self.assertAlmostEqual(s['bolt_stress_pa'], math.pi*1e7)
        p['structure']['thickness_m'] = .004
        self.assertEqual(analyze(p, build_motor(p))['structure']['status'], 'not_applicable')


if __name__ == '__main__':
    unittest.main()
