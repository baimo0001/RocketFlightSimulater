"""批量工程算例：每组使用两个独立积分步长设置比较关键事件与峰值。"""
import copy
import csv
import json
from pathlib import Path
from rocket.project import default_project
from rocket.pipeline import run_project


def cases():
    base=default_project()
    yield '基准_顶点开伞',base
    for scale in [.7,1.4]:
        p=copy.deepcopy(base)
        for part in p['body']['parts']:
            part['mass_kg']*=scale
        yield f'干质量_{scale:g}倍',p
    for cd in [.25,.9]:
        p=copy.deepcopy(base);p['body']['drag_coefficient']=cd
        yield f'阻力系数_{cd:g}',p
    for altitude in [2500,10000]:
        p=copy.deepcopy(base);p['launch']['altitude_m']=altitude
        yield f'发射海拔_{altitude}m',p
    for area in [.06,.24]:
        p=copy.deepcopy(base);p['recovery']['area_m2']=area
        p['solver']['max_time_s']=250
        yield f'降落伞_{area:g}m2',p
    p=copy.deepcopy(base);p['recovery']['mode']='none'
    yield '无降落伞',p
    p=copy.deepcopy(base);p['recovery'].update(mode='altitude',deploy_altitude_m=30)
    yield '下降30m开伞',p
    p=copy.deepcopy(base);p['motor']['mode']='computed'
    yield '内孔燃烧内弹道',p
    p=copy.deepcopy(base);p['motor'].update(mode='computed',throat_diameter_m=.003)
    p['motor']['grain'].update(burn_inner=False,burn_ends=True)
    yield '端面燃烧内弹道',p
    p=copy.deepcopy(base);p['motor']['curve']=[[0,0],[.1,20],[.5,0],[10,0]]
    yield '零推力尾段',p
    p=copy.deepcopy(base);p['motor']['curve']=[[0,0],[1,.1],[2,0]]
    yield '推力不足未起飞',p
    p=copy.deepcopy(base);p['solver']['max_time_s']=1
    yield '最大时间截断',p


def main():
    target=Path(__file__).parent/'validation'
    target.mkdir(exist_ok=True)
    rows=[]
    for name,p in cases():
        coarse=run_project(p)
        fine_p=copy.deepcopy(p)
        fine_p['solver'].update(max_step_s=.01,rtol=1e-9)
        fine=run_project(fine_p)
        a,b=coarse['flight']['summary'],fine['flight']['summary']
        errors={key:abs(a[key]-b[key])/max(abs(b[key]),1e-9) for key in ['apogee_m','max_speed_m_s','flight_time_s']}
        event_a=[e['event'] for e in coarse['flight']['events']]
        event_b=[e['event'] for e in fine['flight']['events']]
        ok=max(errors.values())<.01 and event_a==event_b and coarse['flight']['status']==fine['flight']['status']
        rows.append({'case':name,'pass':ok,'status':coarse['flight']['status'],**a,
                     'max_relative_difference':max(errors.values()),'event_sequence':' > '.join(event_a)})
        print(f"{name}: {'PASS' if ok else 'FAIL'}，最大相对差 {max(errors.values()):.3g}")
    (target/'matrix.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    with open(target/'matrix.csv','w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    if not all(r['pass'] for r in rows):
        raise SystemExit(1)


if __name__=='__main__':
    main()
