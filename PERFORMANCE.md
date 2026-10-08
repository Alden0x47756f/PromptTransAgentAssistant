# 界面性能与资源测量 — v1.0.1

## 改动

1. **按需创建网页界面**：启动时只创建原生悬浮控件；首次展开对话或设置时才导入 WebEngine、启动渲染进程。随后保留页面，收起 / 展开不会丢失对话和草稿。
2. **合并界面刷新**：文本及滚动操作合并到下一动画帧。已通过语言校验的结果在 `done` 时直接完成最终格式化，省去同一结果的中间排版及重复同步布局。
3. **避免重复实例加载桌面模块**：单实例锁检查通过后才导入桌面实现。

标题栏仅保留收起按钮；结果复制操作位于正文和输出上限提示之后。推理仍在后台执行，候选结果仍在语言校验通过后才交给前端。

## 测量结果

同一台 Windows x64 机器，分别启动三个独立 Python 源码进程，取中位数。使用隔离配置，自动加载关闭，不启动 LLM 或调用付费 API。测试结果文本为 600 行；每轮测试连续处理五组结果事件。

| 指标 | v1.0.0 基线 | v1.0.1 |
| --- | ---: | ---: |
| 界面构造时间，含 Python / Qt 模块导入 | 670 ms | 258 ms |
| 未首次展开时，界面进程树工作集总和 | 268 MiB | 66 MiB |
| 未首次展开时，界面进程树私有提交量 | 149 MiB | 36 MiB |
| 首次展开设置页并连通 WebChannel | 81 ms | 572 ms |
| 展开并处理测试结果后的工作集总和 | 353 MiB | 332 MiB |
| 结果事件的同步 JavaScript 处理时间 | 16.1 ms | 0.2 ms |

未首次展开时的工作集约减少 75%，界面构造时间约减少 62%。首次展开承担原本在启动时执行的网页初始化，因此该次展开更慢；后续展开复用页面。

工作集是进程树各进程工作集的合计，共享页可能重复计算；私有提交量提供另一种资源参考。同步 JavaScript 时间不包含后续动画帧的布局、绘制或模型生成时间，不能把这个数值当作完整响应速度提升。空闲 CPU 基线已经接近零，本次不声称空闲 CPU 有显著下降。

首次展开后的网页进程继续保留。模型内存、显存与推理速度仍取决于模型、上下文和 KV 配置；此次界面测量不包含这些资源。EXE 的解压 / 冷启动时间也不包含在源码构造时间中。

## 复现与正确性检查

安装开发依赖后，连续运行三次并使用不同输出文件名：

```powershell
.\.venv\Scripts\python.exe scripts\ui_performance_check.py --output test-results\performance\updated-1.json --expect-updated
```

对比 v1.0.0 时可创建它的源码副本，用当前检查脚本测量旧代码：

```powershell
git archive v1.0.0 --format=zip --output ..\baseline-v1.0.0.zip
Expand-Archive -LiteralPath ..\baseline-v1.0.0.zip -DestinationPath ..\baseline-v1.0.0
.\.venv\Scripts\python.exe scripts\ui_performance_check.py --project ..\baseline-v1.0.0 --output test-results\performance\baseline-1.json
```

检查脚本测量本次启动的进程树，不读取个人配置或密钥。它在真实 Qt / WebChannel 中检查冷启动进入设置、长回复复制按钮位置与可见性、复制文本完整性、代码块复制、输出上限提示后的按钮位置、未完成结果无复制按钮，以及收起后对话和草稿保留。截图和 JSON 写入被 Git 忽略的 `test-results/`。

本次 `pytest`：82 passed、3 个实际模型测试跳过；悬浮控件 12 项行为检查通过。
