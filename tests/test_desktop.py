from copy import deepcopy
import json

from app.config import DEFAULTS, config_bytes
from app.desktop import Bridge


def bridge_for(tmp_path):
    (tmp_path / 'prompts').mkdir()
    (tmp_path / 'prompts' / 'system_prompt.md').write_text('Translate English into Chinese.', encoding='utf-8')
    (tmp_path / 'prompts' / 'user_prompt.md').write_text('{input}', encoding='utf-8')
    cfg = deepcopy(DEFAULTS)
    cfg['model']['auto_load'] = False
    config = tmp_path / 'config.toml'
    config.write_bytes(config_bytes(cfg))
    return Bridge(config, tmp_path / 'credentials.json')


def test_cold_settings_request_reaches_frontend_when_it_connects(tmp_path):
    bridge = bridge_for(tmp_path)
    events = []
    reveals = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))
    bridge.settingsRequested.connect(lambda: reveals.append(True))
    bridge.openConfig()
    bridge.openConfig()
    assert len(reveals) == 2
    assert not any(event['type'] == 'settings' for event in events)
    bridge.initialize()
    assert len([event for event in events if event['type'] == 'settings']) == 1
    assert any(event['type'] == 'state' for event in events)
    bridge.controller.shutdown()


def test_settings_request_after_frontend_connects_is_immediate(tmp_path):
    bridge = bridge_for(tmp_path)
    events = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))
    bridge.initialize()
    events.clear()
    bridge.openConfig()
    assert [event['type'] for event in events] == ['settings']
    bridge.controller.shutdown()
