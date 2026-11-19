"""Native Qingjuan library and exam UI. Network transport is the account API only."""
import copy
import html
import json
import threading
import time
import uuid
import re
from PyQt5.QtCore import Qt,QTimer,pyqtSignal
from PyQt5.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QListWidget,QListWidgetItem,QStackedWidget,QWidget,QScrollArea,QFrame,QRadioButton,QCheckBox,
    QLineEdit,QTextEdit,QSpinBox,QFormLayout,QMessageBox,QFileDialog,QButtonGroup,QSplitter)
from echo.backend import account,paper_cache
from echo.theme import Colors,dialog_qss
from echo.widgets.window_chrome import install_chrome
from echo.widgets.echo_combo import EchoCombo

_windows=[]


def open_paper_book(parent=None,view='papers'):
    owner=str((account.current_user() or {}).get('id') or '')
    if not owner:
        from echo.widgets.account_login import show_account_center
        show_account_center(parent)
        return None
    for window in _windows:
        if window.owner==owner and not window.closed:
            window.show();window.raise_();window.activateWindow();return window
    window=PaperBook(parent);_windows.append(window)
    window.finished.connect(lambda _: _windows.remove(window) if window in _windows else None)
    window.show();return window


def rich(text):
    """Safe Qt rich text for common inline math; no HTML supplied by a model."""
    value=html.escape(str(text))
    value=re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}',r'(\1)/(\2)',value)
    value=re.sub(r'\^\{([^{}]*)\}',r'<sup>\1</sup>',value)
    value=re.sub(r'_\{([^{}]*)\}',r'<sub>\1</sub>',value)
    value=re.sub(r'\^([0-9a-zA-Z+-])',r'<sup>\1</sup>',value)
    for source,target in {'\\times':'×','\\div':'÷','\\pm':'±','\\leq':'≤','\\geq':'≥','\\pi':'π','\\theta':'θ','\\alpha':'α','\\beta':'β','\\infty':'∞','\\cdot':'·','\\sqrt':'√','\\left':'','\\right':''}.items():
        value=value.replace(source,target)
    return value.replace('$','').replace('\\(','').replace('\\)','').replace('\\[','').replace('\\]','').replace('\n','<br>')


class PaperBook(QDialog):
    completed=pyqtSignal(str,object,str)
    def __init__(self,parent=None,autoload=True):
        super().__init__(parent,Qt.Window)
        self.owner=str((account.current_user() or {}).get('id') or '')
        self.closed=False;self.busy=False;self.paper=None;self.answers={};self.edit=0;self.conflict=False
        self.session=account.token()
        self.rows=[];self.offset=0;self.rendering=False;self.expiring=False
        self.setWindowTitle('Echo · 青卷试卷本 Beta');self.resize(960,700);self.setMinimumSize(720,510)
        self.setStyleSheet(dialog_qss()+f'''
            QListWidget,QTextEdit,QLineEdit{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:8px;padding:8px;}}
            QListWidget::item{{padding:12px 8px;border-bottom:1px solid {Colors.BORDER};}}
            QListWidget::item:selected{{background:{Colors.ACCENT_SOFT};color:{Colors.ACCENT};}}
            QScrollArea{{border:0;background:{Colors.WINDOW_BG};}}
            QFrame#PaperQuestion{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:10px;}}
            QPushButton{{min-width:0;min-height:28px;padding:4px 12px;}}
            QLabel{{background:transparent;}}
            QWidget#PaperBody{{background:{Colors.WINDOW_BG};}}
            QRadioButton::indicator,QCheckBox::indicator{{width:16px;height:16px;border:1px solid {Colors.BORDER_STRONG};background:{Colors.WINDOW_BG};border-radius:8px;}}
            QRadioButton::indicator:checked,QCheckBox::indicator:checked{{background:{Colors.ACCENT};border:3px solid {Colors.SURFACE};}}
            QCheckBox::indicator{{border-radius:4px;}}
            QSplitter::handle{{background:transparent;border:0;width:0;}}
        ''')
        root=QVBoxLayout(self);root.setSpacing(10);install_chrome(self,root)
        self.stack=QStackedWidget();root.addWidget(self.stack,1)
        self.notice=QLabel('登录后读取同一账户的网页试卷；答案在本机编辑，保存时通过 API 同步。')
        self.notice.setWordWrap(True);self.notice.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:11px;');root.addWidget(self.notice)
        self.build_library();self.completed.connect(self.finished_request)
        self.saver=QTimer(self,interval=20000,singleShot=True);self.saver.timeout.connect(self.sync)
        self.clock_timer=QTimer(self,interval=1000);self.clock_timer.timeout.connect(self.tick);self.clock_timer.start()
        QApplication.instance().applicationStateChanged.connect(self.focus_changed)
        if autoload and self.owner:QTimer.singleShot(0,self.refresh)
        elif not self.owner:self.lock()

    def same_owner(self):return bool(self.owner) and not self.closed and self.owner==str((account.current_user() or {}).get('id') or '')
    def lock(self):
        self.release_focus();self.saver.stop();self.stack.setEnabled(False)
        self.list.clear();self.paper=None;self.answers={};self.rows=[]
        self.detail_title.clear();self.detail.clear();self.stack.hide()
        self.notice.setText('请登录当前账户后重新打开试卷本。')
        if self.stack.count()>1:
            old=self.stack.widget(1);self.stack.removeWidget(old);old.deleteLater()

    def button(self,title,slot):
        button=QPushButton(title);button.clicked.connect(lambda _:slot());return button
    def build_library(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout();title=QLabel('青卷 · 我的试卷');title.setStyleSheet(f'font-size:22px;font-weight:600;color:{Colors.ACCENT};')
        row.addWidget(title,1);row.addWidget(self.button('刷新',self.refresh));row.addWidget(self.button('导入试卷',self.import_paper));row.addWidget(self.button('新建试卷',self.compose));layout.addLayout(row)
        row=QHBoxLayout();self.filter=EchoCombo();self.filter.addItems(['全部试卷','可开始','进行中','已交卷','本地草稿']);self.filter.currentIndexChanged.connect(self.render_list)
        self.search=QLineEdit();self.search.setPlaceholderText('搜索试卷名称');self.search.textChanged.connect(self.render_list)
        row.addWidget(self.filter);row.addWidget(self.search,1);layout.addLayout(row)
        split=QSplitter();split.setHandleWidth(0);self.list=QListWidget();self.list.currentRowChanged.connect(self.selection);split.addWidget(self.list)
        detail=QWidget();box=QVBoxLayout(detail);box.setContentsMargins(18,10,8,10)
        self.detail_title=QLabel('让知识，成为你会做的题。');self.detail_title.setWordWrap(True);self.detail_title.setStyleSheet('font-size:20px;font-weight:600;')
        box.addWidget(self.detail_title);self.detail=QLabel('网页青卷与 Echo 共用资料和考试记录。\n选择一份试卷开始原生作答，无需打开内嵌网页。');self.detail.setWordWrap(True);box.addWidget(self.detail)
        box.addStretch();self.anti=QCheckBox('专注模式 · 全屏置顶，记录切屏');box.addWidget(self.anti)
        box.addWidget(QLabel('退出后计时继续；系统级切换无法完全阻止。'))
        self.open_button=self.button('选择试卷',self.open_selected);self.open_button.setEnabled(False);box.addWidget(self.open_button)
        split.addWidget(detail);split.setSizes([380,490]);layout.addWidget(split,1);self.stack.addWidget(page)

    def run(self,kind,work):
        if self.busy or not self.same_owner():return
        self.busy=True;self.notice.setText('正在处理…')
        def worker():
            try:value=work();error=''
            except Exception as exc:value=None;error=str(exc)
            try:self.completed.emit(kind,value,error)
            except RuntimeError:pass
        threading.Thread(target=worker,daemon=True,name='echo-paper-api').start()

    def api(self,path,data=None):
        # Snapshot session at dispatch; a switched account cannot be used by an old window.
        if not self.same_owner():raise account.AccountError('账户已变化。')
        return account.request(path,data,timeout=100,max_bytes=2*1024*1024,auth_token=self.session)

    def refresh(self):
        if not self.same_owner():return
        self.session=account.token()
        def work():return {'papers':self.api('/v1/me/qingjuan/papers')['items'],
                           'attempts':self.api('/v1/me/study/attempts')['items']}
        self.run('library',work)

    def finished_request(self,kind,value,error):
        self.busy=False
        if not self.same_owner():self.lock();return
        if error:
            if kind=='attempt':self.expiring=False
            if kind in ('save','submit'):
                self.conflict='其他页面' in error or '重新加载' in error
                self.notice.setText('本地草稿已保留；'+error+' 可重新加载服务端记录后恢复本地草稿。')
                if self.paper:self.body.setEnabled(time.time()+self.offset<self.paper['deadline'])
            else:
                self.notice.setText(error)
                if kind=='library':self.render_list()
            return
        if kind=='library':
            self.rows=[dict(item,entry='paper') for item in value['papers']]+[dict(item,entry='attempt') for item in value['attempts']]
            self.render_list();self.notice.setText('已同步试卷目录。客观题判分与查看试卷不调用 AI。')
        elif kind in ('start','attempt'):
            self.open_attempt(value)
        elif kind in ('save','submit'):
            paper,version=value;self.paper=paper
            if paper['status']=='submitted':self.answers=paper.get('answers',{});self.open_attempt(paper);return
            paper_cache.save(self.owner,paper,self.answers)
            self.body.setEnabled(True)
            self.notice.setText('答案已同步 · '+time.strftime('%H:%M:%S'))
            if self.edit!=version:self.saver.start()
        elif kind in ('import','generate'):
            self.notice.setText('试卷已保存到当前账户。');self.refresh()

    def render_list(self,*args):
        if not self.same_owner():return
        selected=self.filter.currentIndex();needle=self.search.text().strip().lower()
        rows=list(self.rows)
        cached=paper_cache.list_drafts(self.owner)
        known={r['id'] for r in rows if r['entry']=='attempt'}
        for data in cached:
            if data['paper']['id'] not in known:rows.append(dict(data['paper'],entry='draft'))
        if selected==4:rows=[dict(data['paper'],entry='draft') for data in cached]
        self.list.clear()
        for item in rows:
            state='可开始' if item['entry']=='paper' else ('已交卷' if item.get('status')=='submitted' else '进行中')
            if selected in (1,2,3) and state!=['','可开始','进行中','已交卷'][selected]:continue
            if needle not in item.get('title','').lower():continue
            row=QListWidgetItem(item.get('title','未命名试卷')+'\n'+('本地草稿' if item['entry']=='draft' else state))
            row.setData(Qt.UserRole,item);self.list.addItem(row)
        if self.list.count():self.list.setCurrentRow(0)
        else:self.detail_title.setText('还没有试卷');self.detail.setText('从网页保存一份青卷，或导入青卷 JSON，即可在这里答题。');self.open_button.setEnabled(False)

    def selection(self,index):
        item=self.list.currentItem()
        if not item:return
        data=item.data(Qt.UserRole);self.detail_title.setText(data.get('title','试卷'))
        is_paper=data['entry']=='paper';self.open_button.setEnabled(True)
        self.open_button.setText('开始本地答题' if is_paper else ('查看答案与解析' if data.get('status')=='submitted' else '继续本地答题'))
        self.detail.setText(('与网页使用同一份试卷。\n开始后按服务器截止时间计时。' if is_paper else f"{'已交卷' if data.get('status')=='submitted' else '考试进行中'} · {data.get('count','—')} 题\n本机编辑答案，通过账户 API 保存与交卷。")+'\n\n主观题需批改后计入最终成绩。')

    def open_selected(self):
        row=self.list.currentItem()
        if not row:return
        data=row.data(Qt.UserRole);self.session=account.token()
        if data['entry']=='paper':
            # Reuse request ID if a transport failure follows a successfully started exam.
            key=(self.owner,data['id'])
            if getattr(self,'start_key',None)!=key:self.start_key=key;self.start_id=uuid.uuid4().hex
            self.run('start',lambda:self.api('/v1/me/qingjuan/papers/'+data['id']+'/start',{'request_id':self.start_id,'anti_cheat':self.anti.isChecked()}))
        elif data['entry']=='draft':
            cached=paper_cache.load(self.owner,data['id']);self.open_attempt(cached['paper'],cached['answers']);self.notice.setText('已打开本地草稿。联网后可保存进度；服务端截止时间仍然有效。')
        else:self.run('attempt',lambda:self.api('/v1/me/study/attempts/'+data['id']))

    def open_attempt(self,paper,draft=None):
        self.paper=copy.deepcopy(paper);self.answers=copy.deepcopy(draft if draft is not None else paper.get('answers',{}));self.conflict=False;self.expiring=False
        if draft is None and paper['status']=='active':
            try:cached=paper_cache.load(self.owner,paper['id'])
            except (ValueError,OSError):cached=None
            if cached and cached['answers']!=self.answers and QMessageBox.question(self,'本地草稿','发现不同于云端的本地答案，是否恢复？')==QMessageBox.Yes:self.answers=cached['answers']
        self.offset=paper.get('server_time',time.time())-time.time()
        if self.stack.count()>1:
            old=self.stack.widget(1);self.stack.removeWidget(old);old.deleteLater()
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        top=QHBoxLayout();self.clock=QLabel(paper.get('title','试卷'));top.addWidget(self.clock,1)
        top.addWidget(self.button('保存进度',self.sync));top.addWidget(self.button('重新加载',self.reload))
        self.submit_button=self.button('交卷',self.submit);top.addWidget(self.submit_button)
        if paper['status']=='submitted' and paper.get('wrong_count',0):top.addWidget(self.button('错题重做',self.retry_wrong))
        if paper['status']=='submitted' and paper.get('pending_count',0):top.addWidget(self.button('批改主观题',self.grade))
        top.addWidget(self.button('返回试卷本',self.back));layout.addLayout(top)
        self.progress=QLabel();layout.addWidget(self.progress)
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.body=QWidget();self.body.setObjectName("PaperBody");self.body.setAttribute(Qt.WA_StyledBackground,True);questions=QVBoxLayout(self.body);questions.setContentsMargins(0,0,5,10);questions.setSpacing(12)
        scroll.setWidget(self.body);layout.addWidget(scroll,1);self.rendering=True
        submitted=paper['status']=='submitted';self.submit_button.setEnabled(not submitted)
        for ix,q in enumerate(paper.get('questions',[])):
            card=QFrame();card.setObjectName('PaperQuestion');box=QVBoxLayout(card);box.setContentsMargins(18,14,18,14)
            kicker=QLabel(f"第 {ix+1} 题 · {float(q.get('points',0)):.2f} 分");kicker.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:11px;');box.addWidget(kicker)
            stem=QLabel(rich(q.get('question','')));stem.setWordWrap(True);stem.setTextFormat(Qt.RichText);stem.setTextInteractionFlags(Qt.TextSelectableByMouse);stem.setStyleSheet('font-size:15px;line-height:150%;');box.addWidget(stem)
            if q.get('figure'):
                from echo.widgets.paper_figure import PaperFigure
                box.addWidget(PaperFigure(q['figure']))
            ident=q['id'];answer=self.answers.get(ident);kind=q['type']
            if kind in ('single_choice','true_false','multiple_choice'):
                group=QButtonGroup(card);group.setExclusive(kind!='multiple_choice')
                for i,option in enumerate(q.get('options',[])):
                    control=QCheckBox() if kind=='multiple_choice' else QRadioButton()
                    control.setText(chr(65+i)+'.')
                    control.setChecked(i in (answer or []) if kind=='multiple_choice' else answer==i);control.setEnabled(not submitted);group.addButton(control,i)
                    if kind=='multiple_choice':control.toggled.connect(lambda checked,k=ident,n=i:self.choose_many(k,n,checked))
                    else:control.toggled.connect(lambda checked,k=ident,n=i:self.changed(k,n) if checked else None)
                    option_row=QHBoxLayout();option_row.addWidget(control)
                    option_label=QLabel(rich(option));option_label.setWordWrap(True);option_label.setTextFormat(Qt.RichText);option_label.setTextInteractionFlags(Qt.TextSelectableByMouse);option_row.addWidget(option_label,1);box.addLayout(option_row)
            else:
                control=QTextEdit() if kind=='short_answer' else QLineEdit();control.setEnabled(not submitted)
                if kind=='short_answer':control.setMaximumHeight(120);control.setPlainText(str(answer or ''));control.textChanged.connect(lambda k=ident,c=control:self.changed(k,c.toPlainText()))
                else:control.setText(str(answer or ''));control.textChanged.connect(lambda value,k=ident:self.changed(k,value))
                box.addWidget(control)
            if submitted:
                result=paper.get('results',{}).get(ident,{})
                state={'correct':'答对了','incorrect':'需要巩固','partial':'部分正确','unanswered':'未作答','pending':'主观题待批改'}.get(result.get('status'),'待核对')
                review=QLabel(rich(state+'\n参考答案：'+self.answer_text(q,q.get('answer',result.get('answer','—')))+'\n解析：'+str(q.get('explanation',result.get('explanation','暂无解析')))))
                review.setWordWrap(True);review.setStyleSheet(f'color:{Colors.ACCENT};padding-top:8px;');review.setTextInteractionFlags(Qt.TextSelectableByMouse);box.addWidget(review)
            questions.addWidget(card)
        questions.addStretch();self.rendering=False;self.stack.addWidget(page);self.stack.setCurrentWidget(page)
        if paper.get('anti_cheat') and not submitted:self.setWindowFlag(Qt.WindowStaysOnTopHint,True);self.showFullScreen()
        else:self.release_focus()
        paper_cache.save(self.owner,self.paper,self.answers);self.tick()
        self.notice.setText('已交卷，答案与解析已从账户加载。' if submitted else '本地草稿自动保存，联网时同步。断网不会停止服务器计时。')

    @staticmethod
    def answer_text(q,value):
        if isinstance(value,list):return '、'.join(PaperBook.answer_text(q,v) for v in value)
        if type(value)==int and 0<=value<len(q.get('options',[])):return chr(65+value)+'. '+q['options'][value]
        return str(value)
    def choose_many(self,key,index,checked):
        values=set(self.answers.get(key,[]));values.add(index) if checked else values.discard(index);self.changed(key,sorted(values))
    def changed(self,key,value):
        if self.rendering or not self.paper or self.paper['status']!='active' or not self.same_owner():return
        if time.time()+self.offset>=self.paper['deadline']:self.tick();return
        self.answers[key]=value[:6000] if isinstance(value,str) else value;self.edit+=1
        try:paper_cache.save(self.owner,self.paper,self.answers);self.notice.setText('草稿已保存在本机，等待同步…')
        except Exception as exc:self.notice.setText('本地保存失败：'+str(exc))
        if not self.saver.isActive():self.saver.start()
        self.tick()
    def sync(self):
        if not self.paper or self.paper['status']!='active' or self.busy or self.conflict:return
        paper=copy.deepcopy(self.paper);answers=copy.deepcopy(self.answers);version=self.edit
        self.run('save',lambda:(self.api('/v1/me/study/attempts/'+paper['id']+'/answers',{'answers':answers,'revision':paper['revision']}),version))
    def submit(self):
        if not self.paper or self.paper['status']!='active' or self.busy:return
        if self.conflict:self.notice.setText('云端进度已变化，请重新加载后核对本地草稿再交卷。');return
        if QMessageBox.question(self,'交卷','确认提交整卷？交卷后不能修改答案。')!=QMessageBox.Yes:return
        self.saver.stop();paper=copy.deepcopy(self.paper);answers=copy.deepcopy(self.answers);version=self.edit;self.body.setEnabled(False)
        self.run('submit',lambda:(self.api('/v1/me/study/attempts/'+paper['id']+'/submit',{'answers':answers,'revision':paper['revision']}),version))
    def reload(self):
        if self.paper:self.run('attempt',lambda:self.api('/v1/me/study/attempts/'+self.paper['id']))
    def retry_wrong(self):
        if self.busy or not self.paper:return
        aid=self.paper['id']
        if getattr(self,'_retry_for',None)!=aid:self._retry_for=aid;self._retry_id=uuid.uuid4().hex
        self.run('attempt',lambda:self.api('/v1/me/study/attempts/'+aid+'/retry',{'request_id':self._retry_id}))
    def grade(self):
        if self.busy or not self.paper:return
        if QMessageBox.question(self,'主观题批改','使用账户学习点批改主观题？客观题已自动判分。')!=QMessageBox.Yes:return
        aid=self.paper['id']
        if getattr(self,'_grade_for',None)!=aid:self._grade_for=aid;self._grade_id=uuid.uuid4().hex
        self.run('attempt',lambda:self.api('/v1/me/study/attempts/'+aid+'/grade',{'request_id':self._grade_id}))
    def tick(self):
        if not self.same_owner():
            if self.stack.isEnabled():self.lock()
            return
        if not self.paper:return
        submitted=self.paper['status']=='submitted';answered=sum(v not in (None,'',[]) for v in self.answers.values())
        self.progress.setText(f"已答 {answered} / {len(self.paper.get('questions',[]))} 题"+(f" · 已判得分 {float(self.paper.get('score') or 0):.1f} · {self.paper.get('pending_count',0)} 题待批" if submitted else ''))
        if not submitted:
            left=max(0,int(self.paper['deadline']-time.time()-self.offset));self.clock.setText(self.paper['title']+f'  {left//60:02}:{left%60:02}')
            if not left:
                self.body.setEnabled(False);self.notice.setText('时间已到，正在读取服务器交卷记录。未同步的草稿不会计入成绩。')
                if not self.busy and not self.expiring:self.expiring=True;self.reload()
    def release_focus(self):
        if self.isFullScreen() or self.windowFlags()&Qt.WindowStaysOnTopHint:
            self.setWindowFlag(Qt.WindowStaysOnTopHint,False);self.showNormal()
    def focus_changed(self,state):
        if state!=Qt.ApplicationActive and self.same_owner() and self.paper and self.paper.get('anti_cheat') and self.paper['status']=='active':
            session=self.session;aid=self.paper['id']
            def send():
                try:account.request('/v1/me/study/attempts/'+aid+'/events',{'kind':'blur'},auth_token=session)
                except Exception:pass
            threading.Thread(target=send,daemon=True).start()
    def back(self):
        if self.busy:self.notice.setText('请等待当前保存完成。');return
        if self.paper and self.paper['status']=='active':
            if QMessageBox.question(self,'返回试卷本','保存本地草稿并退出作答？服务器计时继续。')!=QMessageBox.Yes:return
            paper_cache.save(self.owner,self.paper,self.answers);self.saver.stop()
        self.release_focus();self.stack.setCurrentIndex(0);self.paper=None
        QTimer.singleShot(400,self.refresh)
    def import_paper(self):
        file,_=QFileDialog.getOpenFileName(self,'导入青卷试卷','','青卷 JSON (*.json)')
        if not file:return
        try:
            from pathlib import Path
            path=Path(file)
            if path.stat().st_size>512*1024:raise ValueError('试卷 JSON 不能超过512 KiB。')
            paper=json.loads(path.read_text(encoding='utf-8-sig'))
        except Exception as exc:self.notice.setText(str(exc));return
        self.session=account.token();self.run('import',lambda:self.api('/v1/me/qingjuan/papers',{'request_id':uuid.uuid4().hex,'paper':paper}))
    def compose(self):
        dialog=QDialog(self);dialog.setWindowTitle('青卷 · 新建试卷');dialog.setStyleSheet(dialog_qss());dialog.resize(470,420)
        box=QVBoxLayout(dialog);form=QFormLayout();fields={}
        for key,title,default in [('title','试卷名称','知识巩固'),('subject','学科','数学'),('grade','年级','初中'),('knowledge','知识点','')]:
            fields[key]=QLineEdit(default);form.addRow(title,fields[key])
        count=EchoCombo();count.addItems(['5','10','15','20']);form.addRow('题量',count)
        minutes=QSpinBox();minutes.setRange(5,120);minutes.setValue(30);form.addRow('限时（分钟）',minutes);box.addLayout(form)
        note=QLabel('AI 命题按管理员设置的比例消耗学习点。生成结果请先核对；开始考试与客观判分免费。');note.setWordWrap(True);box.addWidget(note)
        box.addWidget(self.button('确认生成',dialog.accept));install_chrome(dialog,box)
        if dialog.exec_()!=QDialog.Accepted:return
        data={k:w.text().strip() for k,w in fields.items()};data.update(request_id=uuid.uuid4().hex,count=int(count.currentText()),duration=minutes.value())
        self.session=account.token();self.run('generate',lambda:self.api('/v1/me/qingjuan/generate',data))
    def reject(self):self.close()
    def closeEvent(self,event):
        if self.busy:self.notice.setText('请求处理中，请完成后再关闭。');event.ignore();return
        if self.paper and self.paper['status']=='active' and self.same_owner():
            if QMessageBox.question(self,'退出作答','保留本地草稿并退出？服务器计时继续。')!=QMessageBox.Yes:event.ignore();return
            try:paper_cache.save(self.owner,self.paper,self.answers)
            except Exception as exc:self.notice.setText('保存失败：'+str(exc));event.ignore();return
        self.closed=True;self.clock_timer.stop();self.saver.stop();self.release_focus();event.accept();QDialog.reject(self)
