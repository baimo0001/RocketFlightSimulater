import copy
from datetime import datetime
from . import __version__
from .project import validate_project, without_source_fields
from .motor import build_motor
from .analysis import analyze
from .flight import simulate


def run_project(project, cancel=None):
    validate_project(project)
    p = copy.deepcopy(without_source_fields(project))
    motor = build_motor(p, cancel)
    analysis = analyze(p, motor)
    flight = simulate(p, motor, cancel)
    warnings = motor.warnings+flight['warnings']
    if min(analysis['stability_initial_cal'], analysis['stability_burnout_cal']) <= 0:
        warnings.append('点火或燃尽静稳定裕度非正；一维模型不模拟因此产生的姿态偏离。')
    return {'project': p, 'version': __version__, 'created_at': datetime.now().astimezone().isoformat(),
            'analysis': analysis, 'flight': flight, 'warnings': warnings,
            'motor': {'time_s': motor.time.tolist(), 'thrust_n': motor.thrust.tolist(),
                      'remaining_propellant_kg': motor.remaining.tolist(),
                      'pressure_pa': motor.pressure.tolist() if motor.pressure is not None else None,
                      'total_impulse_ns': motor.total_impulse_ns, 'isp_s': motor.isp_s,
                      'propellant_mass_kg': motor.propellant_mass_kg,
                      'duration_s': motor.duration, 'burnout_time_s':motor.burnout_time,
                      'effective_burn_time_s':motor.effective_burn_time}}
