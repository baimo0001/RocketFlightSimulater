import csv
import html
import json
from pathlib import Path
from matplotlib.figure import Figure
from matplotlib import rcParams
from .project import save_project

rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

EVENT_LABELS = {'ignition':'点火', 'liftoff':'起飞', 'rail_exit':'离轨', 'burnout':'燃尽',
                'apogee':'最高点', 'deployment':'开伞', 'landing':'落地', 'model_limit':'模型高度上限'}
STATUS_LABELS = {'landed':'已落地', 'truncated':'仿真截断', 'no_liftoff':'未起飞',
                 'no_rail_exit':'未离轨', 'model_limit':'达到模型上限'}
STRUCTURE_LABELS = {'missing':'缺少压力输入，未计算', 'pass':'给定载荷下通过简化校核',
                    'fail':'简化校核不通过', 'not_applicable':'不满足薄壁假设，未计算'}


def make_figure(result, kind='flight'):
    fig = Figure(figsize=(10, 6), dpi=100, facecolor='#ffffff', layout='constrained')
    color = '#087f8c'
    flight = result['flight']
    samples = flight['samples']
    t = [x['time_s'] for x in samples]
    if kind == 'flight_combined':
        ax=fig.subplots();right=ax.twinx()
        line1=ax.plot(t,[x['altitude_m'] for x in samples],color='#2479b5',label='高度 / m',linewidth=1.8)
        line2=right.plot(t,[x['velocity_m_s'] for x in samples],color='#74a222',label='竖直速度 / m/s',linewidth=1.5)
        ax.set(xlabel='时间 / s',ylabel='高度 / m');right.set_ylabel('竖直速度 / m/s')
        ax.grid(alpha=.25,linestyle='--');lines=line1+line2
        ax.legend(lines,[x.get_label() for x in lines],loc='upper right',fontsize=9)
        for event in flight['events']:
            if event['event'] in ['burnout','apogee','deployment','landing']:
                ax.plot(event['time_s'],event['altitude_m'],'o',markersize=4,color='#b8802c')
                ax.axvline(event['time_s'],alpha=.18,color='#b8802c',linestyle='--')
    elif kind == 'flight':
        fields = [('altitude_m','高度 / m'), ('velocity_m_s','速度 / m/s'),
                  ('acceleration_m_s2','加速度 / m/s²'), ('dynamic_pressure_pa','动压 / Pa')]
        for ax, (key, label) in zip(fig.subplots(2, 2).flat, fields):
            ax.plot(t, [x[key] for x in samples], color=color, linewidth=1.6)
            ax.set(xlabel='时间 / s', ylabel=label)
            ax.grid(alpha=.18)
            for e in flight['events']:
                if e['event'] in ['apogee', 'deployment']:
                    ax.axvline(e['time_s'], color='#d08b26', alpha=.4, linestyle='--')
    elif kind == 'motor':
        m = result['motor']
        for ax, (key, label) in zip(fig.subplots(2, 2).flat,
                [('thrust_n','推力 / N'), ('remaining_propellant_kg','剩余推进剂 / kg'),
                 ('pressure_pa','燃烧室绝对压力 / Pa'), ('isp_s','发动机指标')]):
            if key in ['thrust_n','remaining_propellant_kg','pressure_pa'] and m[key] is not None:
                ax.plot(m['time_s'], m[key], color=color)
                ax.set(xlabel='时间 / s', ylabel=label); ax.grid(alpha=.18)
            else:
                ax.axis('off')
                text = '曲线模式未提供室压' if key == 'pressure_pa' else (
                    f"总冲：{m['total_impulse_ns']:.4g} N·s\n比冲：{m['isp_s']:.4g} s\n"
                    f"推进剂：{m['propellant_mass_kg']*1000:.4g} g\n曲线时长：{m['duration_s']:.4g} s")
                ax.text(.08, .6, text, va='center', transform=ax.transAxes, fontsize=12)
    else:
        a = result['analysis']
        d = result['project']['body']['diameter_m']
        ax1, ax2 = fig.subplots(2, 1)
        ax1.plot(t, [x['cg_m'] for x in samples], label='重心 CG', color=color)
        ax1.axhline(a['cp_m'], label='压心 CP（小迎角）', color='#d08b26', linestyle='--')
        ax1.set(ylabel='距头锥尖端 / m'); ax1.legend(); ax1.grid(alpha=.18)
        ax2.plot(t, [(a['cp_m']-x['cg_m'])/d for x in samples], color=color)
        ax2.axhline(0, color='#c44444', linestyle='--')
        ax2.set(xlabel='时间 / s', ylabel='静稳定裕度 / 箭体直径'); ax2.grid(alpha=.18)
    return fig


def summary_text(result, include_overview=True):
    a, m, f = result['analysis'], result['motor'], result['flight']
    s = f['summary']
    fmt = lambda v: '—' if v is None else f'{v:.4g}'
    lines = [f"状态：{STATUS_LABELS[f['status']]}",
             f"亚声速模型范围：{'范围内' if f['valid_subsonic'] else '超出范围'}",
             f"最高高度：{s['apogee_m']:.2f} m", f"最大速度：{s['max_speed_m_s']:.2f} m/s",
             f"最大马赫数：{s['max_mach']:.3f}", f"仿真时长：{s['flight_time_s']:.2f} s",
             f"离轨速度：{fmt(s['rail_exit_speed_m_s'])} m/s", f"落地速度：{fmt(s['landing_speed_m_s'])} m/s",
             f"开伞高度：{fmt(s['deployment_altitude_m'])} m", '',
             f"起飞质量：{a['initial_mass_kg']*1000:.2f} g", f"燃尽质量：{a['dry_mass_kg']*1000:.2f} g",
             f"总冲：{m['total_impulse_ns']:.3f} N·s", f"比冲：{m['isp_s']:.3f} s",
             f"有效排气速度：{m['isp_s']*9.80665:.2f} N·s/kg", f"曲线时长：{m['duration_s']:.3f} s",
             f"燃尽时刻：{m['burnout_time_s']:.3f} s",
             f"有效推力时长（>5%峰值）：{m['effective_burn_time_s']:.3f} s",
             f"点火 / 燃尽重心：{a['cg_initial_m']*1000:.1f} / {a['cg_burnout_m']*1000:.1f} mm",
             f"压心：{a['cp_m']*1000:.1f} mm",
             f"点火 / 燃尽静稳定：{a['stability_initial_cal']:.2f} / {a['stability_burnout_cal']:.2f} cal", '',
             f"结构：{STRUCTURE_LABELS[a['structure']['status']]}"]
    st = a['structure']
    if st['hoop_stress_pa'] is not None:
        lines.extend([f"环向 / 轴向应力：{st['hoop_stress_pa']/1e6:.3g} / {st['axial_stress_pa']/1e6:.3g} MPa",
                      f"连接件应力：{st['bolt_stress_pa']/1e6:.3g} MPa"])
    lines.extend(['', '模型提示：']+a['notes']+result['warnings'])
    if not include_overview:
        overview_labels = ('状态：', '最高高度：', '最大速度：', '仿真时长：', '落地速度：')
        lines = [line for line in lines if not line.startswith(overview_labels)]
    return '\n'.join(lines)


def export_report(result, directory):
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    save_project(result['project'], d/'project.json')
    (d/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for filename, rows in [('flight.csv', result['flight']['samples']), ('events.csv', result['flight']['events'])]:
        with open(d/filename, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    m = result['motor']
    with open(d/'motor.csv', 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time_s', 'thrust_n', 'remaining_propellant_kg', 'pressure_pa'])
        for i, t in enumerate(m['time_s']):
            writer.writerow([t, m['thrust_n'][i], m['remaining_propellant_kg'][i],
                             m['pressure_pa'][i] if m['pressure_pa'] else ''])
    for kind in ['flight', 'motor', 'stability']:
        fig = make_figure(result, kind)
        fig.savefig(d/f'{kind}.png', dpi=150)
        fig.clear()
    esc = html.escape
    rows = ''.join(f"<tr><td>{esc(EVENT_LABELS[e['event']])}</td><td>{e['time_s']:.4f}</td>"
                   f"<td>{e['altitude_m']:.3f}</td><td>{e['velocity_m_s']:.3f}</td></tr>" for e in result['flight']['events'])
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{esc(result['project']['name'])}</title>
<style>body{{font:16px/1.65 "Microsoft YaHei",sans-serif;color:#193348;max-width:1100px;margin:40px auto;padding:0 24px}}
h1{{font-size:30px}}h2{{margin-top:32px}}pre{{white-space:pre-wrap;background:#f3f7f8;padding:20px;border-radius:8px}}
table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #ccd8df;padding:8px}}
img{{width:100%;height:auto}}small{{color:#526779}}@media print{{body{{margin:0}}h2{{break-after:avoid}}img{{break-inside:avoid}}}}</style>
<h1>{esc(result['project']['name'])}</h1><small>模型火箭设计与仿真 APP {esc(result['version'])} · {esc(result['created_at'])}</small>
<p>单级、一维竖直、亚声速初步设计模型。静稳定分析不包含姿态动力学。</p>
<p>{esc(result['project']['notes'])}</p><h2>计算结果</h2><pre>{esc(summary_text(result))}</pre>
<h2>飞行事件</h2><table><tr><th>事件</th><th>时间 / s</th><th>高度 / m</th><th>速度 / m/s</th></tr>{rows}</table>
<h2>飞行曲线</h2><img src="flight.png" alt="高度速度加速度动压曲线">
<h2>发动机</h2><img src="motor.png" alt="发动机曲线">
<h2>静稳定</h2><img src="stability.png" alt="重心压心与静稳定裕度">
<h2>本次输入快照</h2><p>同目录 project.json 可重新加载，flight.csv / motor.csv / events.csv 为原始输出。</p>
<pre>{esc(json.dumps(result['project'], ensure_ascii=False, indent=2))}</pre></html>'''
    target = d/'report.html'
    target.write_text(text, encoding='utf-8')
    return target
