"""Same-account cloud papers inside Echo. Tokens stay in an ephemeral HttpOnly cookie."""
from urllib.parse import urlsplit
from PyQt5.QtCore import Qt,QUrl,QTimer
from PyQt5.QtNetwork import QNetworkCookie
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog
from PyQt5.QtWebEngineWidgets import QWebEngineView,QWebEnginePage,QWebEngineProfile,QWebEngineSettings
from echo.backend import account
from echo.theme import Colors,dialog_qss
from echo.widgets.window_chrome import install_chrome
from echo.widgets import dialogs

_windows=[]

class _Page(QWebEnginePage):
    def acceptNavigationRequest(self,url,kind,is_main):
        if url.scheme()=='https' and url.host()=='echo.xhbtroy.cn':return True
        return url.toString()=='about:blank'
    def javaScriptConfirm(self,origin,message):return dialogs.confirm(self.view(),'清卷',message)
    def javaScriptAlert(self,origin,message):dialogs.info(self.view(),'清卷',message)

class CloudWorkspace(QDialog):
    def __init__(self,parent=None,view='qingjuan',autoload=True):
        super().__init__(parent,Qt.Window)
        self.setWindowTitle('Echo · 清卷云端');self.resize(1120,760);self.setMinimumSize(740,520)
        self.setStyleSheet(dialog_qss());self.setAttribute(Qt.WA_DeleteOnClose)
        self.identity=str((account.current_user() or {}).get('id') or '');self.session=account.token();self._closing=False;self._loaded=False
        self.url=QUrl('https://echo.xhbtroy.cn/user#'+('exams' if view=='exams' else 'qingjuan'))
        root=QVBoxLayout(self);row=QHBoxLayout();self.status=QLabel('清卷与网页共用账户和试卷，计时及作答存储在云端。');self.status.setWordWrap(True);row.addWidget(self.status,1)
        retry=QPushButton('重新加载');retry.clicked.connect(lambda:self.web.load(self.url));row.addWidget(retry);root.addLayout(row)
        self.web=QWebEngineView(self);root.addWidget(self.web,1)
        self.profile=QWebEngineProfile(self);self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.page=_Page(self.profile,self.web);self.web.setPage(self.page)
        self.page.setBackgroundColor(QColor(Colors.WINDOW_BG))
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows,False)
        self.profile.downloadRequested.connect(self.download)
        self.page.printRequested.connect(self.print_pdf)
        self.web.loadFinished.connect(lambda ok:self.status.setText('清卷 · 与网页使用同一份资料和作答进度。' if ok else '云端连接失败，请检查网络后重新加载。'))
        install_chrome(self,root,'Echo · 清卷云端')
        self.check=QTimer(self,interval=2000);self.check.timeout.connect(self.account_check);self.check.start()
        if not self.session or not self.identity:
            self.status.setText('请先登录 Echo，再打开清卷云端。');retry.setEnabled(False);return
        cookie=QNetworkCookie(b'__Host-echo_session',self.session.encode());cookie.setPath('/');cookie.setSecure(True);cookie.setHttpOnly(True)
        def ready(item):
            if autoload and not self._closing and bytes(item.name())==b'__Host-echo_session' and not self._loaded:
                self._loaded=True;self.web.load(self.url)
        self.web.load(QUrl('about:blank'))
        self.profile.cookieStore().cookieAdded.connect(ready)
        self.profile.cookieStore().setCookie(cookie,QUrl('https://echo.xhbtroy.cn/'))
        if autoload:QTimer.singleShot(2000,lambda:self.web.load(self.url) if not self._loaded and not self._closing else None)

    def account_check(self):
        if self.identity!=str((account.current_user() or {}).get('id') or '') or self.session!=account.token():
            self._closing=True;self.web.stop();self.profile.cookieStore().deleteAllCookies();self.close()

    def download(self,item):
        url=item.url().toString()
        if urlsplit(url).hostname!='echo.xhbtroy.cn' and not url.startswith('blob:https://echo.xhbtroy.cn/'):item.cancel();return
        name=item.suggestedFileName() if hasattr(item,'suggestedFileName') else '清卷资料.json'
        path,_=QFileDialog.getSaveFileName(self,'保存清卷资料',name)
        if not path:item.cancel();return
        item.setPath(path);item.accept()

    def print_pdf(self):
        path,_=QFileDialog.getSaveFileName(self,'保存清卷 PDF','清卷试卷.pdf','PDF (*.pdf)')
        if path:self.page.printToPdf(path if path.lower().endswith('.pdf') else path+'.pdf')

    def closeEvent(self,event):
        if not self._closing and self._loaded:
            event.ignore()
            def decide(dirty):
                if not dirty or dialogs.confirm(self,'关闭清卷','仍有未保存内容或AI请求在处理。关闭后考试计时继续，确定关闭？'):
                    self._closing=True;self.close()
            self.page.runJavaScript('Boolean(window.echoStudyHasUnsaved && window.echoStudyHasUnsaved())',decide)
            return
        self.check.stop();self.web.stop();self.profile.cookieStore().deleteAllCookies();event.accept();super().closeEvent(event)

def open_cloud_workspace(parent=None,view='qingjuan'):
    window=CloudWorkspace(parent,view);_windows.append(window)
    window.destroyed.connect(lambda:_windows.remove(window) if window in _windows else None)
    window.show();return window
