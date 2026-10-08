import ctypes as ct
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from app.config import ROOT, DEFAULTS, config_bytes, read_config, engine_arguments
from copy import deepcopy
from app.controller import Controller
from app.winprocess import OwnedProcess, kernel, bind
from ctypes import wintypes as wt


def wait_until(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('Condition timed out')


def test_config_rejects_invalid_context_and_cache(tmp_path):
    for key, value in [('context_size', 0), ('cache_type_v', 'unsupported')]:
        cfg = deepcopy(DEFAULTS)
        cfg['model'][key] = value
        file = tmp_path / 'config.toml'
        file.write_bytes(config_bytes(cfg))
        with pytest.raises(ValueError):
            read_config(file)


def test_first_run_creates_config_without_model_and_preserves_existing_config(tmp_path):
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    (prompts / 'system_prompt.md').write_text('Translate text.', encoding='utf-8')
    (prompts / 'user_prompt.md').write_text('{input}', encoding='utf-8')
    path = tmp_path / 'config.toml'
    cfg = read_config(path)
    assert path.is_file()
    assert cfg['model']['model_path'] == str(tmp_path / 'models' / 'model.gguf')
    assert cfg['model']['context_size'] == 32768
    cfg['generation']['temperature'] = .5
    path.write_bytes(config_bytes(cfg))
    existing = path.read_bytes()
    assert read_config(path)['generation']['temperature'] == .5
    assert path.read_bytes() == existing


def test_owned_process_stops_and_does_not_touch_unrelated_process():
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    owned = OwnedProcess([sys.executable, '-c', 'import time; time.sleep(60)'], ROOT)
    try:
        assert owned.poll() is None
        owned.close()
        assert owned.poll() is not None
        owned.close()  # idempotent
        assert unrelated.poll() is None
    finally:
        owned.close()
        unrelated.terminate()
        unrelated.wait(10)


def test_job_kills_child_when_owner_is_forcibly_terminated(tmp_path):
    pid_file = tmp_path / 'pid.txt'
    script = tmp_path / 'owner.py'
    script.write_text(
        'import sys,time\n'
        f'sys.path.insert(0, {str(ROOT)!r})\n'
        'from app.winprocess import OwnedProcess\n'
        'from pathlib import Path\n'
        f'p=OwnedProcess([sys.executable,"-c","import time; time.sleep(90)"],{str(ROOT)!r},log_path={str(tmp_path / "child.log")!r})\n'
        f'Path({str(pid_file)!r}).write_text(str(p.pid))\n'
        'time.sleep(90)\n', encoding='utf-8')
    owner = subprocess.Popen([sys.executable, str(script)])
    child_handle = None
    try:
        wait_until(pid_file.exists, 10)
        pid = int(pid_file.read_text())
        open_process = bind('OpenProcess', [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE)
        child_handle = open_process(0x00100000, False, pid)
        assert child_handle
        owner.terminate()
        owner.wait(10)
        assert kernel.WaitForSingleObject(child_handle, 10000) == 0
    finally:
        if owner.poll() is None:
            owner.terminate()
            owner.wait(10)
        if child_handle:
            kernel.CloseHandle(child_handle)


@pytest.mark.model
def test_real_translation_lifecycle_and_cancellation():
    events = []
    c = Controller(events.append)
    try:
        c.load()
        c.load()  # duplicate toggle must not spawn another engine
        wait_until(lambda: c.state in ('ready', 'error'))
        assert c.state == 'ready', c.detail
        process = c.process
        with httpx.Client(trust_env=False) as client:
            assert client.get(c.url + '/v1/models').status_code == 401
            props = client.get(c.url + '/props', headers=c._headers()).json()
        assert props['default_generation_settings']['n_ctx'] == 32768
        diagnostic = c.log_path.read_text(encoding='utf-8', errors='replace')
        assert 'K (q8_0)' in diagnostic and 'V (q8_0)' in diagnostic
        (ROOT / 'logs' / 'engine-props.json').write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding='utf-8')
        c.send('写一个 Python 脚本读取 CSV，按月份汇总销售额。禁止使用 pandas，输入使用 UTF-8，输出 JSON。')
        c.chat_thread.join(180)
        assert not c.busy
        assert any(e['type'] == 'done' for e in events), events
        output = ''.join(e['text'] for e in events if e['type'] == 'chunk')
        assert all(word in output for word in ('Python', 'CSV', 'pandas', 'UTF-8', 'JSON'))
        assert len(c.history) == 2
        assert '{input}' not in c.history[0]['content']
        assert c.history[0]['content'].count('<source_text>') == 1
        (ROOT / 'logs' / 'integration-response.txt').write_text(output, encoding='utf-8')
        c.new_conversation()
        assert c.history == []
        events.clear()
        c.send('设计一个包含100项具体要求的英文提示词，用于规划一个完整的软件项目。')
        wait_until(lambda: any(e['type'] == 'progress' for e in events))
        c.stop()
        c.chat_thread.join(15)
        assert not c.chat_thread.is_alive()
        assert c.history == []
        assert any(e['type'] == 'cancelled' for e in events)
        events.clear()
        c.send('将以下需求改写成英文提示词：写一本内容详尽的Python教程，包含100个章节。')
        wait_until(lambda: any(e['type'] == 'progress' for e in events))
        c.unload()
        wait_until(lambda: c.state in ('unloaded', 'error'), 25)
        assert c.state == 'unloaded', c.detail
        assert process.poll() is not None
        assert c.process is None
        c.load()
        wait_until(lambda: c.state in ('ready', 'error'))
        assert c.state == 'ready', c.detail
    finally:
        c.shutdown()
    assert c.process is None


@pytest.mark.model
def test_shutdown_while_loading():
    c = Controller(lambda _: None)
    c.load()
    wait_until(lambda: c.process is not None or c.state == 'error', 10)
    process = c.process
    c.shutdown()
    assert c.process is None
    assert not c.load_thread.is_alive()
    assert process is None or process.poll() is not None


@pytest.mark.model
def test_context_overflow_preserves_history():
    events = []
    c = Controller(events.append)
    try:
        c.load()
        wait_until(lambda: c.state in ('ready', 'error'))
        assert c.state == 'ready', c.detail
        c.send('长上下文测试：' + 'alpha beta gamma delta ' * 10000)
        c.chat_thread.join(20)
        assert not c.busy
        assert c.history == []
        assert any(e['type'] == 'error' and 'tokens' in e['message'] for e in events)
        assert not any(e['type'] == 'chunk' for e in events)
    finally:
        c.shutdown()
