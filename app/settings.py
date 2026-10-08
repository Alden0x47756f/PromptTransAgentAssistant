"""Settings form validation, default confirmation, and transactional saving."""
from copy import deepcopy
from pathlib import Path
import re

from .config import DEFAULTS, KV_TYPES, API_URLS, ConfigError, raw_config, read_config, validate_config, config_bytes, normalize_url


LOCAL_FIELDS = {
    'engine_path': ('model', 'engine_path', 'llama 引擎位置', str),
    'model_path': ('model', 'model_path', 'GGUF 模型位置', str),
    'context_size': ('model', 'context_size', '上下文容量', int),
    'cache_type_k': ('model', 'cache_type_k', 'K Cache dtype', str),
    'cache_type_v': ('model', 'cache_type_v', 'V Cache dtype', str),
    'reasoning': ('model', 'reasoning', '本地思考开关', str),
    'reasoning_budget': ('model', 'reasoning_budget', '本地思考预算', int),
    'temperature': ('generation', 'temperature', '温度', float),
    'top_k': ('generation', 'top_k', 'top_k', int),
    'top_p': ('generation', 'top_p', 'top_p', float),
    'max_tokens': ('generation', 'max_tokens', '最大输出 tokens', int),
}
API_FIELDS = {
    'api_protocol': ('api', 'protocol', 'API 协议', str),
    'api_auth_mode': ('api', 'auth_mode', 'API 鉴权方式', str),
    'api_base_url': ('api', 'base_url', 'base_url', str),
    'api_model': ('api', 'model', 'API 模型名称', str),
    'api_endpoint': ('api', 'endpoint', 'OpenAI 接口', str),
    'api_token_field': ('api', 'token_field', '输出 token 字段', str),
    'api_reasoning_effort': ('api', 'reasoning_effort', 'API 思考强度', str),
    'api_thinking_mode': ('api', 'thinking_mode', 'Anthropic 思考模式', str),
    'api_thinking_budget': ('api', 'thinking_budget', 'Anthropic 思考预算', int),
    'api_max_tokens': ('api', 'max_tokens', 'API 最大输出 tokens', int),
}


def form_values(cfg):
    return {field: cfg[section][key] for field, (section, key, _, _) in {**LOCAL_FIELDS, **API_FIELDS}.items()} | {
        'mode': cfg['connection']['mode'], 'auto_load': cfg['model']['auto_load']}


def valid_key(key):
    if not isinstance(key, str) or not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ConfigError([{'field': 'api_key', 'message': 'API Key 必须是非空的可打印 ASCII 字符串，不能包含空格或换行。'}])
    return key


class SettingsService:
    def __init__(self, config_path, secrets):
        self.path, self.secrets = config_path, secrets

    def snapshot(self):
        try:
            cfg = raw_config(self.path)
        except Exception:
            cfg = deepcopy(DEFAULTS)
        values = form_values(cfg)
        defaults = form_values(DEFAULTS)
        saved, credential_error = False, ''
        try:
            saved = bool(self.secrets.get(cfg['api']['protocol'], normalize_url(cfg['api']['base_url'])))
        except Exception as exc:
            credential_error = str(exc)
        return {'values': values, 'defaults': defaults, 'kv_types': list(KV_TYPES), 'api_urls': API_URLS,
                'key_saved': saved, 'credential_error': credential_error}

    def key_status(self, protocol, base_url):
        return bool(self.secrets.get(protocol, normalize_url(base_url)))

    def prepare(self, payload, probe=False):
        if not isinstance(payload, dict) or not isinstance(payload.get('values'), dict):
            raise ConfigError([{'field': 'mode', 'message': '设置数据格式错误。'}])
        values = payload['values']
        try:
            cfg = raw_config(self.path)
        except Exception:
            cfg = deepcopy(DEFAULTS)
        cfg['api'].pop('api_key', None)
        cfg['api'].pop('key', None)
        mode = 'api' if probe else values.get('mode')
        if mode not in ('local', 'api'):
            raise ConfigError([{'field': 'mode', 'message': '请选择本地模型或 API 模式。'}])
        cfg['connection']['mode'] = mode
        missing, errors = [], []
        fields = LOCAL_FIELDS if mode == 'local' else API_FIELDS
        protocol = values.get('api_protocol') or 'openai'
        if protocol not in API_URLS:
            errors.append({'field': 'api_protocol', 'message': '请选择 OpenAI 或 Anthropic 协议。'})
            protocol = 'openai'
        for field, (section, key, label, kind) in fields.items():
            if field in ('api_thinking_mode', 'api_thinking_budget') and protocol != 'anthropic':
                continue
            if field in ('api_endpoint', 'api_token_field') and protocol != 'openai':
                continue
            if field == 'api_thinking_budget' and (values.get('api_thinking_mode') or 'auto') != 'budget':
                continue
            value = values.get(field)
            blank = value is None or isinstance(value, str) and not value.strip()
            if blank:
                if field == 'api_model':
                    if not probe:
                        errors.append({'field': field, 'message': '请填写或选择 API 模型名称。'})
                    cfg[section][key] = ''
                    continue
                value = API_URLS[protocol] if field == 'api_base_url' else DEFAULTS[section][key]
                missing.append({'field': field, 'label': label, 'value': value,
                                'message': f'当前「{label}」参数未设置，将使用默认值「{value}」，请确认。'})
            try:
                if kind is int:
                    if isinstance(value, bool) or not re.fullmatch(r'[+-]?[0-9]+', str(value)):
                        raise ValueError('必须为整数，例如 32768；不能含小数或 K 等单位')
                    value = int(value)
                elif kind is float:
                    if isinstance(value, bool) or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', str(value)):
                        raise ValueError('必须为数字，例如 1.0 或 0.95')
                    value = float(value)
                elif not isinstance(value, str):
                    raise ValueError('必须为文本')
                else:
                    value = value.strip()
                cfg[section][key] = value
            except (ValueError, TypeError, OverflowError) as exc:
                errors.append({'field': field, 'message': label + '：' + str(exc)})
        if not probe:
            if type(values.get('auto_load')) is not bool:
                errors.append({'field': 'auto_load', 'message': '自动启用选项格式无效。'})
            else:
                cfg['model']['auto_load'] = values['auto_load']
        if errors:
            raise ConfigError(errors)
        validation_cfg = deepcopy(cfg)
        if probe and not cfg['api']['model']:
            # A model list can be queried before selecting a model.
            validation_cfg['api']['model'] = 'model-list-probe'
        # Relative local paths are relative to config.toml, just as read_config
        # resolves them; the shell's current directory must not affect saving.
        for key in ('engine_path', 'model_path'):
            value = validation_cfg['model'].get(key)
            if isinstance(value, str) and not Path(value).is_absolute():
                validation_cfg['model'][key] = str(Path(self.path).resolve().parent / value)
        validate_config(validation_cfg, require_files=not probe)
        cfg['api']['base_url'] = validation_cfg['api']['base_url']
        new_key = values.get('api_key', '')
        if not isinstance(new_key, str):
            raise ConfigError([{'field': 'api_key', 'message': 'API Key 格式无效。'}])
        new_key = new_key.strip()
        key = ''
        if mode == 'api':
            key = valid_key(new_key) if new_key else self.secrets.get(cfg['api']['protocol'], cfg['api']['base_url'])
            if not key:
                raise ConfigError([{'field': 'api_key', 'message': '当前服务地址没有已保存密钥，请填写 API Key。'}])
        return cfg, missing, key, new_key if mode == 'api' else ''

    def save(self, cfg, new_key):
        # Check editable prompt files before committing a usable configuration.
        for content, file in (('system_prompt', 'system_prompt_file'), ('default_user_prompt', 'user_prompt_file')):
            if cfg['prompts'].get(file):
                from pathlib import Path
                path = Path(cfg['prompts'][file])
                if not path.is_absolute():
                    path = self.path.parent / path
                text = path.read_text(encoding='utf-8-sig').strip()
            else:
                text = cfg['prompts'].get(content, '').strip()
            if not text:
                raise ValueError('提示词文件为空，请先填写 System/User Prompt。')
            if content == 'default_user_prompt' and text.count('{input}') > 1:
                raise ValueError('User Prompt 最多只能包含一个 {input}。')
        self.secrets.commit_with_config(cfg['api']['protocol'], cfg['api']['base_url'], new_key, self.path, config_bytes(cfg))
        return read_config(self.path)
