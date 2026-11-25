import copy
import json
import math
from pathlib import Path


class ProjectError(ValueError):
    """可向用户直接显示的参数或文件错误。"""


def default_project():
    return {
        'schema_version': 1, 'name': '演示demo单级模型火箭',
        'notes': '只供演示用。',
        'motor': {
            'mode': 'curve',
            'dry_mass_kg': .04, 'position_m': .75, 'propellant_position_m': .75,
            'propellant_mass_kg': .025,
            'curve': [[0, 0], [.05, 22], [.15, 18], [1.3, 16], [1.5, 0]],
            'grain': {'outer_diameter_m': .03, 'inner_diameter_m': .012,
                      'length_m': .05, 'count': 1, 'density_kg_m3': 1500.,
                      'burn_inner': True, 'burn_outer': False, 'burn_ends': False},
            'chamber_diameter_m': .032, 'chamber_length_m': .06,
            'throat_diameter_m': .004, 'expansion_ratio': 1.,
            'burn_a_mm_s': 2., 'burn_n': .3, 'pressure_min_mpa': .15,
            'pressure_max_mpa': 5., 'cstar_m_s': 1000., 'gamma': 1.2,
            'nozzle_efficiency': .9, 'ambient_pressure_pa': 101325.,
        },
        'body': {'diameter_m': .05, 'length_m': .85, 'nose_length_m': .18,
                 'drag_coefficient': .5, 'fin_count': 3, 'fin_root_m': .15,
                 'fin_tip_m': .07, 'fin_span_m': .07, 'fin_sweep_m': .06,
                 'fin_position_m': .65,
                 'parts': [{'name': '头锥', 'mass_kg': .025, 'position_m': .11},
                           {'name': '箭身', 'mass_kg': .08, 'position_m': .50},
                           {'name': '尾翼', 'mass_kg': .015, 'position_m': .74},
                           {'name': '载荷与回收', 'mass_kg': .06, 'position_m': .27}]},
        'structure': {'pressure_pa': None,
                      'diameter_m': .032, 'thickness_m': .001, 'length_m': .06,
                      'density_kg_m3': 2700., 'allowable_stress_pa': 50e6,
                      'safety_factor': 2., 'bolt_count': 4,
                      'bolt_effective_area_m2': 8e-6, 'bolt_allowable_pa': 60e6},
        'launch': {'altitude_m': 0., 'rail_length_m': 1., 'temperature_k': 288.15,
                   'sea_level_pressure_pa': 101325.},
        'recovery': {'mode': 'apogee', 'delay_s': .5, 'deploy_altitude_m': 80.,
                     'area_m2': .12, 'drag_coefficient': 1.2},
        'solver': {'output_step_s': .05, 'max_step_s': .04, 'rtol': 1e-7,
                   'max_time_s': 180.}
    }


def validate_project(p):
    if not isinstance(p, dict) or p.get('schema_version') != 1:
        raise ProjectError('项目版本不支持（需要 schema_version=1）')

    def walk(value, template, path=''):
        if isinstance(template, dict):
            if not isinstance(value, dict):
                raise ProjectError(f'{path}：需要参数分组')
            for k, v in template.items():
                if k not in value:
                    raise ProjectError(f'{path}.{k}：缺少字段')
                walk(value[k], v, f'{path}.{k}'.strip('.'))
        elif isinstance(template, bool):
            if not isinstance(value, bool):
                raise ProjectError(f'{path}：需要布尔值')
        elif isinstance(template, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ProjectError(f'{path}：需要有限数值')
        elif isinstance(template, str) and not isinstance(value, str):
            raise ProjectError(f'{path}：需要文字')
        elif isinstance(template, list) and not isinstance(value, list):
            raise ProjectError(f'{path}：需要列表')
    walk(p, default_project())

    def positive(group, *keys, zero=False):
        for k in keys:
            v = p[group][k]
            if v < 0 or (not zero and v == 0):
                raise ProjectError(f'{group}.{k}：必须为' + ('非负数' if zero else '正数'))
    m, b, s, r, l, g = p['motor'], p['body'], p['structure'], p['recovery'], p['launch'], p['motor']['grain']
    for key in ['outer_diameter_m', 'length_m', 'density_kg_m3', 'count']:
        if g[key] <= 0:
            raise ProjectError(f'motor.grain.{key}：必须为正数')
    if g['count'] != int(g['count']):
        raise ProjectError('motor.grain.count：段数必须为正整数')
    if not 0 <= g['inner_diameter_m'] < g['outer_diameter_m']:
        raise ProjectError('motor.grain.inner_diameter_m：内径必须小于外径且不能为负')
    if not any(g[k] for k in ['burn_inner', 'burn_outer', 'burn_ends']) or (g['burn_inner'] and not g['inner_diameter_m']):
        raise ProjectError('motor.grain：需要有效可燃表面，中空燃烧需要正内径')
    if g['outer_diameter_m'] >= m['chamber_diameter_m'] or g['length_m']*g['count'] > m['chamber_length_m']:
        raise ProjectError('motor.grain：药柱必须适配燃烧室并保留正自由容积')
    positive('motor', 'dry_mass_kg', 'propellant_mass_kg', 'throat_diameter_m', 'burn_a_mm_s',
             'cstar_m_s', 'pressure_min_mpa', 'pressure_max_mpa', 'ambient_pressure_pa')
    if m['mode'] not in ['curve', 'computed']:
        raise ProjectError('motor.mode：只能为 curve 或 computed')
    if not 0 <= m['burn_n'] < 1 or not 1 < m['gamma'] <= 1.67:
        raise ProjectError('motor：需要 0≤燃速指数<1、1<比热比≤1.67')
    if m['expansion_ratio'] < 1 or not 0 < m['nozzle_efficiency'] <= 1:
        raise ProjectError('motor：膨胀比须≥1，喷管效率须在 (0,1]')
    if m['pressure_min_mpa'] >= m['pressure_max_mpa']:
        raise ProjectError('motor：压力有效区间上下限颠倒')
    positive('body', 'diameter_m', 'length_m', 'nose_length_m', 'fin_root_m', 'fin_tip_m', 'fin_span_m')
    positive('body', 'drag_coefficient', 'fin_sweep_m', zero=True)
    if b['nose_length_m'] >= b['length_m'] or b['fin_position_m'] < b['nose_length_m'] or b['fin_position_m']+b['fin_root_m'] > b['length_m']:
        raise ProjectError('body：头锥或尾翼位置超出箭体范围')
    if b['fin_count'] not in [3, 4]:
        raise ProjectError('body.fin_count：首版支持 3 或 4 片尾翼')
    if not b['parts']:
        raise ProjectError('body.parts：至少需要一个干质量部件（不含发动机）')
    for i, part in enumerate(b['parts']):
        if not isinstance(part, dict) or not isinstance(part.get('name'), str):
            raise ProjectError(f'body.parts[{i}]：部件格式错误')
        for k in ['mass_kg', 'position_m']:
            v = part.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ProjectError(f'body.parts[{i}].{k}：需要有限非负数')
        if part['position_m'] > b['length_m']:
            raise ProjectError(f'body.parts[{i}].position_m：超出箭体长度')
    for k in ['position_m', 'propellant_position_m']:
        if not 0 <= m[k] <= b['length_m']:
            raise ProjectError(f'motor.{k}：超出箭体长度')
    positive('structure', 'diameter_m', 'thickness_m', 'length_m', 'density_kg_m3',
             'allowable_stress_pa', 'safety_factor', 'bolt_count', 'bolt_effective_area_m2', 'bolt_allowable_pa')
    if s['bolt_count'] != int(s['bolt_count']) or s['safety_factor'] < 1:
        raise ProjectError('structure：连接件数量须为整数，安全系数须≥1')
    if s['pressure_pa'] is not None and (isinstance(s['pressure_pa'], bool) or not isinstance(s['pressure_pa'], (int, float)) or not math.isfinite(s['pressure_pa']) or s['pressure_pa'] <= 0):
        raise ProjectError('structure.pressure_pa：须为正压力或空值')
    if r['mode'] not in ['none', 'apogee', 'altitude']:
        raise ProjectError('recovery.mode：不支持的开伞模式')
    positive('recovery', 'area_m2', 'drag_coefficient')
    positive('recovery', 'delay_s', 'deploy_altitude_m', zero=True)
    if not -500 <= l['altitude_m'] <= 19000 or not 250 <= l['temperature_k'] <= 320:
        raise ProjectError('launch：海拔范围 -500~19000 m，海平面温度范围 250~320 K')
    positive('launch', 'rail_length_m', 'sea_level_pressure_pa')
    positive('solver', 'output_step_s', 'max_step_s', 'rtol', 'max_time_s')
    q = p['solver']
    if q['max_time_s']/q['output_step_s'] > 300000 or q['max_time_s']/q['max_step_s'] > 1000000:
        raise ProjectError('solver：采样/步长过密，请减少仿真时间或增大步长')
    if not 1e-10 <= q['rtol'] <= .001:
        raise ProjectError('solver.rtol：范围 1e-10~1e-3')


def load_project(path):
    try:
        p = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as e:
        raise ProjectError(f'无法读取项目：{e}') from e
    validate_project(p)
    return without_source_fields(p)


def without_source_fields(project):
    """Accept legacy schema-1 metadata without carrying it into new outputs."""
    updated = dict(project)
    for group in ('motor', 'structure'):
        updated[group] = dict(project[group])
        updated[group].pop('source', None)
    return updated


def save_project(p, path):
    validate_project(p)
    target = Path(path)
    temp = target.with_suffix(target.suffix+'.tmp')
    temp.write_text(json.dumps(without_source_fields(p), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(target)
