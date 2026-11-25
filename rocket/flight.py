import math
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq, minimize_scalar
from .atmosphere import atmosphere
from .analysis import mass_properties
from .project import ProjectError
from .motor import G0


def vertical_acceleration(height, velocity, mass, thrust, cd, area, rho):
    return (thrust-.5*rho*cd*area*velocity*abs(velocity))/mass-G0


def simulate(p, motor, cancel=None):
    b, l, r, q = p['body'], p['launch'], p['recovery'], p['solver']
    end = q['max_time_s']
    events = [{'event': 'ignition', 'time_s': 0., 'altitude_m': 0., 'velocity_m_s': 0.}]
    warnings = []
    if cancel and cancel.is_set():
        raise ProjectError('计算已取消')
    area = math.pi*b['diameter_m']**2/4
    def surplus(t):
        return motor.at(t)[0]-mass_properties(p, motor, t)[0]*G0
    lift = None
    last = 0.
    # Include midpoint to handle explicit mass curves even with flat force sections.
    nodes = np.unique(np.r_[motor.time, (motor.time[1:]+motor.time[:-1])/2])
    if surplus(0) > 0:
        lift = 0.
    else:
        for node in nodes[1:]:
            if surplus(float(node)) > 0:
                lift = brentq(surplus, last, float(node))
                break
            last = float(node)
    rail_exited = False
    apogee = None
    deployed = False
    landed = False
    out_of_range = False
    segments = []
    peak_speed = 0.
    peak_mach = 0.
    def event(name, t, y):
        events.append({'event': name, 'time_s': float(t), 'altitude_m': max(0., float(y[0])),
                       'velocity_m_s': float(y[1])})
    if lift is None:
        status = 'no_liftoff'
        stop = min(end, motor.duration)
        warnings.append('推力未克服重量，未起飞、未离轨。')
    elif lift >= end:
        status, stop = 'truncated', end
    else:
        event('liftoff', lift, [0, 0])
        t, y = float(lift), np.array([0., 0.])
        knots = motor.time[motor.time > t+1e-10]
        while t < end-1e-9 and not landed and not out_of_range:
            if cancel and cancel.is_set():
                raise ProjectError('计算已取消')
            deploy_time = apogee+r['delay_s'] if apogee is not None and r['mode'] == 'apogee' else math.inf
            if not deployed and r['mode'] == 'apogee' and t >= deploy_time-1e-8:
                deployed = True
                event('deployment', t, y)
            next_knots = knots[knots > t+1e-9]
            target = min(end, float(next_knots[0]) if len(next_knots) else end)
            if not deployed and t+1e-9 < deploy_time < target:
                target = deploy_time

            def derivative(ti, yi):
                if cancel and cancel.is_set():
                    raise ProjectError('计算已取消')
                # Solver stages may overshoot a terminal altitude; bound evaluation only.
                alt = min(20000., max(-500., l['altitude_m']+yi[0]))
                rho = atmosphere(alt, l['temperature_k'], l['sea_level_pressure_pa'])[0]
                cd_area = b['drag_coefficient']*area
                if deployed:
                    cd_area += r['drag_coefficient']*r['area_m2']
                mass = mass_properties(p, motor, ti)[0]
                acceleration = vertical_acceleration(yi[0], yi[1], mass, motor.at(ti)[0], cd_area, 1., rho)
                if yi[0] <= 0 and yi[1] <= 0 and acceleration <= 0:
                    return [0., 0.]
                return [yi[1], acceleration]

            funcs, names = [], []
            def add(name, fn, direction):
                fn.terminal = True
                fn.direction = direction
                funcs.append(fn); names.append(name)
            add('landing', lambda ti, yi: yi[0] if ti > lift+1e-7 else 1e-12, -1)
            add('model_limit', lambda ti, yi: 20000-l['altitude_m']-yi[0], -1)
            if not rail_exited:
                add('rail_exit', lambda ti, yi: yi[0]-l['rail_length_m'], 1)
            if apogee is None:
                add('apogee', lambda ti, yi: yi[1] if ti > lift+1e-7 else 1e-12, -1)
            if not deployed and apogee is not None and r['mode'] == 'altitude' and y[0] >= r['deploy_altitude_m']-1e-8:
                add('deployment', lambda ti, yi: yi[0]-r['deploy_altitude_m'], -1)
            sol = solve_ivp(derivative, (t, target), y, dense_output=True, events=funcs,
                            max_step=q['max_step_s'], rtol=q['rtol'], atol=1e-9)
            if not sol.success:
                raise ProjectError('飞行积分未收敛：'+sol.message)
            # Physical maxima use the integrator grid/dense solution, never display sampling.
            diagnostic_times = np.unique(np.r_[sol.t, (sol.t[:-1]+sol.t[1:])/2])
            states = sol.sol(diagnostic_times)
            speeds = np.abs(states[1])
            sounds = np.array([atmosphere(min(20000., max(-500., l['altitude_m']+float(h))),
                                         l['temperature_k'], l['sea_level_pressure_pa'])[3] for h in states[0]])
            for values, kind in [(speeds, 'speed'), (speeds/sounds, 'mach')]:
                best = float(max(values))
                index = int(np.argmax(values))
                if 0 < index < len(diagnostic_times)-1:
                    def metric(ti):
                        state = sol.sol(ti)
                        speed = abs(float(state[1]))
                        if kind == 'speed':
                            return speed
                        sound = atmosphere(min(20000., max(-500., l['altitude_m']+float(state[0]))),
                                           l['temperature_k'], l['sea_level_pressure_pa'])[3]
                        return speed/sound
                    optimum = minimize_scalar(lambda ti: -metric(ti),
                                              bounds=(diagnostic_times[index-1], diagnostic_times[index+1]),
                                              method='bounded', options={'xatol':1e-10})
                    best = max(best, -float(optimum.fun))
                if kind == 'speed':
                    peak_speed = max(peak_speed, best)
                else:
                    peak_mach = max(peak_mach, best)
            segments.append((t, float(sol.t[-1]), sol.sol, deployed))
            t, y = float(sol.t[-1]), sol.y[:, -1]
            triggered = next((names[i] for i, ts in enumerate(sol.t_events) if len(ts)), None)
            if triggered:
                event(triggered, t, y)
                if triggered == 'rail_exit':
                    rail_exited = True
                elif triggered == 'apogee':
                    apogee = t
                elif triggered == 'deployment':
                    deployed = True
                elif triggered == 'landing':
                    landed = True
                elif triggered == 'model_limit':
                    out_of_range = True
        stop = t
        status = 'landed' if landed else 'model_limit' if out_of_range else 'truncated'
        if not rail_exited:
            status = 'no_rail_exit'
            warnings.append('未离轨；该次轨迹不能作为正常自由飞行结果。')
        if status == 'truncated':
            warnings.append('达到最大仿真时间，轨迹截断；尚未发生的事件不予推算。')
        if out_of_range:
            warnings.append('超过大气模型 20000 m 上限，停止积分。')
    if stop >= motor.burnout_time:
        state = next((seg[2](motor.burnout_time) for seg in segments if seg[0] <= motor.burnout_time <= seg[1]), [0, 0])
        event('burnout', motor.burnout_time, state)
    events.sort(key=lambda e: e['time_s'])
    sample_times = np.unique(np.r_[np.arange(0, stop, q['output_step_s']), stop, [e['time_s'] for e in events]])
    samples = []
    seg_index = 0
    deploy_at = next((e['time_s'] for e in events if e['event'] == 'deployment'), math.inf)
    for ti in sample_times:
        while seg_index+1 < len(segments) and segments[seg_index][1] < ti-1e-9:
            seg_index += 1
        seg = segments[seg_index] if segments else None
        height, v = seg[2](ti) if seg and seg[0]-1e-9 <= ti <= seg[1]+1e-9 else [0., 0.]
        height, v = max(0., float(height)), float(v)
        if landed and abs(ti-stop) < 1e-8:
            height = 0.
        thrust, remain, pressure = motor.at(float(ti))
        mass, cg = mass_properties(p, motor, float(ti))
        rho, pa, temp, sound = atmosphere(min(20000., l['altitude_m']+height), l['temperature_k'], l['sea_level_pressure_pa'])
        cda = b['drag_coefficient']*area+(r['drag_coefficient']*r['area_m2'] if ti >= deploy_at else 0)
        drag = -.5*rho*cda*v*abs(v)
        acceleration = (thrust+drag)/mass-G0
        if lift is None or ti < lift:
            acceleration = 0.
        samples.append({'time_s': float(ti), 'altitude_m': height, 'velocity_m_s': v,
                        'acceleration_m_s2': acceleration, 'mass_kg': mass, 'cg_m': cg,
                        'thrust_n': thrust, 'drag_n': drag, 'dynamic_pressure_pa': .5*rho*v*v,
                        'mach': abs(v)/sound, 'density_kg_m3': rho, 'pressure_pa': pressure,
                        'remaining_propellant_kg': remain})
    max_mach = peak_mach
    if max_mach >= .8:
        warnings.append('马赫数达到/超过 0.8，恒定阻力系数和亚声速静稳定近似超范围，结果仅作数值演示。')
    if r['mode'] != 'none' and not deployed and status == 'landed':
        warnings.append('落地前未满足开伞条件。')
    summary = {'apogee_m': max(s['altitude_m'] for s in samples),
               'max_speed_m_s': peak_speed,
               'max_mach': max_mach, 'flight_time_s': stop,
               'landing_speed_m_s': abs(samples[-1]['velocity_m_s']) if landed else None,
               'rail_exit_speed_m_s': next((e['velocity_m_s'] for e in events if e['event'] == 'rail_exit'), None),
               'deployment_altitude_m': next((e['altitude_m'] for e in events if e['event'] == 'deployment'), None)}
    return {'status': status, 'valid_subsonic': max_mach < .8 and not out_of_range,
            'samples': samples, 'events': events, 'summary': summary, 'warnings': warnings}
