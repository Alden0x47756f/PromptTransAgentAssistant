"""Safe, actionable diagnostics suitable for the window's error sheet."""
import re
import httpx


def redact(text, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[已隐藏密钥]')
    text = re.sub(r'(?i)(bearer\s+)[^\s"\x27]+', r'\1[已隐藏密钥]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|authorization)["\x27]?\s*[:=]\s*["\x27]?)[^\s,"\x27]+', r'\1[已隐藏密钥]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[已隐藏密钥]', text)
    return text


class ApiError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def diagnostic(exc, phase, cfg=None, log_path=None, secrets=()):
    detail = redact(str(exc), secrets)
    summary = detail.splitlines()[0] if detail else '操作未完成。'
    lowered = detail.lower()
    if isinstance(exc, ApiError):
        summary = {400: 'API 参数或模型设置不受服务支持。', 401: 'API 鉴权失败，请检查密钥与服务地址。',
                   403: '当前密钥没有访问此模型或服务的权限。', 404: 'API 路径或模型不存在，请检查协议、地址及模型名称。',
                   429: 'API 请求受限或额度不足，请查看服务返回详情。'}.get(exc.status, 'API 服务返回错误，请查看详情。')
    elif isinstance(exc, httpx.TimeoutException):
        summary = 'API 连接或响应超时，请检查网络、服务状态与 base_url。'
    elif isinstance(exc, httpx.ConnectError):
        summary = '无法连接 API 服务，请检查地址、网络及 TLS 证书。'
    elif any(word in lowered for word in ('out of memory', 'failed to allocate', 'cuda error: out')):
        summary = '模型加载时内存或显存不足，可减少上下文或 GPU 层数后重试。'
    elif any(word in lowered for word in ('unsupported model', 'unknown model architecture', 'unknown architecture')):
        summary = '当前 llama 引擎不支持该模型架构，请使用兼容的引擎。'
    elif 'cache' in lowered and any(word in lowered for word in ('unsupported', 'not support', 'head_dim', 'multiple')):
        summary = '模型或引擎不支持当前 KV Cache 配置，请尝试 f16 或 q8_0。'
    elif isinstance(exc, PermissionError):
        summary = '文件或目录无法写入，请检查权限、只读状态及文件占用。'
    metadata = ['阶段：' + phase, '错误类型：' + type(exc).__name__]
    if cfg:
        mode = cfg['connection']['mode']
        metadata.append('模式：' + mode)
        if mode == 'api':
            metadata.extend(['协议：' + cfg['api']['protocol'], '地址：' + cfg['api']['base_url'], '模型：' + cfg['api']['model']])
        else:
            model = cfg['model']
            metadata.extend(['模型：' + model['model_path'], '上下文：' + str(model['context_size']),
                             'KV：K=' + model['cache_type_k'] + ' / V=' + model['cache_type_v']])
    if log_path:
        metadata.append('日志：' + str(log_path))
    return {'summary': redact(summary, secrets), 'reason': detail[:320] if isinstance(exc, ApiError) else '',
            'details': redact('\n'.join(metadata) + '\n\n' + detail[:10000], secrets)}
