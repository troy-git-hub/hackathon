"""Non-blocking, invite-only account login and account overview."""
import threading
import os
from PyQt5.QtCore import Qt,QTimer,QObject,pyqtSignal,QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QLabel,QPushButton,QCheckBox,QHBoxLayout,QScrollArea,QWidget,QApplication,QFrame
from echo.backend import account,cloud_sync
from echo.theme import Colors,dialog_qss,apply_native_titlebar

class _Result(QObject):
    done=pyqtSignal(str,object,str)

class _AccountTitleBar(QWidget):
    def __init__(self,dialog):
        super().__init__(dialog);self.dialog=dialog;self.offset=None;self.setFixedHeight(42)
        row=QHBoxLayout(self);row.setContentsMargins(18,6,10,4)
        title=QLabel('Echo · 登录');row.addWidget(title);row.addStretch(1)
        close=QPushButton('×');close.setFixedSize(28,28);close.setStyleSheet('min-width:0;padding:0;border:none;font-size:20px;');close.clicked.connect(dialog.reject);row.addWidget(close)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.offset=event.globalPos()-self.dialog.frameGeometry().topLeft();event.accept()
    def mouseMoveEvent(self,event):
        if self.offset is not None and event.buttons()&Qt.LeftButton:self.dialog.move(event.globalPos()-self.offset);event.accept()
    def mouseReleaseEvent(self,event):self.offset=None

class AccountLogin(QDialog):
    def __init__(self,parent=None,restore=False,allow_skip=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog|Qt.FramelessWindowHint)
        self.setObjectName('EchoAccountLogin')
        self.setWindowTitle('Echo · 登录')
        self.setMinimumWidth(440)
        self.setStyleSheet(dialog_qss()+f'''
            QDialog#EchoAccountLogin {{ border:1px solid {Colors.BORDER}; border-radius:10px; }}
            QScrollArea#EchoAccountScroll,
            QWidget#EchoAccountViewport,
            QWidget#EchoAccountContent {{ background:{Colors.WINDOW_BG}; color:{Colors.TEXT_PRIMARY}; }}
        ''')
        apply_native_titlebar(self)
        self.result_bus=_Result(self)
        self.result_bus.done.connect(self._finished)
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0);outer.addWidget(_AccountTitleBar(self))
        scroll=QScrollArea(self);scroll.setObjectName('EchoAccountScroll');scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setObjectName('EchoAccountViewport');scroll.viewport().setAttribute(Qt.WA_StyledBackground,True)
        content=QWidget();content.setObjectName('EchoAccountContent');content.setAttribute(Qt.WA_StyledBackground,True)
        scroll.setWidget(content);outer.addWidget(scroll)
        self.scroll=scroll;self.content=content
        root=QVBoxLayout(content)
        root.setContentsMargins(28,25,28,25)
        root.setSpacing(12);root.setAlignment(Qt.AlignTop)
        title=QLabel('欢迎回来，继续听懂。')
        title.setStyleSheet(f'font-size:23px;font-weight:600;color:{Colors.ACCENT};')
        root.addWidget(title)
        root.addWidget(QLabel('使用 Echo 账户登录。新账户须持有邀请码。'))
        form=QFormLayout()
        self.email=QLineEdit();self.email.setPlaceholderText('you@example.com')
        self.code=QLineEdit();self.code.setMaxLength(6);self.code.setPlaceholderText('6 位验证码')
        self.invite=QLineEdit();self.invite.setPlaceholderText('ECHO-…（注册时填写）')
        self.name=QLineEdit();self.name.setPlaceholderText('你的昵称')
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password)
        self.confirm_password=QLineEdit();self.confirm_password.setEchoMode(QLineEdit.Password)
        form.addRow('邮箱',self.email)
        self.register=QCheckBox('持邀请码注册新账户')
        form.addRow('',self.register)
        self.password_login=QCheckBox('使用密码登录（取消勾选可用邮箱验证码）')
        self.password_login.setChecked(True)
        form.addRow('',self.password_login)
        form.addRow('昵称',self.name)
        form.addRow('邀请码',self.invite)
        form.addRow('验证码',self.code)
        form.addRow('密码',self.password)
        form.addRow('确认密码',self.confirm_password)
        root.addLayout(form)
        self.form=form
        self.register.toggled.connect(self._mode)
        self.password_login.toggled.connect(self._mode)
        row=QHBoxLayout()
        self.send=QPushButton('获取验证码');self.send.clicked.connect(self._send)
        self.submit=QPushButton('登录 Echo');self.submit.clicked.connect(self._login)
        row.addWidget(self.send);row.addWidget(self.submit);root.addLayout(row)
        self.notice=QLabel('内测免费发信模式：收件邮箱须先完成 Cloudflare 验证，请联系管理员。')
        self.notice.setTextFormat(Qt.PlainText);self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        self.cloud_enabled=QCheckBox('登录后自动同步学习档案和复习进度（推荐）')
        self.cloud_enabled.setChecked(cloud_sync.status()['enabled'])
        root.addWidget(self.cloud_enabled)
        cloud_notice=QLabel('同步包含个人资料、知识掌握和复习记录，可在用户中心暂停。不包含 API 密钥、录音、截图或原始课件。')
        cloud_notice.setWordWrap(True);cloud_notice.setStyleSheet(f'font-size:11px;color:{Colors.TEXT_SECONDARY};')
        root.addWidget(cloud_notice)
        link=QPushButton('打开网页用户中心 ↗')
        link.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(account.USER_CENTER)))
        root.addWidget(link)
        self.skipped=False
        self.skip=QPushButton('暂时跳过 · 仅使用自己的 API（不推荐）')
        self.skip.setVisible(allow_skip);self.skip.clicked.connect(self._skip)
        root.addWidget(self.skip)
        self.cooldown=0
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self._tick)
        self._mode()
        screen=QApplication.primaryScreen()
        if screen:
            available=max(360,screen.availableGeometry().height()-80)
            self.setMaximumHeight(available);self.resize(490,min(720,available))
        if restore:QTimer.singleShot(0,lambda:self._work('restore',account.restore))
    def _mode(self):
        reg=self.register.isChecked();password=self.password_login.isChecked() or reg
        for widget,visible in ((self.name,reg),(self.invite,reg),(self.code,reg or not password),(self.password,password),(self.confirm_password,reg)):
            widget.setVisible(visible)
            self.form.labelForField(widget).setVisible(visible)
        self.password_login.setVisible(not reg)
        self.send.setVisible(reg or not password)
        self.submit.setText('注册并登录' if reg else '登录 Echo')
    def _work(self,kind,callback):
        self.submit.setEnabled(False);self.send.setEnabled(False)
        self.skip.setEnabled(False)
        self.notice.setText('正在连接 Echo…')
        bus=self.result_bus
        def run():
            try:value=callback();error=''
            except Exception as e:value=None;error=str(e)
            try:bus.done.emit(kind,value,error)
            except RuntimeError:pass
        threading.Thread(target=run,daemon=True,name='echo-account').start()
    def _send(self):
        email=self.email.text().strip();invite=self.invite.text().strip() if self.register.isChecked() else ''
        if '@' not in email or (self.register.isChecked() and not invite):
            self.notice.setText('请填写邮箱；注册时还需要邀请码。');return
        self._work('code',lambda:account.send_code(email,invite))
    def _login(self):
        email=self.email.text().strip();code=self.code.text().strip();password=self.password.text() if self.password_login.isChecked() or self.register.isChecked() else ''
        invite=self.invite.text().strip() if self.register.isChecked() else '';name=self.name.text().strip()
        if self.register.isChecked() and (not 12<=len(password)<=128 or password!=self.confirm_password.text()):
            self.notice.setText('注册需设置 12 至 128 位密码，并保证两次输入一致。');return
        self._work('login',lambda:account.login(email,code,password,invite,name))
    def _finished(self,kind,value,error):
        self.submit.setEnabled(True);self.send.setEnabled(self.cooldown==0)
        self.skip.setEnabled(True)
        if error:self.notice.setText(error);return
        if kind=='code':
            self.cooldown=60;self.timer.start();self._tick();self.notice.setText(value.get('message','验证码已发送。'));return
        if value:
            try:cloud_sync.configure(enabled=self.cloud_enabled.isChecked())
            except account.AccountError as exc:self.notice.setText(str(exc));return
            os.environ['ECHO_ACCOUNT_GUEST']='0'
            self.password.clear();self.confirm_password.clear();self.accept()
        else:self.notice.setText('请登录 Echo 账户。')
    def _skip(self):
        self.skipped=True
        os.environ['ECHO_ACCOUNT_GUEST']='1';os.environ['ECHO_ACCOUNT_ACTIVE']='0';os.environ['ECHO_ACCOUNT_CUSTOM_API']='1'
        self.accept()
    def _tick(self):
        self.cooldown=max(0,self.cooldown-1)
        self.send.setText(f'{self.cooldown} 秒后重试' if self.cooldown else '获取验证码')
        if not self.cooldown:self.timer.stop();self.send.setEnabled(True)

def ensure_account(parent=None,allow_skip=False):
    os.environ['ECHO_ACCOUNT_ACTIVE']='1'
    if account.current_user():return True
    return AccountLogin(parent,restore=True,allow_skip=allow_skip).exec_()==QDialog.Accepted

def show_account_center(parent=None):
    if not ensure_account(parent):return
    dialog=QDialog(parent);dialog.setWindowTitle('Echo · 用户中心');dialog.setMinimumWidth(400);dialog.setStyleSheet(dialog_qss())
    root=QVBoxLayout(dialog)
    user=account.current_user()
    title=QLabel(f"{user['name']}\n{user['email']}\n\n账户余额：{user['balance']} 学习点")
    title.setTextFormat(Qt.PlainText);title.setWordWrap(True);root.addWidget(title)
    root.addWidget(QLabel('课堂在本机，复习在云端。当前不提供充值。'))
    sync_status=QLabel();sync_status.setTextFormat(Qt.PlainText);sync_status.setWordWrap(True);root.addWidget(sync_status)
    enabled=QCheckBox('这台设备自动同步学习档案（推荐）');enabled.setChecked(cloud_sync.status()['enabled']);root.addWidget(enabled)
    sync_button=QPushButton('立即同步学习数据');root.addWidget(sync_button)
    bind_button=QPushButton('将本机学习资料关联到当前账户');root.addWidget(bind_button)
    def update_status():
        info=cloud_sync.status();sync_status.setText(info['message'])
        bound=info.get('bound_account');bind_button.setVisible(bool(bound and bound!=account.current_user()['id']) if account.current_user() else False)
    def toggle(value):
        try:cloud_sync.configure(enabled=value);update_status()
        except Exception as exc:sync_status.setText(str(exc))
    enabled.toggled.connect(toggle)
    def rebind():
        from echo.widgets import dialogs
        if dialogs.confirm(dialog,'确认本机资料归属','本机资料关联了另一个账户。继续会把这份本机学习资料同步到当前登录的账户，不会删除原账户的云端副本。确认这份资料属于你并继续？',ok_text='确认关联'):
            cloud_sync.configure(bind=True);update_status()
    bind_button.clicked.connect(rebind)
    refresh_button=QPushButton('刷新账户余额');root.addWidget(refresh_button)
    status=QLabel('');status.setTextFormat(Qt.PlainText);status.setWordWrap(True);root.addWidget(status)
    result_bus=_Result(dialog)
    def finished(kind,value,error):
        refresh_button.setEnabled(True)
        sync_button.setEnabled(True)
        if error:status.setText(error);return
        if kind=='sync':update_status();status.setText(value['message']);return
        title.setText(f"{value['name']}\n{value['email']}\n\n账户余额：{value['balance']} 学习点")
        status.setText('账户信息已刷新。')
    result_bus.done.connect(finished)
    def refresh():
        refresh_button.setEnabled(False)
        def run():
            try:value=account.refresh();error=''
            except Exception as exc:value=None;error=str(exc)
            try:result_bus.done.emit('refresh',value,error)
            except RuntimeError:pass
        threading.Thread(target=run,daemon=True,name='echo-account-refresh').start()
    refresh_button.clicked.connect(refresh)
    def sync():
        sync_button.setEnabled(False);status.setText('正在同步…')
        def run():
            value=cloud_sync.sync_once()
            try:result_bus.done.emit('sync',value,'')
            except RuntimeError:pass
        threading.Thread(target=run,daemon=True,name='echo-manual-sync').start()
    sync_button.clicked.connect(sync)
    status_timer=QTimer(dialog);status_timer.setInterval(2000);status_timer.timeout.connect(update_status);status_timer.start();update_status()
    QTimer.singleShot(0,refresh)
    web=QPushButton('打开网页 · 学习分析、复习与在线练习 ↗');web.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(account.USER_CENTER)));root.addWidget(web)
    logout=QPushButton('退出当前账户');root.addWidget(logout)
    def leave():
        account.logout();dialog.accept()
    logout.clicked.connect(leave)
    dialog.exec_()
