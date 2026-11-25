import math
from .motor import G0


def mass_properties(p, motor, time):
    parts = p['body']['parts']
    m = p['motor']
    remaining = motor.at(time)[1]
    mass = sum(x['mass_kg'] for x in parts)+m['dry_mass_kg']+remaining
    moment = sum(x['mass_kg']*x['position_m'] for x in parts)
    moment += m['dry_mass_kg']*m['position_m']+remaining*m['propellant_position_m']
    return mass, moment/mass


def analyze(p, motor):
    b, s = p['body'], p['structure']
    d = b['diameter_m']
    cr, ct, span, sweep = b['fin_root_m'], b['fin_tip_m'], b['fin_span_m'], b['fin_sweep_m']
    # Original subsonic Barrowman equations, cone + constant-diameter tube + trapezoid fins.
    midchord = math.hypot(span, sweep+(ct-cr)/2)
    cna_fins = (1+(d/2)/(span+d/2))*(4*b['fin_count']*(span/d)**2)/(1+math.sqrt(1+(2*midchord/(cr+ct))**2))
    x_fins = b['fin_position_m']+sweep/3*(cr+2*ct)/(cr+ct)+(cr+ct-cr*ct/(cr+ct))/6
    x_cone = 2*b['nose_length_m']/3
    cp = (2*x_cone+cna_fins*x_fins)/(2+cna_fins)
    m0, cg0 = mass_properties(p, motor, 0)
    mf, cgf = mass_properties(p, motor, motor.duration+1)
    pressure = s['pressure_pa']
    if pressure is None and motor.pressure is not None:
        pressure = max(0., float(max(motor.pressure))-p['motor']['ambient_pressure_pa'])
    shell_mass = math.pi*((s['diameter_m']/2+s['thickness_m'])**2-(s['diameter_m']/2)**2)*s['length_m']*s['density_kg_m3']
    structural = {'status': 'missing', 'pressure_pa': pressure,
                  'hoop_stress_pa': None, 'axial_stress_pa': None, 'bolt_stress_pa': None,
                  'shell_mass_kg': shell_mass}
    if pressure is not None:
        # diam is internal diameter; thin wall valid only when thickness/radius <= 0.1.
        if s['thickness_m']/(s['diameter_m']/2) > .1:
            structural['status'] = 'not_applicable'
        else:
            hoop = pressure*s['diameter_m']/(2*s['thickness_m'])
            axial = hoop/2
            bolt = pressure*math.pi*s['diameter_m']**2/4/(s['bolt_count']*s['bolt_effective_area_m2'])
            sf = s['safety_factor']
            utilization = max(hoop*sf/s['allowable_stress_pa'], bolt*sf/s['bolt_allowable_pa'])
            structural.update(status='pass' if utilization <= 1 else 'fail', hoop_stress_pa=hoop,
                              axial_stress_pa=axial, bolt_stress_pa=bolt, utilization=utilization)
    return {'initial_mass_kg': m0, 'dry_mass_kg': mf, 'cg_initial_m': cg0, 'cg_burnout_m': cgf,
            'cp_m': cp, 'stability_initial_cal': (cp-cg0)/d, 'stability_burnout_cal': (cp-cgf)/d,
            'peak_thrust_weight': float(max(motor.thrust))/(m0*G0),
            'structure': structural,
            'notes': ['压心采用圆锥头锥、等直径箭身、3/4片梯形尾翼的 Barrowman 小迎角近似。',
                      '干质量表不含发动机；发动机干质量与推进剂各计入一次。',
                      '壳体计算质量仅作参考，不自动加入整箭质量；需自行在质量表中填写。',
                      '结构为内压薄壁近似及端盖轴向载荷的连接件校核，未包含热效应和应力集中。']}
