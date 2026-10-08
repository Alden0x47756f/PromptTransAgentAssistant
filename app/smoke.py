"""Opt-in runtime smoke check, usable in the packaged EXE without Python."""
import json
import re
import time

from PySide6.QtCore import QTimer
from .config import ROOT


class SmokeCheck:
    def __init__(self, application, bridge, panel, ball):
        self.application, self.bridge, self.panel, self.ball = application, bridge, panel, ball
        self.events = []
        self.report = {'passed': False}
        self.stage = 'ready'
        self.pending = False
        self.started = time.monotonic()
        bridge.event.connect(lambda raw: self.events.append(json.loads(raw)))
        ball.toggle_panel() if not panel.isVisible() else None
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def tick(self):
        try:
            c = self.bridge.controller
            if time.monotonic() - self.started > 180:
                raise RuntimeError('Packaged smoke check timed out: ' + self.stage)
            if c.state == 'error':
                raise RuntimeError(c.detail)
            if self.pending:
                return
            if self.stage == 'ready' and c.state == 'ready':
                self.pending = True

                def connected(raw):
                    self.pending = False
                    value = json.loads(raw)
                    if not value['connected'] or value['state'] != 'ready':
                        return
                    self.report['webchannel'] = True
                    self.report['automatic_model_load'] = True
                    self.report['prompt_files'] = True
                    self.stage = 'translate'
                    self.panel.view.page().runJavaScript("document.getElementById('input').value='I have already tested the application. Keep --ctx-size 32768 and q8_0.'; document.getElementById('input').dispatchEvent(new Event('input')); document.getElementById('send').click();")

                self.panel.view.page().runJavaScript("JSON.stringify({connected:!!backend,state:state.state})", connected)
            elif self.stage == 'translate':
                errors = [e for e in self.events if e['type'] == 'error']
                if errors:
                    raise RuntimeError(str(errors))
                done = next((e for e in self.events if e['type'] == 'done'), None)
                if done and not c.busy:
                    output = ''.join(e['text'] for e in self.events if e['type'] == 'chunk')
                    if not re.search(r'[\u4e00-\u9fff]', output) or '32768' not in output:
                        raise RuntimeError('Packaged English-to-Chinese check failed')
                    self.report['translation'] = output
                    self.report['reasoning_characters'] = done.get('reasoning_characters', 0)
                    self.panel.view.page().runJavaScript("document.getElementById('close').click()")
                    self.stage, self.close_time = 'close', time.monotonic()
            elif self.stage == 'close' and time.monotonic() - self.close_time > .5:
                if self.panel.isVisible() or not self.ball.isVisible() or c.state != 'ready':
                    raise RuntimeError('X did not preserve the application and loaded model')
                self.report['close_preserves_model'] = True
                self.report['passed'] = True
                self.timer.stop()
                self.bridge.exit()  # the same exit callback used by the context menu
        except Exception as exc:
            self.report['error'] = str(exc)
            self.timer.stop()
            self.application.exit(1)

    def save(self):
        self.report['process_cleanup'] = self.bridge.controller.process is None
        self.report['passed'] = self.report['passed'] and self.report['process_cleanup']
        (ROOT / 'test-results').mkdir(exist_ok=True)
        (ROOT / 'test-results' / 'executable-smoke.json').write_text(
            json.dumps(self.report, indent=2, ensure_ascii=False), encoding='utf-8')
        return 0 if self.report['passed'] else 1
