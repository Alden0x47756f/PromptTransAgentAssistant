# 参与贡献

欢迎提交问题、修复和小范围改进。请先搜索现有 Issue；较大的行为或界面变更建议先说明使用场景和预期结果。

## 本地开发

在 Windows 10 / 11 x64 上安装 Python 3.11，然后运行：

```powershell
.\Setup.cmd
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py --expanded
.\.venv\Scripts\python.exe -m pytest -q
```

默认测试不需要模型或付费 API。`--run-model` 会启用真实本地模型测试，应在自己的配置与硬件上主动执行。

## 提交变更

1. Fork 仓库并创建分支，保持改动聚焦。
2. 涉及行为改变时添加相应回归检查，说明验证环境和结果。
3. 更新受影响的说明，提交 Pull Request，描述问题与最终行为。

请保留同窗口设置页、关闭面板与退出软件的区别，以及任意 API 模型 ID / 自定义思考强度支持。不要新增模型名称白名单，也不要把模型列表成功当作推理兼容性的证明。

不要提交个人 `config.toml`、凭据、API Key、日志、输入内容、模型权重或构建产物。截图和服务错误也可能包含敏感信息，提交前请检查。安全问题请优先使用 GitHub 仓库可用的私密漏洞报告入口；公开反馈中不要贴真实密钥或可直接利用的私人服务信息。

提交贡献表示你有权提交相应内容，并同意按本仓库的 MIT License 分发该贡献。第三方内容应说明来源与相应许可。
