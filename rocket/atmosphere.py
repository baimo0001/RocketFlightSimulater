import math
from .project import ProjectError

G0 = 9.80665
R = 287.05287


def atmosphere(altitude_m, temperature_k=288.15, pressure_pa=101325.):
    """干空气两层静力近似，-500~20000 m；海平面温度/压力可指定。"""
    if not -500 <= altitude_m <= 20000:
        raise ProjectError('大气模型超出 -500~20000 m 适用范围')
    lapse = .0065
    if altitude_m <= 11000:
        t = temperature_k-lapse*altitude_m
        p = pressure_pa*(t/temperature_k)**(G0/(R*lapse))
    else:
        t = temperature_k-lapse*11000
        p11 = pressure_pa*(t/temperature_k)**(G0/(R*lapse))
        p = p11*math.exp(-G0*(altitude_m-11000)/(R*t))
    return p/(R*t), p, t, math.sqrt(1.4*R*t)
