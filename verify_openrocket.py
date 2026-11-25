"""调用本机 OpenRocket 23.09 核心进行独立对照，不改写安装文件。"""
import copy
import argparse
import csv
import json
import os
import shutil
import subprocess
from pathlib import Path
import numpy as np
from rocket.project import default_project, save_project
from rocket.motor import build_motor
from rocket.pipeline import run_project

ROOT=Path(__file__).parent.resolve()


def make_properties(p,matched):
    b,m=p['body'],p['motor'];motor=build_motor(p)
    parts=b['parts'];dry=sum(x['mass_kg'] for x in parts)
    values={'name':p['name'],'matched':str(matched).lower(),'diameter':b['diameter_m'],'length':b['length_m'],
            'nose':b['nose_length_m'],'fin_count':b['fin_count'],'fin_root':b['fin_root_m'],
            'fin_tip':b['fin_tip_m'],'fin_span':b['fin_span_m'],'fin_sweep':b['fin_sweep_m'],
            'fin_position':b['fin_position_m'],'airframe_mass':dry,
            'airframe_cg':sum(x['mass_kg']*x['position_m'] for x in parts)/dry,
            'motor_position':m['position_m'],'motor_dry':m['dry_mass_kg'],
            'rail':p['launch']['rail_length_m'],'altitude':p['launch']['altitude_m'],'cd':b['drag_coefficient']}
    times=np.unique(np.r_[motor.time,np.arange(0,motor.duration,.002)])
    rows=[motor.at(float(t)) for t in times]
    values['times']=','.join(f'{t:.12g}' for t in times)
    values['forces']=','.join(f'{row[0]:.12g}' for row in rows)
    values['remaining']=','.join(f'{row[1]:.12g}' for row in rows)
    return '\n'.join(f'{k}={v}' for k,v in values.items())


def scenarios():
    for name,scale,cd,alt in [('baseline',1,.5,0),('light',.7,.5,0),('heavy',1.4,.5,0),
                               ('low_drag',1,.25,0),('high_drag',1,.9,0),('altitude_2500',1,.5,2500)]:
        p=default_project();p['name']=name;p['recovery']['mode']='none'
        p['body']['drag_coefficient']=cd;p['launch']['altitude_m']=alt
        for part in p['body']['parts']:
            part['mass_kg']*=scale
        yield name,p


def main():
    parser = argparse.ArgumentParser(description='使用 OpenRocket 23.09 生成对照结果')
    parser.add_argument('--install', type=Path, default=os.environ.get('OPENROCKET_HOME'),
                        help='包含 OpenRocket.jar 的安装目录，也可设置 OPENROCKET_HOME')
    parser.add_argument('--ecj', type=Path, help='可选 Eclipse Java 编译器 JAR，用于没有 JDK 17 的环境')
    parser.add_argument('--output', type=Path, default=ROOT/'validation/openrocket')
    parser.add_argument('--first', action='store_true', help='仅运行基准工况的两种对照模式')
    args = parser.parse_args()
    if args.install is None:
        parser.error('请通过 --install 或 OPENROCKET_HOME 指定 OpenRocket 23.09 安装目录')
    jar = args.install.resolve()/'OpenRocket.jar'
    if not jar.is_file():
        parser.error(f'找不到 {jar}')
    bundled_java = jar.parent/'jre/bin/java.exe'
    java = str(bundled_java) if bundled_java.is_file() else shutil.which('java')
    if not java:
        parser.error('找不到 Java 17。请安装 JDK 17 或使用 OpenRocket 自带的 Java 运行时')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    compiler = [java, '-jar', str(args.ecj.resolve()), '-17'] if args.ecj else ['javac', '--release', '17']
    try:
        subprocess.run(compiler + ['-encoding', 'UTF-8', '-cp', str(jar), '-d', str(out),
                                  str(ROOT/'tools/OpenRocketReference.java')], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Java 适配器编译失败，请检查 JDK 17 或 --ecj 参数。\n{exc}\n')
    results=[]
    selected=list(scenarios())[:1] if args.first else list(scenarios())
    for name,p in selected:
        app=run_project(p)
        summary=app['flight']['summary']
        for matched in [True,False]:
            case=out/(name+('_matched' if matched else '_native'))
            case.mkdir(exist_ok=True)
            save_project(p,case/'project.json')
            (case/'input.properties').write_text(make_properties(p,matched),encoding='utf-8')
            cmd=[java,'-Djava.awt.headless=true','-Dfile.encoding=UTF-8',
                 '-Djava.util.prefs.userRoot='+str(out/'preferences'),
                 '--add-opens=java.base/java.lang=ALL-UNNAMED',
                 '-cp',os.pathsep.join((str(out),str(jar))),'OpenRocketReference',
                 str(case/'input.properties'),str(case)]
            run=subprocess.run(cmd,capture_output=True,encoding='utf-8',errors='replace',timeout=120)
            (case/'run.log').write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
            if run.returncode:
                print(run.stderr[-5000:]);raise SystemExit(run.returncode)
            with open(case/'summary.csv',encoding='utf-8') as f:
                ref={k:float(v) for k,v in next(csv.DictReader(f)).items()}
            apex_error=abs(summary['apogee_m']/ref['apogee_m']-1)
            speed_error=abs(summary['max_speed_m_s']/ref['max_ascent_speed_m_s']-1)
            row={'case':name,'mode':'matched_constant_cd' if matched else 'native_extended_barrowman',
                 'app_apogee_m':summary['apogee_m'],'openrocket_apogee_m':ref['apogee_m'],
                 'apogee_relative_difference':apex_error,'app_max_speed_m_s':summary['max_speed_m_s'],
                 'openrocket_max_ascent_speed_m_s':ref['max_ascent_speed_m_s'],
                 'speed_relative_difference':speed_error,'app_cp_m':app['analysis']['cp_m'],
                 'openrocket_cp_at_mach0_m':ref['cp_m'],'app_initial_mass_kg':app['analysis']['initial_mass_kg'],
                 'openrocket_initial_mass_kg':ref['initial_mass_kg'],
                 'app_initial_cg_m':app['analysis']['cg_initial_m'],'openrocket_initial_cg_m':ref['initial_cg_m'],
                 'app_total_impulse_ns':app['motor']['total_impulse_ns'],'openrocket_total_impulse_ns':ref['total_impulse_ns'],
                 'matched_pass':apex_error<.01 and speed_error<.01 if matched else None}
            results.append(row)
            print(f"{name} {'matched' if matched else 'native'}: 高度差{apex_error:.3%}，速度差{speed_error:.3%}")
    (out/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    with open(out/'comparison.csv','w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(results[0]));writer.writeheader();writer.writerows(results)
    if any(r['matched_pass'] is False for r in results):
        raise SystemExit(1)


if __name__=='__main__':
    main()
