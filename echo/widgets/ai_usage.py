"""Read-only account AI usage with Qingjuan purpose and request-id tracing."""
import datetime
import threading
from PyQt5.QtCore import Qt,QTimer,pyqtSignal
from PyQt5.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView
from echo.backend import account
from echo.theme import Colors,dialog_qss
from echo.widgets.echo_combo import EchoCombo
from echo.widgets.window_chrome import install_chrome


def purpose_label(item):return '清卷' if item.get('purpose')=='qingjuan_generate' else item.get('purpose_label') or '学习辅助'


class AIUsageDialog(QDialog):
    completed=pyqtSignal(object,str)
    def __init__(self,parent=None,autoload=True):
        super().__init__(parent,Qt.Window);self.setWindowTitle('Echo · AI 调用与用量');self.resize(940,520)
        self.owner=str((account.current_user() or {}).get('id') or '');self.items=[];self.busy=False;self.closed=False
        self.setStyleSheet(dialog_qss()+f'QTableWidget{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};}}QHeaderView::section{{background:{Colors.WINDOW_BG};padding:8px;color:{Colors.TEXT_SECONDARY};border:0;}}')
        root=QVBoxLayout(self);row=QHBoxLayout();row.addWidget(QLabel('AI 调用与用量'),1)
        self.filter=EchoCombo();self.filter.addItem('全部用途','');self.filter.addItem('清卷','qingjuan_generate');self.filter.currentIndexChanged.connect(self.render);row.addWidget(self.filter)
        self.refresh_button=QPushButton('刷新记录');self.refresh_button.clicked.connect(self.refresh);row.addWidget(self.refresh_button);root.addLayout(row)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['时间','用途','状态','输入 token','输出 token','学习点','请求编号'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table,1);self.notice=QLabel('按服务端实际token和学习点展示。清卷命题、重出、配图和批改均归“清卷”；请求编号可用于核对。')
        self.notice.setWordWrap(True);self.notice.setTextFormat(Qt.PlainText);root.addWidget(self.notice);install_chrome(self,root)
        self.completed.connect(self.finish);self.owner_timer=QTimer(self);self.owner_timer.setInterval(1000);self.owner_timer.timeout.connect(self.check_owner);self.owner_timer.start()
        if autoload:QTimer.singleShot(0,self.refresh)

    def check_owner(self):
        if self.closed:return False
        if self.owner and self.owner==str((account.current_user() or {}).get('id') or ''):return True
        self.owner_timer.stop()
        self.items=[];self.table.setRowCount(0);self.refresh_button.setEnabled(False);self.notice.setText('请登录原账户后重新打开用量窗口。');return False

    def refresh(self):
        if self.busy or not self.check_owner():return
        self.busy=True;self.refresh_button.setEnabled(False);session=account.token();self.notice.setText('正在读取用量，不会调用AI…')
        def work():
            try:result,error=account.request('/v1/me/requests',timeout=15,auth_token=session),''
            except Exception as exc:result,error=None,str(exc)
            try:self.completed.emit(result,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='echo-ai-usage').start()

    def finish(self,result,error):
        self.busy=False
        if not self.check_owner():return
        self.refresh_button.setEnabled(True)
        if error:self.notice.setText(error+'，请稍后重试。');return
        self.items=result.get('items',[]);self.render();self.notice.setText('显示最近100条账户请求。学习点由服务端结算；用清卷筛选和请求编号核对，不在客户端估算扣费。')

    def render(self):
        key=self.filter.currentData();items=[v for v in self.items if not key or v.get('purpose')==key];self.table.setRowCount(len(items))
        for row,item in enumerate(items):
            try:stamp=datetime.datetime.fromtimestamp(item.get('created',0)).strftime('%m-%d %H:%M')
            except (TypeError,ValueError,OSError,OverflowError):stamp='—'
            values=[stamp,purpose_label(item),{'pending':'处理中','succeeded':'已完成','failed':'失败/已返还'}.get(item.get('state'),'待确认'),
              item.get('input_tokens','—'),item.get('output_tokens','—'),item.get('cost','—'),item.get('request_id','')]
            for column,value in enumerate(values):self.table.setItem(row,column,QTableWidgetItem(str(value)))

    def done(self,result):self.closed=True;self.owner_timer.stop();super().done(result)
