# 验证指南

本项目从三个层面验证仿真结果：解析算例、积分收敛以及与 OpenRocket 23.09 的同条件对照。

## 自动测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe validate_matrix.py
```

测试覆盖解析弹道、大气、质量与重心、结构及静稳定、事件定位、项目加载和报告导出。`validate_matrix.py` 计算 16 组工况，用两套积分步长和容差比较峰值、时长及事件顺序，输出 `validation/matrix.csv` 和 `validation/matrix.json`。

## OpenRocket 对照

可选验证需要 OpenRocket 23.09 和可用的 JDK 17 编译器。把下面的目录替换为你的安装目录：

```powershell
.\.venv\Scripts\python.exe verify_openrocket.py --install "<OpenRocket 安装目录>"
```

也可设置 `OPENROCKET_HOME`。安装目录应包含 `OpenRocket.jar`。路径中存在空格时加引号。如果使用 OpenRocket 自带的 Java 17 和 Eclipse Java 编译器，可通过 `--ecj "<编译器 JAR 路径>"` 编译适配器。加上 `--first` 仅计算基准工况。

默认生成 6 个工况，每组计算两次。第一种使用相同常数阻力系数，比较独立引擎对同一组假设的结果。第二种使用 OpenRocket 原生气动模型，评估模型选择对输出的影响。结果保存在 `validation/openrocket/comparison.csv`，各工况目录还包含时序和事件文件。

| 对照项 | 既有 6 组工况的结果 |
| --- | ---: |
| 同常数阻力系数，最高高度最大相对差 | 0.0086% |
| 同常数阻力系数，最大上升速度最大相对差 | 0.0027% |
| 原生气动与常数阻力模型，最高高度相对差 | 5.3%–36.6% |

这些差异量化的是计算实现和模型选择。真实飞行误差需要结合实际飞行记录评估。
