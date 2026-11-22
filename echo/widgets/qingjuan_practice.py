"""Local, untimed trial of an authored paper. Objective scoring never uses AI."""
import copy
import time
from PyQt5.QtCore import Qt,QTimer
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QScrollArea,QWidget,QLabel,
    QPushButton,QRadioButton,QCheckBox,QButtonGroup,QTextEdit,QMessageBox,QApplication,QSizePolicy)
from echo.backend import qingjuan_local as local
from echo.theme import Colors,dialog_qss
from echo.widgets.window_chrome import install_chrome
from echo.widgets.paper_book import rich


class LocalPaperPractice(QDialog):
    def __init__(self,document,parent=None):
        super().__init__(parent);self.setWindowTitle('清卷 · 本机试做（不计时）');self.resize(760,720)
        screen=QApplication.primaryScreen()
        if screen:self.resize(min(760,screen.availableGeometry().width()-40),min(720,screen.availableGeometry().height()-40))
        self.doc=copy.deepcopy(document);self.owner=document['owner'];self.closed=False
        self.setStyleSheet(dialog_qss()+f'QScrollArea,QWidget#LocalPractice{{background:{Colors.WINDOW_BG};border:0;}}QTextEdit{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:8px;}}')
        current=self.doc.get('practice',{})
        if current.get('paper_hash')!=local.fingerprint(self.doc['paper']):current={}
        self.practice=current or {'paper_hash':local.fingerprint(self.doc['paper']),'answers':{},'results':{},'submitted':False}
        self.doc['practice']=self.practice
        self.save_timer=QTimer(self);self.save_timer.setSingleShot(True);self.save_timer.setInterval(650);self.save_timer.timeout.connect(self.save)
        root=QVBoxLayout(self);self.paper_title=QLabel(self.doc['paper']['meta']['title']);self.paper_title.setTextFormat(Qt.PlainText);self.paper_title.setWordWrap(True);root.addWidget(self.paper_title)
        hint=QLabel('非计时本机试做 · 选择/判断本地自动判分，多选完全匹配计分；主观题可另行手动请求AI批改。');hint.setWordWrap(True);root.addWidget(hint)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);root.addWidget(self.scroll,1)
        self.notice=QLabel();self.notice.setWordWrap(True);self.notice.setTextFormat(Qt.PlainText);root.addWidget(self.notice)
        actions=QHBoxLayout();self.submit_button=QPushButton('提交本机试做');self.submit_button.clicked.connect(self.submit);actions.addWidget(self.submit_button)
        self.retry_button=QPushButton('新一轮试做');self.retry_button.clicked.connect(self.restart);actions.addWidget(self.retry_button)
        self.return_button=QPushButton('保存并返回');self.return_button.clicked.connect(self.close);actions.addWidget(self.return_button);root.addLayout(actions)
        install_chrome(self,root);self.render()
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.check_owner);self.timer.start()

    def render(self):
        body=QWidget();body.setObjectName('LocalPractice');box=QVBoxLayout(body);box.setSpacing(12);self.inputs={}
        submitted=self.practice['submitted']
        number=0
        for section in self.doc['paper']['sections']:
            heading=QLabel(section['title']);heading.setTextFormat(Qt.PlainText);heading.setWordWrap(True);heading.setStyleSheet('font-size:17px;font-weight:600;');box.addWidget(heading)
            for parent in section['questions']:
                if parent.get('questions'):
                    context=QLabel(rich(parent['stem']+'\n'+parent.get('passage','')));context.setWordWrap(True);box.addWidget(context)
                for q in parent.get('questions') or [parent]:
                    number+=1;label=QLabel(f'<b>{number}.</b> '+rich(q['stem'])+f" <small>（{q['score']:g}分）</small>");label.setWordWrap(True);box.addWidget(label)
                    if q.get('figure') or parent.get('figure'):
                        from echo.widgets.paper_figure import PaperFigure
                        box.addWidget(PaperFigure(q.get('figure') or parent['figure']))
                    answer=self.practice['answers'].get(q['id'],'');kind=q['type']
                    if kind in ('choice','multi','tf'):
                        options=['正确','错误'] if kind=='tf' else q['options'];group=QButtonGroup(body);group.setExclusive(kind!='multi');buttons=[]
                        for i,option in enumerate(options):
                            widget=QCheckBox() if kind=='multi' else QRadioButton();widget.setText('' if kind=='tf' else chr(65+i)+'.')
                            value=option if kind=='tf' else chr(65+i);widget.setChecked(value in answer if kind=='multi' else value==answer);widget.setEnabled(not submitted);group.addButton(widget)
                            widget.toggled.connect(lambda checked,q=q,buttons=buttons:self.choice_changed(q,buttons));buttons.append((widget,value))
                            row=QHBoxLayout();row.addWidget(widget);caption=QLabel(rich(option));caption.setWordWrap(True);caption.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);row.addWidget(caption,1);box.addLayout(row)
                        self.inputs[q['id']]=buttons
                    else:
                        widget=QTextEdit();widget.setAcceptRichText(False);widget.setMaximumHeight(115);widget.setPlainText(answer);widget.setEnabled(not submitted)
                        widget.textChanged.connect(lambda q=q,w=widget:self.changed(q['id'],w.toPlainText()[:12000]));box.addWidget(widget);self.inputs[q['id']]=widget
                    if submitted:
                        result=self.practice['results'].get(q['id'],{});review=QLabel(rich(result.get('feedback','待批改')+'\n参考答案：'+q['answer']+'\n解析：'+q['analysis']))
                        review.setWordWrap(True);review.setStyleSheet(f'background:{Colors.SURFACE};padding:12px;border-radius:8px;');box.addWidget(review)
        box.addStretch();old=self.scroll.takeWidget()
        if old:old.deleteLater()
        self.scroll.setWidget(body);self.submit_button.setEnabled(not submitted)
        if submitted:
            results=self.practice['results'];score=sum(r.get('awarded_points',0) for r in results.values());pending=sum(r.get('status')=='pending' for r in results.values())
            self.notice.setText(f'本机已判得分 {score:g} · {pending} 题待批改；尚有待批时不是最终总分。返回工作台可手动AI批改。')
        else:self.notice.setText('答案只保存在本机；提交前不显示参考答案与解析。')

    def choice_changed(self,q,buttons):self.changed(q['id'],''.join(value for widget,value in buttons if widget.isChecked()))

    def changed(self,ident,value):
        if self.practice['submitted'] or not self.check_owner():return
        self.practice['answers'][ident]=value
        self.save_timer.start()

    def save(self):
        self.save_timer.stop()
        if local.owner()!=self.owner:return False
        try:self.practice['updated']=time.time();self.doc['practice']=self.practice;local.save(self.doc);return True
        except Exception as exc:self.notice.setText('本机作答未保存，请重试后再关闭：'+str(exc));return False

    def submit(self):
        if not self.check_owner() or self.practice['submitted']:return
        if QMessageBox.question(self,'提交本机试做','确认提交？这一步不会调用AI。')!=QMessageBox.Yes:return
        old=copy.deepcopy(self.practice)
        self.practice.update(submitted=True,results=local.objective_results(self.doc['paper'],self.practice['answers']))
        if not self.save():self.practice=old;self.doc['practice']=old;return
        self.render()

    def restart(self):
        if not self.check_owner():return
        if QMessageBox.question(self,'新一轮试做','用新作答替换本机这轮试做？卷稿保持不变。')!=QMessageBox.Yes:return
        old=copy.deepcopy(self.practice)
        self.practice={'paper_hash':local.fingerprint(self.doc['paper']),'answers':{},'results':{},'submitted':False}
        if self.save():self.render()
        else:self.practice=old;self.doc['practice']=old

    def check_owner(self):
        if local.owner()==self.owner:return True
        self.scroll.hide();self.paper_title.setText('账户已变化');self.submit_button.setEnabled(False);self.retry_button.setEnabled(False)
        if hasattr(self,'timer'):self.timer.stop()
        self.save_timer.stop()
        self.notice.setText('账户已变化，请关闭后重新打开。');return False

    def reject(self):self.close()

    def closeEvent(self,event):
        if self.closed:event.accept();return
        if local.owner()==self.owner and not self.save():event.ignore();return
        self.closed=True;self.timer.stop();self.save_timer.stop();event.accept();QDialog.reject(self)
