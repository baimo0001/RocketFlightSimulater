import copy
import math
import tempfile
import unittest
from pathlib import Path

from rocket.project import default_project, validate_project, load_project, save_project, ProjectError
from rocket.motor import build_motor, grain_state, read_curve, read_eng


class ProjectTests(unittest.TestCase):
    def test_invalid_geometry_cannot_create_negative_mass(self):
        p = default_project()
        p['motor']['grain']['inner_diameter_m'] = .06
        with self.assertRaises(ProjectError):
            validate_project(p)

    def test_nonfinite_and_unknown_schema_rejected(self):
        for key, value in [('schema_version', 99), ('body.diameter_m', float('nan'))]:
            p = default_project()
            if '.' in key:
                a, b = key.split('.')
                p[a][b] = value
            else:
                p[key] = value
            with self.assertRaises(ProjectError):
                validate_project(p)

    def test_roundtrip_unicode(self):
        p = default_project()
        p['name'] = '中文测试火箭'
        with tempfile.TemporaryDirectory() as d:
            f = Path(d)/'项目.json'
            save_project(p, f)
            self.assertEqual(load_project(f), p)


class MotorTests(unittest.TestCase):
    def test_grain_volume_independent_hand_calculation(self):
        g = default_project()['motor']['grain']
        g.update(outer_diameter_m=.03, inner_diameter_m=.01, length_m=.1, count=2)
        s = grain_state(g, 0)
        self.assertAlmostEqual(s['volume_m3'], .00004*math.pi)
        self.assertAlmostEqual(s['area_m2'], .002*math.pi)

    def test_triangle_curve_impulse_and_mass_interpolation(self):
        p = default_project()
        p['motor'].update(curve=[[0, 0], [1, 10], [2, 0]], propellant_mass_kg=.02)
        m = build_motor(p)
        self.assertAlmostEqual(m.total_impulse_ns, 10)
        self.assertAlmostEqual(m.at(1)[1], .01)
        self.assertAlmostEqual(m.isp_s, 10/(.02*9.80665))
        self.assertEqual(m.at(3)[:2], (0., 0.))

    def test_curve_rejects_duplicates_and_increasing_remaining_mass(self):
        for curve in [[[0, 0], [1, 5], [1, 0]], [[0, 0, .02], [1, 5, .03], [2, 0, 0]]]:
            p = default_project()
            p['motor'].update(curve=curve, propellant_mass_kg=.02)
            with self.assertRaises(ProjectError):
                build_motor(p)

    def test_zero_thrust_tail_is_not_burn_time(self):
        p = default_project()
        p['motor']['curve'] = [[0,0],[.1,20],[.5,0],[10,0]]
        m = build_motor(p)
        self.assertEqual(m.duration, 10)
        self.assertAlmostEqual(m.burnout_time, .5)
        self.assertAlmostEqual(m.effective_burn_time, .475)

    def test_csv_and_eng_import_do_not_mix_records(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d)/'curve.csv'
            f.write_text('time_s,thrust_n\n0,0\n1,10\n2,0\n', encoding='utf-8-sig')
            self.assertEqual(read_curve(f), [[0., 0.], [1., 10.], [2., 0.]])
            f = Path(d)/'test.eng'
            f.write_text('; test\nA 18 70 3 .02 .05 Demo\n0 0\n1 10\n2 0\nB 20 80 P .03 .06 Demo\n0 0\n1 20\n2 0\n')
            records = read_eng(f)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[1]['curve'][1], [1., 20.])

    def test_computed_motor_mass_closes_and_pressure_increases_with_burn_area(self):
        p = default_project()
        p['motor']['mode'] = 'computed'
        m = build_motor(p)
        expected = 1500*math.pi/4*(.03**2-.012**2)*.05
        self.assertAlmostEqual(m.propellant_mass_kg, expected, places=10)
        self.assertAlmostEqual(m.remaining[-1], 0, places=12)
        self.assertGreater(m.pressure[-2], m.pressure[1])
        self.assertGreater(m.total_impulse_ns, 0)
        self.assertAlmostEqual(sum(m.consumed), expected, places=9)


if __name__ == '__main__':
    unittest.main()
