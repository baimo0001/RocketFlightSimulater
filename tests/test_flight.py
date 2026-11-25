import copy
import threading
import unittest
from rocket.project import default_project, ProjectError
from rocket.motor import build_motor
from rocket.flight import simulate, vertical_acceleration
from rocket.pipeline import run_project


class FlightTests(unittest.TestCase):
    def test_vacuum_constant_mass_ballistic_matches_analytic(self):
        self.assertAlmostEqual(vertical_acceleration(0, 20, 2, 0, 0, .1, 1.2), -9.80665)
        # Constant thrust 30N, mass 2kg gives acceleration 5.19335m/s².
        self.assertAlmostEqual(vertical_acceleration(0, 0, 2, 30, 0, .1, 1.2), 5.19335)

    def test_drag_opposes_descent(self):
        a = vertical_acceleration(0, -10, 1, 0, 1, .2, 1.2)
        self.assertAlmostEqual(a, 2.19335)

    def test_integrated_vacuum_flight_matches_hand_ballistic_solution(self):
        p = default_project()
        p['body']['parts'] = [{'name':'恒质量算例','mass_kg':1.9,'position_m':.3}]
        p['body']['drag_coefficient'] = 0
        p['motor'].update(dry_mass_kg=.1, propellant_mass_kg=1e-10,
                          curve=[[0,0],[1e-6,30],[2,30],[2.000001,0]])
        p['recovery']['mode'] = 'none'
        p['launch']['rail_length_m'] = .01
        f = run_project(p)['flight']
        # Negligible 1us ramps; 2s at a=30/2-g, then ballistic ascent.
        expected_apogee = 10.3867+10.3867**2/(2*9.80665)
        self.assertAlmostEqual(f['summary']['apogee_m'], expected_apogee, delta=.0001)

    def test_demo_has_ordered_events_and_ground_endpoint(self):
        result = run_project(default_project())
        f = result['flight']
        self.assertEqual(f['status'], 'landed')
        keys = [e['event'] for e in f['events']]
        for k in ['liftoff', 'rail_exit', 'burnout', 'apogee', 'deployment', 'landing']:
            self.assertIn(k, keys)
        self.assertEqual(keys, ['ignition', 'liftoff', 'rail_exit', 'burnout', 'apogee', 'deployment', 'landing'])
        self.assertEqual(f['samples'][-1]['altitude_m'], 0)
        self.assertGreater(f['summary']['apogee_m'], 50)
        self.assertLess(f['summary']['landing_speed_m_s'], 10)

    def test_no_liftoff_is_not_a_normal_flight(self):
        p = default_project()
        p['motor']['curve'] = [[0, 0], [1, .1], [2, 0]]
        f = simulate(p, build_motor(p))
        self.assertEqual(f['status'], 'no_liftoff')
        self.assertNotIn('rail_exit', [e['event'] for e in f['events']])

    def test_truncation_and_late_deployment(self):
        p = default_project()
        p['solver']['max_time_s'] = 1
        self.assertEqual(run_project(p)['flight']['status'], 'truncated')
        p = default_project()
        p['recovery']['delay_s'] = 1000
        f = run_project(p)['flight']
        self.assertEqual(f['status'], 'landed')
        self.assertNotIn('deployment', [e['event'] for e in f['events']])

    def test_altitude_trigger_only_on_descent_and_step_convergence(self):
        p = default_project()
        p['recovery'].update(mode='altitude', deploy_altitude_m=30)
        f = run_project(p)['flight']
        e = next(e for e in f['events'] if e['event'] == 'deployment')
        self.assertAlmostEqual(e['altitude_m'], 30, places=5)
        self.assertLess(e['velocity_m_s'], 0)
        p['solver']['max_step_s'] /= 2
        finer = run_project(p)['flight']
        self.assertLess(abs(finer['summary']['apogee_m']/f['summary']['apogee_m']-1), .01)
        self.assertLess(abs(finer['summary']['flight_time_s']/f['summary']['flight_time_s']-1), .01)

    def test_cancel_is_observed(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ProjectError):
            run_project(default_project(), stop)

    def test_output_decimation_cannot_hide_supersonic_peak(self):
        p = default_project()
        p['motor']['curve'] = [[0,0],[.05,1000],[.3,0],[10,0]]
        p['recovery']['mode'] = 'none'
        p['solver']['output_step_s'] = 100
        coarse = run_project(p)['flight']
        p['solver']['output_step_s'] = .01
        fine = run_project(p)['flight']
        self.assertFalse(coarse['valid_subsonic'])
        self.assertGreater(coarse['summary']['max_mach'], 1)
        self.assertAlmostEqual(coarse['summary']['max_speed_m_s'], fine['summary']['max_speed_m_s'], places=6)
        self.assertAlmostEqual(coarse['summary']['max_mach'], fine['summary']['max_mach'], places=6)

    def test_zero_force_tail_does_not_omit_burnout_before_landing(self):
        p = default_project()
        p['motor']['curve'] = [[0,0],[.1,20],[.5,0],[10,0]]
        p['recovery']['mode'] = 'none'
        e = next(e for e in run_project(p)['flight']['events'] if e['event']=='burnout')
        self.assertAlmostEqual(e['time_s'], .5)


if __name__ == '__main__':
    unittest.main()
