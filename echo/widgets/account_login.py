"""Non-blocking, invite-only account login and account overview."""
import threading
import os
from PyQt5.QtCore import Qt,QTimer,QObject,pyqtSignal,QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QLabel,QPushButton,QCheckBox,QHBoxLayout,QScrollArea,QWidget,QApplication,QFrame
from echo.backend import account,cloud_sync
from echo.theme import Colors,dialog_qss,apply_native_titlebar
from echo.widgets.echo_line_edit import EchoLineEdit as QLineEdit

class _Result(QObject):
    done=pyqtSignal(str,object,str)

from echo.widgets.window_chrome import EchoTitleBar


class _AccountTitleBar(EchoTitleBar):
    def __init__(self,dialog):
        super().__init__(dialog,'Echo · 登录',minimize=False)
        self.layout().setContentsMargins(18,6,10,4)


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
        root.setContentsMargins(22,18,22,20)
        root.setSpacing(10);root.setAlignment(Qt.AlignTop)
        title=QLabel('欢迎回来，继续听懂。')
        title.setStyleSheet(f'font-size:23px;font-weight:600;color:{Colors.ACCENT};')
        root.addWidget(title)
        subtitle=QLabel('使用 Echo 账户登录。新账户须持有邀请码。');subtitle.setWordWrap(True);root.addWidget(subtitle)
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
        self.password_login=QCheckBox('密码登录（取消后使用邮箱验证码）')
        self.password_login.setChecked(True)
        form.addRow('',self.password_login)
        form.addRow('昵称',self.name)
        form.addRow('邀请码',self.invite)
        form.addRow('验证码',self.code)
        form.addRow('密码',self.password)
        form.addRow('确认密码',self.confirm_password)
        self.totp=QLineEdit();self.totp.setMaxLength(6);self.totp.setPlaceholderText('已开启验证器时填写');form.addRow('验证器动态码',self.totp)
        self.recovery=QLineEdit();self.recovery.setMaxLength(80);self.recovery.setPlaceholderText('恢复码可替代动态码');form.addRow('恢复码（可选）',self.recovery)
        self._form_rows=[]
        for row_index in range(form.rowCount()):
            label_item=form.itemAt(row_index,QFormLayout.LabelRole);field_item=form.itemAt(row_index,QFormLayout.FieldRole)
            self._form_rows.append((label_item.widget() if label_item else None,field_item.widget()))
        form.setVerticalSpacing(8)
        root.addLayout(form)
        self.form=form
        self.two_factor=QPushButton('使用验证器或恢复码 ▸');self.two_factor.setCheckable(True);self.two_factor.setObjectName('Link')
        self.two_factor.toggled.connect(self._mode);root.addWidget(self.two_factor)
        self.register.toggled.connect(self._mode)
        self.password_login.toggled.connect(self._mode)
        row=QHBoxLayout()
        self.send=QPushButton('获取验证码');self.send.clicked.connect(self._send)
        self.submit=QPushButton('登录 Echo');self.submit.clicked.connect(self._login)
        row.addWidget(self.send);row.addWidget(self.submit);root.addLayout(row)
        self.forgot=QPushButton('忘记密码？');self.forgot.setObjectName('Link')
        self.forgot.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(account.USER_CENTER+'?auth=reset')))
        root.addWidget(self.forgot)
        self.notice=QLabel('注册请到网页完成人机与邮箱开通验证；已开启验证器时，登录须填写动态码。')
        self.notice.setTextFormat(Qt.PlainText);self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        self.retry_restore=QPushButton('重试连接 · 恢复已有登录')
        self.retry_restore.clicked.connect(lambda:self._work('restore',account.restore));root.addWidget(self.retry_restore);self.retry_restore.hide()
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
        visible={self.email:True,self.register:True,self.password_login:not reg,
                 self.name:reg,self.invite:reg,self.code:reg or not password,
                 self.password:password,self.confirm_password:reg,
                 self.totp:not reg and self.two_factor.isChecked(),self.recovery:not reg and self.two_factor.isChecked()}
        while self.form.rowCount():self.form.takeRow(0)
        for label,widget in self._form_rows:
            show=visible.get(widget,True);widget.setVisible(show)
            if label:label.setVisible(show)
            if show:
                if label:self.form.addRow(label,widget)
                else:self.form.addRow(widget)
        self.two_factor.setVisible(not reg)
        self.two_factor.setText('验证器 / 恢复码 ▾' if self.two_factor.isChecked() else '使用验证器或恢复码 ▸')
        self.send.setVisible(reg or not password)
        self.submit.setText('注册并登录' if reg else '登录 Echo')
    def _work(self,kind,callback):
        self.submit.setEnabled(False);self.send.setEnabled(False)
        self.skip.setEnabled(False)
        self.retry_restore.setEnabled(False)
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
        totp=self.totp.text().strip();recovery=self.recovery.text().strip()
        self._work('login',lambda:account.login(email,code,password,invite,name,totp,recovery))
    def _finished(self,kind,value,error):
        self.submit.setEnabled(True);self.send.setEnabled(self.cooldown==0)
        self.skip.setEnabled(True)
        self.retry_restore.setEnabled(True)
        if not error:self.retry_restore.hide()
        if error:
            self.notice.setText(error)
            self.retry_restore.setVisible(kind=='restore')
            if kind=='login' and any(word in error for word in ('验证器','动态码','恢复码','双重验证')):self.two_factor.setChecked(True)
            return
        if kind=='code':
            self.cooldown=60;self.timer.start();self._tick();self.notice.setText(value.get('message','验证码已发送。'));return
        if value:
            try:cloud_sync.configure(enabled=self.cloud_enabled.isChecked())
            except account.AccountError as exc:self.notice.setText(str(exc));return
            os.environ['ECHO_ACCOUNT_GUEST']='0'
            if account.persistence_error():
                from echo.widgets import dialogs
                dialogs.info(self,'登录状态保存提示',account.persistence_error())
            self.password.clear();self.confirm_password.clear();self.accept()
        else:self.notice.setText(account.restore_message() or '请登录 Echo 账户。')
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
    from echo.widgets.account_center import AccountCenter
    return AccountCenter(parent).exec_()
