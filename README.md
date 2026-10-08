# PromptTransAgentAssistant

<img src="frontend/branding/logo.png" alt="PromptTransAgentAssistant 的 P 标志" width="96" />

一个轻量的 Windows 悬浮提示词助手：把中文需求整理为英文 Prompt，把英文内容翻译为中文。支持本地 GGUF 模型和兼容 OpenAI / Anthropic 协议的 API。

*A floating Windows assistant for Chinese–English prompt translation and refinement, powered by local models or compatible APIs.*

## 功能

- 白色悬浮条贴靠屏幕边缘；悬停变为圆球，点击展开对话，支持拖动和左右吸附。
- 对话与设置在同一个窗口切换；展开期间保持圆球，收起后等待 1 秒再变回悬浮条。
- 本地模型 / API 模式切换，以及启用 / 停用滑块；切换进行中显示等待状态。
- 独立的 System Prompt 和 User Prompt Markdown 文件，便于自行编辑。
- 可配置本地采样、上下文、输出长度、KV Cache 类型及模型 / 引擎位置。
- 支持任意 API 模型名称和自定义思考强度，密钥通过 Windows DPAPI 加密持久化。
- 保存时校验格式；缺失参数提示将采用的默认值；加载和调用失败提供诊断弹窗。

## 下载与运行

从 [Releases](https://github.com/NanamiDoko/PromptTransAgentAssistant/releases) 下载 Windows 压缩包，解压到可写目录，再运行 `PromptTransAgentAssistant.exe`。EXE 版本不需要安装 Python，请保留同目录下的 `prompts/` 文件夹。

应用面向 Windows 10 / 11 x64。本地推理还需要自行准备 GGUF 模型、支持该模型的 `llama-server.exe` 及其配套运行库；使用 CUDA 引擎时需要对应的 NVIDIA 驱动。模型、引擎和模型权重不随本项目分发。资源占用取决于模型、量化方式、上下文、KV Cache 类型和硬件。

首次运行会在程序旁创建 `config.toml`，仅在文件不存在时创建，已有设置不会被覆盖。默认启用本地模型自动加载；未准备默认文件时会显示诊断，请进入“配置”选择自己的文件或切换到 API。

**关闭面板与退出软件：**窗口右上角的 `×`、最小化、Esc 或 Alt+F4 收起对话窗口；通过悬浮球右键菜单“退出”结束应用。退出时会清理本应用启动的本地模型进程。

## 从源码启动

安装 Python 3.11 x64，然后在项目目录执行：

```powershell
git clone https://github.com/NanamiDoko/PromptTransAgentAssistant.git
cd PromptTransAgentAssistant
.\Setup.cmd
.\Start.cmd
```

`Setup.cmd` 调用 Windows 原生 `Setup.ps1`，创建 `.venv` 并安装运行依赖。有 `uv` 时使用它，否则使用当前 Python 与 pip。也可以直接执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
.\.venv\Scripts\python.exe .\main.py --expanded
```

`Start.cmd` 优先运行目录中的 EXE；若要测试源码，请使用上面的 Python 命令。当前桌面实现依赖 Windows API，不提供 Unix 启动脚本。

## 本地模型设置

点击“配置”，选择本地模型，填写 GGUF 文件及 llama 引擎位置。默认相对路径为 `models/model.gguf` 和 `runtime/llama-server.exe`，也可以填写自己的绝对路径。相对路径以 `config.toml` 所在目录为基准。请保留 llama 引擎目录中的配套 DLL。

| 参数 | 默认值 |
| --- | --- |
| 上下文容量 | 32768（32K） |
| K / V Cache Dtype | q8_0 / q8_0 |
| 最大输出 tokens | 8192 |
| Temperature | 1.0 |
| Top K / Top P / Min P | 64 / 0.95 / 0.05 |
| 思考模式 / 预算 | on / -1 |
| GPU 层数 / Flash Attention | all / on |
| 启动时自动启用 | true |

`reasoning_budget = -1` 表示不额外限制引擎的思考预算，最终仍受输出长度、上下文和模型 / 引擎支持范围约束。小模型的思考能力及结果质量取决于所用模型。修改影响加载的参数后，应用会重新启用相应后端；操作期间滑块显示等待状态。

## API 设置

1. 在同一个设置页选择 API 模式。
2. 选择 OpenAI 或 Anthropic 协议，填写 `base_url` 前缀与 API Key。不要填写带账号密码的 URL，也不要将 `base_url` 填为具体的 `/chat/completions` 或 `/messages` 请求地址。
3. 手动填写模型名称，或点击“获取模型列表并测试连接”。模型列表只提供候选项，手动输入的模型不受内置名单限制。
4. 选择接口、输出长度及思考配置，保存并启用。

| 协议 / 接口 | 输出长度字段 | 思考强度字段 |
| --- | --- | --- |
| OpenAI Chat Completions | max_tokens 或 max_completion_tokens，按服务要求选择 | reasoning_effort |
| OpenAI Responses | max_output_tokens | reasoning.effort |
| Anthropic Messages | max_tokens | output_config.effort |

默认鉴权为 OpenAI Bearer Token、Anthropic `x-api-key`；设置中也可选择兼容服务要求的鉴权头。Anthropic 可选择服务默认、关闭、adaptive 或预算模式。`auto` 表示不发送额外的思考强度字段，由服务决定。

思考强度下拉框在初始及输入为空时提供 `low / medium / high / xhigh / max / ultra`；输入后筛选关联项，也可以提交自定义值。**应用不会根据模型名称猜测支持能力或拒绝新模型。** 服务是否接受该模型、思考等级和协议参数，以实际调用结果为准；不兼容时会显示服务错误。

“获取模型列表并测试连接”检测模型列表接口的网络、鉴权和响应格式，**成功不代表实际推理调用一定成功**。某些兼容服务不提供模型列表，但仍可手动配置模型进行调用。

API Key 存储在当前 Windows 用户的 `%LOCALAPPDATA%\PromptTransAgentAssistant\credentials.json` 中，使用 DPAPI 加密，并按协议与 `base_url` 区分；不写入 `config.toml`，也不会把已保存密钥明文回填到界面。切换服务需要保存对应服务的密钥。

## 修改提示词

两个文件以 UTF-8 保存：

- `prompts/system_prompt.md`：角色、语言方向及输出规则。
- `prompts/user_prompt.md`：每次请求注入的用户模板。`{input}` 可出现一次，用于插入输入文本；未包含该占位符时，输入会追加在模板后。

通过设置页的提示词入口或文本编辑器修改，保存后开启新对话即可读取新内容，无需重新下载模型。文件不能为空；应用会报告文件缺失、读取失败或重复占位符等问题。若希望更换文件位置，可修改 `config.toml` 的 `[prompts]` 路径。

应用使用语言方向判断、逐轮规则和输出校验，尽量避免英文输入得到英文回复，并对无法通过校验的结果提示错误。判断与校验存在边界，混合语言、专有名词、代码和特殊文本需要自行验证；这些机制不能保证任意模型始终正确翻译。

## 配置、隐私与故障排查

`config.example.toml` 是公开的默认配置参考；实际 `config.toml`、密钥、日志、模型、引擎、构建产物及测试截图均被 Git 忽略。公开仓库保留两份提示词，不包含开发者个人运行设置或历史数据。

本地模式将请求发给本机 llama 服务；API 模式将输入及提示词发送到用户选择的服务。提交 Issue 前请自行清理诊断、日志和截图中的密钥、地址、个人路径及输入内容。

- **模型无法启用：**确认模型是有效 GGUF、引擎支持该模型、DLL 完整，并检查诊断中的显存 / 内存及参数问题。必要时减少上下文或调整 KV Cache 类型。
- **API 返回错误：**检查协议、接口、鉴权、模型 ID、思考参数及服务返回的错误；兼容协议不代表所有参数均兼容。
- **EXE 图标仍旧：**运行 `RefreshIcon.cmd` 刷新 Windows Shell 图标，然后在资源管理器按 F5。旧的固定快捷方式可能需要取消固定后重新固定。刷新助手不会删除系统缓存文件或重启资源管理器。
- **修改不生效：**确认运行的是刚更新的 EXE 或指定源码；退出旧实例后重开。程序使用单实例锁。

## 开发、测试与构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\Build.cmd
```

`Build.cmd` 使用 PyInstaller 生成带图标的窗口模式 EXE。分发时将 EXE 与 `prompts/` 放在同一目录；可附上 `config.example.toml` 和图标刷新助手，但不要打包个人 `config.toml`、凭据、模型、日志或旧构建。

发布准备中的 Windows 本地测试结果为 **80 passed、3 skipped**。API 测试使用本地 HTTP 模拟服务验证请求结构、鉴权与错误处理，没有调用付费 API；默认跳过实际 GPU / 模型测试。准备自己的模型和引擎后，可在个人配置下执行 `python -m pytest -q --run-model`，该命令会启动真实模型并占用计算资源。

| 路径 | 职责 |
| --- | --- |
| main.py / app/desktop.py | Qt 生命周期、悬浮控件、WebChannel 桥接 |
| frontend/ | 对话与设置页、样式、Logo |
| app/controller.py | 后端状态、模型进程、请求、语言边界处理 |
| app/providers.py | OpenAI / Anthropic 协议适配 |
| app/config.py / app/settings.py | 默认值、校验、设置保存 |
| app/secrets_store.py / app/diagnostics.py | Windows 密钥存储、诊断与脱敏 |
| scripts/ / tests/ | 打包与检查脚本、测试 |

## 参与与许可

问题反馈与贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。应用代码采用 [MIT License](LICENSE)。外部模型、llama 引擎、Qt 及其他依赖分别遵循各自的许可证；相关说明和许可证文本见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。本仓库的 MIT 许可不替代这些项目的许可，仓库不分发模型权重。
