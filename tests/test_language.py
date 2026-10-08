import httpx
import pytest
import json

from app.controller import Controller
from app.config import ROOT, DEFAULTS, config_bytes, read_config
from app.language import source_language, format_user, missing_material, validate_output, LanguageError


@pytest.mark.parametrize('text,expected', [
    ('我想读取CSV文件，优先用Python，不添加依赖。', 'zh'),
    ('I want to read CSV files without adding dependencies.', 'en'),
    ('Yes, I have already finished the implementation.', 'en'),
    ('Translate the word "你好" into French.', 'en'),
    ('```text\nI want to build a minimal application.\n```', 'en'),
    ('```markdown\n# Task\nTranslate this paragraph without adding anything.\n```', 'en'),
    ('请保留 C:\\example\\llama-server.exe 和 --ctx-size 32768。', 'zh'),
    ('```python\nprint("Hello")\n```', 'neutral'),
    ('Okay.', 'en'),
    ('"I want to build a small application."', 'en'),
    ('你好', 'zh'),
])
def test_source_direction(text, expected):
    assert source_language(text) == expected


def test_template_replaces_only_application_placeholder():
    source = 'Preserve the variable {input} in this Python template.'
    assert format_user('<source_text>\n{input}\n</source_text>', source) == '<source_text>\n' + source + '\n</source_text>'


def test_markdown_prompts_reload_on_new_conversation(tmp_path):
    (tmp_path / 'prompts').mkdir()
    system = tmp_path / 'prompts' / 'system_prompt.md'
    user = tmp_path / 'prompts' / 'user_prompt.md'
    system.write_text('Original rules', encoding='utf-8-sig')
    user.write_text('<source_text>\n{input}\n</source_text>', encoding='utf-8')
    config = tmp_path / 'config.toml'
    config.write_bytes(config_bytes(DEFAULTS))
    c = Controller(lambda _: None, config)
    assert c.config['prompts']['system_prompt'] == 'Original rules'
    system.write_text('Updated rules', encoding='utf-8')
    c.history = [{'role': 'user', 'content': 'previous input'}]
    c.new_conversation()
    assert c.config['prompts']['system_prompt'] == 'Updated rules'
    assert not c.history


def test_missing_material_is_distinct_from_provided_material_and_software_feature():
    assert missing_material('帮我写一个总结会议纪要的提示词，先概括结论，再列行动项。') == 'the meeting minutes'
    assert missing_material('总结会议纪要：张三负责在周五前交付报告。') is None
    assert missing_material('开发一个能够总结会议纪要的软件。') is None


@pytest.mark.parametrize('reply', ['Yes, I can help you with this.', 'Here is the translation: Hello.',
                                  '```text\nI want to read a CSV file.\n```',
                                  '译文：“I want to read a CSV file without changing its contents.”',
                                  '以下是结果。 I want to build an application and read files without adding dependencies.'])
def test_english_reply_to_english_source_is_rejected(reply):
    with pytest.raises(LanguageError):
        validate_output(reply, 'en')


def test_chinese_translation_can_preserve_technical_code():
    assert validate_output('请保留 Python 代码：\n```python\nprint("hello")\n```', 'en')
    assert validate_output('“我想构建一个小应用。”', 'en')
    assert validate_output(r'保持 C:\example\model.gguf 原样。设置 --ctx-size 32768 并使用 q8_0。', 'en')


def test_english_prompt_uses_a_longer_outer_fence_for_embedded_code():
    candidate = '```text\nReview this code without executing it:\n```python\nprint("hello")\n```\n```'
    output = validate_output(candidate, 'zh')
    assert output.startswith('````text\n') and output.endswith('\n````')
    assert '```python\nprint("hello")\n```' in output


@pytest.mark.parametrize('candidates,expected', [
    (['I want to read a CSV file.', 'I want to read a CSV file.'], None),
    (['I want to read a CSV file.', '我想读取 CSV 文件。'], '我想读取 CSV 文件。'),
])
def test_wrong_language_is_never_emitted_to_frontend(monkeypatch, candidates, expected):
    events = []
    c = Controller(events.append)
    c.state, c.url, c.key = 'ready', 'http://localhost:1', 'test'
    requests = []

    def fake_request(request):
        requests.append(request)
        if request.url.path == '/apply-template':
            return httpx.Response(200, json={'prompt': 'test'})
        return httpx.Response(200, json={'tokens': [1, 2, 3]})

    client_class = httpx.Client
    monkeypatch.setattr('app.controller.httpx.Client', lambda **kw: client_class(transport=httpx.MockTransport(fake_request)))
    replies = iter(candidates)
    monkeypatch.setattr(c, '_completion', lambda *args: (next(replies), 'stop', 100))
    c.send('I want to read a CSV file.')
    c.chat_thread.join(10)
    chunks = [event['text'] for event in events if event['type'] == 'chunk']
    assert chunks == ([expected] if expected else [])
    assert len(c.history) == (2 if expected else 0)
    assert not any('I want' in chunk for chunk in chunks)


def test_budget_exhaustion_retries_using_the_engine_supported_budget_field(monkeypatch):
    events, budgets = [], []
    c = Controller(events.append)
    c.state, c.url, c.key = 'ready', 'http://localhost:1', 'test'

    def fake_request(request):
        if request.url.path == '/apply-template':
            return httpx.Response(200, json={'prompt': 'test'})
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': [1, 2]})
        body = json.loads(request.content)
        budgets.append(body['reasoning_budget_tokens'])
        first = len(budgets) == 1
        delta = {'reasoning_content': 'thinking'} if first else {'content': '我想读取 CSV 文件。'}
        payload = {'choices': [{'delta': delta, 'finish_reason': 'length' if first else 'stop'}]}
        return httpx.Response(200, text='data: ' + json.dumps(payload) + '\n\ndata: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})

    client_class = httpx.Client
    monkeypatch.setattr('app.controller.httpx.Client', lambda **kw: client_class(transport=httpx.MockTransport(fake_request)))
    c.send('I want to read a CSV file.')
    c.chat_thread.join(10)
    assert budgets == [-1, 1024]
    assert [e['text'] for e in events if e['type'] == 'chunk'] == ['我想读取 CSV 文件。']
    assert any(e['type'] == 'done' for e in events)
