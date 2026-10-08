import argparse
import logging
import sys

from app.config import ROOT, ASSET_ROOT


def main():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PromptTransAgentAssistant.Desktop')
    parser = argparse.ArgumentParser(description='Local and API prompt translation assistant')
    parser.add_argument('--expanded', action='store_true', help='Open the conversation panel immediately')
    parser.add_argument('--self-test', action='store_true', help='Run a runtime check and exit')
    args = parser.parse_args()
    (ROOT / 'logs').mkdir(exist_ok=True)
    diagnostic = None
    if args.self_test:
        import faulthandler
        diagnostic = (ROOT / 'logs' / 'smoke-threads.log').open('w', encoding='utf-8')
        faulthandler.enable(file=diagnostic)
        faulthandler.dump_traceback_later(45, repeat=True, file=diagnostic)
    logging.basicConfig(filename=ROOT / 'logs' / 'app.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s', encoding='utf-8')
    from PySide6.QtCore import QLockFile
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    application = QApplication(sys.argv[:1])
    application.setApplicationName('PromptTransAgentAssistant')
    application.setWindowIcon(QIcon(str(ASSET_ROOT / 'frontend' / 'branding' / 'app.ico')))
    application.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT / 'logs' / 'application.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, 'Prompt assistant', '应用已经运行。请点击屏幕边缘的 P 悬浮球。')
        return 0
    from app.desktop import Bridge, Panel, FloatingBall
    try:
        bridge = Bridge()
    except Exception as exc:
        logging.exception('Invalid startup configuration')
        QMessageBox.critical(None, '配置错误', f'{exc}\n\n请检查 {ROOT / "config.toml"}')
        return 1
    panel = Panel(bridge, bridge.controller.config['ui'])
    ball = FloatingBall(panel, bridge, bridge.controller.config['ui'])
    # quit() asks visible windows to accept Close, which the floating UI ignores.
    # Explicit menu Exit must terminate the event loop and run aboutToQuit cleanup.
    bridge.exitRequested.connect(lambda: application.exit(0))

    def cleanup():
        try:
            bridge.controller.shutdown()
        except Exception:
            logging.exception('Shutdown cleanup failed')
        ball.hide()
        panel.hide()

    application.aboutToQuit.connect(cleanup)
    ball.show()
    if args.expanded:
        ball.toggle_panel()
    if bridge.controller.config['model']['auto_load'] and not bridge.controller.startup_error:
        QTimer.singleShot(0, bridge.controller.load)
    smoke = None
    if args.self_test:
        from app.smoke import SmokeCheck
        smoke = SmokeCheck(application, bridge, panel, ball)
    result = application.exec()
    lock.unlock()
    if diagnostic:
        faulthandler.cancel_dump_traceback_later()
        diagnostic.close()
    return smoke.save() if smoke else result


if __name__ == '__main__':
    raise SystemExit(main())
