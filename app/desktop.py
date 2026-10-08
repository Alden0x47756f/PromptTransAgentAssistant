import json
import logging
import os
import subprocess
import time
import math
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Qt, QUrl, QPoint, QRectF, QPropertyAnimation, QEasingCurve, Property, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QGuiApplication, QCursor, QPainterPath, QRegion
from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication, QMenu, QFileDialog
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from .config import ROOT, ASSET_ROOT
from .controller import Controller

log = logging.getLogger(__name__)


class Bridge(QObject):
    event = Signal(str)
    collapseRequested = Signal()
    exitRequested = Signal()
    moveRequested = Signal()
    settingsRequested = Signal()

    def __init__(self, config_path=None, secrets_path=None):
        super().__init__()
        self.controller = Controller(lambda data: self.event.emit(json.dumps(data, ensure_ascii=False)), config_path, secrets_path)

    @Slot()
    def initialize(self):
        self.controller.notify_state()
        if self.controller.startup_error:
            self.event.emit(json.dumps({'type': 'settings_error', 'message': self.controller.startup_error['summary'],
                                        'diagnostic': self.controller.startup_error}, ensure_ascii=False))

    @Slot()
    def loadModel(self):
        self.controller.load()

    @Slot()
    def unloadModel(self):
        self.controller.unload()

    @Slot(str)
    def send(self, text):
        self.controller.send(text)

    @Slot()
    def stop(self):
        self.controller.stop()

    @Slot()
    def newConversation(self):
        self.controller.new_conversation()

    @Slot(str)
    def copyText(self, text):
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        if clipboard.text() != text:
            self.controller.failure(RuntimeError('当前 Windows 会话无法写入剪贴板。请检查会话权限或剪贴板占用，也可手动选择文本复制。'), '复制文本', 'settings_error')
            return
        self.controller.event('copied')

    @Slot()
    def openConfig(self):
        self.controller.show_settings()
        self.settingsRequested.emit()

    @Slot(str)
    def saveSettings(self, raw):
        try:
            if len(raw) > 50000:
                raise ValueError('设置数据过大，请检查输入。')
            self.controller.save_settings(json.loads(raw))
        except Exception as exc:
            self.controller.failure(exc, '读取设置表单', 'settings_error')

    @Slot(str)
    def probeApi(self, raw):
        try:
            if len(raw) > 50000:
                raise ValueError('设置数据过大，请检查输入。')
            self.controller.probe_api(json.loads(raw))
        except Exception as exc:
            self.controller.failure(exc, '读取 API 设置', 'settings_error')

    @Slot(str, result=str)
    def keyStatus(self, raw):
        try:
            value = json.loads(raw)
            return json.dumps({'saved': self.controller.settings.key_status(value['protocol'], value['base_url'])})
        except Exception as exc:
            return json.dumps({'saved': False, 'error': str(exc)})

    @Slot(str)
    def clearKey(self, raw):
        try:
            if self.controller.busy or self.controller.saving or self.controller.state in ('loading', 'unloading'):
                raise ValueError('请停止当前生成或等待模型操作完成后再清除密钥。')
            value = json.loads(raw)
            from .config import normalize_url
            url = normalize_url(value['base_url'])
            if value['protocol'] not in ('openai', 'anthropic'):
                raise ValueError('API 协议无效。')
            self.controller.secret_store.clear(value['protocol'], url)
            api = self.controller.config['api']
            if self.controller.config['connection']['mode'] == 'api' and api['protocol'] == value['protocol'] and api['base_url'] == url:
                self.controller.unload()
            self.event.emit(json.dumps({'type': 'key_cleared'}))
        except Exception as exc:
            self.controller.failure(exc, '清除已保存密钥', 'settings_error')

    @Slot(str)
    def browseFile(self, kind):
        if kind not in ('model', 'engine'):
            return
        extension = 'GGUF 模型 (*.gguf)' if kind == 'model' else 'llama 引擎 (*.exe)'
        path, _ = QFileDialog.getOpenFileName(QApplication.activeWindow(), '选择模型文件' if kind == 'model' else '选择 llama-server.exe', '', extension)
        if path:
            self.event.emit(json.dumps({'type': 'file_selected', 'field': 'model_path' if kind == 'model' else 'engine_path', 'path': path}, ensure_ascii=False))

    @Slot()
    def openLogs(self):
        try:
            (ROOT / 'logs').mkdir(exist_ok=True)
            os.startfile(str(ROOT / 'logs'))
        except Exception as exc:
            self.controller.failure(exc, '打开日志目录', 'settings_error')

    @Slot()
    def collapse(self):
        self.collapseRequested.emit()

    @Slot(str)
    def openPrompt(self, kind):
        if kind not in ('system', 'user'):
            return
        file_key = 'system_prompt_file' if kind == 'system' else 'user_prompt_file'
        from .config import raw_config
        try:
            path = Path(raw_config(self.controller.config_path)['prompts'][file_key])
            if not path.is_absolute():
                path = self.controller.config_path.parent / path
            try:
                os.startfile(str(path))
            except OSError:
                subprocess.Popen(['notepad.exe', str(path)])
        except Exception as exc:
            self.event.emit(json.dumps({'type': 'error', 'message': f'无法打开提示词：{exc}'}, ensure_ascii=False))

    @Slot()
    def exit(self):
        self.exitRequested.emit()

    @Slot()
    def beginDrag(self):
        self.moveRequested.emit()


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() in ('file', 'qrc', 'about'):
            return True
        return False

    def javaScriptConsoleMessage(self, level, message, line, source):
        log.info('Frontend %s:%s %s', source, line, message)


class Panel(QWidget):
    visibilityChanged = Signal(bool)

    def __init__(self, bridge, cfg):
        super().__init__()
        self.setWindowTitle('PromptTransAgentAssistant')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(cfg['panel_width'], cfg['panel_height'])
        self.duration = cfg['animation_ms']
        self.view = QWebEngineView(self)
        page = LocalPage(self.view)
        self.view.setPage(page)
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.channel = QWebChannel(page)
        self.channel.registerObject('backend', bridge)
        page.setWebChannel(self.channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.view.load(QUrl.fromLocalFile(str(ASSET_ROOT / 'frontend' / 'index.html')))
        self.animation = QPropertyAnimation(self, b'windowOpacity', self)
        self.animation.setDuration(self.duration)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._after_animation)
        self.collapsing = False
        self.bridge = bridge
        bridge.collapseRequested.connect(self.collapse)
        bridge.moveRequested.connect(self.begin_drag)

    def reveal(self):
        self.collapsing = False
        self.animation.stop()
        self.setWindowOpacity(0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        self.view.setFocus()

    def collapse(self):
        if not self.isVisible():
            return
        self.animation.stop()
        self.collapsing = True
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0.0)
        self.animation.start()

    def _after_animation(self):
        if self.collapsing:
            self.hide()

    def begin_drag(self):
        if self.windowHandle():
            self.windowHandle().startSystemMove()

    def closeEvent(self, event):
        event.ignore()
        self.collapse()

    def showEvent(self, event):
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibilityChanged.emit(False)


class FloatingBall(QWidget):
    def __init__(self, panel, bridge, cfg):
        super().__init__()
        self.panel, self.bridge, self.cfg = panel, bridge, cfg
        self.logo = QPixmap(str(ASSET_ROOT / 'frontend' / 'branding' / 'logo.png'))
        self.setWindowTitle('Prompt assistant · 右键退出')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(68, 84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('点击展开 · 拖动贴边 · 右键菜单')
        self.status = 'unloaded'
        self.press_position = None
        self.dragged = False
        self.edge = cfg['edge']
        self.hovered = False
        self.menu_open = False
        self._shape_progress = 0.0
        self._shape_target = 0.0
        self._close_grace_until = 0.0
        self.compact_timer = QTimer(self)
        self.compact_timer.setSingleShot(True)
        self.compact_timer.timeout.connect(self._try_compact)
        self.shape_animation = QPropertyAnimation(self, b'shapeProgress', self)
        self.shape_animation.setDuration(cfg['animation_ms'])
        self.shape_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation = QPropertyAnimation(self, b'windowOpacity', self)
        self.animation.setDuration(cfg['animation_ms'])
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setWindowOpacity(cfg['resting_opacity'])
        self.bridge.event.connect(self.handle_event)
        self.bridge.settingsRequested.connect(self.reveal_settings)
        self.panel.visibilityChanged.connect(self._panel_visibility)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() + 1 if cfg['edge'] == 'right' else screen.left()
        self.move(x, screen.top() + (screen.height() - self.height()) // 2)
        self._update_hit_region()
        if self.panel.isVisible():
            self._set_expanded(True)

    def _get_shape_progress(self):
        return self._shape_progress

    def _set_shape_progress(self, value):
        self._shape_progress = max(0.0, min(1.0, value))
        self._update_hit_region()
        self.update()

    shapeProgress = Property(float, _get_shape_progress, _set_shape_progress)

    def _shape(self):
        bar = QRectF(58 if self.edge == 'right' else 0, 6, 10, 72)
        circle = QRectF(7, 15, 54, 54)
        progress = self._shape_progress
        bounds = QRectF(*(start + (end - start) * progress for start, end in zip(
            (bar.x(), bar.y(), bar.width(), bar.height()),
            (circle.x(), circle.y(), circle.width(), circle.height()))))
        return bounds, 5 + 22 * progress

    def _update_hit_region(self):
        if self._shape_target > 0 or self._shape_progress > .001:
            # Retain the hover region during a morph so a stationary edge cursor
            # cannot repeatedly enter/leave as the painted circle moves inward.
            self.setMask(QRegion(self.rect()))
        else:
            bounds, radius = self._shape()
            path = QPainterPath()
            path.addRoundedRect(bounds, radius, radius)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _cursor_inside(self):
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _held_open(self):
        return self.panel.isVisible() or self.hovered or self._cursor_inside() or self.press_position is not None or self.menu_open

    def _set_expanded(self, expanded):
        target = 1.0 if expanded else 0.0
        if expanded:
            self.compact_timer.stop()
        if self._shape_target != target:
            self.shape_animation.stop()
            self._shape_target = target
            self._update_hit_region()
            self.shape_animation.setStartValue(self._shape_progress)
            self.shape_animation.setEndValue(target)
            self.shape_animation.start()
        self.fade(1.0 if expanded else self.cfg['resting_opacity'])

    def _try_compact(self):
        if self._held_open():
            return
        remaining = math.ceil((self._close_grace_until - time.monotonic()) * 1000)
        if remaining > 0:
            self.compact_timer.start(remaining)
        else:
            self._set_expanded(False)

    @Slot(bool)
    def _panel_visibility(self, visible):
        if visible:
            self._set_expanded(True)
        else:
            self._close_grace_until = time.monotonic() + 1.0
            self.compact_timer.start(1000)

    @Slot(str)
    def handle_event(self, raw):
        event = json.loads(raw)
        if event['type'] == 'state':
            self.status = event['state']
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor('#ffffff'))
        painter.setPen(QPen(QColor('#e0e0e0'), 1))
        bounds, radius = self._shape()
        painter.drawRoundedRect(bounds, radius, radius)
        progress = self._shape_progress
        painter.save()
        path = QPainterPath()
        path.addRoundedRect(bounds, radius, radius)
        painter.setClipPath(path)
        painter.setOpacity(progress * progress)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(12, 20, 44, 44), self.logo, QRectF(self.logo.rect()))
        painter.restore()
        painter.setOpacity(progress * progress)
        painter.setBrush(QColor('#0066cc') if self.status == 'ready' else QColor('#7a7a7a'))
        painter.setPen(QPen(QColor('#ffffff'), 2))
        painter.drawEllipse(47, 55, 9, 9)

    def fade(self, target):
        self.animation.stop()
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(target)
        self.animation.start()

    def enterEvent(self, event):
        self.hovered = True
        self._set_expanded(True)

    def leaveEvent(self, event):
        self.hovered = False
        self._try_compact()

    def toggle_panel(self):
        if self.panel.isVisible() and not self.panel.collapsing:
            self.panel.collapse()
            return
        self.position_panel()
        self._set_expanded(True)
        self.panel.reveal()

    def reveal_settings(self):
        self.position_panel()
        self._set_expanded(True)
        if not self.panel.isVisible() or self.panel.collapsing:
            self.panel.reveal()

    def position_panel(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        rect = screen.availableGeometry()
        self.panel.resize(min(self.cfg['panel_width'], rect.width() - 80),
                          min(self.cfg['panel_height'], rect.height() - 20))
        is_right = self.x() > rect.center().x()
        x = self.x() - self.panel.width() if is_right else self.x() + self.width()
        y = self.y() + self.height() // 2 - self.panel.height() // 2
        self.panel.move(max(rect.left(), min(x, rect.right() - self.panel.width() + 1)),
                        max(rect.top(), min(y, rect.bottom() - self.panel.height() + 1)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_position = event.globalPosition().toPoint()
            self.offset = self.press_position - self.pos()
            self.dragged = False
            self._set_expanded(True)

    def mouseMoveEvent(self, event):
        if self.press_position and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if (current - self.press_position).manhattanLength() > 5:
                self.dragged = True
            if self.dragged:
                self.move(current - self.offset)
                if self.panel.isVisible():
                    self.position_panel()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.press_position is None:
            return
        self.press_position = None
        if self.dragged:
            screen = QGuiApplication.screenAt(event.globalPosition().toPoint()) or QGuiApplication.primaryScreen()
            rect = screen.availableGeometry()
            x = rect.right() - self.width() + 1 if self.geometry().center().x() > rect.center().x() else rect.left()
            self.edge = 'right' if self.geometry().center().x() > rect.center().x() else 'left'
            self.move(x, max(rect.top(), min(self.y(), rect.bottom() - self.height() + 1)))
            self._update_hit_region()
            if self.panel.isVisible():
                self.position_panel()
            self._try_compact()
        else:
            self.toggle_panel()

    def contextMenuEvent(self, event):
        self.menu_open = True
        self._set_expanded(True)
        menu = QMenu(self)
        api_mode = self.bridge.controller.config['connection']['mode'] == 'api'
        menu.addAction('展开 / 收起', self.toggle_panel)
        if self.status in ('ready', 'error'):
            menu.addAction('停用 API' if api_mode else '卸载模型', self.bridge.unloadModel)
        elif self.status == 'unloaded':
            menu.addAction('启用 API' if api_mode else '加载模型', self.bridge.loadModel)
        menu.addAction('编辑配置', self.bridge.openConfig)
        menu.addAction('编辑 System Prompt', lambda: self.bridge.openPrompt('system'))
        menu.addAction('编辑 User Prompt', lambda: self.bridge.openPrompt('user'))
        menu.addSeparator()
        menu.addAction('退出并卸载模型', self.bridge.exit)
        try:
            menu.exec(event.globalPos())
        finally:
            self.menu_open = False
            self._try_compact()

    def closeEvent(self, event):
        event.ignore()
        self.panel.collapse()
