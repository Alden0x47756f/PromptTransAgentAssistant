import asyncio
from copy import deepcopy
import json
import threading
import time

import httpx
import pytest

from app import providers
from app.config import DEFAULTS
from app.controller import Controller
from app.diagnostics import ApiError
from test_settings import setup_settings, api_draft


@pytest.mark.parametrize('protocol,endpoint,model,effort', [
    ('openai', 'chat', 'deepseekv4.1-flash', 'vendor-custom'),
    ('anthropic', 'chat', 'deepseekv4.1-flash', 'vendor-custom'),
    ('openai', 'responses', 'unlisted-future-model', 'unlisted-effort'),
    ('openai', 'chat', 'gpt-4', 'max'),
    ('anthropic', 'chat', 'claude-unlisted', 'xhigh'),
])
def test_model_and_effort_are_opaque_and_passed_verbatim(protocol, endpoint, model, effort):
    api = deepcopy(DEFAULTS['api'])
    api.update(protocol=protocol, endpoint=endpoint, model=model, reasoning_effort=effort)
    resource, body = providers.request_body(api, [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'source'}], 8192)
    assert body['model'] == model
    if protocol == 'anthropic':
        assert body['output_config']['effort'] == effort and body['system'] == 'rules'
        assert all(message['role'] != 'system' for message in body['messages'])
    elif endpoint == 'responses':
        assert body['reasoning']['effort'] == effort and body['instructions'] == 'rules'
    else:
        assert body['reasoning_effort'] == effort


def test_output_field_is_chosen_explicitly_not_from_a_model_name():
    api = deepcopy(DEFAULTS['api'])
    api.update(model='gpt-6-custom', token_field='max_tokens')
    assert 'max_tokens' in providers.request_body(api, [], 8192)[1]
    api.update(model='deepseekv4.1-flash', token_field='max_completion_tokens')
    assert 'max_completion_tokens' in providers.request_body(api, [], 8192)[1]


def test_thinking_budget_support_is_left_to_the_service():
    api = deepcopy(DEFAULTS['api'])
    api.update(protocol='anthropic', model='deepseekv4.1-flash', thinking_mode='budget', thinking_budget=128)
    assert providers.request_body(api, [], 64)[1]['thinking']['budget_tokens'] == 128


def test_authentication_can_be_selected_for_a_compatible_gateway():
    api = deepcopy(DEFAULTS['api'])
    api.update(protocol='anthropic', auth_mode='bearer')
    headers = providers.api_headers(api, 'test-only-key')
    assert headers['Authorization'] == 'Bearer test-only-key'
    assert headers['anthropic-version'] == '2023-06-01'
    assert 'x-api-key' not in headers


def sse(*events):
    return ''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events) + 'data: [DONE]\n\n'


def patch_async(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize('protocol,endpoint', [('openai', 'chat'), ('openai', 'responses'), ('anthropic', 'chat')])
def test_all_protocols_extract_text_and_separate_thinking(monkeypatch, protocol, endpoint):
    api = deepcopy(DEFAULTS['api'])
    api.update(protocol=protocol, endpoint=endpoint, base_url='https://example.test/custom/v1', model='deepseekv4.1-flash')
    requests, progress = [], []
    def handler(request):
        requests.append(request)
        if protocol == 'anthropic':
            content = sse({'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'private thought'}},
                          {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '你好。'}},
                          {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}})
        elif endpoint == 'responses':
            content = sse({'type': 'response.reasoning_summary_text.delta', 'delta': 'private thought'},
                          {'type': 'response.output_text.delta', 'delta': '你好。'}, {'type': 'response.completed'})
        else:
            content = sse({'choices': [{'delta': {'reasoning_content': 'private thought'}, 'finish_reason': None}]},
                          {'choices': [{'delta': {'content': '你好。'}, 'finish_reason': 'stop'}]})
        return httpx.Response(200, text=content, headers={'content-type': 'text/event-stream'})
    patch_async(monkeypatch, handler)
    with httpx.Client(headers=providers.api_headers(api, 'test-only-token')) as client:
        result = providers.complete(client, api, [{'role': 'user', 'content': 'Hello'}], 8192, threading.Event(), lambda *args, **kw: progress.append(kw))
    assert result == ('你好。', 'stop', len('private thought'))
    assert all('private thought' not in str(event) for event in progress)
    assert requests[0].url.path.startswith('/custom/v1/')
    if protocol == 'anthropic':
        assert requests[0].headers['x-api-key'] == 'test-only-token'
        assert requests[0].headers['anthropic-version'] == '2023-06-01'
    else:
        assert requests[0].headers['authorization'] == 'Bearer test-only-token'


def test_cancel_before_server_headers_returns_promptly(monkeypatch):
    started, cancel = threading.Event(), threading.Event()
    async def handler(request):
        started.set()
        await asyncio.sleep(60)
        return httpx.Response(200, json={'choices': []})
    patch_async(monkeypatch, handler)
    api = deepcopy(DEFAULTS['api'])
    api.update(model='unlisted-model', base_url='https://example.test/v1')
    results = []
    def run():
        with httpx.Client(headers=providers.api_headers(api, 'test-only-token')) as client:
            results.append(providers.complete(client, api, [], 8192, cancel, lambda *a, **kw: None))
    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(5)
    beginning = time.monotonic()
    cancel.set()
    worker.join(3)
    assert not worker.is_alive() and time.monotonic() - beginning < 3
    assert results == [('', None, 0)]


def test_server_rejection_is_reported_instead_of_client_capability_checks(monkeypatch):
    api = deepcopy(DEFAULTS['api'])
    api.update(model='deepseekv4.1-flash', reasoning_effort='custom-effort')
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={'error': {'message': 'Service rejects custom-effort for this model'}})
    patch_async(monkeypatch, handler)
    with httpx.Client() as client, pytest.raises(ApiError, match='Service rejects'):
        providers.complete(client, api, [], 8192, threading.Event(), lambda *a, **kw: None)
    assert seen[0]['model'] == 'deepseekv4.1-flash' and seen[0]['reasoning_effort'] == 'custom-effort'


def create_api_controller(setup):
    service, path, store = setup
    cfg, _, _, key = service.prepare(api_draft(service))
    service.save(cfg, key)
    events = []
    c = Controller(events.append, path, store.path)
    c.load()
    c.load_thread.join(5)
    assert c.state == 'ready'
    return c, events


def test_api_wrong_language_never_reaches_the_ui(setup_settings, monkeypatch):
    replies = iter(['This is an English answer.', '这是中文译文。'])
    def handler(request):
        return httpx.Response(200, text=sse({'choices': [{'delta': {'content': next(replies)}, 'finish_reason': 'stop'}]}),
                              headers={'content-type': 'text/event-stream'})
    patch_async(monkeypatch, handler)
    c, events = create_api_controller(setup_settings)
    try:
        c.send('This is an English answer.')
        c.chat_thread.join(10)
        assert [e['text'] for e in events if e['type'] == 'chunk'] == ['这是中文译文。']
        assert len(c.history) == 2
    finally:
        c.shutdown()


def test_api_errors_preserve_state_and_redact_keys(setup_settings, monkeypatch, caplog):
    secret = 'test-only-private-token'
    def handler(request):
        return httpx.Response(401, json={'error': {'message': 'invalid credential ' + secret}})
    patch_async(monkeypatch, handler)
    c, events = create_api_controller(setup_settings)
    try:
        c.send('Hello.')
        c.chat_thread.join(10)
        error = next(e for e in events if e['type'] == 'error')
        assert '鉴权失败' in error['message']
        assert 'HTTP 401' in error['diagnostic']['details']
        assert secret not in json.dumps(events) and secret not in caplog.text
        assert c.history == [] and c.state == 'ready' and not c.busy
    finally:
        c.shutdown()


def test_api_model_list_is_advisory_and_does_not_gate_saved_model(setup_settings, monkeypatch):
    service, path, store = setup_settings
    c = Controller(lambda _: None, path, store.path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'data': [{'id': 'different-model'}]}))) as client:
        cfg, _, _, _ = service.prepare(api_draft(service))
        assert providers.models(client, cfg['api']) == [{'id': 'different-model', 'name': 'different-model'}]
        assert cfg['api']['model'] == 'deepseekv4.1-flash'
    c.shutdown()
