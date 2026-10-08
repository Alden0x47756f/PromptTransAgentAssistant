"""Measure Windows UI process-tree resources and verify result controls, without an LLM.

Run each baseline/variant in a fresh interpreter, using --project for another checkout.
Memory is the sum of process working sets (shared pages may be counted more than once).
"""
import argparse
from copy import deepcopy
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import sys
import tempfile
import time

started = time.perf_counter()
parser = argparse.ArgumentParser()
parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--expect-updated', action='store_true')
args = parser.parse_args()
sys.path.insert(0, str(args.project.resolve()))
from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QApplication
from app.config import DEFAULTS, config_bytes
from app.desktop import Bridge, Panel, FloatingBall


class Entry(ctypes.Structure):
    _fields_ = [('size', wt.DWORD), ('usage', wt.DWORD), ('pid', wt.DWORD),
                ('heap', ctypes.c_size_t), ('module', wt.DWORD), ('threads', wt.DWORD),
                ('parent', wt.DWORD), ('priority', wt.LONG), ('flags', wt.DWORD),
                ('name', wt.WCHAR * 260)]


class Memory(ctypes.Structure):
    _fields_ = [('size', wt.DWORD), ('faults', wt.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('peak', 'working', 'pool_peak', 'pool',
                                           'nonpaged_peak', 'nonpaged', 'pagefile',
                                           'pagefile_peak', 'private')]


kernel = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
kernel.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel.OpenProcess.restype = wt.HANDLE
kernel.CloseHandle.argtypes = [wt.HANDLE]
kernel.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(Memory), wt.DWORD]


def resources():
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    entry = Entry(size=ctypes.sizeof(Entry))
    parents = {}
    try:
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.pid] = entry.parent
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    pids = {os.getpid()}
    while True:
        children = {pid for pid, parent in parents.items() if parent in pids}
        if children <= pids:
            break
        pids |= children
    working = private = cpu = 0
    for pid in pids:
        handle = kernel.OpenProcess(0x0410, False, pid)
        if not handle:
            continue
        try:
            memory = Memory(size=ctypes.sizeof(Memory))
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.size):
                working += memory.working
                private += memory.private
            times = [wt.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                cpu += sum((value.dwHighDateTime << 32) | value.dwLowDateTime for value in times[2:]) / 1e7
        finally:
            kernel.CloseHandle(handle)
    return {'processes': len(pids), 'working_mib': working / 1048576,
            'private_mib': private / 1048576, 'cpu_seconds': cpu}


temporary = tempfile.TemporaryDirectory(prefix='prompt-ui-performance-')
workspace = Path(temporary.name)
(workspace / 'prompts').mkdir()
for name in ('system_prompt.md', 'user_prompt.md'):
    (workspace / 'prompts' / name).write_bytes((args.project / 'prompts' / name).read_bytes())
cfg = deepcopy(DEFAULTS)
cfg['model']['auto_load'] = False
config = workspace / 'config.toml'
config.write_bytes(config_bytes(cfg))
app = QApplication([])
app.setQuitOnLastWindowClosed(False)


class RecordingBridge(Bridge):
    copied = None

    @Slot(str)
    def copyText(self, text):
        self.copied = text
        self.event.emit(json.dumps({'type': 'copied'}))


class CheckedBall(FloatingBall):
    def _cursor_inside(self):
        return False


bridge = RecordingBridge(config, workspace / 'credentials.json')
panel = Panel(bridge, cfg['ui'])
ball = CheckedBall(panel, bridge, cfg['ui'])
ball.show()
report = {'construct_ms': (time.perf_counter() - started) * 1000, 'passed': False}
first_open = None
sample = None
payload = '\n'.join(f'第 {i} 项：保留 UTF-8、CSV 与 JSON，并明确输入、处理步骤和输出。' for i in range(600))


def finish(error=None):
    if error:
        report['error'] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    bridge.controller.shutdown()
    ball.hide()
    panel.hide()
    app.exit(0 if report['passed'] else 1)


def opened(raw):
    if not raw:
        QTimer.singleShot(30, check_open)
        return
    report['first_open_ms'] = (time.perf_counter() - first_open) * 1000
    panel.view.page().runJavaScript("JSON.stringify({settings:!document.getElementById('settings-view').hidden,connected:!!backend})", run_checks)


def check_open():
    panel.view.page().runJavaScript('!!backend', opened)


def run_checks(raw):
    try:
        value = json.loads(raw)
        assert value['settings'] and value['connected'], value
        report['first_open_settings'] = True
        script = """(()=>{
            switchView('chat');
            window.benchmarkText=PAYLOAD;
            window.benchmarkSamples=[];
            for(let i=0;i<5;i++){
                handleEvent(JSON.stringify({type:'reset'}));
                const start=performance.now();
                handleEvent(JSON.stringify({type:'accepted',text:'Fixture',direction:'英文 → 中文'}));
                handleEvent(JSON.stringify({type:'chunk',text:benchmarkText}));
                handleEvent(JSON.stringify({type:'done',reason:'stop'}));
                benchmarkSamples.push(performance.now()-start);
            }
            document.getElementById('input').value='Preserved draft';
        })()""".replace('PAYLOAD', json.dumps(payload, ensure_ascii=False))
        panel.view.page().runJavaScript(script, lambda _: QTimer.singleShot(300, inspect))
    except Exception as exc:
        finish(exc)


def inspect():
    panel.view.page().runJavaScript("""JSON.stringify({
        samples:benchmarkSamples,
        onlyMinimize:!document.getElementById('close')&&!!document.getElementById('collapse'),
        copyBelow:(()=>{const b=document.querySelector('.copy-button'),body=document.querySelector('.assistant .message-body');return b.getBoundingClientRect().top>=body.getBoundingClientRect().bottom;})(),
        contentMatches:document.querySelector('.assistant .message-body').textContent===benchmarkText,
        copyVisible:(()=>{const b=document.querySelector('.copy-button').getBoundingClientRect(),c=document.getElementById('conversation').getBoundingClientRect();return b.top>=c.top&&b.bottom<=c.bottom;})()
    })""", inspected)


def inspected(raw):
    try:
        value = json.loads(raw)
        assert value['contentMatches'], value
        if args.expect_updated:
            assert value['onlyMinimize'] and value['copyBelow'] and value['copyVisible'], value
        report['ui'] = value
        panel.view.page().runJavaScript("document.querySelector('.copy-button').click()", lambda _: QTimer.singleShot(100, copied))
    except Exception as exc:
        finish(exc)


def copied():
    try:
        assert bridge.copied == payload
        report['copy_exact'] = True
        panel.view.page().runJavaScript("document.getElementById('collapse').click()", lambda _: QTimer.singleShot(350, collapsed))
    except Exception as exc:
        finish(exc)


def collapsed():
    try:
        assert not panel.isVisible() and ball.isVisible()
        report['minimize_keeps_app'] = True
        ball.toggle_panel()
        QTimer.singleShot(300, resumed)
    except Exception as exc:
        finish(exc)


def resumed():
    panel.view.page().runJavaScript("document.getElementById('input').value==='Preserved draft'&&document.querySelector('.assistant .message-body').textContent===benchmarkText", retained)


def retained(ok):
    if not ok:
        finish('Conversation or draft lost after minimize')
        return
    report['draft_and_result_retained'] = True
    report['expanded'] = resources()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.grab().save(str(args.output.with_suffix('.png')))
    script = """(()=>{
        handleEvent(JSON.stringify({type:'accepted',text:'Formatting fixture',direction:'中文 → 英文'}));
        handleEvent(JSON.stringify({type:'chunk',text:'说明。\\n```prompt\\nUse UTF-8 and JSON.\\nPreserve <input> literally.\\n```\\n完成。'}));
        handleEvent(JSON.stringify({type:'done',reason:'length'}));
    })()"""
    panel.view.page().runJavaScript(script, lambda _: QTimer.singleShot(100, check_formatted))


def check_formatted():
    panel.view.page().runJavaScript("""JSON.stringify((()=>{
        const article=document.querySelector('.assistant:last-child');
        const body=article.querySelector('.message-body'),button=article.querySelector('.copy-button'),note=article.querySelector('.result-note');
        const value={safeMarkup:!body.querySelector('input'),oneCopy:article.querySelectorAll('.copy-button').length===1,
                     footerAfterNote:button.getBoundingClientRect().top>=note.getBoundingClientRect().bottom};
        button.click();return value;
    })())""", formatted)


def formatted(raw):
    try:
        value = json.loads(raw)
        assert value['safeMarkup'] and value['oneCopy'], value
        if args.expect_updated:
            assert value['footerAfterNote'], value
        report['formatted'] = value
        QTimer.singleShot(100, copied_formatted)
    except Exception as exc:
        finish(exc)


def copied_formatted():
    try:
        assert bridge.copied == 'Use UTF-8 and JSON.\nPreserve <input> literally.'
        report['fenced_copy_exact'] = True
        panel.view.page().runJavaScript("""(()=>{
            handleEvent(JSON.stringify({type:'accepted',text:'Cancellation fixture',direction:'英文 → 中文'}));
            handleEvent(JSON.stringify({type:'cancelled'}));
            return !document.querySelector('.assistant:last-child .copy-button');
        })()""", cancelled)
    except Exception as exc:
        finish(exc)


def cancelled(ok):
    if not ok:
        finish('Unvalidated/cancelled output received a copy button')
        return
    report['no_copy_without_result'] = True
    report['passed'] = True
    finish()


def open_panel():
    global first_open
    report['idle_cpu_seconds'] = resources()['cpu_seconds'] - sample['cpu_seconds']
    first_open = time.perf_counter()
    bridge.openConfig()
    QTimer.singleShot(30, check_open)


def idle():
    global sample
    sample = resources()
    report['idle'] = sample
    QTimer.singleShot(1000, open_panel)


QTimer.singleShot(1500, idle)
QTimer.singleShot(15000, lambda: finish('UI check timed out') if not report['passed'] else None)
exit_code = app.exec()
temporary.cleanup()
raise SystemExit(exit_code)
