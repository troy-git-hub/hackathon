"""Personal learning overview, with read-only account summaries and folded sync."""
import threading
import datetime
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QUrl, QPointF
from PyQt5.QtGui import QDesktopServices, QPainter, QPainterPath, QColor, QPen
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QCheckBox,QFrame,QScrollArea,QWidget,QGridLayout)
from echo.backend import account, cloud_sync, store
from echo.theme import Colors, dialog_qss
from echo.widgets.window_chrome import install_chrome


class _Bus(QObject):
    done=pyqtSignal(str,object,str)


def label(text='',size=12,muted=False):
    widget=QLabel(text);widget.setTextFormat(Qt.PlainText);widget.setWordWrap(True)
    widget.setStyleSheet(f'color:{Colors.TEXT_SECONDARY if muted else Colors.TEXT_PRIMARY};font-size:{size}px;background:transparent;')
    return widget


class LearningTrend(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.items=[];self.setMinimumHeight(105)
    def set_items(self,items):
        self.items=list(items or [])[-7:];self.setAccessibleName('近七天已提交题次');self.setToolTip('；'.join(str(i['day'])+'：'+str(i['answered'])+'题次' for i in self.items));self.update()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        w,h=self.width(),self.height();left,right,top,bottom=18,w-18,20,h-26
        painter.setPen(QPen(QColor(Colors.BORDER),1));painter.drawLine(left,bottom,right,bottom)
        if not self.items or not any(i.get('answered',0) for i in self.items):
            painter.setPen(QColor(Colors.TEXT_SECONDARY));painter.drawText(self.rect(),Qt.AlignCenter,'完成一次作答后，这里会记录你的学习节奏。');return
        maximum=max(1,max(i['answered'] for i in self.items));path=QPainterPath()
        for ix,item in enumerate(self.items):
            x=left+(right-left)*ix/max(1,len(self.items)-1);y=bottom-(bottom-top)*item['answered']/maximum
            if ix:path.lineTo(x,y)
            else:path.moveTo(x,y)
        painter.setPen(QPen(QColor(Colors.ACCENT),2));painter.drawPath(path)
        for ix,item in enumerate(self.items):
            x=left+(right-left)*ix/max(1,len(self.items)-1);y=bottom-(bottom-top)*item['answered']/maximum
            painter.setBrush(QColor(Colors.ACCENT));painter.drawEllipse(QPointF(x,y),3,3)
            painter.setPen(QColor(Colors.TEXT_SECONDARY));painter.drawText(int(x)-18,h-19,40,18,Qt.AlignCenter,item['day'])
            painter.drawText(int(x)-18,int(y)-19,36,16,Qt.AlignCenter,str(item['answered']))


class AccountCenter(QDialog):
    def __init__(self,parent=None,autoload=True):
        super().__init__(parent,Qt.Window)
        self.setWindowTitle('Echo · 我的学习')
        self._owner=str((account.current_user() or {}).get('id') or '')
        self._busy=False;self._closed=False
        self.setMinimumSize(480,400);self.resize(740,670)
        self.setStyleSheet(dialog_qss()+f'''
            QScrollArea,QWidget#AccountContent{{background:{Colors.WINDOW_BG};border:0;}}
            QFrame#LearningSummary{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:10px;}}
            QPushButton{{font-size:12px;padding:5px 12px;min-width:0;}}
            QPushButton#AccountLink{{background:transparent;border:0;color:{Colors.ACCENT};text-align:left;padding:4px 0;}}
        ''')
        root=QVBoxLayout(self);root.setSpacing(10)
        self.bus=_Bus(self);self.bus.done.connect(self.finished_request)
        head=QHBoxLayout();identity=QVBoxLayout();identity.setSpacing(3)
        self.name=label('',18);self.email=label('',11,True)
        identity.addWidget(self.name);identity.addWidget(self.email);head.addLayout(identity,1)
        self.balance=label('',13);head.addWidget(self.balance);root.addLayout(head)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setObjectName('AccountContent');scroll.viewport().setAttribute(Qt.WA_StyledBackground,True)
        body=QWidget();body.setObjectName('AccountContent');body.setAttribute(Qt.WA_StyledBackground,True)
        content=QVBoxLayout(body);content.setContentsMargins(0,0,5,0);content.setSpacing(12)
        scroll.setWidget(body);root.addWidget(scroll,1)
        self.metrics=label('');content.addWidget(self.metrics)
        grid=QGridLayout();grid.setSpacing(9);self.summary_values={}
        for ix,(key,title) in enumerate([('answered','已提交题次'),('average_score','已批试卷均分'),('materials','资料 / 清卷'),('points','近七日学习点')]):
            card=QFrame();card.setObjectName('LearningSummary');box=QVBoxLayout(card);box.setContentsMargins(12,10,12,10)
            box.addWidget(label(title,10,True));value=label('—',21);box.addWidget(value);self.summary_values[key]=value;grid.addWidget(card,ix//2,ix%2)
        content.addLayout(grid)
        self.study_detail=label('刷新后显示账户中的试卷、资料与作答数据。',11,True);content.addWidget(self.study_detail)
        self.trend=LearningTrend();content.addWidget(self.trend)
        self.attempts=self.section(content,'最近的试卷与每日小题')
        self.lessons=self.section(content,'最近学习')
        self.requests=self.section(content,'最近的 AI 辅助')
        self.notice=label('',11,True);content.addWidget(self.notice)
        links=QHBoxLayout()
        self.refresh_button=self.button('刷新摘要',self.refresh);links.addWidget(self.refresh_button)
        web=self.button('打开网页学习空间 ↗',lambda:QDesktopServices.openUrl(QUrl(account.USER_CENTER)))
        links.addWidget(web);links.addStretch();content.addLayout(links)
        tools=QHBoxLayout();tools.addWidget(self.button('云端试卷与错题',lambda:self.open_cloud('exams')));tools.addWidget(self.button('清卷 · 拍卷与命题',lambda:self.open_cloud('qingjuan')));tools.addStretch();content.addLayout(tools)
        self.sync_toggle=self.button('同步与账户 ▸',self.toggle_sync);self.sync_toggle.setCheckable(True)
        self.sync_toggle.setObjectName('AccountLink');content.addWidget(self.sync_toggle)
        self.sync_panel=QWidget();sync=QVBoxLayout(self.sync_panel);sync.setContentsMargins(0,2,0,0);sync.setSpacing(8)
        self.sync_status=label('',11,True);sync.addWidget(self.sync_status)
        self.auto_sync=QCheckBox('这台设备自动同步学习档案');self.auto_sync.setChecked(cloud_sync.status()['enabled'])
        self.auto_sync.toggled.connect(self.change_sync);sync.addWidget(self.auto_sync)
        row=QHBoxLayout();self.sync_button=self.button('立即同步',self.sync);row.addWidget(self.sync_button)
        self.bind_button=self.button('关联本机资料',self.rebind);row.addWidget(self.bind_button)
        self.logout_button=self.button('退出账户',self.logout);row.addWidget(self.logout_button);row.addStretch();sync.addLayout(row)
        sync.addWidget(label('同步学习记录与复习进度；不上传密钥、录音或原始截图。',11,True))
        content.addWidget(self.sync_panel);self.sync_panel.hide();content.addStretch()
        install_chrome(self,root)
        self.render_identity(account.current_user() or {})
        self.render_local();self.update_sync()
        self.status_timer=QTimer(self);self.status_timer.setInterval(2000)
        self.status_timer.timeout.connect(self.update_sync);self.status_timer.start()
        if autoload:QTimer.singleShot(0,self.refresh)

    def section(self,layout,title):
        frame=QFrame();frame.setObjectName('LearningSummary');box=QVBoxLayout(frame)
        box.setContentsMargins(14,12,14,12);box.setSpacing(8);box.addWidget(label(title,13))
        rows=QVBoxLayout();rows.setSpacing(8);box.addLayout(rows);layout.addWidget(frame)
        return rows

    def button(self,text,slot):
        widget=QPushButton(text);widget.setCursor(Qt.PointingHandCursor)
        widget.clicked.connect(lambda checked=False:slot());return widget

    def same_owner(self):
        return not self._closed and self._owner==str((account.current_user() or {}).get('id') or '')

    def render_identity(self,user):
        self.name.setText(user.get('name') or '继续你的学习')
        self.email.setText(user.get('email') or '')
        self.balance.setText(str(user.get('balance',0))+' 学习点')

    @staticmethod
    def clear(layout):
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()

    def render_local(self):
        bound=cloud_sync.status().get('bound_account')
        if bound and str(bound)!=self._owner:
            self.metrics.setText('本机资料尚未关联到当前账户')
            self.lessons.addWidget(label('为保护资料隐私，本机的其他账户记录不在此显示。',12,True))
            self.requests.addWidget(label('点击刷新，查看当前账户的学习摘要。',11,True))
            return
        try:
            stats=store.stats();lessons=store.list_lessons(limit=3)
        except Exception:stats={};lessons=[]
        self.metrics.setText(f"本机已听 {stats.get('lessons',0)} 节课 · {stats.get('pending',0)} 项待复习")
        self.render_lessons(lessons,local=True)
        self.clear(self.requests);self.requests.addWidget(label('尚未加载账户摘要，点击“刷新摘要”查看。',11,True))

    def render_lessons(self,items,local=False):
        self.clear(self.lessons)
        if not items:self.lessons.addWidget(label('还没有课堂记录。先开一节课，Echo 会陪你记下重点。',12,True));return
        for item in items[:3]:
            stamp=item.get('time') if local else item.get('ended_at')
            try:when=datetime.datetime.fromtimestamp(float(stamp)).strftime('%m月%d日')
            except (ValueError,TypeError,OverflowError,OSError):when='最近'
            row=QHBoxLayout();row.addWidget(label(item.get('title') or '未命名课堂',12),1)
            row.addWidget(label(when+(' · 本机' if local else ''),11,True));host=QWidget();host.setLayout(row)
            row.setContentsMargins(0,0,0,0);self.lessons.addWidget(host)

    def refresh(self):
        if self._busy or not self.same_owner():return
        self._busy=True;self.refresh_button.setEnabled(False);self.notice.setText('正在加载近期学习与任务摘要…')
        session=account.token()
        def work():
            values={};errors=[]
            def fetch(key,path):
                try:return key,account.request(path,timeout=12,max_bytes=1024*1024,auth_token=session),''
                except Exception as exc:return key,None,str(exc)
            with ThreadPoolExecutor(max_workers=3) as pool:
                jobs=[pool.submit(fetch,key,path) for key,path in [('user','/v1/me'),('workspace','/v1/me/workspace'),('requests','/v1/me/requests'),('summary','/v1/me/summary')]]
                for job in jobs:
                    key,value,error=job.result()
                    if error:errors.append(error)
                    else:values[key]=value
            try:self.bus.done.emit('summary',values,'；'.join(dict.fromkeys(errors)))
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='echo-personal-summary').start()

    def finished_request(self,kind,value,error):
        if kind=='logout':
            if self._closed:return
            self.setEnabled(True)
            if error:self.notice.setText(error);self.status_timer.start()
            else:self.accept()
            return
        if not self.same_owner():return
        self._busy=False;self.refresh_button.setEnabled(True);self.sync_button.setEnabled(True);self.logout_button.setEnabled(True)
        if kind=='sync':self.update_sync();self.notice.setText(error or value.get('message','同步已完成。'));return
        value=value or {}
        if value.get('user') and str(value['user']['user'].get('id',''))!=self._owner:
            self.notice.setText('账户信息已变化，请关闭后重新打开。');return
        if value.get('user'):self.render_identity(value['user']['user'])
        workspace=value.get('workspace')
        if workspace:
            stats=workspace.get('stats',{})
            self.metrics.setText(f"云端 {stats.get('knowledge',0)} 个知识点 · {stats.get('due',0)} 项待复习 · {stats.get('weakness',0)} 项待巩固")
            if workspace.get('lessons'):self.render_lessons(workspace['lessons'])
        if value.get('summary'):self.render_summary(value['summary'])
        if 'requests' in value:
            self.clear(self.requests)
            items=value['requests'].get('items',[])[:3]
            states={'succeeded':'已完成','failed':'未完成 · 额度已返还','pending':'处理中'}
            for item in items:
                row=QHBoxLayout();row.setContentsMargins(0,0,0,0)
                row.addWidget(label((item.get('purpose_label') or '学习辅助')+' · '+states.get(item.get('state'),'状态待更新'),12),1)
                row.addWidget(label(('已返还' if item.get('state')=='failed' else str(item.get('cost',0))+' 点'),11,True))
                widget=QWidget();widget.setLayout(row);self.requests.addWidget(widget)
            if not items:self.requests.addWidget(label('还没有账户 AI 请求。听课时需要帮助，再让 Echo 出手。',12,True))
        self.notice.setText(('部分云端摘要暂未加载：'+error+'；已保留可用内容，可重试。') if error else '近期摘要已更新。AI 任务由你使用时触发，刷新不会调用模型。')

    def open_cloud(self,view):
        if not self.same_owner():return
        from echo.widgets.paper_book import open_paper_book
        self._cloud=open_paper_book(self,view)
        if self._cloud:self._cloud.finished.connect(lambda _:self.refresh() if self.same_owner() else None)

    def render_summary(self,data):
        if str(data.get('user_id',''))!=self._owner:return
        stats=data.get('study',{});usage=data.get('usage_7d',{});quota=data.get('storage',{})
        values={'answered':str(stats.get('answered',0)), 'average_score':'—' if stats.get('average_score') is None else str(stats['average_score']),
                'materials':str(stats.get('materials',0))+' / '+str(stats.get('papers',0)), 'points':str(usage.get('points',0))}
        for key,text in values.items():self.summary_values[key].setText(text)
        self.study_detail.setText(f"已交 {stats.get('submitted',0)} 卷 · 进行中 {stats.get('in_progress',0)} · 待回顾 {stats.get('wrong',0)} 题次 · 待批 {stats.get('pending',0)} 题\n个人云端占用 {quota.get('used_bytes',0)/1048576:.1f} MiB · 近七日已完成 {usage.get('completed',0)} 次 AI 辅助。均分不含待批试卷。")
        self.trend.set_items(data.get('daily',[]));self.clear(self.attempts)
        for item in data.get('recent_attempts',[])[:3]:
            if item.get('status')=='submitted':state='待批改' if item.get('pending_count') else str(item.get('score',0))+' 分'
            else:state='进行中' if item.get('deadline',0)>data.get('server_time',0) else '到时待交卷'
            row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.addWidget(label(item.get('title') or '学习检测',12),1);row.addWidget(label(state,11,True));host=QWidget();host.setLayout(row);self.attempts.addWidget(host)
        if not data.get('recent_attempts'):self.attempts.addWidget(label('还没有云端试卷。可从清卷导入，或开始每日小题。',11,True))

    def toggle_sync(self):
        expanded=self.sync_toggle.isChecked();self.sync_panel.setVisible(expanded)
        self.sync_toggle.setText('同步与账户 ▾' if expanded else '同步与账户 ▸')

    def update_sync(self):
        if not self.same_owner():
            self.name.setText('账户已变更');self.email.clear();self.balance.clear();self.metrics.clear()
            self.clear(self.lessons);self.clear(self.requests);self.clear(self.attempts)
            for value in self.summary_values.values():value.setText('—')
            self.study_detail.clear();self.trend.set_items([])
            self.notice.setText('账户已变更，请关闭后重新打开。');self.refresh_button.setEnabled(False);self.sync_panel.setEnabled(False)
            self.status_timer.stop();return
        info=cloud_sync.status();self.sync_status.setText(info.get('message',''))
        bound=info.get('bound_account');self.bind_button.setVisible(bool(bound and bound!=self._owner))

    def change_sync(self,enabled):
        if not self.same_owner():return
        try:cloud_sync.configure(enabled=enabled);self.update_sync()
        except Exception as exc:self.notice.setText(str(exc))

    def rebind(self):
        from echo.widgets import dialogs
        if not self.same_owner():return
        if dialogs.confirm(self,'确认资料归属','将本机资料关联到当前账户？请确认资料属于你。原账户的云端副本保留。',ok_text='确认关联'):
            try:cloud_sync.configure(bind=True);self.update_sync()
            except Exception as exc:self.notice.setText(str(exc))

    def sync(self):
        if not self.same_owner():return
        self.sync_button.setEnabled(False);self.notice.setText('正在同步学习数据…')
        def work():
            try:value,error=cloud_sync.sync_once(),''
            except Exception as exc:value,error={},str(exc)
            try:self.bus.done.emit('sync',value,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='echo-personal-sync').start()

    def logout(self):
        if not self.same_owner():return
        # The account client clears its vault as well as its in-memory session.
        self.status_timer.stop();self.setEnabled(False);self.notice.setText('正在退出账户…')
        def work():
            try:account.logout();error=''
            except Exception as exc:error=str(exc)
            try:self.bus.done.emit('logout',None,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='echo-account-logout').start()

    def done(self,result):
        self._closed=True;self.status_timer.stop();super().done(result)

    def closeEvent(self,event):
        self._closed=True;self.status_timer.stop();super().closeEvent(event)
