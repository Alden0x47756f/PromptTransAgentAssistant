"""Exercise the floating control's morph/delay states without moving the user's cursor."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, DEFAULTS, config_bytes
from app.desktop import Bridge, Panel, FloatingBall
from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication

temporary = tempfile.TemporaryDirectory(prefix='prompt-morph-check-')
workspace = Path(temporary.name)
(workspace / 'prompts').mkdir()
for name in ('system_prompt.md', 'user_prompt.md'):
    (workspace / 'prompts' / name).write_bytes((ROOT / 'prompts' / name).read_bytes())
cfg = deepcopy(DEFAULTS)
cfg['model']['auto_load'] = False
config = workspace / 'config.toml'
config.write_bytes(config_bytes(cfg))
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
bridge = Bridge(config, workspace / 'credentials.json')
panel = Panel(bridge, cfg['ui'])

class CheckedBall(FloatingBall):
    def _cursor_inside(self):
        return False

ball = CheckedBall(panel, bridge, cfg['ui'])
ball.show()
output = ROOT / 'test-results' / 'floating-morph'
output.mkdir(parents=True, exist_ok=True)
checks = {}
stage = 'idle'
started = stage_time = time.monotonic()
failure = None

def enter():
    QApplication.sendEvent(ball, QEvent(QEvent.Type.Enter))

def leave():
    QApplication.sendEvent(ball, QEvent(QEvent.Type.Leave))

def transition(name):
    global stage, stage_time
    stage, stage_time = name, time.monotonic()

def save(name):
    ball.grab().save(str(output / (name + '.png')))

def finish():
    timer.stop()
    bridge.controller.shutdown()
    panel.hide()
    ball.hide()
    checks['failure'] = failure
    checks['stage'] = stage
    (output / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False), flush=True)
    temporary.cleanup()
    app.exit(1 if failure else 0)

def click():
    local = QPointF(34, 42)
    global_point = QPointF(ball.mapToGlobal(QPoint(34, 42)))
    QApplication.sendEvent(ball, QMouseEvent(QEvent.Type.MouseButtonPress, local, global_point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(ball, QMouseEvent(QEvent.Type.MouseButtonRelease, local, global_point, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

def tick():
    global failure
    elapsed = time.monotonic() - stage_time
    if time.monotonic() - started > 18:
        raise AssertionError('Timeout at ' + stage)
    if stage == 'idle' and elapsed > .5:
        assert ball.shapeProgress < .001 and not panel.isVisible()
        bounds, _ = ball._shape()
        assert bounds.width() == 10 and bounds.height() == 72 and bounds.right() == ball.width()
        assert not ball.mask().contains(QPoint(10, 42))
        checks['initial_strip_at_right_edge'] = True
        save('strip-right')
        enter()
        transition('hover')
    elif stage == 'hover' and elapsed > .3:
        assert ball.shapeProgress > .99 and ball.windowOpacity() > .95
        checks['hover_morphs_to_ball'] = True
        save('ball')
        leave()
        transition('normal-leave')
    elif stage == 'normal-leave' and elapsed > .3:
        assert ball.shapeProgress < .001
        checks['normal_leave_returns_to_strip'] = True
        enter()
        transition('reverse-midway')
    elif stage == 'reverse-midway' and elapsed > .07:
        assert 0 < ball.shapeProgress < 1
        before = ball.shapeProgress
        leave()
        assert abs(before - ball.shapeProgress) < .02
        enter()
        checks['animation_retargets_without_jumping'] = True
        transition('click-open')
    elif stage == 'click-open' and elapsed > .3:
        click()
        leave()
        transition('page-open')
    elif stage == 'page-open' and elapsed > .7:
        assert panel.isVisible() and ball.shapeProgress > .99 and ball.windowOpacity() > .95
        checks['click_opens_page_and_keeps_ball'] = True
        bridge.collapse()
        transition('wait-for-hide')
    elif stage == 'wait-for-hide' and not panel.isVisible():
        transition('close-grace')
    elif stage == 'close-grace' and elapsed > .55:
        assert ball.shapeProgress > .99
        checks['ball_retained_during_one_second_grace'] = True
        transition('grace-end')
    elif stage == 'grace-end' and elapsed > .75:
        assert ball.shapeProgress < .001
        checks['strip_after_close_when_not_hovered'] = True
        enter()
        click()
        transition('reopen')
    elif stage == 'reopen' and elapsed > .3:
        leave()
        panel.collapse()
        transition('hover-on-return')
    elif stage == 'hover-on-return' and not panel.isVisible():
        enter()
        transition('held-after-close')
    elif stage == 'held-after-close' and elapsed > 1.4:
        assert ball.shapeProgress > .99
        checks['hover_cancels_pending_compaction'] = True
        leave()
        transition('left-after-hold')
    elif stage == 'left-after-hold' and elapsed > .3:
        assert ball.shapeProgress < .001
        checks['leaving_after_grace_compacts'] = True
        screen = QGuiApplication.primaryScreen().availableGeometry()
        ball.move(screen.left() + 120, screen.center().y() - 42)
        enter()
        ball.press_position = QPoint(0, 0)
        ball.dragged = True
        local = QPointF(34, 42)
        global_point = QPointF(ball.mapToGlobal(QPoint(34, 42)))
        QApplication.sendEvent(ball, QMouseEvent(QEvent.Type.MouseButtonRelease, local, global_point, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        leave()
        transition('left-edge')
    elif stage == 'left-edge' and elapsed > .3:
        assert ball.edge == 'left' and ball.x() == QGuiApplication.primaryScreen().availableGeometry().left()
        assert ball.shapeProgress < .001
        bounds, _ = ball._shape()
        assert bounds.left() == 0
        checks['drag_snap_preserves_left_strip'] = True
        save('strip-left')
        ball.menu_open = True
        enter()
        leave()
        transition('menu-held')
    elif stage == 'menu-held' and elapsed > .3:
        assert ball.shapeProgress > .99
        checks['context_menu_keeps_ball'] = True
        ball.menu_open = False
        ball._try_compact()
        transition('menu-closed')
    elif stage == 'menu-closed' and elapsed > .3:
        assert ball.shapeProgress < .001
        bridge.openConfig()
        transition('settings-open')
    elif stage == 'settings-open' and elapsed > .4:
        assert panel.isVisible() and ball.shapeProgress > .99
        checks['settings_page_keeps_ball'] = True
        finish()

def safe_tick():
    global failure
    try:
        tick()
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        finish()

timer = QTimer()
timer.timeout.connect(safe_tick)
timer.start(20)
sys.exit(app.exec())
