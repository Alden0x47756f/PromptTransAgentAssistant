# Repository guide

Windows desktop application using Python 3.11, PySide6, Qt WebEngine, a WebChannel bridge, and httpx. The frontend is plain HTML/CSS/JavaScript. Windows APIs implement credential encryption, owned-process cleanup, and Shell icon refresh.

## Commands

Run from the repository root in PowerShell:

```powershell
.\Setup.cmd
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py --expanded
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\Build.cmd
```

Use the direct Python command to test source: Start.cmd prefers an existing EXE. Real-model tests are opt-in with `--run-model` and consume GPU/memory resources. Do not launch a second model against an active user session during routine checks.

## Architecture

- `main.py`: application startup, single-instance lock, window icon and shutdown.
- `app/desktop.py`: floating strip/ball, panel lifecycle and WebChannel bridge.
- `frontend/`: same-window conversation/settings views and branding assets.
- `app/controller.py`: worker lifecycle, local llama-server ownership, API integration, language routing and output validation.
- `app/providers.py`: OpenAI Chat/Responses and Anthropic Messages adapters.
- `app/config.py`, `app/settings.py`: defaults, typed validation and transactional settings changes.
- `app/secrets_store.py`: current-user Windows DPAPI credential persistence, scoped by protocol and base URL.
- `app/diagnostics.py`: understandable errors and credential redaction.
- `prompts/system_prompt.md`, `prompts/user_prompt.md`: editable UTF-8 prompts.
- `scripts/build_exe.py`: PyInstaller one-file Windows packaging with icon and frontend assets.

## Behavior to preserve

Settings replace the content of the current panel. The titlebar has only a minimize button, which hides the panel; the floating control's explicit right-click Exit ends the application and cleans up its own model process. Result copy actions follow the body and any completion note. Keep floating morph animation, hover handling and one-second collapse grace stable.

The native floating control starts without WebEngine. Panel.view creates the browser on first use; settings requests before WebChannel initialization must be replayed once it connects. Preserve the page and draft across later minimizes. UI performance and correctness checks are documented in PERFORMANCE.md.

API model IDs and custom reasoning efforts are opaque service values. Validate syntax and configuration, not model existence with an allowlist. The model-list button checks list connectivity/authentication; actual inference is a separate operation. Map fields according to the selected protocol and endpoint rather than guessing from model names.

Default local context is 32768, K/V cache q8_0, reasoning on with budget -1, temperature 1.0, top_k 64, top_p 0.95, max output 8192. Generic local defaults point to `models/model.gguf` and `runtime/llama-server.exe`.

## Private files and validation

Never commit private `config.toml`, keys, credential stores, personal paths, logs, screenshots containing user data, binaries, model weights or local audit reports. Keep runtime configuration creation absent-only. Treat prompt edits as user content and preserve the UTF-8 Markdown configuration path workflow.

Run checks appropriate to the changed behavior. API unit/integration checks use mock/local HTTP services; do not describe them as successful calls to paid providers. Language routing and fail-closed validation reduce wrong-language output but are not a proof of perfect translation for all models or inputs. Keep docs honest about that boundary.
