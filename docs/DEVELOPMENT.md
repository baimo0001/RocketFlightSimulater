# 开发指南

Python 入口是 `app.py`。Windows 图形界面使用 Tkinter/ttk，绘图使用 Matplotlib，数值计算使用 NumPy 和 SciPy。图形界面和命令行共用计算入口。

| 路径 | 职责 |
| --- | --- |
| `rocket/gui.py`、`rocket/ui_style.py` | 中文界面、组件编辑、主题与图表交互 |
| `rocket/project.py` | 项目格式、参数校验、文件加载与保存 |
| `rocket/pipeline.py` | 运行一次仿真并返回输入快照、分析及飞行结果 |
| `rocket/flight.py`、`rocket/analysis.py` | 飞行事件积分、质量与静稳定、结构校核 |
| `rocket/report.py` | PNG、CSV、JSON 和 HTML 报告 |
| `tests/`、`tools/` | 回归测试与外部对照适配器 |

## 验证改动

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe validate_matrix.py
```

图形界面测试请在可以创建 Tk 窗口的桌面环境运行。改动涉及项目格式时，用旧项目和新增示例各验证一次打开、运行、保存与再次打开。修改计算模块时，在提交说明中列明模型假设、输入和预期误差。报告问题时可附去除个人路径、备注和实验数据后的最小示例。

## 构建 Windows 便携包

按 README 建好环境，然后安装打包工具：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\build.ps1
```

可用 `-Python` 指定另一个环境的 Python 可执行文件。构建输出为 `dist/NebulaRocket/`。分发时压缩整个目录。发布前应将其复制到另一目录，再用其中的 EXE 打开示例、运行仿真并导出报告。

提交内容以源码、公开示例、文档和测试为主。`.gitignore` 已忽略构建产物、虚拟环境、运行日志和本地验证输出。
