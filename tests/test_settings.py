from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.config import DEFAULTS, ConfigError, config_bytes, engine_arguments, read_config, validate_config
from app.controller import Controller
from app.settings import SettingsService, form_values
from app.secrets_store import SecretStore


@pytest.fixture
def setup_settings(tmp_path):
    (tmp_path / 'prompts').mkdir()
    (tmp_path / 'prompts' / 'system_prompt.md').write_text('Translate English into Simplified Chinese.', encoding='utf-8')
    (tmp_path / 'prompts' / 'user_prompt.md').write_text('<source_text>\n{input}\n</source_text>', encoding='utf-8')
    cfg = deepcopy(DEFAULTS)
    cfg['model']['auto_load'] = False
    engine = tmp_path / 'llama-server.exe'
    model = tmp_path / 'model.gguf'
    engine.write_bytes(b'fixture-only; never execute')
    model.write_bytes(b'GGUFfixture-only; never load')
    cfg['model']['engine_path'] = str(engine)
    cfg['model']['model_path'] = str(model)
    path = tmp_path / 'config.toml'
    path.write_bytes(config_bytes(cfg))
    store = SecretStore(tmp_path / 'credentials.json')
    return SettingsService(path, store), path, store


def payload(service, mode='local'):
    values = service.snapshot()['values']
    values['mode'] = mode
    values['api_key'] = ''
    return {'values': values, 'confirmed': False}


def test_default_confirmation_does_not_write_until_confirmed(setup_settings):
    service, path, store = setup_settings
    events = []
    c = Controller(events.append, path, store.path)
    draft = payload(service)
    draft['values'].update(temperature='', top_k='')
    original = path.read_bytes()
    c.save_settings(draft)
    assert path.read_bytes() == original and not store.path.exists()
    confirmation = next(e for e in events if e['type'] == 'settings_confirm')
    assert {entry['field'] for entry in confirmation['defaults']} == {'temperature', 'top_k'}
    assert '默认值「1.0」' in confirmation['defaults'][0]['message']
    draft['confirmed'] = True
    c.save_settings(draft)
    assert any(e['type'] == 'settings_saved' for e in events)
    assert read_config(path)['generation']['temperature'] == 1.0
    assert read_config(path)['generation']['top_k'] == 64
    c.shutdown()


@pytest.mark.parametrize('field,value', [
    ('temperature', 'abc'), ('temperature', 'NaN'), ('temperature', 'Infinity'), ('temperature', '1e309'),
    ('temperature', '-1'), ('temperature', '2.1'), ('context_size', '32K'), ('context_size', '0'),
    ('top_k', '2.5'), ('top_k', '-1'), ('top_p', '0'), ('top_p', '1.1'),
    ('max_tokens', '32768'), ('cache_type_k', 'unknown'), ('cache_type_v', 'unknown'),
    ('reasoning_budget', '-2'), ('model_path', 'C:\\example-missing\\model.gguf'),
])
def test_invalid_form_is_rejected_without_writing(setup_settings, field, value):
    service, path, store = setup_settings
    draft = payload(service)
    draft['values'][field] = value
    before = path.read_bytes()
    with pytest.raises(ConfigError):
        service.prepare(draft)
    assert path.read_bytes() == before and not store.path.exists()


def test_corrupt_gguf_is_reported(setup_settings, tmp_path):
    service, _, _ = setup_settings
    broken = tmp_path / 'broken.gguf'
    broken.write_bytes(b'not-a-gguf')
    draft = payload(service)
    draft['values']['model_path'] = str(broken)
    with pytest.raises(ConfigError, match='GGUF 文件头'):
        service.prepare(draft)


def test_context_and_kv_are_configurable_and_used_in_engine_arguments(setup_settings):
    service, _, _ = setup_settings
    draft = payload(service)
    draft['values'].update(context_size='16384', max_tokens='4096', cache_type_k='f16', cache_type_v='q4_0')
    cfg, _, _, _ = service.prepare(draft)
    args = engine_arguments(cfg, 12345, 'test-only-key')
    assert args[args.index('--ctx-size') + 1] == '16384'
    assert args[args.index('--cache-type-k') + 1] == 'f16'
    assert args[args.index('--cache-type-v') + 1] == 'q4_0'


def test_relative_local_paths_are_validated_against_config_directory(setup_settings, monkeypatch, tmp_path):
    service, path, _ = setup_settings
    other_directory = tmp_path / 'unrelated-working-directory'
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)
    draft = payload(service)
    draft['values'].update(engine_path='llama-server.exe', model_path='model.gguf')
    cfg, _, _, _ = service.prepare(draft)
    assert cfg['model']['engine_path'] == 'llama-server.exe'
    assert cfg['model']['model_path'] == 'model.gguf'


def api_draft(service):
    draft = payload(service, 'api')
    draft['values'].update(api_base_url='https://example.test/v1', api_model='deepseekv4.1-flash',
                           api_key='test-only-private-token', api_reasoning_effort='custom-effort')
    return draft


def test_api_does_not_require_local_model_files(setup_settings):
    service, _, _ = setup_settings
    draft = api_draft(service)
    cfg, _, _, _ = service.prepare(draft)
    cfg['model']['model_path'] = 'C:/example-missing/model.gguf'
    cfg['model']['engine_path'] = 'C:/example-missing/engine.exe'
    validate_config(cfg, require_files=True)


@pytest.mark.parametrize('base_url', ['ftp://example.test', 'https://user:pass@example.test', 'https://example.test?key=abc', 'https://example.test:invalid', 'https://exa mple.test'])
def test_invalid_urls_are_rejected(setup_settings, base_url):
    service, _, _ = setup_settings
    draft = api_draft(service)
    draft['values']['api_base_url'] = base_url
    with pytest.raises(ConfigError):
        service.prepare(draft)


def test_dpapi_persistence_survives_a_new_process_without_plaintext(setup_settings):
    service, path, store = setup_settings
    draft = api_draft(service)
    cfg, _, key, new_key = service.prepare(draft)
    service.save(cfg, new_key)
    assert key.encode() not in path.read_bytes() and key.encode() not in store.path.read_bytes()
    assert 'api_key' not in path.read_text(encoding='utf-8')
    snapshot = service.snapshot()
    assert snapshot['key_saved'] is True and key not in json.dumps(snapshot)
    digest = hashlib.sha256(key.encode()).hexdigest()
    program = ('from app.secrets_store import SecretStore; import hashlib; '
               f'key=SecretStore({str(store.path)!r}).get("openai","https://example.test/v1"); '
               f'assert hashlib.sha256(key.encode()).hexdigest()=={digest!r}')
    completed = subprocess.run([sys.executable, '-c', program], capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr.decode(errors='replace')
    assert store.get('openai', 'https://other.test/v1') == ''
    assert store.get('anthropic', 'https://example.test/v1') == ''


def test_api_key_is_never_reused_for_a_different_address(setup_settings):
    service, _, _ = setup_settings
    cfg, _, _, new_key = service.prepare(api_draft(service))
    service.save(cfg, new_key)
    draft = payload(service, 'api')
    draft['values']['api_base_url'] = 'https://other.test/v1'
    with pytest.raises(ConfigError, match='没有已保存密钥'):
        service.prepare(draft)


def test_missing_api_credentials_do_not_receive_fake_defaults(setup_settings):
    service, _, _ = setup_settings
    draft = payload(service, 'api')
    with pytest.raises(ConfigError, match='模型'):
        service.prepare(draft)
    draft['values']['api_model'] = 'unlisted-model'
    with pytest.raises(ConfigError, match='没有已保存密钥'):
        service.prepare(draft)


def test_failed_config_write_restores_previous_ciphertext(setup_settings, monkeypatch):
    service, path, store = setup_settings
    cfg, _, _, key = service.prepare(api_draft(service))
    service.save(cfg, key)
    original_config, original_ciphertext = path.read_bytes(), store.path.read_bytes()
    draft = payload(service, 'api')
    draft['values']['api_key'] = 'test-only-replacement-token'
    cfg, _, _, key = service.prepare(draft)
    import app.secrets_store as module
    original_write = module.atomic_write
    def fail_config(target, content):
        if Path(target) == path:
            raise PermissionError('config is read-only')
        return original_write(target, content)
    monkeypatch.setattr(module, 'atomic_write', fail_config)
    with pytest.raises(PermissionError):
        service.save(cfg, key)
    assert path.read_bytes() == original_config
    assert store.path.read_bytes() == original_ciphertext


def test_api_activation_never_spawns_a_local_process(setup_settings, monkeypatch):
    service, path, store = setup_settings
    cfg, _, _, key = service.prepare(api_draft(service))
    service.save(cfg, key)
    def forbidden(*args, **kwargs):
        raise AssertionError('API mode tried to launch llama')
    monkeypatch.setattr('app.controller.OwnedProcess', forbidden)
    c = Controller(lambda _: None, path, store.path)
    c.load()
    c.load_thread.join(5)
    assert c.state == 'ready' and c.process is None
    c.shutdown()


def test_sampling_settings_apply_without_unloading_or_clearing_history(setup_settings):
    service, path, store = setup_settings
    events = []
    c = Controller(events.append, path, store.path)
    c.state = 'ready'
    c.history = [{'role': 'user', 'content': 'existing conversation'}]
    draft = payload(service)
    draft['values'].update(temperature='.5', top_p='.8', top_k='32')
    c.save_settings(draft)
    assert c.state == 'ready' and len(c.history) == 1
    assert c.config['generation']['temperature'] == .5
    assert not next(e for e in events if e['type'] == 'settings_saved')['reload']
    c.shutdown()


def test_broken_startup_config_can_be_fixed_in_settings(setup_settings):
    service, path, store = setup_settings
    path.write_text('invalid TOML = ]', encoding='utf-8')
    c = Controller(lambda _: None, path, store.path)
    assert c.startup_error is not None
    draft = payload(service)
    draft['values']['auto_load'] = False
    draft['values']['engine_path'] = str(path.parent / 'llama-server.exe')
    draft['values']['model_path'] = str(path.parent / 'model.gguf')
    c.save_settings(draft)
    deadline = time.monotonic() + 5
    while c.saving and time.monotonic() < deadline:
        time.sleep(.02)
    assert c.startup_error is None
    assert read_config(path)['connection']['mode'] == 'local'
    c.shutdown()


@pytest.mark.parametrize('available', [True, False])
def test_copy_reports_unavailable_clipboard_instead_of_false_success(setup_settings, monkeypatch, available):
    import app.desktop as desktop
    _, path, store = setup_settings
    events = []
    c = Controller(events.append, path, store.path)
    class Clipboard:
        value = ''
        def setText(self, value):
            self.value = value if available else ''
        def text(self):
            return self.value
    clipboard = Clipboard()
    monkeypatch.setattr(desktop, 'QApplication', SimpleNamespace(clipboard=lambda: clipboard))
    desktop.Bridge.copyText(SimpleNamespace(controller=c), '中文结果。')
    assert any(e['type'] == 'copied' for e in events) == available
    assert any(e['type'] == 'settings_error' and '剪贴板' in e['message'] for e in events) == (not available)
    c.shutdown()
