"""独立基准：标准大气表、几何微分关系、端面燃烧解析解和静稳定手算。"""
import copy
import math
import unittest
from rocket.project import default_project, ProjectError
from rocket.atmosphere import atmosphere
from rocket.motor import build_motor, grain_state
from rocket.analysis import analyze
from rocket.pipeline import run_project


class ReferenceCases(unittest.TestCase):
    def test_five_standard_atmosphere_reference_points(self):
        # ISA geometric-altitude approximation; rounded engineering table values.
        for altitude, rho, pressure, temperature in [(0,1.225,101325,288.15),
                (5000,.73612,54019.9,255.65),(11000,.36392,22632.1,216.65),
                (15000,.19367,12044.6,216.65),(20000,.08803,5474.9,216.65)]:
            with self.subTest(altitude=altitude):
                actual=atmosphere(altitude)
                self.assertAlmostEqual(actual[0],rho,delta=.00002)
                self.assertAlmostEqual(actual[1],pressure,delta=1.)
                self.assertAlmostEqual(actual[2],temperature,delta=.01)

    def test_seven_burn_surface_combinations_preserve_volume_derivative(self):
        for mask in range(1,8):
            g=default_project()['motor']['grain']
            g.update(burn_inner=bool(mask&1),burn_outer=bool(mask&2),burn_ends=bool(mask&4),count=3)
            x=.001; step=1e-8
            dv=(grain_state(g,x-step)['volume_m3']-grain_state(g,x+step)['volume_m3'])/(2*step)
            self.assertAlmostEqual(dv,grain_state(g,x)['area_m2'],delta=1e-10)

    def test_end_burn_constant_area_matches_analytic_burn_time(self):
        p=default_project();m=p['motor'];g=m['grain']
        m.update(mode='computed',throat_diameter_m=.003)
        g.update(burn_inner=False,burn_ends=True)
        motor=build_motor(p)
        pc=float(motor.pressure[0])/1e6
        rate=.002*pc**.3
        self.assertAlmostEqual(motor.duration,.025/rate,places=8)
        self.assertLess(max(motor.pressure[:-1])-min(motor.pressure[:-1]),1e-7)

    def test_sonic_exit_thrust_matches_momentum_plus_pressure(self):
        p=default_project();p['motor']['mode']='computed'
        motor=build_motor(p);m=p['motor']
        pc=motor.pressure[0];gamma=m['gamma']
        pe=pc*(2/(gamma+1))**(gamma/(gamma-1))
        area=math.pi*m['throat_diameter_m']**2/4
        # M=1: momentum flux = gamma * exit pressure * throat area.
        expected=.9*((gamma+1)*pe-m['ambient_pressure_pa'])*area
        self.assertAlmostEqual(motor.thrust[0],expected,places=10)

    def test_rectangular_fin_static_center_hand_reference(self):
        p=default_project()
        p['body'].update(fin_count=4,fin_root_m=.1,fin_tip_m=.1,fin_span_m=.05,
                         fin_sweep_m=0,fin_position_m=.6)
        self.assertAlmostEqual(analyze(p,build_motor(p))['cp_m'],.5413369410713945,places=12)

    def test_variable_mass_vacuum_matches_rocket_equation(self):
        p=default_project()
        p['body']['parts']=[{'name':'解析算例干质量','mass_kg':1.7,'position_m':.3}]
        p['body']['drag_coefficient']=0
        p['motor'].update(dry_mass_kg=.1,propellant_mass_kg=.2,
                          curve=[[0,0],[1e-6,40],[2,40],[2.000001,0]])
        p['recovery']['mode']='none'
        p['launch']['rail_length_m']=.01
        f=run_project(p)['flight']
        burnout=next(e for e in f['events'] if e['event']=='burnout')
        # Constant mass flow .1 kg/s, exhaust velocity 400m/s, m0=2, mf=1.8.
        expected_v=400*math.log(2/1.8)-9.80665*2
        expected_h=400*(2+18*math.log(.9))-.5*9.80665*4
        self.assertAlmostEqual(burnout['velocity_m_s'],expected_v,delta=.0001)
        self.assertAlmostEqual(burnout['altitude_m'],expected_h,delta=.0001)

    def test_wrong_pressure_range_and_nonchoked_nozzle_are_rejected(self):
        for changes in [{'pressure_max_mpa':.2},{'ambient_pressure_pa':2e6}]:
            p=default_project();p['motor'].update(mode='computed',**changes)
            with self.assertRaises(ProjectError):
                build_motor(p)


if __name__=='__main__':
    unittest.main()
