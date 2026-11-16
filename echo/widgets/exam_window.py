"""Full-paper beta with recoverable answers and optional focus constraints."""
import threading
import time
import copy
import math
from PyQt5.QtCore import Qt, QEvent, QSettings, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QApplication,QCheckBox,QComboBox,QDialog,QHBoxLayout,QLabel,QListWidget,
    QListWidgetItem,QMessageBox,QPushButton,QScrollArea,QSpinBox,QStackedWidget,QTextEdit,QVBoxLayout,QWidget)
from echo.backend import assessment, exam
from echo.theme import Colors, dialog_qss
from echo.widgets.echo_combo import EchoCombo
from echo.widgets.window_chrome import install_chrome

_windows = []


def open_exam_window(engine=None, parent=None):
    for existing in _windows:
        if existing._owner == exam.owner():
            existing.show(); existing.raise_(); existing.activateWindow()
            return existing
    window = ExamWindow(engine,parent)
    _windows.append(window)
    window.finished.connect(lambda: _windows.remove(window) if window in _windows else None)
    window.show()
    return window


class ExamWindow(QDialog):
    generated = pyqtSignal(object,str)

    def __init__(self,engine=None,parent=None):
        super().__init__(parent,Qt.Window)
        self.setWindowTitle('Echo · 考试机 Beta')
        self.resize(940,650)
        self.setStyleSheet(dialog_qss())
        self.setStyleSheet(self.styleSheet()+f'''
            QListWidget, QTextEdit {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};
                border:1px solid {Colors.BORDER};border-radius:9px;padding:8px;}}
            QScrollArea {{border:0;background:{Colors.WINDOW_BG};}}
            QWidget#examBody {{background:{Colors.WINDOW_BG};}}
        ''')
        self.paper,self._building,self._submitting = None,False,False
        self._closing = self._confirming = self._focus_lost = self._changing_window = False
        self._owner = exam.owner()
        root = QVBoxLayout(self)
        heading=QHBoxLayout();heading.addWidget(QLabel('考试机 · Beta　｜　多章组卷 · 整卷作答'),1)
        self.cloud_paper_button=QPushButton('清卷 · 云端 ↗')
        self.cloud_paper_button.setToolTip('打开同一账户的网页试卷，在线作答。')
        self.cloud_paper_button.clicked.connect(self.open_cloud)
        heading.addWidget(self.cloud_paper_button);root.addLayout(heading)
        self.stack = QStackedWidget()
        root.addWidget(self.stack,1)
        setup = QWidget(); form = QVBoxLayout(setup)
        form.addWidget(QLabel('选择小本章节或课堂知识点，合并为一张综合试卷（AI 组卷消耗学习点）。'))
        self.sources = QListWidget()
        try:
            for source in exam.chapters(engine):
                item = QListWidgetItem(source['title']); item.setData(Qt.UserRole,source)
                item.setCheckState(Qt.Unchecked); self.sources.addItem(item)
        except Exception as exc:
            form.addWidget(QLabel('章节读取失败：'+str(exc)))
        form.addWidget(self.sources,1)
        row = QHBoxLayout()
        self.count = EchoCombo(); self.count.addItems(['5','10','15','20']); self.count.setCurrentText('10')
        self.minutes = QSpinBox(); self.minutes.setRange(5,180); self.minutes.setValue(30); self.minutes.setSuffix(' 分钟')
        row.addWidget(QLabel('题量'));row.addWidget(self.count);row.addWidget(QLabel('限时'));row.addWidget(self.minutes)
        form.addLayout(row)
        self.anti = QCheckBox('防作弊模式：全屏置顶、记录失焦，退出需要确认（无法阻止系统级切换）')
        self.anti.setChecked(QSettings('Echo','Echo').value('exam_anti_cheat',False,type=bool))
        form.addWidget(self.anti)
        self.make = QPushButton('生成完整试卷'); self.make.clicked.connect(self.build); form.addWidget(self.make)
        self.history = EchoCombo(); form.addWidget(self.history)
        resume = QPushButton('打开所选存档 / 继续考试'); resume.clicked.connect(self.restore); form.addWidget(resume)
        self.stack.addWidget(setup)
        self.message = QLabel('本机试卷保存在本机；网页试卷可从“清卷 · 云端”打开并作答。'); self.message.setWordWrap(True);root.addWidget(self.message)
        self.generated.connect(self.built)
        self.timer = QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.tick)
        QApplication.instance().applicationStateChanged.connect(self.focus_changed)
        self.refresh_history()
        install_chrome(self,root)

    def open_cloud(self):
        if self.paper and self.paper['status']=='active':
            self.message.setText('请先保存并退出本次考试，再打开云端试卷。');return
        try:
            from echo.widgets.cloud_workspace import open_cloud_workspace
            self._cloud_workspace=open_cloud_workspace(parent=self,view='qingjuan')
        except ImportError:
            self.message.setText('当前版本尚未包含云端学习窗口，请使用完成集成后的版本。')

    def refresh_history(self):
        self.history.clear()
        try:
            for paper in reversed(exam.load()):
                self.history.addItem(paper['title']+' · '+('已交卷' if paper['status']=='submitted' else '可继续'),paper)
        except Exception as exc: self.message.setText('存档读取失败：'+str(exc))

    def build(self):
        if self._building:return
        if exam.owner()!=self._owner:
            self.message.setText('账户已切换，请关闭后重新打开考试机。');return
        selected = [self.sources.item(i).data(Qt.UserRole) for i in range(self.sources.count()) if self.sources.item(i).checkState()==Qt.Checked]
        if not 1<=len(selected)<=12:
            self.message.setText('请选择 1 至 12 个章节。');return
        count,minutes,anti = int(self.count.currentText()),self.minutes.value(),self.anti.isChecked()
        QSettings('Echo','Echo').setValue('exam_anti_cheat',anti)
        self._building=True;self.make.setEnabled(False);self.message.setText('正在合并章节组卷，请稍候…')
        def work():
            try:self.generated.emit(exam.generate(selected,count,minutes,anti),'')
            except Exception as exc:self.generated.emit(None,str(exc))
        threading.Thread(target=work,daemon=True,name='echo-exam').start()

    def built(self,paper,error):
        self._building=False;self.make.setEnabled(True)
        if error:self.message.setText(error);return
        self.refresh_history();self.start(paper)

    def restore(self):
        paper=self.history.currentData()
        if paper:
            try:
                latest=next((p for p in exam.load() if p['id']==paper['id']),None)
                if latest is None:raise ValueError('所选试卷已不在存档中，请重新打开考试机。')
                self.start(latest)
            except Exception as exc:self.message.setText('无法恢复考试：'+str(exc))

    def start(self,paper):
        if exam.owner()!=self._owner:
            self.message.setText('账户已切换，请关闭后重新打开考试机。');return
        try:
            paper=copy.deepcopy(exam.validate(paper))
            if paper['owner'] != self._owner: raise ValueError('这份试卷属于其他账户。')
            if paper['status']=='ready':
                exam.checkpoint(paper,started_at=time.time(),status='active')
        except Exception as exc:
            self.message.setText('无法恢复考试：'+str(exc));return
        self.paper=paper
        self.cloud_paper_button.setEnabled(paper['status']!='active')
        if self.stack.count()>1:
            old=self.stack.widget(1);self.stack.removeWidget(old);old.deleteLater()
        page=QWidget();layout=QVBoxLayout(page)
        top=QHBoxLayout();self.clock=QLabel();top.addWidget(self.clock,1)
        self.submit_button=QPushButton('交卷');self.submit_button.clicked.connect(self.submit);top.addWidget(self.submit_button)
        leave=QPushButton('退出答题');leave.clicked.connect(self.close);top.addWidget(leave);layout.addLayout(top)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();body.setObjectName('examBody');questions=QVBoxLayout(body)
        self.inputs=[]
        for q in paper['questions']:
            label=QLabel(q['id']+'. ['+assessment.TYPES[q['type']]+'] '+q['question']);label.setWordWrap(True);label.setTextFormat(Qt.PlainText);questions.addWidget(label)
            saved=paper['answers'].get(q['id'],'')
            if q['type'] in ('single_choice','true_false'):
                widget=EchoCombo();widget.addItem('请选择','')
                for i,option in enumerate(q['options']):widget.addItem(chr(65+i)+'. '+option,chr(65+i))
                widget.setCurrentIndex(max(0,widget.findData(saved)))
                widget.currentIndexChanged.connect(lambda _,q=q,w=widget:self.answer(q['id'],w.currentData()))
            elif q['type']=='matching':
                widget=QWidget();matches=QVBoxLayout(widget);combos=[]
                for i,left in enumerate(q['left']):
                    combo=EchoCombo();combo.addItem(left+' → 请选择',-1)
                    for j,right in enumerate(q['right']):combo.addItem(right,j)
                    value=saved[i] if isinstance(saved,list) and i<len(saved) else -1
                    combo.setCurrentIndex(value+1 if type(value) is int and -1<=value<len(q['right']) else 0)
                    combos.append(combo);matches.addWidget(combo)
                for combo in combos:combo.currentIndexChanged.connect(lambda _,q=q,cs=combos:self.answer(q['id'],[c.currentData() for c in cs]))
            else:
                widget=QTextEdit();widget.setAcceptRichText(False);widget.setMaximumHeight(100);widget.setPlainText(str(saved))
                widget.textChanged.connect(lambda q=q,w=widget:self.answer(q['id'],w.toPlainText()[:12000]))
            widget.setEnabled(paper['status']!='submitted');questions.addWidget(widget);self.inputs.append(widget)
            if paper['status']=='submitted':
                result=paper['results'].get(q['id'],{'feedback':'判分记录缺失，请核对参考答案。'})
                review=QLabel(result['feedback']+'\n参考答案：'+assessment.reference(q)+'\n解析：'+q['explain'])
                review.setTextFormat(Qt.PlainText);review.setWordWrap(True);questions.addWidget(review)
        questions.addStretch();scroll.setWidget(body);layout.addWidget(scroll,1)
        self.stack.addWidget(page);self.stack.setCurrentWidget(page)
        if paper['status']=='submitted':
            self.timer.stop();self.release_protection();self.show_result();return
        if paper['anti_cheat']:
            self._changing_window=True
            self.setWindowFlag(Qt.WindowStaysOnTopHint,True);self.showFullScreen()
            self._changing_window=False
        self.timer.start();self.tick()

    def answer(self,ident,value):
        if not self.paper or self.paper['status']!='active':return
        if exam.owner()!=self._owner:self.tick();return
        if time.time()>=self.paper['started_at']+self.paper['duration_seconds']:
            self.submit(expired=True);return
        self.paper['answers'][ident]=value
        try:
            exam.save(self.paper)
            self.message.setText('答案已保存。主观题交卷后显示待批改。')
        except Exception as exc:self.message.setText('保存失败，答案暂留本窗口，请重试交卷或保存退出：'+str(exc))

    def release_protection(self):
        self._changing_window=True
        if self.windowFlags() & Qt.WindowStaysOnTopHint or self.isFullScreen():
            self.setWindowFlag(Qt.WindowStaysOnTopHint,False);self.showNormal()
        self._changing_window=False

    def tick(self):
        if not self.paper or self.paper['status']!='active':return
        if exam.owner()!=self._owner:
            self.timer.stop();self.release_protection()
            self.stack.setEnabled(False);self.message.setText('账户已切换，考试已暂停，请关闭窗口。');return
        remaining=max(0,math.ceil(self.paper['duration_seconds']-(time.time()-self.paper['started_at'])))
        self.clock.setText(self.paper['title']+f'　剩余 {remaining//60:02d}:{remaining%60:02d}')
        if not remaining:self.submit(expired=True)

    def focus_changed(self,state):
        if state!=Qt.ApplicationActive:self.record_focus_loss()
        elif self.isActiveWindow():self._focus_lost=False

    def event(self,event):
        if event.type()==QEvent.WindowDeactivate:
            QTimer.singleShot(0,self.window_deactivated)
        elif event.type()==QEvent.WindowActivate:
            self._focus_lost=False
        return super().event(event)

    def window_deactivated(self):
        popup=QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if popup is not None and (popup is self or self.isAncestorOf(popup)):return
        if not self.isActiveWindow() and not self._confirming:self.record_focus_loss()

    def record_focus_loss(self):
        if (not self.paper or self.paper['status']!='active' or not self.paper['anti_cheat'] or
                self._focus_lost or self._closing or self._changing_window or exam.owner()!=self._owner):return
        self._focus_lost=True
        if len(self.paper['events'])<500:
            try:exam.checkpoint(self.paper,events=self.paper['events']+[{'type':'focus_lost','at':time.time()}])
            except Exception as exc:self.message.setText('失焦记录保存失败：'+str(exc))

    def confirm(self,title,text):
        self._confirming=True
        try:return QMessageBox.question(self,title,text)==QMessageBox.Yes
        finally:self._confirming=False

    def submit(self,checked=False,expired=False):
        if self._submitting or not self.paper or self.paper['status']=='submitted':return
        if exam.owner()!=self._owner:self.tick();return
        self._submitting=True
        if not expired and not self.confirm('交卷','确认提交整张试卷？交卷后不能修改答案。'):
            self._submitting=False;return
        try:exam.submit(self.paper)
        except Exception as exc:
            self.message.setText('交卷存档失败：'+str(exc));self._submitting=False;return
        self.timer.stop();self.release_protection()
        self._submitting=False;self.start(self.paper)

    def show_result(self):
        self.submit_button.setEnabled(False)
        results=self.paper['results']
        scored=sum((results.get(q['id'],{}).get('score') or 0)*q['points'] for q in self.paper['questions'])
        pending=sum(results.get(q['id'],{}).get('status','pending')=='pending' for q in self.paper['questions'])
        graded=sum(q['points'] for q in self.paper['questions'] if results.get(q['id'],{}).get('status','pending')!='pending')
        self.message.setText(f'已交卷 · 已判部分 {scored:g} / {graded:g} 分 · {pending} 题待批改；整卷满分 100（本地 Beta 暂不自动批改主观题）')
        self.clock.setText('试卷回顾 · 失焦记录 '+str(sum(e.get('type')=='focus_lost' for e in self.paper['events'] if isinstance(e,dict))))

    def reject(self):self.close()

    def closeEvent(self,event):
        if self._closing:event.accept();return
        if self._building:
            self.message.setText('正在生成试卷，请等待请求结束后关闭。');event.ignore();return
        if self.paper and self.paper['status']=='active' and exam.owner()==self._owner:
            if not self.confirm('退出考试','保存并退出？计时继续，重新打开可恢复；退出会记录在试卷中。'):
                event.ignore();return
            try:exam.checkpoint(self.paper,events=self.paper['events']+[{'type':'exit','at':time.time()}])
            except Exception as exc:
                self.message.setText('保存失败：'+str(exc));event.ignore();return
        self._closing=True
        self.timer.stop();event.accept();QDialog.reject(self)
