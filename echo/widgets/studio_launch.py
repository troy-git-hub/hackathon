"""Launch the local interactive classroom (studio-live), with a cloud fallback."""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from echo.backend import paths

PORT = 18771
CLOUD = 'https://echo.xhbtroy.cn/studio.html'


def _listening():
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=0.4):
            return True
    except OSError:
        return False


def _ready():
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/health' % PORT, timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def classroom_url(topic=''):
    url = 'http://127.0.0.1:%d/' % PORT
    if topic.strip():
        url += '?' + urlencode({'topic': topic.strip()[:160]})
    return url


def open_studio(parent=None, topic=''):
    """The product always opens the cloud classroom and asks it to start the lesson."""
    topic = (topic or '').strip() or '今天的一课'
    url = CLOUD + '?' + urlencode({'topic': topic[:160], 'autostart': '1'})
    QDesktopServices.openUrl(QUrl(url))
    return None


def open_local_studio(parent=None, topic=''):
    """Explicit source-only debugging, never the default classroom entry."""
    root = Path(paths.PROJECT_ROOT)
    script = root / 'studio-live' / 'server.py'
    if paths.is_frozen() or not script.is_file():
        url = CLOUD
        if topic.strip():
            url += '?' + urlencode({'topic': topic.strip()[:160]})
        QDesktopServices.openUrl(QUrl(url))
        return None
    if not _listening():
        python = root / '.venv' / 'Scripts' / 'python.exe'
        if not python.is_file():
            python = Path(sys.executable)
        logs = root / 'logs'
        logs.mkdir(exist_ok=True)
        with (logs / 'studio-live-launch.log').open('ab') as log:
            process = subprocess.Popen(
                [str(python), str(script)], cwd=str(root / 'studio-live'),
                stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                env={**os.environ, 'ECHO_STUDIO_LIVE_PORT': str(PORT)})
        if parent is not None:
            parent._studio_local_process = process
        deadline = time.time() + 8
        while time.time() < deadline and not _ready():
            if process.poll() is not None:
                from echo.widgets import dialogs
                dialogs.info(parent, '本机 AI 课堂未启动',
                             '课堂服务没有起来。详细原因见项目 logs/studio-live-launch.log。')
                return process
            time.sleep(0.2)
    QDesktopServices.openUrl(QUrl(classroom_url(topic)))
    return getattr(parent, '_studio_local_process', None)
