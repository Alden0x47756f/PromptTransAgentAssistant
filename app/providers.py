"""OpenAI Chat/Responses and Anthropic Messages protocol adapters."""
import json
import asyncio
import time
import httpx

from .diagnostics import ApiError


# Model IDs and effort values are opaque service identifiers. Never infer
# existence, capabilities, or request fields from a model name or allowlist.


def endpoint(api, resource):
    root = api['base_url'].rstrip('/')
    # Accept both the service root and a versioned/custom API prefix.
    if root.rsplit('/', 1)[-1].lower() == resource.rsplit('/', 1)[-1].lower():
        raise ValueError('请填写 base_url 前缀，而不是具体请求地址。')
    from urllib.parse import urlsplit
    if urlsplit(root).path in ('', '/'):
        root += '/v1'
    return root + '/' + resource


def api_headers(api, key):
    mode = api.get('auth_mode', 'protocol')
    if mode == 'protocol':
        mode = 'x-api-key' if api['protocol'] == 'anthropic' else 'bearer'
    headers = {'Authorization': 'Bearer ' + key} if mode == 'bearer' else {mode: key}
    if api['protocol'] == 'anthropic':
        headers['anthropic-version'] = '2023-06-01'
    return headers


def raise_for_api(response):
    if response.is_success:
        return
    response.read()
    try:
        payload = response.json()
        error = payload.get('error', payload)
        message = error.get('message', str(error)) if isinstance(error, dict) else str(error)
    except (ValueError, AttributeError):
        message = response.text[:2000]
    raise ApiError(response.status_code, f'HTTP {response.status_code}\n' + str(message)[:3000])


def models(client, api):
    result = []
    url = endpoint(api, 'models')
    # Anthropic uses cursor pagination; OpenAI returns its complete list.
    for _ in range(10):
        response = client.get(url)
        raise_for_api(response)
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            raise ValueError('服务未返回兼容的模型列表。请检查协议，或手动填写模型名称。')
        for item in payload['data']:
            if isinstance(item, dict) and isinstance(item.get('id'), str):
                result.append({'id': item['id'], 'name': item.get('display_name') or item['id']})
        if api['protocol'] != 'anthropic' or not payload.get('has_more') or not payload.get('last_id'):
            break
        from urllib.parse import urlencode
        url = endpoint(api, 'models') + '?' + urlencode({'after_id': payload['last_id']})
    return sorted({item['id']: item for item in result}.values(), key=lambda item: item['id'])


def request_body(api, messages, max_tokens, effort_override=None):
    effort = api['reasoning_effort'] if effort_override is None else effort_override
    if api['protocol'] == 'anthropic':
        body = {'model': api['model'], 'stream': True, 'max_tokens': max_tokens,
                'system': '\n\n'.join(m['content'] for m in messages if m['role'] == 'system'),
                'messages': [m for m in messages if m['role'] != 'system']}
        thinking = api['thinking_mode']
        if thinking == 'adaptive':
            body['thinking'] = {'type': 'adaptive'}
        elif thinking == 'budget':
            body['thinking'] = {'type': 'enabled', 'budget_tokens': api['thinking_budget']}
        elif thinking == 'off':
            body['thinking'] = {'type': 'disabled'}
        if effort != 'auto':
            body['output_config'] = {'effort': effort}
        return 'messages', body
    if api['endpoint'] == 'responses':
        body = {'model': api['model'], 'stream': True, 'store': False, 'max_output_tokens': max_tokens,
                'instructions': '\n\n'.join(m['content'] for m in messages if m['role'] == 'system'),
                'input': [m for m in messages if m['role'] != 'system']}
        if effort != 'auto':
            body['reasoning'] = {'effort': effort}
        return 'responses', body
    body = {'model': api['model'], 'messages': messages, 'stream': True}
    token_name = api.get('token_field', 'max_tokens')
    body[token_name] = max_tokens
    if effort != 'auto':
        body['reasoning_effort'] = effort
    return 'chat/completions', body


def sse_events(response):
    lines = []
    for line in response.iter_lines():
        if not line:
            if lines:
                yield '\n'.join(lines)
                lines = []
        elif line.startswith('data:'):
            lines.append(line[5:].lstrip())
            if sum(map(len, lines)) > 2097152:
                raise ValueError('API 流事件过大，已停止读取。')
    if lines:
        yield '\n'.join(lines)


async def _sse_events_async(response):
    lines = []
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield '\n'.join(lines)
                lines = []
        elif line.startswith('data:'):
            lines.append(line[5:].lstrip())
            if sum(map(len, lines)) > 2097152:
                raise ValueError('API 流事件过大，已停止读取。')
    if lines:
        yield '\n'.join(lines)


async def _complete_async(headers, timeout, api, messages, max_tokens, cancel, emit):
    resource, body = request_body(api, messages, max_tokens)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, trust_env=False) as client:
        async def read_result():
            output, reason, thoughts, last_progress = '', None, 0, 0
            async with client.stream('POST', endpoint(api, resource), json=body) as response:
                if not response.is_success:
                    await response.aread()
                    raise_for_api(response)
                if 'text/event-stream' not in response.headers.get('content-type', ''):
                    await response.aread()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise ValueError('API 返回内容必须是 JSON 对象。')
                    if data.get('error'):
                        error = data['error']
                        raise ApiError(400, error.get('message', str(error)) if isinstance(error, dict) else str(error))
                    if api['protocol'] == 'anthropic':
                        output = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
                        reason = 'length' if data.get('stop_reason') == 'max_tokens' else 'stop' if data.get('stop_reason') in ('end_turn', 'stop_sequence') else None
                    elif resource == 'responses':
                        output = ''.join(p.get('text', '') for item in data.get('output', []) if item.get('type') == 'message' for p in item.get('content', []) if p.get('type') == 'output_text')
                        reason = 'stop' if data.get('status') == 'completed' else 'length' if data.get('status') == 'incomplete' else None
                    else:
                        choices = data.get('choices') or [{}]
                        first = choices[0]
                        output, reason = first.get('message', {}).get('content') or '', first.get('finish_reason')
                else:
                    async for data in _sse_events_async(response):
                        if data == '[DONE]':
                            break
                        event = json.loads(data)
                        if not isinstance(event, dict):
                            raise ValueError('API 流事件必须是 JSON 对象。')
                        if event.get('error') or event.get('type') == 'error':
                            error = event.get('error', event)
                            raise ApiError(400, error.get('message', str(error)) if isinstance(error, dict) else str(error))
                        if api['protocol'] == 'anthropic':
                            delta = event.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                output += delta.get('text', '')
                            elif delta.get('type') == 'thinking_delta':
                                thoughts += len(delta.get('thinking', ''))
                            elif event.get('type') == 'content_block_start':
                                block = event.get('content_block', {})
                                if block.get('type') == 'text':
                                    output += block.get('text', '')
                            if event.get('type') == 'message_delta':
                                stop = delta.get('stop_reason')
                                reason = 'length' if stop == 'max_tokens' else 'stop' if stop in ('end_turn', 'stop_sequence') else reason
                        elif resource == 'responses':
                            kind = event.get('type')
                            if kind == 'response.output_text.delta':
                                output += event.get('delta', '')
                            elif kind in ('response.reasoning_summary_text.delta', 'response.reasoning_text.delta'):
                                thoughts += len(event.get('delta', ''))
                            elif kind == 'response.completed':
                                reason = 'stop'
                            elif kind == 'response.incomplete':
                                reason = 'length'
                            elif kind == 'response.failed':
                                raise ApiError(400, str(event.get('response', {}).get('error', 'API 生成失败。')))
                        else:
                            for choice in event.get('choices', []):
                                delta = choice.get('delta', {})
                                output += delta.get('content') or ''
                                thoughts += len(delta.get('reasoning_content') or '')
                                reason = choice.get('finish_reason') or reason
                        if time.monotonic() - last_progress > 1:
                            emit('progress', message='正在生成并校验结果…' if output else '正在等待 API 结果…')
                            last_progress = time.monotonic()
            if not isinstance(output, str):
                raise ValueError('API 正文类型不符合文本协议。')
            return output, reason, thoughts

        async def cancelled():
            while not cancel.is_set():
                await asyncio.sleep(.05)

        result_task = asyncio.create_task(read_result())
        cancel_task = asyncio.create_task(cancelled())
        try:
            finished, _ = await asyncio.wait((result_task, cancel_task), return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in finished:
                result_task.cancel()
                await asyncio.gather(result_task, return_exceptions=True)
                return '', None, 0
            return await result_task
        finally:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)


def complete(client, api, messages, max_tokens, cancel, emit):
    # Task cancellation closes the socket even if the server has not sent headers.
    # Inference still runs on the controller's background worker, never the UI thread.
    return asyncio.run(_complete_async(dict(client.headers), client.timeout, api, messages, max_tokens, cancel, emit))
