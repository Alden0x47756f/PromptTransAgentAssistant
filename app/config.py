from copy import deepcopy
from pathlib import Path
import json
import math
import re
import sys
import tomllib
from urllib.parse import urlsplit, urlunsplit

ASSET_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else ASSET_ROOT
CONFIG_PATH = ROOT / 'config.toml'
KV_TYPES = ('f32', 'f16', 'bf16', 'q8_0', 'q4_0', 'q4_1', 'iq4_nl', 'q5_0', 'q5_1')
API_URLS = {'openai': 'https://api.openai.com/v1', 'anthropic': 'https://api.anthropic.com/v1'}
DEFAULTS = {
    'connection': {'mode': 'local'},
    'model': {
        'engine_path': 'runtime/llama-server.exe',
        'model_path': 'models/model.gguf',
        'context_size': 32768, 'cache_type_k': 'q8_0', 'cache_type_v': 'q8_0',
        'gpu_layers': 'all', 'flash_attention': 'on', 'batch_size': 512, 'ubatch_size': 128,
        'startup_timeout_seconds': 180, 'auto_load': True, 'reasoning': 'on', 'reasoning_budget': -1,
    },
    'generation': {'temperature': 1.0, 'top_k': 64, 'top_p': .95, 'min_p': .05, 'max_tokens': 8192},
    'api': {'protocol': 'openai', 'base_url': API_URLS['openai'], 'model': '', 'endpoint': 'chat',
            'reasoning_effort': 'auto', 'thinking_mode': 'auto', 'thinking_budget': 1024,
            'max_tokens': 8192, 'token_field': 'max_tokens', 'auth_mode': 'protocol'},
    'prompts': {'system_prompt_file': 'prompts/system_prompt.md', 'user_prompt_file': 'prompts/user_prompt.md'},
    'ui': {'edge': 'right', 'resting_opacity': .48, 'animation_ms': 200, 'panel_width': 430, 'panel_height': 650},
}


class ConfigError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('；'.join(error['message'] for error in errors))


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(char.isspace() for char in value):
        raise ValueError('base_url 必须是完整的 HTTP/HTTPS 地址，不能包含空格。')
    parts = urlsplit(value.strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('base_url 必须使用 HTTP/HTTPS，且不能包含账号、密码、查询参数或片段。')
    try:
        parts.port
    except ValueError as exc:
        raise ValueError('base_url 端口格式不正确。') from exc
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip('/'), '', ''))


def raw_config(path=CONFIG_PATH):
    defaults = deepcopy(DEFAULTS)
    if not Path(path).exists():
        # Create a private configuration on first launch; never overwrite one.
        try:
            with Path(path).open('xb') as file:
                file.write(config_bytes(defaults))
        except FileExistsError:
            pass
    source = tomllib.loads(Path(path).read_text(encoding='utf-8-sig'))
    for section, values in source.items():
        if isinstance(values, dict):
            defaults.setdefault(section, {}).update(values)
        else:
            raise ValueError('配置节格式错误：' + section)
    # Legacy inline prompts remain authoritative unless file keys were explicitly set.
    if 'prompts' in source:
        for content, file in (('system_prompt', 'system_prompt_file'), ('default_user_prompt', 'user_prompt_file')):
            if content in source['prompts'] and file not in source['prompts']:
                defaults['prompts'].pop(file, None)
    return defaults


def validate_config(cfg, require_files=False):
    errors = []
    def fail(field, message):
        errors.append({'field': field, 'message': message})
    def number(section, key, low, high, integer=False):
        value = cfg[section].get(key)
        valid = type(value) is int if integer else type(value) in (int, float) and math.isfinite(value)
        if not valid or not low <= value <= high:
            fail(key if section != 'api' else 'api_' + key, f'{section}.{key} 必须是 {low}～{high} 的' + ('整数。' if integer else '有限数字。'))
    mode = cfg['connection'].get('mode')
    if mode not in ('local', 'api'):
        fail('mode', '请选择本地模型或 API 模式。')
    model, gen, api, ui = (cfg[key] for key in ('model', 'generation', 'api', 'ui'))
    if type(model['auto_load']) is not bool:
        fail('auto_load', '自动启用必须是 true/false。')
    if mode == 'local':
        for key in ('engine_path', 'model_path'):
            if not isinstance(model.get(key), str) or not model[key].strip():
                fail(key, key + ' 必须是非空文件路径。')
    number('model', 'context_size', 256, 2097152, True)
    number('model', 'reasoning_budget', -1, 2097152, True)
    number('model', 'batch_size', 1, 32768, True)
    number('model', 'ubatch_size', 1, 32768, True)
    number('model', 'startup_timeout_seconds', 10, 1800, True)
    if isinstance(model['ubatch_size'], int) and isinstance(model['batch_size'], int) and model['ubatch_size'] > model['batch_size']:
        fail('ubatch_size', 'ubatch_size 不能大于 batch_size。')
    for key in ('cache_type_k', 'cache_type_v'):
        if model[key] not in KV_TYPES:
            fail(key, key + ' 必须从支持的 KV 类型中选择。')
    if model['reasoning'] not in ('on', 'off'):
        fail('reasoning', '思考开关必须为 on/off。')
    if model['flash_attention'] not in ('on', 'off', 'auto'):
        fail('flash_attention', 'Flash Attention 必须为 on/off/auto。')
    if str(model['gpu_layers']) not in ('all', 'auto') and not re.fullmatch(r'[0-9]+', str(model['gpu_layers'])):
        fail('gpu_layers', 'GPU 层数必须为 all、auto 或非负整数。')
    number('generation', 'temperature', 0, 2)
    number('generation', 'top_k', 0, 1000, True)
    number('generation', 'top_p', .000001, 1)
    number('generation', 'min_p', 0, 1)
    number('generation', 'max_tokens', 1, 2097152, True)
    if type(gen['max_tokens']) is int and type(model['context_size']) is int and gen['max_tokens'] >= model['context_size'] - 32:
        fail('max_tokens', '最大输出 tokens 必须小于上下文容量减 32，为输入和聊天模板预留空间。')
    if api.get('protocol') not in API_URLS:
        fail('api_protocol', 'API 协议必须是 OpenAI 或 Anthropic。')
    try:
        api['base_url'] = normalize_url(api['base_url'])
    except (ValueError, TypeError) as exc:
        fail('api_base_url', str(exc))
    number('api', 'max_tokens', 1, 2097152, True)
    number('api', 'thinking_budget', 0, 2097152, True)
    if api['endpoint'] not in ('chat', 'responses'):
        fail('api_endpoint', 'OpenAI 接口必须是 Chat Completions 或 Responses。')
    if not isinstance(api['reasoning_effort'], str) or not api['reasoning_effort'].strip() or len(api['reasoning_effort']) > 128:
        fail('api_reasoning_effort', '思考强度必须是非空字符串，最多 128 字符；auto 表示服务默认。')
    if api['token_field'] not in ('max_tokens', 'max_completion_tokens'):
        fail('api_token_field', '请选择 max_tokens 或 max_completion_tokens 输出字段。')
    if api['auth_mode'] not in ('protocol', 'bearer', 'x-api-key', 'api-key'):
        fail('api_auth_mode', '鉴权方式格式无效。')
    if api['thinking_mode'] not in ('auto', 'off', 'adaptive', 'budget'):
        fail('api_thinking_mode', 'Anthropic 思考模式无效。')
    if not isinstance(api['model'], str) or len(api['model']) > 256:
        fail('api_model', '模型名称必须是字符串，最多 256 字符。')
    if mode == 'api' and not api['model']:
        fail('api_model', '请填写或选择 API 模型。')
    if 'api_key' in api or 'key' in api:
        fail('api_key', '配置文件不接受明文 API Key，请通过设置页加密保存。')
    if ui['edge'] not in ('left', 'right'):
        fail('edge', '屏幕边缘必须是 left/right。')
    number('ui', 'resting_opacity', .1, 1)
    number('ui', 'animation_ms', 0, 1000, True)
    number('ui', 'panel_width', 320, 900, True)
    number('ui', 'panel_height', 420, 1200, True)
    if require_files and mode == 'local':
        for key, label, suffix in (('engine_path', 'llama 引擎', '.exe'), ('model_path', 'GGUF 模型', '.gguf')):
            value = model.get(key)
            if not isinstance(value, str) or not Path(value).is_file() or Path(value).suffix.lower() != suffix:
                fail(key, label + '文件不存在或文件类型不正确：' + str(value))
            elif key == 'model_path':
                try:
                    with Path(value).open('rb') as file:
                        if file.read(4) != b'GGUF':
                            fail(key, '所选文件没有有效的 GGUF 文件头，请检查下载是否完整。')
                except OSError:
                    fail(key, 'GGUF 文件无法读取，请检查访问权限。')
    if errors:
        raise ConfigError(errors)
    return cfg


def read_config(path=CONFIG_PATH, require_files=False):
    cfg = raw_config(path)
    for key in ('engine_path', 'model_path'):
        if isinstance(cfg['model'][key], str):
            resolved = Path(cfg['model'][key])
            if not resolved.is_absolute():
                cfg['model'][key] = str(Path(path).resolve().parent / resolved)
    validate_config(cfg, require_files)
    for content_key, file_key in (('system_prompt', 'system_prompt_file'), ('default_user_prompt', 'user_prompt_file')):
        if cfg['prompts'].get(file_key):
            prompt_path = Path(cfg['prompts'][file_key])
            if not prompt_path.is_absolute():
                prompt_path = Path(path).resolve().parent / prompt_path
            cfg['prompts'][content_key] = prompt_path.read_text(encoding='utf-8-sig').strip()
    if any(not isinstance(cfg['prompts'].get(key), str) or not cfg['prompts'][key].strip()
           for key in ('system_prompt', 'default_user_prompt')):
        raise ValueError('两个提示词必须非空，请检查 prompts 文件夹。')
    if cfg['prompts']['default_user_prompt'].count('{input}') > 1:
        raise ValueError('User Prompt 最多只能包含一个 {input}。')
    return cfg


def config_bytes(cfg):
    source = deepcopy(cfg)
    for content, file in (('system_prompt', 'system_prompt_file'), ('default_user_prompt', 'user_prompt_file')):
        if source['prompts'].get(file):
            source['prompts'].pop(content, None)
    lines = ['# UTF-8. Generated by the settings page. API keys are stored with Windows DPAPI.']
    for section, values in source.items():
        lines.extend(['', '[' + section + ']'])
        for key, value in values.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]+', key) or isinstance(value, (dict, list)):
                raise ValueError('无法保存不支持的配置字段：' + key)
            lines.append(key + ' = ' + json.dumps(value, ensure_ascii=False, allow_nan=False))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def engine_arguments(cfg, port, api_key):
    model = cfg['model']
    return [model['engine_path'], '--model', model['model_path'],
            '--ctx-size', str(model['context_size']), '--cache-type-k', model['cache_type_k'], '--cache-type-v', model['cache_type_v'],
            '--parallel', '1', '--flash-attn', model['flash_attention'],
            '--gpu-layers', str(model['gpu_layers']), '--fit', 'off',
            '--batch-size', str(model['batch_size']), '--ubatch-size', str(model['ubatch_size']),
            '--host', '127.0.0.1', '--port', str(port), '--api-key', api_key,
            '--jinja', '--reasoning', model['reasoning'],
            '--reasoning-format', 'deepseek', '--reasoning-budget', str(model['reasoning_budget']),
            '--no-context-shift', '--no-webui', '--log-colors', 'off', '--log-verbosity', '4']
