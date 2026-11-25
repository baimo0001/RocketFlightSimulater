import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import brentq

from .project import ProjectError, validate_project

G0 = 9.80665


@dataclass
class Motor:
    time: np.ndarray
    thrust: np.ndarray
    remaining: np.ndarray
    pressure: np.ndarray | None
    propellant_mass_kg: float
    total_impulse_ns: float
    isp_s: float
    consumed: list
    warnings: list
    mode: str

    @property
    def duration(self):
        return float(self.time[-1])

    @property
    def burnout_time(self):
        last = int(np.flatnonzero(self.thrust > 0)[-1])
        return float(self.time[min(last+1, len(self.time)-1)])

    @property
    def effective_burn_time(self):
        """累计高于峰值推力 5% 的时长，线性段内求交点。"""
        threshold = float(max(self.thrust))*.05
        duration = 0.
        for i, (f0, f1) in enumerate(zip(self.thrust[:-1], self.thrust[1:])):
            dt = self.time[i+1]-self.time[i]
            if min(f0, f1) >= threshold:
                duration += dt
            elif max(f0, f1) > threshold:
                duration += dt*(max(f0, f1)-threshold)/abs(f1-f0)
        return float(duration)

    def at(self, t):
        if t > self.duration:
            return 0., 0., 0. if self.pressure is not None else None
        thrust = float(np.interp(t, self.time, self.thrust, left=0, right=0))
        # With proportional mass flow, integrate the linear thrust exactly.
        if self.mode == 'curve_proportional':
            i = min(max(int(np.searchsorted(self.time, t, side='right'))-1, 0), len(self.time)-2)
            dt = max(0., t-self.time[i])
            used = self.propellant_mass_kg/self.total_impulse_ns*(self.thrust[i]+thrust)*dt/2
            remaining = max(0., float(self.remaining[i])-used)
        else:
            remaining = float(np.interp(t, self.time, self.remaining))
        pressure = float(np.interp(t, self.time, self.pressure)) if self.pressure is not None else None
        return thrust, remaining, pressure


def grain_state(g, regression):
    ri = g['inner_diameter_m']/2 + regression*g['burn_inner']
    ro = g['outer_diameter_m']/2 - regression*g['burn_outer']
    length = g['length_m'] - 2*regression*g['burn_ends']
    if ri >= ro or length <= 0:
        return {'volume_m3': 0., 'area_m2': 0.}
    n = g['count']
    volume = math.pi*(ro*ro-ri*ri)*length*n
    area = 2*math.pi*n*(length*(ri*g['burn_inner']+ro*g['burn_outer'])
                         +(ro*ro-ri*ri)*g['burn_ends'])
    return {'volume_m3': volume, 'area_m2': area}


def read_curve(path):
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if not {'time_s', 'thrust_n'}.issubset(reader.fieldnames or []):
                raise ProjectError('CSV 需要 time_s,thrust_n 列，可选 remaining_propellant_kg')
            fields = ['time_s', 'thrust_n']
            if 'remaining_propellant_kg' in reader.fieldnames:
                fields.append('remaining_propellant_kg')
            return [[float(row[k]) for k in fields] for row in reader]
    except (OSError, ValueError, KeyError) as e:
        raise ProjectError(f'推力 CSV 无法读取：{e}') from e


def read_eng(path):
    records = []
    try:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            line = line.split(';')[0].strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) >= 7:
                record = {'name': fields[0], 'propellant_mass_kg': float(fields[4]),
                          'dry_mass_kg': float(fields[5])-float(fields[4]), 'curve': []}
                records.append(record)
            elif len(fields) == 2 and records:
                records[-1]['curve'].append([float(v) for v in fields])
            else:
                raise ProjectError('ENG 行格式无效，需标准 7 列头部及两列时序')
        if not records:
            raise ProjectError('ENG 中没有发动机记录')
        return records
    except (OSError, ValueError) as e:
        raise ProjectError(f'ENG 无法读取：{e}') from e


def build_motor(p, cancel=None):
    validate_project(p)
    m = p['motor']
    if m['mode'] == 'computed':
        return computed_motor(m, cancel)
    try:
        a = np.asarray(m['curve'], dtype=float)
    except (ValueError, TypeError) as e:
        raise ProjectError('motor.curve：需要等长两列或三列数值') from e
    if a.ndim != 2 or a.shape[0] < 3 or a.shape[1] not in [2, 3] or not np.all(np.isfinite(a)):
        raise ProjectError('motor.curve：至少三个有限数据点，格式为时间/推力/可选剩余质量')
    t, f = a[:, 0], a[:, 1]
    if t[0] != 0 or np.any(np.diff(t) <= 0) or np.any(f < 0) or f[0] != 0 or f[-1] != 0:
        raise ProjectError('motor.curve：须从 0 秒起、时间递增、推力非负且首尾推力为 0')
    impulse = float(np.trapz(f, t))
    if impulse <= 0:
        raise ProjectError('motor.curve：总冲必须为正')
    mp = m['propellant_mass_kg']
    warnings = []
    if a.shape[1] == 3:
        remaining = a[:, 2]
        if np.any(np.diff(remaining) > 1e-12) or np.any(remaining < 0) or not math.isclose(remaining[0], mp, abs_tol=1e-9) or abs(remaining[-1]) > 1e-9:
            raise ProjectError('motor.curve：剩余质量须从推进剂质量非增到 0，且不能为负')
        mode = 'curve_mass'
    else:
        remaining = mp*(1-cumulative_trapezoid(f, t, initial=0)/impulse)
        mode = 'curve_proportional'
        warnings.append('曲线未提供剩余质量：采用质量流量与推力成比例近似。')
    return Motor(t, f, remaining, None, mp, impulse, impulse/(mp*G0),
                 (-np.diff(remaining)).tolist(), warnings, mode)


def computed_motor(m, cancel=None):
    g = m['grain']
    rho = g['density_kg_m3']
    at = math.pi*m['throat_diameter_m']**2/4
    gamma = m['gamma']
    expansion = m['expansion_ratio']
    def area_ratio(mach):
        return ((2/(gamma+1)*(1+(gamma-1)*mach*mach/2))**((gamma+1)/(2*(gamma-1))))/mach
    me = 1. if expansion == 1 else brentq(lambda x: area_ratio(x)-expansion, 1.000000001, 30)
    pe_pc = (1+(gamma-1)*me*me/2)**(-gamma/(gamma-1))
    momentum_cf = math.sqrt(2*gamma**2/(gamma-1)*(2/(gamma+1))**((gamma+1)/(gamma-1))
                            *(1-pe_pc**((gamma-1)/gamma)))
    radial_surfaces = int(g['burn_inner'])+int(g['burn_outer'])
    limits = []
    if radial_surfaces:
        limits.append((g['outer_diameter_m']-g['inner_diameter_m'])/(2*radial_surfaces))
    if g['burn_ends']:
        limits.append(g['length_m']/2)
    end = min(limits)
    x = np.linspace(0, end, 501)
    time, thrust, pressure, remaining, consumed = [0.], [], [], [], []
    mp = grain_state(g, 0)['volume_m3']*rho
    for i in range(len(x)-1):
        if cancel and cancel.is_set():
            raise ProjectError('计算已取消')
        state = grain_state(g, float(x[i]))
        mid = grain_state(g, float((x[i]+x[i+1])/2))
        kn = mid['area_m2']/at
        # r in m/s, P normalized to 1 MPa: pressure below is MPa.
        p_mpa = (kn*rho*m['cstar_m_s']*(m['burn_a_mm_s']*.001)/1e6)**(1/(1-m['burn_n']))
        if not m['pressure_min_mpa'] <= p_mpa <= m['pressure_max_mpa']:
            raise ProjectError(f'motor：准稳态压力 {p_mpa:.4g} MPa 超出燃速参数有效区间，停止计算')
        pc = p_mpa*1e6
        pa = m['ambient_pressure_pa']
        critical = (2/(gamma+1))**(gamma/(gamma-1))
        if pa/pc >= critical or pe_pc*pc < .4*pa:
            raise ProjectError('motor：非堵塞或强过膨胀状态不在当前喷管近似适用范围内')
        cf = m['nozzle_efficiency']*(momentum_cf+(pe_pc-pa/pc)*expansion)
        if cf <= 0:
            raise ProjectError('motor：喷管模型未得到正推力')
        mdot = pc*at/m['cstar_m_s']
        dm = rho*(state['volume_m3']-grain_state(g, float(x[i+1]))['volume_m3'])
        dt = dm/mdot
        thrust.append(cf*pc*at)
        pressure.append(pc)
        remaining.append(rho*state['volume_m3'])
        consumed.append(dm)
        time.append(time[-1]+dt)
    # Piecewise constant cell loads: duplicate near-node times keep endpoint steps localized.
    times, forces, masses, pressures = [], [], [], []
    for i in range(len(thrust)):
        eps = min(1e-8, (time[i+1]-time[i])*1e-4)
        times.extend([time[i], time[i+1]-eps])
        forces.extend([thrust[i], thrust[i]])
        masses.extend([remaining[i], max(0., remaining[i]-consumed[i])])
        pressures.extend([pressure[i], pressure[i]])
    times.append(time[-1]); forces.append(0.); masses.append(0.); pressures.append(0.)
    impulse = float(np.trapz(forces, times))
    return Motor(np.array(times), np.array(forces), np.array(masses), np.array(pressures),
                 mp, impulse, impulse/(mp*G0), consumed,
                 ['准稳态内弹道：忽略点火/尾喷瞬态、侵蚀燃烧及喷管烧蚀。',
                  '计算模式推力使用给定固定环境压力；不随飞行海拔修正。'],
                 'computed')
