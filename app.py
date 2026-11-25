import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='模型火箭设计与仿真 APP')
    parser.add_argument('--project', type=Path, help='载入 JSON 项目')
    parser.add_argument('--run', action='store_true', help='无界面计算')
    parser.add_argument('--export', type=Path, help='报告输出目录（与 --run 配合）')
    parser.add_argument('--demo', action='store_true', help='使用演示项目')
    parser.add_argument('--smoke-test', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    from rocket.project import default_project, load_project, ProjectError
    try:
        p = load_project(args.project) if args.project else default_project()
        if args.run:
            from rocket.pipeline import run_project
            from rocket.report import export_report
            result = run_project(p)
            if args.export:
                export_report(result, args.export)
            output = json.dumps(result['flight']['summary'], ensure_ascii=False, indent=2)
            if sys.stdout:
                print(output)
            return 0
        import tkinter as tk
        import matplotlib
        matplotlib.use('TkAgg')
        from rocket.gui import App
        if sys.platform == 'win32':
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        root = tk.Tk()
        if sys.platform == 'win32':
            root.attributes('-alpha', 0)
        app = App(root, p)
        if sys.platform == 'win32':
            root.after(320, lambda: root.attributes('-alpha', 1))
        if args.smoke_test:
            app.start_smoke_test(args.smoke_test)
        root.mainloop()
        return 0
    except Exception as e:
        if args.run:
            if sys.stderr:
                print(f'计算失败：{e}', file=sys.stderr)
            return 1
        import tkinter.messagebox as mb
        mb.showerror('启动失败', str(e))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
