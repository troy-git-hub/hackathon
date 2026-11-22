"""Native goal setup and daily intent, sharing the account learning-path API."""
import os
import threading
import uuid
from PyQt5.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QTabWidget, QWidget, QScrollArea, QFrame, QCheckBox, QGridLayout,
    QButtonGroup, QRadioButton, QTextEdit)
from echo.backend import account, learning_path as api, paths
from echo.theme import Colors, dialog_qss
from echo.widgets.echo_combo import EchoCombo
from echo.widgets.echo_line_edit import EchoLineEdit
from echo.widgets.window_chrome import install_chrome


class _Bus(QObject):
    done = pyqtSignal(str, object, object)


def label(text=''):
    w = QLabel(text); w.setTextFormat(Qt.PlainText); w.setWordWrap(True)
    return w


def combo(items):
    w = EchoCombo()
    for title, value in items: w.addItem(title, value)
    return w


class LearningPath(QDialog):
    def __init__(self, parent=None, snapshot=None, autoload=True):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('Echo · 学习目标与今日安排')
        self.setWindowIcon(QIcon(paths.asset('assets', 'echo.ico')))
        self.resize(640, 720); self.setMinimumSize(460, 450)
        self.setStyleSheet(dialog_qss() + f'''
            QScrollArea,QWidget#LearningPathContent{{background:{Colors.WINDOW_BG};border:0;}}
            QTabWidget::pane{{background:{Colors.WINDOW_BG};border:0;}}
            QTabBar::tab{{background:{Colors.WINDOW_BG};color:{Colors.TEXT_SECONDARY};border:0;padding:9px 16px;}}
            QTabBar::tab:selected{{background:{Colors.SURFACE};color:{Colors.ACCENT};border-bottom:2px solid {Colors.ACCENT};}}
            QLineEdit{{min-height:0;padding:7px 9px;}}
            QCheckBox,QRadioButton{{color:{Colors.TEXT_PRIMARY};spacing:7px;}}
            QCheckBox::indicator,QRadioButton::indicator{{width:16px;height:16px;border:1px solid {Colors.BORDER_STRONG};background:{Colors.SURFACE};}}
            QCheckBox::indicator{{border-radius:4px;}}
            QRadioButton::indicator{{border-radius:9px;}}
            QCheckBox::indicator:checked,QRadioButton::indicator:checked{{background:{Colors.ACCENT};border:3px solid {Colors.ACCENT_BORDER};}}
            QTextEdit{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:6px;padding:7px;}}
            QPushButton{{min-width:0;}}
            QPushButton#LearningPrimary{{background:{Colors.ACCENT};color:{Colors.ON_ACCENT};border:0;font-weight:600;}}
        ''')
        self.client = api.Client(); self.snapshot = {}; self.busy = False; self.closed = False
        self.dirty = False; self.conflict = False; self.reflection_id = uuid.uuid4().hex
        root = QVBoxLayout(self)
        self.heading=label('学习目标'); self.heading.setStyleSheet('font-size:21px;font-weight:600;'); root.addWidget(self.heading)
        root.addWidget(label('目标与兴趣跟随账户同步。打开、保存和切换今日模式不消耗学习点。'))
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        goal = self.page('学习目标'); form = QFormLayout(); form.setRowWrapPolicy(QFormLayout.WrapLongRows); goal.addLayout(form)
        self.subject = combo([(s,s) for s in ('数学','语文','英语','物理','化学','生物','历史','地理','其他')]); self.subject.setEditable(True)
        self.subject.lineEdit().setMaxLength(30)
        self.target = EchoLineEdit(); self.target.setMaxLength(160); self.target.setPlaceholderText('例如：能独立解一次函数应用题')
        self.deadline = EchoLineEdit(); self.deadline.setMaxLength(10); self.deadline.setPlaceholderText('可选 · YYYY-MM-DD')
        self.minutes = combo([(f'{n} 分钟',n) for n in api.MINUTES]); self.minutes.setCurrentIndex(2)
        self.style = combo([(text,key) for key,text in api.STYLES])
        for name,w in [('学科',self.subject),('具体目标',self.target),('目标日期',self.deadline),('每天投入',self.minutes),('讲解偏好',self.style)]: form.addRow(name,w)
        goal.addWidget(label('兴趣（可选，最多5项）'))
        grid = QGridLayout(); self.interest_grid = grid; self.interests = {}
        for i,text in enumerate(api.INTERESTS):
            check = QCheckBox(text); self.interests[text] = check; grid.addWidget(check,i//4,i%4); check.toggled.connect(self.mark_dirty)
        goal.addLayout(grid)
        self.custom = EchoLineEdit(); self.custom.setMaxLength(80); self.custom.setPlaceholderText('其他兴趣或希望怎样举例（可选）'); goal.addWidget(self.custom)
        self.save = self.button('保存学习目标', self.save_goal); self.save.setObjectName('LearningPrimary'); goal.addStretch()
        for w in (self.target,self.deadline,self.custom): w.textChanged.connect(self.mark_dirty)
        self.subject.currentTextChanged.connect(self.mark_dirty)
        for w in (self.minutes,self.style): w.currentIndexChanged.connect(self.mark_dirty)
        daily = self.page('今天的学习')
        self.summary = label('先读取账户中的学习方案。'); daily.addWidget(self.summary)
        self.day_label = label(); daily.addWidget(self.day_label)
        self.mode_group = QButtonGroup(self)
        self.review = QRadioButton('复习已学 · 先回想，再验证'); self.learn = QRadioButton('学习新知识 · 先选知识或资料')
        self.mode_group.addButton(self.review); self.mode_group.addButton(self.learn); daily.addWidget(self.review); daily.addWidget(self.learn)
        self.day_save = self.button('保存今天的选择', self.save_today); daily.addWidget(self.day_save)
        daily.addWidget(label('此选择用于安排学习，不会自动生成课程或重复创建今日试卷。'))
        self.route = label(); daily.addWidget(self.route)
        daily.addWidget(label('合上笔记，回想一个知识点'))
        self.topic = EchoLineEdit(); self.topic.setMaxLength(160); self.topic.setPlaceholderText('今天学了什么？'); daily.addWidget(self.topic)
        self.recall = QTextEdit(); self.recall.setAcceptRichText(False); self.recall.setPlaceholderText('用自己的话说明关键关系（最多800字）'); self.recall.setFixedHeight(95); daily.addWidget(self.recall)
        self.confidence = combo([('还没懂',1),('有点模糊',2),('能说清楚',3)]); daily.addWidget(self.confidence)
        self.question = EchoLineEdit(); self.question.setMaxLength(300); self.question.setPlaceholderText('还没想明白的问题（可选）'); daily.addWidget(self.question)
        self.reflect_save = self.button('保存这次回想', self.save_reflection); daily.addWidget(self.reflect_save)
        self.progress = label(); daily.addWidget(self.progress); daily.addStretch()
        from echo.widgets.learning_planner import LearningPlanner
        planning=self.page('学习规划 Beta');self.planner=LearningPlanner(self);self.planner.action.connect(self.plan_action);planning.addWidget(self.planner)
        root.addWidget(self.save)
        self.tabs.currentChanged.connect(self.select_page)
        self.notice = label(); root.addWidget(self.notice)
        self.refresh_button = self.button('刷新云端方案', self.reload); root.addWidget(self.refresh_button)
        self.bus = _Bus(self); self.bus.done.connect(self.finished)
        install_chrome(self, root)
        self.owner_timer = QTimer(self); self.owner_timer.timeout.connect(self.check_owner); self.owner_timer.start(1000)
        if snapshot is not None: self.render(snapshot)
        elif autoload: QTimer.singleShot(0,self.reload)

    def page(self, title):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(); body.setObjectName('LearningPathContent'); box = QVBoxLayout(body); box.setSpacing(12)
        scroll.setWidget(body); self.tabs.addTab(scroll,title); return box

    def select_page(self,index):
        title=('学习目标','今天的学习','学习规划 · Beta')[index]
        self.heading.setText(title);self.setWindowTitle('Echo · '+title)
        self.save.setVisible(index==0)

    def button(self,text,slot):
        w = QPushButton(text); w.clicked.connect(lambda checked=False:slot()); return w

    def mark_dirty(self,*args): self.dirty = True

    def check_owner(self):
        if not self.client.current():
            self.snapshot = {}; self.closed = True
            for w in (self.target,self.deadline,self.custom,self.topic,self.question): w.clear()
            self.recall.clear(); self.summary.clear(); self.route.clear(); self.progress.clear()
            self.subject.clearEditText()
            self.planner.render({})
            for w in self.interests.values(): w.setChecked(False)
            self.close()

    def start(self, kind, fn):
        if self.busy or self.closed: return
        if not self.client.current(): self.check_owner(); return
        self.busy = True; self.tabs.setEnabled(False); self.save.setEnabled(False); self.refresh_button.setEnabled(False); self.notice.setText('正在同步账户方案…')
        def work():
            try: value,error = fn(),None
            except Exception as exc: value,error = None,exc
            try: self.bus.done.emit(kind,value,error)
            except RuntimeError: pass
        threading.Thread(target=work,daemon=True).start()

    def reload(self):
        if self.dirty:
            from echo.widgets import dialogs
            if not dialogs.confirm(self,'刷新学习目标','刷新会替换尚未保存的目标修改，是否继续？'): return
        self.start('read',self.client.read)

    def save_goal(self):
        if self.conflict: self.notice.setText('其他终端已修改，请先刷新并确认，再保存。'); return
        value = {'subject':self.subject.currentText(),'target':self.target.text(),'deadline':self.deadline.text().strip(),
            'minutes':self.minutes.currentData(),'style':self.style.currentData(),'interest':self.custom.text(),
            'interests':[v for v,w in self.interests.items() if w.isChecked()]}
        if len(value['interests'])>5: self.notice.setText('兴趣最多选择5项。'); return
        revision = (self.snapshot.get('goal') or {}).get('revision',0)
        self.start('goal',lambda:self.client.save_goal(value,revision))

    def require_today(self):
        if self.conflict: self.notice.setText('云端版本已改变，请先刷新并确认。'); return False
        if not self.snapshot.get('goal'): self.tabs.setCurrentIndex(0); self.notice.setText('请先保存学习目标。'); return False
        if self.snapshot.get('day') != api.today(): self.notice.setText('已进入新的一天，请先刷新今日安排。'); return False
        return True

    def save_today(self):
        if not self.require_today(): return
        mode = 'learn' if self.learn.isChecked() else 'review'
        revision = self.snapshot.get('day_plan',{}).get('revision',0)
        self.start('today',lambda:self.client.set_today(mode,revision))

    def save_reflection(self):
        if not self.require_today(): return
        if not self.topic.text().strip() or len(self.recall.toPlainText())>800: self.notice.setText('请填写知识点，回想内容最多800字。'); return
        value = {'id':self.reflection_id,'topic':self.topic.text(),'source_id':'','recall':self.recall.toPlainText(),
            'confidence':self.confidence.currentData(),'next_question':self.question.text()}
        self.start('reflection',lambda:self.client.reflect(value))

    def finished(self,kind,value,error):
        if self.closed or not self.client.current(): self.check_owner(); return
        self.busy = False; self.tabs.setEnabled(True); self.save.setEnabled(True); self.refresh_button.setEnabled(True)
        if error:
            self.conflict = getattr(error,'status_code',None)==409 or self.conflict
            self.notice.setText(('云端版本或状态已改变，请刷新并确认；没有自动重试。' if self.conflict else str(error)))
            return
        # Saving daily intent/reflection must not overwrite an unsaved goal draft.
        keep_goal = kind in ('today','reflection','plan','task') and self.dirty
        self.render(value,keep_goal)
        if kind=='goal': self.tabs.setCurrentIndex(1)
        self.notice.setText('已同步到账户。' if kind!='read' else '已读取账户方案。')

    def render(self,value,keep_goal=False):
        self.snapshot = value; self.conflict = False; goal = value.get('goal') or {}
        if not keep_goal:
            self.subject.setEditText(goal.get('subject','数学')); self.target.setText(goal.get('target',''))
            self.deadline.setText(goal.get('deadline','')); self.custom.setText(goal.get('interest',''))
            for w,key,default in [(self.minutes,'minutes',15),(self.style,'style','visual')]:
                w.setCurrentIndex(max(0,w.findData(goal.get(key,default))))
            selected = goal.get('interests',[])
            for text in selected:
                if text not in self.interests:
                    i = len(self.interests); check = QCheckBox(text); self.interests[text] = check
                    self.interest_grid.addWidget(check,i//4,i%4); check.toggled.connect(self.mark_dirty)
            for text,w in self.interests.items(): w.setChecked(text in selected)
            self.dirty = False
        self.summary.setText(goal.get('target') or '先设定一个具体、可验证的目标。')
        plan = value.get('day_plan',{}); self.day_label.setText(f"{value.get('day','')} · 按北京时间安排")
        self.learn.setChecked(plan.get('mode')=='learn'); self.review.setChecked(plan.get('mode','review')=='review')
        self.day_save.setEnabled(bool(goal)); self.reflect_save.setEnabled(bool(goal))
        recommendations = value.get('recommendations',[])
        text = '\n'.join(f"• {p.get('topic','')} · {p.get('reason','')}" for p in recommendations[:3])
        self.route.setText(('可以从这里开始：\n'+text) if text else '还没有同步知识点。先正常听课或添加资料，再用已有题目验证理解。')
        p = value.get('progress',{}); self.progress.setText('今日：'+ ' · '.join(name+(' ✓' if p.get(key) else ' 待完成') for key,name in [('recalled','回想'),('practiced','练习'),('reflected','留下问题')]))
        self.planner.render(value)
        if not goal: self.tabs.setCurrentIndex(0)

    def plan_action(self,action,task):
        if self.closed or not self.client.current():self.check_owner();return
        if action in ('save_plan','task_state'):
            if not self.require_today():return
            snapshot=self.snapshot
            if action=='save_plan':self.start('plan',lambda:self.client.save_plan(snapshot))
            else:self.start('task',lambda:self.client.set_task(snapshot,task.get('id'),'pending' if task.get('state')=='done' else 'done'))
        elif action=='reflect':
            self.tabs.setCurrentIndex(1)
            if not self.recall.toPlainText().strip():self.topic.setText(str(task.get('topic',''))[:160])
            self.recall.setFocus()
        elif action=='practice':
            from echo.widgets.paper_book import open_paper_book
            child=open_paper_book(self);self._planner_child=child
            ident=(self.snapshot.get('practice') or {}).get('id')
            if child and isinstance(ident,str) and len(ident)==32 and all(c in '0123456789abcdef' for c in ident):
                def open_existing():child.run('attempt',lambda:child.api('/v1/me/study/attempts/'+ident))
                if child.busy:
                    def loaded(kind,value,error):
                        if kind=='library':
                            try:child.completed.disconnect(loaded)
                            except (TypeError,RuntimeError):pass
                            if not error and self.client.current() and not self.closed:open_existing()
                    child.completed.connect(loaded)
                else:open_existing()
        elif action=='qingjuan':
            from echo.widgets.qingjuan_workbench import open_qingjuan_workbench
            child=open_qingjuan_workbench(parent=self);self._planner_child=child
            if child:child.notice.setText('规划建议范围：'+str(task.get('topic',''))+'。请核对蓝图后再命题；尚未请求模型。')
        elif action=='studio':
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl('https://echo.xhbtroy.cn/studio.html'))

    def closeEvent(self,event):
        self.closed = True; self.owner_timer.stop(); super().closeEvent(event)


def open_learning_path(parent=None,snapshot=None,view=0):
    from echo.widgets.account_login import ensure_account
    if not ensure_account(parent): return
    previous = getattr(parent,'_learning_path_window',None) if parent else None
    if previous and not previous.closed:
        previous.tabs.setCurrentIndex(view);previous.select_page(view)
        previous.show(); previous.raise_(); previous.activateWindow(); return previous
    window = LearningPath(parent,snapshot)
    if parent: parent._learning_path_window = window
    window.tabs.setCurrentIndex(view);window.select_page(view)
    window.show(); window.raise_(); return window


def open_learning_planner(parent=None):
    return open_learning_path(parent,view=2)


class GoalOnboarding(QObject):
    """One read per login identity; no polling the server or forced retry loop."""
    def __init__(self, parent, ready=lambda:True):
        super().__init__(parent); self.seen = set(); self.pending = False; self.ready = ready
        self.bus = _Bus(self); self.bus.done.connect(self.finish)
        self.timer = QTimer(self); self.timer.timeout.connect(self.check); self.timer.start(2500)

    def check(self):
        if self.pending or not self.parent().isVisible() or not self.ready() or os.getenv('ECHO_OFFLINE')=='1': return
        user = account.current_user() or {}; client = api.Client()
        key = (client.owner,client.session)
        if not client.owner or not client.session or user.get('_session_offline') or key in self.seen: return
        self.seen.add(key); self.pending = True
        def read():
            try: value,error = client.read(),None
            except Exception as exc: value,error = None,exc
            try: self.bus.done.emit('onboard',(client,value),error)
            except RuntimeError: pass
        threading.Thread(target=read,daemon=True).start()

    def finish(self,kind,result,error):
        self.pending = False; client,value = result
        if error or not client.current() or not self.parent().isVisible() or not self.ready(): return
        if not value.get('goal'): open_learning_path(self.parent(),value)
