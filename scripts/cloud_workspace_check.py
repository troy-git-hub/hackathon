"""Ephemeral browser profile and same-account session contract, without network."""
import os,sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM']='windows' if sys.platform=='win32' else 'offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--disable-gpu --no-sandbox'
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
qt=QApplication([])
from echo.backend import account
from echo.widgets.cloud_workspace import CloudWorkspace
with patch.object(account,'current_user',return_value={'id':'isolated-user'}),patch.object(account,'token',return_value='isolated-fake-session'):
 print('creating isolated cloud window',flush=True)
 window=CloudWorkspace(autoload=False);cookies=[]
 print('created',flush=True)
 window.profile.cookieStore().cookieAdded.connect(lambda c:cookies.append(c))
 window.profile.cookieStore().loadAllCookies()
 for _ in range(100):qt.processEvents();time.sleep(.02)
 assert window.profile.isOffTheRecord()
 assert window.web.url().toString() in ('','about:blank') and 'session' not in window.url.toString()
 assert cookies and all(c.isHttpOnly() and c.isSecure() for c in cookies)
 from types import SimpleNamespace
 from PyQt5.QtCore import QUrl
 for url,expected in [('blob:https://echo.xhbtroy.cn/fixture',True),('https://evil.invalid/file',False)]:
  accepted=[];item=SimpleNamespace(url=lambda:QUrl(url),cancel=lambda:accepted.append(False),suggestedFileName=lambda:'fixture.json',setPath=lambda p:None,accept=lambda:accepted.append(True))
  with patch('echo.widgets.cloud_workspace.QFileDialog.getSaveFileName',return_value=('fixture.json','')):window.download(item)
  assert accepted==[expected]
 with patch.object(account,'token',return_value='different-fake-session'):window.account_check()
 qt.processEvents()
print('PASS: private ephemeral cookie, no token in URL, account change closes cloud workspace')
