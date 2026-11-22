"""Launch the source-workspace local Studio, with an explicit cloud alternative."""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from PyQt5.QtCore import QUrl
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QDesktopServices
from echo.backend import paths


def open_studio(parent=None,topic=''):
    root=Path(paths.PROJECT_ROOT)
    script=root/'scripts'/'studio_local.py'
    if not paths.is_frozen() and script.is_file():
        previous=getattr(parent,'_studio_local_process',None)
        if previous and previous.poll() is None:
            from echo.widgets import dialogs
            dialogs.info(parent,'本机 Studio','Studio 正在启动或已运行。请查看已打开的本机网页；启动日志在项目 logs/studio-local-launch.log。')
            return previous
        python=root/'.venv'/'Scripts'/'python.exe'
        if not python.is_file():python=Path(sys.executable)
        logs=root/'logs';logs.mkdir(exist_ok=True)
        command=[str(python),str(script)]
        if topic.strip():command+=['--topic',topic.strip()[:160]]
        with (logs/'studio-local-launch.log').open('ab') as log:
            process=subprocess.Popen(command,cwd=str(root),stdout=log,stderr=log,
              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if parent is not None:parent._studio_local_process=process
        if parent is not None:
            timer=QTimer(parent);timer.setInterval(1000)
            def check():
                code=process.poll()
                if code is None:return
                timer.stop()
                if code:
                    from echo.widgets import dialogs
                    dialogs.info(parent,'本机 Studio 未启动','请先启动 Docker Desktop，再重试。详细原因见项目 logs/studio-local-launch.log。')
            timer.timeout.connect(check);timer.start();parent._studio_local_watch=timer
        return process
    from echo.widgets import dialogs
    dialogs.info(parent,'AI 课堂 · Studio','当前安装版通过浏览器使用云端 Studio。本机隔离版请在项目中运行 Studio-Local.cmd。')
    url='https://echo.xhbtroy.cn/studio.html'
    if topic.strip():url+='?'+urlencode({'topic':topic.strip()[:160]})
    QDesktopServices.openUrl(QUrl(url))
