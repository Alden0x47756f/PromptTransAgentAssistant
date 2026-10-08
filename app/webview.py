"""WebEngine components loaded only when the conversation panel is first used."""
import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from .config import ASSET_ROOT

log = logging.getLogger(__name__)


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        return url.scheme() in ('file', 'qrc', 'about')

    def javaScriptConsoleMessage(self, level, message, line, source):
        log.info('Frontend %s:%s %s', source, line, message)


def create_view(parent, bridge):
    view = QWebEngineView(parent)
    page = LocalPage(view)
    view.setPage(page)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    channel = QWebChannel(page)
    channel.registerObject('backend', bridge)
    page.setWebChannel(channel)
    view.load(QUrl.fromLocalFile(str(ASSET_ROOT / 'frontend' / 'index.html')))
    return view, channel
