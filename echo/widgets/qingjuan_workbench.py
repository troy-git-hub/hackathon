"""Native local Qingjuan authoring, editing, finalizing and offline export."""
import copy
import json
import threading
import time
from pathlib import Path
from PyQt5.QtCore import Qt,QTimer,pyqtSignal,QSizeF,QMarginsF,QUrl
from PyQt5.QtGui import QPageSize,QPageLayout,QIcon,QDesktopServices,QKeySequence
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QTextEdit,QCheckBox,QSpinBox,QDoubleSpinBox,QTabWidget,QWidget,QSplitter,QScrollArea,QTableWidget,
    QTreeWidget,QTreeWidgetItem,QFileDialog,QMessageBox,QInputDialog,QApplication,
    QGroupBox,QGridLayout,QMenu,QShortcut,QSizePolicy,QProgressBar)
from echo.backend import qingjuan_local as local
from echo.theme import Colors,dialog_qss,style_menu
from echo.widgets.echo_combo import EchoCombo
from echo.widgets.echo_line_edit import EchoLineEdit as QLineEdit
from echo.widgets.window_chrome import install_chrome

_windows=[]


def open_qingjuan_workbench(parent=None):
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        from echo.widgets import dialogs
        dialogs.info(parent,'清卷 · 缺少本地排版组件','请使用完整安装版，或通过项目虚拟环境运行 Echo（需要 requirements.txt 中的 PyQtWebEngine）。')
        return None
    who=local.owner()
    for window in _windows:
        if window.owner==who and not window.closed:
            window.show();window.raise_();window.activateWindow();return window
    window=QingjuanWorkbench(parent);_windows.append(window)
    window.finished.connect(lambda _: _windows.remove(window) if window in _windows else None)
    window.show();return window


def combo(items):
    result=EchoCombo()
    for label,value in items:result.addItem(label,value)
    return result


def editable_combo(items):
    from echo.widgets.echo_line_edit import EchoLineEdit
    result=combo([(text,text) for text in items]);result.setEditable(True)
    result.setLineEdit(EchoLineEdit());result.setInsertPolicy(EchoCombo.NoInsert)
    result.lineEdit().setMaxLength(200)
    return result


def spin(value,low,high,decimals=False):
    result=QDoubleSpinBox() if decimals else QSpinBox()
    result.setRange(low,high);result.setValue(value)
    if decimals:result.setDecimals(2)
    return result


class QingjuanWorkbench(QDialog):
    completed=pyqtSignal(str,object,str)
    generation_progress=pyqtSignal(str,object)

    def __init__(self,parent=None):
        # A real top-level window, not an owned dialog collapsing to a caption.
        super().__init__(None,Qt.Window|Qt.WindowMinimizeButtonHint|Qt.WindowCloseButtonHint)
        self.owner=local.owner();self.closed=False;self.busy=False;self.printing=False;self.loading=True;self._pdf_pending=None
        self.doc=local.new(self.owner);self.selected_path=None;self._editing=False;self._render_serial=0
        self.setWindowTitle('Echo · 清卷本地工作台');self.resize(1240,820);self.setMinimumSize(960,620)
        from echo.backend import paths
        self.setWindowIcon(QIcon(paths.asset('assets','echo.ico')))
        screen=(parent.screen() if parent is not None else QApplication.primaryScreen())
        if screen:
            area=screen.availableGeometry();width=max(600,area.width()-32);height=max(400,area.height()-40)
            self.setMinimumSize(min(960,width),min(620,height));self.resize(min(1240,width),min(820,height))
        self.setStyleSheet(dialog_qss()+f'''
          QTabWidget::pane{{border:0;}}QTabBar::tab{{padding:8px 12px;background:{Colors.SURFACE};color:{Colors.TEXT_SECONDARY};}}
          QTabBar::tab:selected{{color:{Colors.ACCENT};border-bottom:2px solid {Colors.ACCENT};}}
          QTreeWidget,QTableWidget,QTextEdit{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:7px;}}
          QHeaderView::section{{background:{Colors.WINDOW_BG};color:{Colors.TEXT_SECONDARY};padding:6px;border:0;}}
          QScrollArea,QWidget#QingjuanForm{{background:{Colors.WINDOW_BG};border:0;}}
          QPushButton{{min-width:0;font-size:12px;padding:5px 10px;}}
          QGroupBox{{border:1px solid {Colors.BORDER};border-radius:12px;margin-top:12px;padding:16px 10px 10px;}}
          QGroupBox::title{{subcontrol-origin:margin;left:12px;padding:0 5px;color:{Colors.TEXT_PRIMARY};font-weight:600;}}
          QWidget#SectionCard{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:10px;}}
          QPushButton#QingjuanGenerate{{background:{Colors.ACCENT};color:{Colors.ON_ACCENT};font-size:15px;font-weight:700;padding:9px 18px;border:0;border-radius:9px;min-height:25px;min-width:140px;}}
          QPushButton#QingjuanGenerate:disabled{{background:{Colors.SURFACE};color:{Colors.TEXT_SECONDARY};}}
        ''')
        root=QVBoxLayout(self);root.setSpacing(9)
        top=QHBoxLayout();title=QLabel('清卷');title.setStyleSheet(f'font-size:21px;font-weight:600;color:{Colors.ACCENT};');top.addWidget(title)
        self.file_list=EchoCombo();self.file_list.setMinimumWidth(190);self.file_list.activated.connect(self.open_selected);top.addWidget(self.file_list,1)
        top.addWidget(self.button('新建',self.new_document));top.addWidget(self.button('保存',self.save_current));top.addWidget(self.button('另存草稿',self.fork))
        self.more_button=self.button('更多 ▾',self.show_more);top.addWidget(self.more_button)
        self.generate_button=self.button('AI 命题  ↗',self.generate);self.generate_button.setObjectName('QingjuanGenerate');self.generate_button.setMinimumWidth(170)
        self.generate_button.setToolTip('根据当前蓝图生成完整试卷 · Ctrl+Enter');top.addWidget(self.generate_button);root.addLayout(top)
        self.generate_shortcut=QShortcut(QKeySequence('Ctrl+Return'),self);self.generate_shortcut.activated.connect(lambda:self.guard(self.generate))
        actions=QHBoxLayout();self.state_label=QLabel();actions.addWidget(self.state_label,1)
        self.retry_button=self.button('重试原请求',lambda:self.generate(retry=True));actions.addWidget(self.retry_button)
        self.final_button=self.button('核对并定稿',self.finalize);actions.addWidget(self.final_button)
        actions.addWidget(self.button('本机试做',self.practice_paper))
        self.export_kind=combo([('试卷','paper'),('答案与解析','answers'),('答题卡','sheet')]);self.export_kind.currentIndexChanged.connect(self.render_preview)
        actions.addWidget(self.button('网上作答 ↗',self.open_exam))
        actions.addWidget(self.export_kind);self.export_button=self.button('导出 ▾',self.show_exports);actions.addWidget(self.export_button)
        root.addLayout(actions)
        self.generation_panel=QWidget();progress_layout=QVBoxLayout(self.generation_panel);progress_layout.setContentsMargins(0,0,0,0);progress_layout.setSpacing(3)
        self.generation_label=QLabel();self.generation_label.setWordWrap(True)
        self.generation_bar=QProgressBar();self.generation_bar.setRange(0,5);self.generation_bar.setFormat('%v / 5 阶段');self.generation_bar.setFixedHeight(18)
        self.generation_bar.setStyleSheet(f'QProgressBar{{border:1px solid {Colors.BORDER};border-radius:5px;background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};text-align:center;}}QProgressBar::chunk{{background:{Colors.ACCENT};border-radius:4px;}}')
        progress_layout.addWidget(self.generation_label);progress_layout.addWidget(self.generation_bar);root.addWidget(self.generation_panel);self.generation_panel.hide()
        self.generation_started=0;self.generation_text='';self.generation_clock=QTimer(self);self.generation_clock.setInterval(500);self.generation_clock.timeout.connect(self.refresh_generation_progress)
        self.generation_progress.connect(self.receive_generation_progress)
        split=QSplitter(Qt.Horizontal);self.main_splitter=split;split.setChildrenCollapsible(False)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(310)
        self.tabs.currentChanged.connect(self._fade_tab)
        self.build_blueprint();self.build_layout();self.build_editor();self.build_grading()
        split.addWidget(self.tabs)
        from echo.widgets.qingjuan_preview import PaperPreview
        self.preview=PaperPreview();self.preview.selected.connect(self.select_preview)
        self.preview.page().pdfPrintingFinished.connect(self.pdf_done)
        self.preview.loadFinished.connect(self.preview_loaded)
        split.addWidget(self.preview);split.setSizes([340,870]);split.setStretchFactor(1,1);root.addWidget(split,1)
        self.notice=QLabel('蓝图和卷稿保存在本机；AI 操作走 Echo 云端并按清卷用途计费。');self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText);root.addWidget(self.notice)
        chrome=install_chrome(self,root,minimize=True)
        self.pin_button=chrome.pin_control('置顶此工作台',self.toggle_pin)
        chrome.layout().insertWidget(chrome.layout().count()-2,self.pin_button)
        self.completed.connect(self.finish)
        self.save_timer=QTimer(self);self.save_timer.setSingleShot(True);self.save_timer.setInterval(800);self.save_timer.timeout.connect(self.autosave)
        self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(220);self.preview_timer.timeout.connect(self._render_preview_now)
        self.owner_timer=QTimer(self);self.owner_timer.setInterval(1000);self.owner_timer.timeout.connect(self.check_owner);self.owner_timer.start()
        self.populate();self.refresh_files();self.loading=False

    def showEvent(self,event):
        super().showEvent(event)
        if getattr(self,'_taskbar_set',False):return
        self._taskbar_set=True
        # Set this window's identity without changing other Echo windows/groups.
        import os
        if os.name=='nt':
            try:
                import ctypes,uuid
                from ctypes import wintypes
                class GUID(ctypes.Structure):_fields_=[('data',ctypes.c_ubyte*16)]
                def guid(value):return GUID((ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le))
                class Key(ctypes.Structure):_fields_=[('fmtid',GUID),('pid',wintypes.DWORD)]
                class Value(ctypes.Structure):_fields_=[('vt',ctypes.c_ushort),('r1',ctypes.c_ushort),('r2',ctypes.c_ushort),('r3',ctypes.c_ushort),('value',ctypes.c_void_p),('padding',ctypes.c_void_p)]
                shell=ctypes.WinDLL('shell32');fn=shell.SHGetPropertyStoreForWindow
                fn.argtypes=[wintypes.HWND,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)];fn.restype=ctypes.c_long
                iid=guid('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99');store=ctypes.c_void_p()
                if fn(int(self.winId()),ctypes.byref(iid),ctypes.byref(store))<0:return
                table=ctypes.cast(store,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                key=Key(guid('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'),5);text=ctypes.create_unicode_buffer('Echo.Qingjuan')
                value=Value();value.vt=31;value.value=ctypes.cast(text,ctypes.c_void_p)
                try:
                    ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,ctypes.POINTER(Key),ctypes.POINTER(Value))(table[6])(store,ctypes.byref(key),ctypes.byref(value))
                    ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p)(table[7])(store)
                finally:ctypes.WINFUNCTYPE(ctypes.c_ulong,ctypes.c_void_p)(table[2])(store)
            except Exception:
                import logging
                logging.getLogger('echo.qingjuan').warning('Could not set Qingjuan taskbar identity')

    def _fade_tab(self,index):
        try:
            from echo.widgets import motion
            motion.fade_widget(self.tabs.widget(index),motion.DURATION_PAGE,slide=6)
        except Exception:
            pass

    def toggle_pin(self):
        pinned=not bool(self.windowFlags()&Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint,pinned);self.pin_button.setChecked(pinned)
        self.pin_button.setToolTip('取消置顶' if pinned else '置顶此工作台');self.show()

    def popup(self,button,items):
        menu=style_menu(QMenu(self))
        for label,slot in items:
            if label is None:menu.addSeparator();continue
            menu.addAction(label,lambda fn=slot:self.guard(fn))
        menu.exec_(button.mapToGlobal(button.rect().bottomLeft()));menu.deleteLater()

    def show_more(self):
        self.popup(self.more_button,[('高级 · 导入卷稿 JSON',self.import_paper),('高级 · 导出卷稿 JSON',lambda:self.export('json')),
          (None,None),('按蓝图建立空白卷稿',self.blank_paper),('恢复已领取的命题结果',self.recover_received)])

    def show_exports(self):
        self.popup(self.export_button,[('导出 PDF',lambda:self.export('pdf')),('导出离线 HTML',lambda:self.export('html')),
          ('高级 · 导出 JSON',lambda:self.export('json'))])

    def open_exam(self):
        QDesktopServices.openUrl(QUrl('https://exam.echo.xhbtroy.cn'))
        self.notice.setText('已打开考试站，那里展示云端试卷；当前卷稿仍保存在本机。')

    def button(self,text,slot):
        b=QPushButton(text);b.setCursor(Qt.PointingHandCursor);b.clicked.connect(lambda _:self.guard(slot));return b

    def guard(self,slot):
        try:
            if not self.check_owner():return
            if self.busy or self.printing:raise ValueError('请求或导出正在处理中，请等待完成。')
            slot()
        except Exception as exc:self.notice.setText(str(exc))

    def scroll_form(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame)
        body=QWidget();body.setObjectName('QingjuanForm');scroll.setWidget(body)
        box=QVBoxLayout(body);box.setContentsMargins(3,10,8,5);box.setSpacing(10)
        return scroll,box

    def group(self,box,title):
        group=QGroupBox(title);body=QVBoxLayout(group);body.setSpacing(9);box.addWidget(group);return body

    def build_blueprint(self):
        page,box=self.scroll_form();self.fields={}
        intro=QLabel('先选学科与用途，一键套用蓝图，再交给 AI 命题。');intro.setWordWrap(True);box.addWidget(intro)
        info=self.group(box,'试卷信息');form=QFormLayout();form.setSpacing(9)
        choices={
          'title':['我的复习试卷','单元知识检测','期中复习试卷','期末复习试卷','错题巩固练习'],
          'subject':['数学','语文','英语','物理','化学','生物','历史','地理','道德与法治','科学'],
          'grade':['小学'+v+'年级' for v in '一二三四五六']+['初中'+v+'年级' for v in '一二三']+['高中'+v+'年级' for v in '一二三']+['大学'],
          'term':['上学期','下学期','全年','上册','下册'],
          'exam_name':['阶段检测','单元练习','期中考试','期末考试','中考模拟','高考模拟']}
        grid=QGridLayout();grid.setSpacing(8)
        for index,(key,label,default) in enumerate([('title','试卷名称','我的复习试卷'),('school','学校',''),('subject','学科','数学'),('grade','年级','初中二年级'),('term','学期 / 册别','上学期'),('exam_name','考试类型','阶段检测')]):
            w=editable_combo(choices[key]) if key in choices else QLineEdit(default)
            if isinstance(w,EchoCombo):w.setEditText(default);w.editTextChanged.connect(self.changed)
            else:w.setMaxLength(200);w.textChanged.connect(self.changed)
            self.fields[key]=w
            if index<2:form.addRow(label,w)
            else:
                row=(index-2)//2*2;col=(index-2)%2;grid.addWidget(QLabel(label),row,col);grid.addWidget(w,row+1,col)
        info.addLayout(form)
        self.fields['paper_scope']=combo([('正式整卷','full'),('专项练习','special')]);form.addRow('出卷用途',self.fields['paper_scope'])
        self.fields['duration']=spin(90,5,240);self.fields['duration'].setSuffix(' 分钟');self.fields['total_score']=spin(100,1,2000,True);self.fields['total_score'].setSuffix(' 分')
        for col,(key,label) in enumerate([('duration','时长'),('total_score','试卷总分')]):grid.addWidget(QLabel(label),4,col);grid.addWidget(self.fields[key],5,col)
        info.addLayout(grid)
        row=QHBoxLayout();self.preset_kind=combo([('学科推荐蓝图','balanced'),('选择题专项','choice'),('阅读专项','reading'),('写作专项','writing')]);row.addWidget(self.preset_kind,1)
        row.addWidget(self.button('套用蓝图',self.apply_template));info.addLayout(row)
        self.template_hint=QLabel();self.template_hint.setWordWrap(True);info.addWidget(self.template_hint)
        self.sections_body=self.group(box,'题型结构');self.section_rows=[];self.sections_box=QVBoxLayout();self.sections_box.setSpacing(10);self.sections_body.addLayout(self.sections_box)
        row=QHBoxLayout();row.addWidget(self.button('＋ 添加大题',self.add_section));row.addStretch();row.addWidget(self.button('同步总分',self.sync_total));self.sections_body.addLayout(row)
        self.blueprint_total=QLabel();self.sections_body.addWidget(self.blueprint_total)
        req=self.group(box,'命题要求');self.fields['extra_requirements']=QTextEdit();self.fields['extra_requirements'].setAcceptRichText(False)
        self.fields['extra_requirements'].setPlaceholderText('知识点 / 章节 / 课文 / 教材版本，例如：一次函数；几何题配图；不超出已学范围。')
        self.fields['extra_requirements'].setFixedHeight(100);self.fields['extra_requirements'].textChanged.connect(self.changed);req.addWidget(self.fields['extra_requirements'])
        form=QFormLayout();self.fields['review_strategy']=combo([('人工核对','human'),('AI辅助审核（手动触发）','ai')]);form.addRow('审校方式',self.fields['review_strategy'])
        self.fields['mode']=combo([('标准命题','standard'),('极速','fast'),('精细','fine')]);form.addRow('命题方式',self.fields['mode'])
        self.fields['figures']=combo([('按需配图','auto'),('丰富配图','rich'),('不配图','off')]);form.addRow('配图',self.fields['figures'])
        self.fields['figure_style']=combo([('教材线稿','line'),('卡通情景','cartoon'),('手绘风格','sketch')]);form.addRow('图形风格',self.fields['figure_style']);req.addLayout(form)
        for w in self.fields.values():
            if isinstance(w,EchoCombo):w.currentIndexChanged.connect(self.changed)
            elif isinstance(w,(QSpinBox,QDoubleSpinBox)):w.valueChanged.connect(self.changed)
        for key in ('subject','grade','paper_scope'):
            w=self.fields[key]
            (w.editTextChanged if w.isEditable() else w.currentIndexChanged).connect(self.template_context_changed)
        box.addStretch();self.tabs.addTab(page,'命题蓝图')

    def template_context_changed(self,*args):
        if self.loading:return
        self.template_hint.setText('推荐：'+self.value(self.fields['grade'])+' · '+self.value(self.fields['subject'])+'。点击“套用蓝图”更新结构，已有题目不会被替换。')

    def apply_template(self):
        if self.doc['state']=='final':raise ValueError('请先另存草稿。')
        result=local.blueprint_template(self.value(self.fields['subject']),self.value(self.fields['paper_scope']),self.preset_kind.currentData(),self.value(self.fields['grade']))
        self.loading=True;self.fill_sections(result['sections'])
        if self.preset_kind.currentData()!='balanced':self.set_value(self.fields['paper_scope'],'special')
        for key in ('total_score','duration','figures'):self.set_value(self.fields[key],result[key])
        self.set_value(self.layout_fields['template'],result['layout_template']);self.loading=False;self.changed()
        self.template_hint.setText('蓝图已套用 · '+str(len(result['sections']))+' 大题 · '+str(result['total_score'])+' 分；可以直接 AI 命题。')
        self.notice.setText('已更新命题蓝图，当前卷稿保留；点击 AI 命题生成新卷。')

    def build_layout(self):
        page,box=self.scroll_form();form=QFormLayout();self.layout_fields={}
        specs={'template':[('清爽现代','modern'),('正式考试','gaokao'),('小学练习','primary'),('英语试卷','english')],
          'colorMode':[('黑白打印','mono'),('彩色','color')],'density':[('紧凑','compact'),('标准','normal'),('宽松','loose')],
          'paperSize':[('A4','a4'),('16开','16k')],'columns':[('单栏',1),('双栏',2)],'optionCols':[('自动','auto'),('一列','1'),('两列','2'),('四列','4')]}
        names={'template':'模板','colorMode':'颜色','density':'密度','paperSize':'纸张','columns':'栏数','optionCols':'选项列数'}
        for key,items in specs.items():
            w=combo(items);w.currentIndexChanged.connect(self.changed);self.layout_fields[key]=w;form.addRow(names[key],w)
        box.addLayout(form)
        for key,title in [('bindLine','装订线'),('sealLine','密封线'),('instructions','考试说明'),('scoreBox','卷头分数栏'),('sectionScore','大题得分栏'),('splitVolume','分第I/II卷'),('essayGrid','作文方格'),('answerQuestion','答案页附题干'),('sheetHint','答题卡提示')]:
            w=QCheckBox(title);w.toggled.connect(self.changed);self.layout_fields[key]=w;box.addWidget(w)
        form=QFormLayout()
        for key,title in [('fields','卷头字段（逗号分隔）'),('watermark','水印'),('footerLeft','左页脚'),('footerRight','右页脚')]:
            w=QLineEdit();w.setMaxLength(200);w.textChanged.connect(self.changed);self.layout_fields[key]=w;form.addRow(title,w)
        box.addLayout(form);box.addWidget(QLabel('排版只在本机完成；公式、配图与字体均使用随程序附带的本地资源。'))
        box.addStretch();self.tabs.addTab(page,'排版')

    def build_editor(self):
        page,box=self.scroll_form()
        self.questions=QTreeWidget();self.questions.setHeaderHidden(True);self.questions.setMinimumHeight(170);self.questions.currentItemChanged.connect(self.load_question);box.addWidget(self.questions)
        row=QHBoxLayout()
        for title,fn in [('添加题目',self.add_question),('删除',self.delete_question),('↑',lambda:self.move_question(-1)),('↓',lambda:self.move_question(1)),('撤销',self.undo)]:row.addWidget(self.button(title,fn))
        box.addLayout(row);form=QFormLayout();self.qtype=combo([(v,k) for k,v in local.TYPES.items()]);form.addRow('题型',self.qtype)
        self.qscore=spin(5,.01,150,True);form.addRow('分值',self.qscore);self.qspace=spin(3,0,12);form.addRow('作答空白行',self.qspace)
        self.qknowledge=QLineEdit();form.addRow('知识点',self.qknowledge);self.qchars=spin(600,100,1500);form.addRow('作文格字数',self.qchars);box.addLayout(form)
        self.qtexts={}
        for key,title in [('stem','题干'),('options','选项（每行一个，不加字母）'),('answer','参考答案'),('analysis','解析'),('passage','阅读/完形材料'),('requirements','写作要求（每行一项）')]:
            box.addWidget(QLabel(title));w=QTextEdit();w.setAcceptRichText(False);w.setMinimumHeight(70);w.setMaximumHeight(140);self.qtexts[key]=w;box.addWidget(w)
        self.qpassage_title=QLineEdit();self.qpassage_author=QLineEdit();form=QFormLayout();form.addRow('材料标题',self.qpassage_title);form.addRow('材料作者',self.qpassage_author);box.addLayout(form)
        advanced_toggle=QPushButton('高级 · 配图数据与 JSON ▸');advanced_toggle.setCheckable(True);box.addWidget(advanced_toggle)
        advanced=QWidget();advanced_box=QVBoxLayout(advanced);advanced_box.setContentsMargins(0,0,0,0)
        advanced_box.addWidget(QLabel('结构配图 JSON（可留空）'))
        self.qfigure=QTextEdit();self.qfigure.setMaximumHeight(130);advanced_box.addWidget(self.qfigure)
        advanced_box.addWidget(self.button('复制所选题 JSON',self.copy_question));box.addWidget(advanced);advanced.hide()
        advanced_toggle.toggled.connect(advanced.setVisible)
        self._loading_question=False;self._question_dirty=False
        for w in list(self.qtexts.values())+[self.qfigure,self.qpassage_title,self.qpassage_author,self.qknowledge]:
            w.textChanged.connect(self.question_changed)
        self.qtype.currentIndexChanged.connect(self.question_changed)
        for w in (self.qscore,self.qspace,self.qchars):w.valueChanged.connect(self.question_changed)
        box.addWidget(self.button('应用题目修改',self.apply_question))
        box.addWidget(self.button('放弃当前题的未应用编辑',self.discard_question_edit))
        self.instruction=QLineEdit();self.instruction.setPlaceholderText('重出要求，例如：换一组数字、降低难度');box.addWidget(self.instruction)
        row=QHBoxLayout();row.addWidget(self.button('AI 重出此题',self.regenerate));row.addWidget(self.button('AI 配图',self.figure));box.addLayout(row)
        self.tabs.addTab(page,'题目编辑')

    def build_grading(self):
        page,box=self.scroll_form();hint=QLabel('在原生作答页完成试卷，客观题自动判分；交卷后可在这里手动批改主观题。网上作答请前往考试站。');hint.setWordWrap(True);box.addWidget(hint)
        row=QHBoxLayout();row.addWidget(self.button('开始本机作答',self.practice_paper));row.addWidget(self.button('网上作答 ↗',self.open_exam));box.addLayout(row)
        self.student_answers=QTextEdit(self);self.student_answers.hide()  # Internal transfer from native practice, never an input requirement.
        box.addWidget(self.button('AI 批改本机主观题',self.grade))
        self.grade_result=QTextEdit();self.grade_result.setReadOnly(True);box.addWidget(self.grade_result,1)
        box.addWidget(self.button('AI 审核当前卷稿',self.review))
        self.tabs.addTab(page,'审校与作答')

    def show_review_results(self):
        lines=[]
        practice=self.doc.get('practice',{})
        if practice.get('submitted'):
            results=practice.get('results',{});pending=sum(v.get('status')=='pending' for v in results.values())
            score=sum(v.get('awarded_points',0) for v in results.values());lines.append(f'本机试做 · 已判得分 {score:g} · {pending}题待批改\n')
        grading={g['id']:g for g in self.doc.get('grading',{}).get('grades',[])}
        for number,q in enumerate(self.leaves(),1):
            result=grading.get(q['id']) or practice.get('results',{}).get(q['id'])
            if result:lines.append(f"第{number}题 · {local.TYPES[q['type']]}\n{result.get('feedback','待批改')}\n")
        review=self.doc.get('review',{})
        if review:
            lines.extend(['卷稿审校',review.get('summary','')])
            for item in review.get('issues',[]):lines.append(' · '+item.get('message',''))
        self.grade_result.setPlainText('\n'.join(lines) or '还没有审校或作答记录。先完成命题，再打开本机作答；也可以手动 AI 审校卷稿。')

    def value(self,w):
        if isinstance(w,EchoCombo):return w.currentText().strip() if w.isEditable() else w.currentData()
        if isinstance(w,QCheckBox):return w.isChecked()
        if isinstance(w,(QSpinBox,QDoubleSpinBox)):return w.value()
        if isinstance(w,QTextEdit):return w.toPlainText()
        return w.text()

    def set_value(self,w,value):
        if isinstance(w,EchoCombo):
            if w.isEditable():w.setEditText(str(value))
            else:w.setCurrentIndex(max(0,w.findData(value)))
        elif isinstance(w,QCheckBox):w.setChecked(bool(value))
        elif isinstance(w,(QSpinBox,QDoubleSpinBox)):w.setValue(value)
        elif isinstance(w,QTextEdit):w.setPlainText(str(value))
        else:w.setText(str(value))

    def section_specs(self):
        return [{key:self.value(widget) for key,widget in row['fields'].items()} for row in self.section_rows]

    def add_section(self,spec=None):
        if len(self.section_rows)>=12:raise ValueError('最多12个大题。')
        spec=spec or {'title':'新大题','type':'short','count':1,'score_each':5,'difficulty':'mixed','knowledge':''}
        card=QWidget();card.setObjectName('SectionCard');box=QVBoxLayout(card);box.setContentsMargins(10,10,10,10);box.setSpacing(8)
        row={'card':card,'fields':{}};fields=row['fields'];title=QLineEdit(spec.get('title',''));title.setPlaceholderText('大题名称');title.textChanged.connect(self.changed);fields['title']=title
        heading=QHBoxLayout();heading.addWidget(title,1)
        for text,fn in [('↑',lambda:self.move_section_card(row,-1)),('↓',lambda:self.move_section_card(row,1)),('×',lambda:self.remove_section_card(row))]:
            button=self.button(text,fn);button.setStyleSheet('padding:0;min-width:24px;max-width:24px;min-height:24px;');button.setToolTip({'↑':'上移大题','↓':'下移大题','×':'删除大题'}[text]);heading.addWidget(button)
        box.addLayout(heading);grid=QGridLayout();grid.setSpacing(6)
        widgets={'type':combo([(v,k) for k,v in local.TYPES.items()]),'count':spin(spec['count'],1,20),'score_each':spin(spec['score_each'],.01,150,True),
          'difficulty':combo([('混合难度','mixed'),('基础','easy'),('中等','medium'),('困难','hard')]),'with_figures':combo([('按需配图',None),('必须配图',True),('不配图',False)])}
        self.set_value(widgets['type'],spec['type']);self.set_value(widgets['difficulty'],spec.get('difficulty','mixed'));self.set_value(widgets['with_figures'],spec.get('with_figures'))
        # 侧栏只有约 340px：EchoCombo 的圆角内边距让组合框最小宽动辄 100+，
        # 三列一排就把卡片撑到 335，整页出横向滚动条。这里压住下限，窄栏里允许省略。
        for key,limit in (('type',92),('count',56),('score_each',80),('difficulty',88),('with_figures',88)):
            widgets[key].setMinimumWidth(limit)
        for col,(key,label) in enumerate([('type','题型'),('count','题量'),('score_each','每题分')]):
            grid.addWidget(QLabel(label),0,col);grid.addWidget(widgets[key],1,col)
        grid.setColumnStretch(0,2);grid.setColumnStretch(1,1);grid.setColumnStretch(2,1);box.addLayout(grid)
        line=QHBoxLayout();line.addWidget(widgets['difficulty'],1);line.addWidget(widgets['with_figures'],1);box.addLayout(line)
        fields.update(widgets);knowledge=QLineEdit(spec.get('knowledge',''));knowledge.setPlaceholderText('本大题知识点 / 范围（可选）');knowledge.textChanged.connect(self.changed);fields['knowledge']=knowledge;box.addWidget(knowledge)
        for w in widgets.values():(w.currentIndexChanged if isinstance(w,EchoCombo) else w.valueChanged).connect(self.changed)
        self.section_rows.append(row);self.sections_box.addWidget(card);self.changed()

    def remove_section_card(self,row):
        if len(self.section_rows)<=1:raise ValueError('至少保留一个大题。')
        self.section_rows.remove(row);self.sections_box.removeWidget(row['card']);row['card'].deleteLater();self.changed()

    def move_section_card(self,row,direction):
        index=self.section_rows.index(row);target=index+direction
        if not 0<=target<len(self.section_rows):return
        self.section_rows[index],self.section_rows[target]=self.section_rows[target],self.section_rows[index]
        self.sections_box.removeWidget(row['card']);self.sections_box.insertWidget(target,row['card']);self.changed()

    def fill_sections(self,sections):
        for row in self.section_rows:self.sections_box.removeWidget(row['card']);row['card'].deleteLater()
        self.section_rows=[]
        for spec in sections:self.add_section(spec)

    def sync_total(self):self.fields['total_score'].setValue(sum(s['count']*s['score_each'] for s in self.section_specs()))

    def populate(self):
        self.loading=True;cfg=self.doc['config'];lay=self.doc['layout']
        self.student_answers.clear()
        for key,w in self.fields.items():self.set_value(w,cfg.get(key,local.DEFAULT_CONFIG.get(key,'')))
        self.fill_sections(cfg['sections'])
        for key,w in self.layout_fields.items():self.set_value(w,','.join(lay[key]) if key=='fields' else lay[key])
        self.show_review_results()
        self._question_dirty=False
        if not self.selected_path and self.doc.get('editor_drafts'):
            self.selected_path=[int(v) for v in next(iter(self.doc['editor_drafts'])).split('.')]
        self.loading=False;self.update_state();self.render_tree();self.render_preview()

    def capture(self,strict=False):
        cfg={**self.doc['config'],**{key:self.value(w) for key,w in self.fields.items()},'sections':self.section_specs()}
        lay={**self.doc['layout'],**{key:self.value(w) for key,w in self.layout_fields.items()}}
        lay['fields']=[v.strip() for v in lay['fields'].replace('，',',').split(',') if v.strip()];lay['figureStyle']=cfg['figure_style']
        if strict:cfg=local.config(cfg);lay=local.layout(lay)
        return cfg,lay

    def changed(self,*args):
        if self.loading or self.busy or self.doc['state']=='final':return
        try:
            sections=self.section_specs()
            self.blueprint_total.setText(f"合计 {sum(s['count'] for s in sections)} 主题 · {sum(s['count']*s['score_each'] for s in sections):g} 分")
        except (AttributeError,RuntimeError):pass
        if hasattr(self,'save_timer'):self.save_timer.start()

    def autosave(self):
        try:self.save_current(quiet=True)
        except Exception as exc:self.notice.setText('草稿未保存：'+str(exc))

    def save_current(self,quiet=False):
        if self.busy or not self.check_owner():return
        self.save_timer.stop()
        if self.doc['state']=='final':return
        self.stash_question_edit()
        cfg,lay=self.capture();updated=copy.deepcopy(self.doc);updated.update(config=cfg,layout=lay)
        if updated['paper']:
            updated['paper']['meta'].update({k:cfg[k] for k in ('title','school','subject','grade','term','duration')})
            if len(updated['paper']['sections'])==len(cfg['sections']):
                for section,spec in zip(updated['paper']['sections'],cfg['sections']):
                    if spec['title']:section['title']=spec['title']
        preview_changed=updated.get('paper')!=self.doc.get('paper') or lay!=self.doc.get('layout')
        library_changed=cfg.get('title')!=self.doc['config'].get('title')
        local.save(updated);self.doc=updated
        if library_changed or not quiet:self.refresh_files()
        self.update_state()
        if not quiet:self.notice.setText('已保存本机草稿；尚未应用的题目编辑请点“应用题目修改”。')
        if preview_changed:self.render_preview()

    def refresh_files(self):
        self.documents=local.list_documents(self.owner);self.file_list.blockSignals(True);self.file_list.clear()
        for d in self.documents:self.file_list.addItem(('定稿 · ' if d['state']=='final' else '草稿 · ')+d['config'].get('title','未命名'),d['id'])
        index=self.file_list.findData(self.doc['id'])
        if index<0:self.file_list.insertItem(0,'新草稿 · '+self.doc['config'].get('title','未命名'),self.doc['id']);index=0
        self.file_list.setCurrentIndex(index);self.file_list.blockSignals(False)

    def open_selected(self,index):
        ident=self.file_list.itemData(index)
        if not ident or ident==self.doc['id']:return
        self.guard(lambda:self.load_document(ident))

    def load_document(self,ident):
        if self.busy:raise ValueError('请等待AI请求结束。')
        self.save_current(quiet=True);self.doc=local.load(self.owner,ident);self.selected_path=None;self.populate();self.refresh_files()

    def new_document(self):
        if self.busy:raise ValueError('请等待AI请求结束。')
        self.save_current(quiet=True);self.doc=local.new(self.owner);self.selected_path=None;local.save(self.doc);self.populate();self.refresh_files()

    def fork(self):
        if self.busy:raise ValueError('请等待AI请求结束。')
        self.save_current(quiet=True);self.doc=local.fork(self.doc);self.populate();self.refresh_files();self.notice.setText('已另存为新草稿，原定稿保持不变。')

    def update_state(self):
        final=self.doc['state']=='final';self.state_label.setText(('已定稿 · ' if final else '本机草稿 · ')+f"版本 {self.doc['revision']}")
        self.generate_button.setEnabled(not final and not self.busy and local.GENERATION_ENABLED);self.retry_button.setEnabled(not final and not self.busy and bool(self.doc.get('pending',{}).get('generate')))
        self.retry_button.setVisible(bool(self.doc.get('pending',{}).get('generate')))
        self.final_button.setEnabled(not final and not self.busy and bool(self.doc.get('paper')))
        for index in range(3):self.tabs.setTabEnabled(index,not final and not self.busy)

    def render_tree(self):
        if not self.doc.get('practice'):self.student_answers.clear()
        self.show_review_results()
        self.questions.blockSignals(True);self.questions.clear();self.tree_paths={}
        def append(parent,q,path):
            item=QTreeWidgetItem([local.TYPES[q['type']]+' · '+q['stem'][:24]+f" ({q['score']:g}分)"]);item.setData(0,Qt.UserRole,path);parent.addChild(item);self.tree_paths[tuple(path)]=item
            for i,c in enumerate(q.get('questions',[])):append(item,c,path+[i])
        for si,s in enumerate((self.doc.get('paper') or {}).get('sections',[])):
            group=QTreeWidgetItem([s['title']]);self.questions.addTopLevelItem(group)
            for qi,q in enumerate(s['questions']):append(group,q,[si,qi])
            group.setExpanded(True)
        self.questions.blockSignals(False)
        if self.selected_path and tuple(self.selected_path) in self.tree_paths:self.questions.setCurrentItem(self.tree_paths[tuple(self.selected_path)])

    def question(self,path=None,paper=None):
        path=path or self.selected_path
        if not path or len(path) not in (2,3):raise ValueError('请先在题目树或预览中选择一道题。')
        paper=paper or self.doc.get('paper');q=paper['sections'][path[0]]['questions'][path[1]]
        return q['questions'][path[2]] if len(path)==3 else q

    def load_question(self,item,previous=None):
        if not item or item.data(0,Qt.UserRole) is None:return
        self.stash_question_edit()
        self.selected_path=list(item.data(0,Qt.UserRole));q=self.question()
        self._loading_question=True
        self.set_value(self.qtype,q['type']);self.qscore.setValue(q['score']);self.qspace.setValue(q.get('answer_space',3));self.qknowledge.setText(q.get('knowledge',''))
        self.qchars.setValue(q.get('grid',{}).get('chars',600))
        for key,w in self.qtexts.items():w.setPlainText('\n'.join(q.get(key,[])) if key in ('options','requirements') else q.get(key,''))
        self.qpassage_title.setText(q.get('passage_title',''));self.qpassage_author.setText(q.get('passage_author',''))
        self.qfigure.setPlainText(json.dumps(q['figure'],ensure_ascii=False,indent=2) if q.get('figure') else '')
        draft=self.doc.get('editor_drafts',{}).get('.'.join(map(str,self.selected_path)))
        if draft:
            self.set_value(self.qtype,draft['type']);self.qscore.setValue(draft['score']);self.qspace.setValue(draft['space']);self.qchars.setValue(draft['chars']);self.qknowledge.setText(draft['knowledge'])
            for key,w in self.qtexts.items():w.setPlainText(draft['texts'][key])
            self.qpassage_title.setText(draft['passage_title']);self.qpassage_author.setText(draft['passage_author']);self.qfigure.setPlainText(draft['figure'])
            self.notice.setText('已恢复这道题的未应用编辑；应用后才进入预览、命题和导出。')
        self._loading_question=False;self._question_dirty=bool(draft)

    def question_changed(self,*args):
        if self.loading or self._loading_question or not self.selected_path or self.doc['state']=='final':return
        self._question_dirty=True;self.save_timer.start()

    def stash_question_edit(self):
        if not self._question_dirty or not self.selected_path:return
        self.doc.setdefault('editor_drafts',{})['.'.join(map(str,self.selected_path))]={
          'type':self.qtype.currentData(),'score':self.qscore.value(),'space':self.qspace.value(),'chars':self.qchars.value(),
          'knowledge':self.qknowledge.text(),'texts':{k:w.toPlainText() for k,w in self.qtexts.items()},
          'passage_title':self.qpassage_title.text(),'passage_author':self.qpassage_author.text(),'figure':self.qfigure.toPlainText()}

    def require_applied(self):
        if self._question_dirty or self.doc.get('editor_drafts'):raise ValueError('仍有未应用的题目草稿，请逐题应用或放弃后继续；草稿已可保存在本机。')

    def discard_question_edit(self):
        if not self.selected_path:return
        self._question_dirty=False;self.doc.get('editor_drafts',{}).pop('.'.join(map(str,self.selected_path)),None);local.save(self.doc)
        self.load_question(self.questions.currentItem())

    def select_preview(self,value):
        try:
            path=tuple(int(v) for v in value.split('.'))
            if path in self.tree_paths:self.tabs.setCurrentIndex(2);self.questions.setCurrentItem(self.tree_paths[path])
        except (ValueError,IndexError):pass

    def editable(self):
        if self.busy or self.doc['state']=='final':raise ValueError('请先另存草稿，或等待请求完成。')
        if not self.doc.get('paper'):raise ValueError('请先命题或导入试卷。')

    def apply_question(self):
        self.editable();paper=copy.deepcopy(self.doc['paper']);q=self.question(paper=paper)
        q.update(type=self.qtype.currentData(),score=self.qscore.value(),answer_space=self.qspace.value(),knowledge=self.qknowledge.text(),grid={'chars':self.qchars.value()})
        for key,w in self.qtexts.items():q[key]=[v.strip() for v in w.toPlainText().splitlines() if v.strip()] if key in ('options','requirements') else w.toPlainText()
        q['passage_title']=self.qpassage_title.text();q['passage_author']=self.qpassage_author.text()
        q['figure']=json.loads(self.qfigure.toPlainText()) if self.qfigure.toPlainText().strip() else None
        updated=copy.deepcopy(self.doc);updated.get('editor_drafts',{}).pop('.'.join(map(str,self.selected_path)),None)
        local.replace_paper(updated,paper);self.doc=updated;self._question_dirty=False
        self.render_tree();self.render_preview();self.update_state();self.notice.setText('题目已应用并保存在本机；原版可撤销。')

    def question_list(self,paper=None):
        path=self.selected_path
        if not path:raise ValueError('请先选择一道题。')
        p=paper or self.doc['paper'];items=p['sections'][path[0]]['questions']
        return (items[path[1]]['questions'],path[2]) if len(path)==3 else (items,path[1])

    def add_question(self):
        self.editable();self.require_applied();paper=copy.deepcopy(self.doc['paper'])
        if not self.selected_path:self.selected_path=[0,0]
        items,index=self.question_list(paper)
        items.insert(index+1,{'type':'short','stem':'请在这里编辑新题。','answer':'待核对','analysis':'待补充解析','score':5})
        local.replace_paper(self.doc,paper);self.render_tree();self.render_preview();self.notice.setText('已添加待编辑题目；定稿前请替换占位内容并核对分值。')

    def delete_question(self):
        self.editable();self.require_applied();paper=copy.deepcopy(self.doc['paper']);items,index=self.question_list(paper)
        if len(items)<=1:raise ValueError('至少保留一道题；整大题删除可通过JSON导入调整。')
        items.pop(index);local.replace_paper(self.doc,paper);self.selected_path=None;self.render_tree();self.render_preview()

    def move_question(self,direction):
        self.editable();self.require_applied();paper=copy.deepcopy(self.doc['paper']);items,index=self.question_list(paper);target=index+direction
        if not 0<=target<len(items):return
        items[index],items[target]=items[target],items[index];self.selected_path[-1]=target
        local.replace_paper(self.doc,paper);self.render_tree();self.render_preview()

    def undo(self):
        self.editable();self.require_applied()
        if not self.doc['history']:raise ValueError('没有可撤销的题目版本。')
        updated=copy.deepcopy(self.doc);updated['paper']=updated['history'].pop()['paper'];updated['grading']={};updated.pop('review',None);updated.pop('practice',None);local.save(updated);self.doc=updated;self.render_tree();self.render_preview()

    def copy_question(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(json.dumps(self.question(),ensure_ascii=False,indent=2));self.notice.setText('所选题目JSON已复制。')

    def render_preview(self,*args):
        if not hasattr(self,'preview') or self.closed:return
        if hasattr(self,'preview_timer'):self.preview_timer.start()

    def _render_preview_now(self):
        if self.closed or local.owner()!=self.owner:return
        if not self.doc.get('paper'):
            self.preview.show_empty();return
        try:self.preview.render(self.doc['paper'],local.layout(self.doc['layout']),self.export_kind.currentData())
        except Exception as exc:self.notice.setText('排版未完成：'+str(exc))

    def launch(self,operation,payload,fresh=False):
        if self.busy:raise ValueError('已有请求处理中。')
        if local.owner()=='local-guest':raise ValueError('请先在设置登录Echo账户，再重新打开清卷工作台。')
        if not QMessageBox.question(self,'清卷 · 云端 AI','本次'+{'generate':'命题','regenerate':'重出','figure':'配图','grade':'批改','review':'审校'}[operation]+'将发送相关内容到Echo云端并按实际token计费。继续？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:return
        self.busy=True;self.tabs.setEnabled(False);self.update_state();self.notice.setText('清卷AI正在处理，请等待；不会自动重复发起新请求。')
        self.generation_started=time.monotonic();self.generation_text='准备请求';self.generation_bar.setValue(0);self.generation_panel.show();self.generation_clock.start();self.refresh_generation_progress()
        document=copy.deepcopy(self.doc);who=self.owner
        def work():
            try:value={'result':local.ai(document,operation,payload,fresh,on_progress=lambda value:self.generation_progress.emit(who,value)),'document':document,'payload':payload};error=''
            except Exception as exc:value={'document':document};error=str(exc)
            if local.owner()!=who:error='账户已变化，旧账户回复未在此窗口显示。'
            try:self.completed.emit(operation,value,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='echo-qingjuan-'+operation).start()

    def receive_generation_progress(self,who,value):
        if self.closed or not self.busy or who!=self.owner or local.owner()!=who:return
        self.generation_bar.setValue(max(0,min(3,int(value['step']))));self.generation_text=value['text'];self.refresh_generation_progress()

    def refresh_generation_progress(self):
        elapsed=max(0,int(time.monotonic()-self.generation_started))
        self.generation_label.setText(self.generation_text+f' · 已等待 {elapsed} 秒')

    def generate(self,retry=False):
        if self.doc['state']=='final':raise ValueError('请先另存草稿。')
        self.require_applied()
        self.save_current(quiet=True);cfg,lay=self.capture(strict=True)
        if retry:
            pending=self.doc.get('pending',{}).get('generate')
            if not pending or pending.get('fingerprint')!=local.fingerprint({'operation':'generate','payload':{'config':cfg,'layout':lay}}):raise ValueError('蓝图或排版已改变，不能作为原任务重试。请明确发起新命题。')
        self.launch('generate',{'config':cfg,'layout':lay},fresh=not retry)

    def recover_received(self):
        if self.doc['state']=='final':raise ValueError('请先另存草稿。')
        paper=self.doc.get('received',{}).get('paper')
        if not paper:raise ValueError('没有已领取的命题结果。')
        local.replace_paper(self.doc,paper);self.render_tree();self.render_preview();self.update_state()
        self.notice.setText('已恢复本机领取副本，未重新调用AI。请核对题量、分值和答案后再定稿。')

    def blank_paper(self):
        if self.doc['state']=='final':raise ValueError('请先另存草稿。')
        self.save_current(quiet=True);cfg,lay=self.capture(strict=True)
        if self.doc.get('paper') and QMessageBox.question(self,'新建离线卷稿','用待编辑卷稿替换当前内容？原版可从撤销中找回。')!=QMessageBox.Yes:return
        paper={'meta':{k:cfg[k] for k in ('title','school','subject','grade','term','duration')},'sections':[]}
        for spec in cfg['sections']:
            questions=[]
            for index in range(spec['count']):
                q={'type':spec['type'],'stem':'待编辑题目 '+str(index+1),'score':spec['score_each'],'answer':'待核对','analysis':'待补充解析','knowledge':spec['knowledge'],'answer_space':3}
                if q['type'] in ('choice','multi'):q.update(options=['选项一','选项二'],answer='A')
                elif q['type']=='tf':q['answer']='正确'
                elif q['type'] in ('reading','cloze'):
                    q['passage']='请补充完整阅读材料。';q['questions']=[{'type':'short','stem':'待编辑子题','answer':'待核对','analysis':'待补充解析','score':q['score']}]
                questions.append(q)
            paper['sections'].append({'title':spec['title'] or local.TYPES[spec['type']],'type':spec['type'],'questions':questions})
        local.replace_paper(self.doc,paper);self.render_tree();self.render_preview();self.update_state();self.tabs.setCurrentIndex(2)
        self.notice.setText('已离线建卷。所有占位题需编辑核对后才能定稿，未调用AI。')

    def regenerate(self):
        self.editable();self.require_applied();self.save_current(quiet=True)
        self.launch('regenerate',{'config':self.doc['config'],'section':self.doc['paper']['sections'][self.selected_path[0]],'question':self.question(),'instruction':self.instruction.text(),'path':self.selected_path},fresh=True)

    def figure(self):
        self.editable();self.require_applied();self.save_current(quiet=True)
        self.launch('figure',{'config':self.doc['config'],'question':self.question(),'path':self.selected_path},fresh=True)

    def leaves(self):
        result=[]
        for s in (self.doc.get('paper') or {}).get('sections',[]):
            for q in s['questions']:result.extend(q.get('questions') or [q])
        return result

    def answer_template(self):self.student_answers.setPlainText(json.dumps({q['id']:'' for q in self.leaves()},ensure_ascii=False,indent=2))

    def grade(self):
        if not self.doc.get('paper'):raise ValueError('请先打开一张试卷。')
        self.require_applied()
        raw=self.student_answers.toPlainText().strip()
        practice=self.doc.get('practice',{})
        if raw:answers=json.loads(raw)
        elif practice.get('submitted') and practice.get('paper_hash')==local.fingerprint(self.doc['paper']):answers=practice.get('answers',{})
        else:raise ValueError('请先在本机作答页完成并提交试卷。')
        allowed={q['id'] for q in self.leaves()}
        if not isinstance(answers,dict) or set(answers)-allowed or not answers:raise ValueError('作答JSON中包含未知题号或没有作答。')
        previous=self.doc.get('practice',{}).get('answers',{})
        combined={**previous,**{k:str(v)[:12000] for k,v in answers.items()}}
        self.doc['practice']={'paper_hash':local.fingerprint(self.doc['paper']),'answers':combined,'submitted':True,
            'results':local.objective_results(self.doc['paper'],combined)}
        local.save(self.doc)
        entries=[{**q,'student_answer':combined[q['id']]} for q in self.leaves() if q['type'] not in ('choice','multi','tf') and combined.get(q['id'],'').strip()]
        if not entries:
            self.show_review_results();self.notice.setText('客观题已在本机自动判分；没有已作答的主观题，未调用AI。');return
        self.launch('grade',{'entries':entries},fresh=True)

    def practice_paper(self):
        self.require_applied();self.save_current(quiet=True)
        if not self.doc.get('paper'):raise ValueError('请先命题或导入试卷。')
        from echo.widgets.qingjuan_practice import LocalPaperPractice
        dialog=LocalPaperPractice(self.doc,self);dialog.exec_()
        if not self.check_owner():return
        self.doc=dialog.doc;self.update_state()
        if dialog.practice['submitted']:
            pending={key:dialog.practice['answers'].get(key,'') for key,result in dialog.practice['results'].items() if result.get('status')=='pending'}
            self.student_answers.setPlainText(json.dumps(pending,ensure_ascii=False,indent=2))
            self.show_review_results()
            self.tabs.setCurrentIndex(3)
            self.notice.setText('本机试做已保存。客观题自动判分；主观题仍需你手动点击AI批改。')

    def review(self):
        if not self.doc.get('paper'):raise ValueError('请先打开一张试卷。')
        self.require_applied();self.save_current(quiet=True)
        self.launch('review',{'config':self.doc['config'],'paper':self.doc['paper']},fresh=True)

    def finish(self,operation,value,error):
        self.busy=False;self.tabs.setEnabled(True);self.generation_clock.stop()
        if not self.check_owner():return
        self.doc=value['document'];self.update_state()
        if error:
            self.generation_text='未完成，原卷保留';self.refresh_generation_progress()
            self.notice.setText('请求未完成：'+error+'。可重试原请求，不要重复付费命题。');return
        try:
            self.generation_bar.setValue(4);self.generation_text='校验题量、题型与分值';self.refresh_generation_progress()
            result=value['result']
            if operation=='generate':
                paper=local.normalize(result.get('paper',result));cfg=value['payload']['config']
                if len(paper['sections'])!=len(cfg['sections']):raise ValueError('AI大题数量不符，原卷已保留。')
                for actual,spec in zip(paper['sections'],cfg['sections']):
                    if len(actual['questions'])!=spec['count'] or any(q['type']!=spec['type'] or abs(q['score']-spec['score_each'])>.01 for q in actual['questions']):raise ValueError('AI题量、题型或分值不符，原卷已保留。')
                paper['meta'].update({k:cfg[k] for k in ('title','school','subject','grade','term','duration')});local.replace_paper(self.doc,paper)
            elif operation in ('regenerate','figure'):
                paper=copy.deepcopy(self.doc['paper']);path=value['payload']['path'];q=self.question(path,paper)
                if operation=='figure':q['figure']=result.get('figure')
                else:
                    replacement=result.get('question',result)
                    if replacement.get('type')!=q['type'] or replacement.get('score')!=q['score']:raise ValueError('重出题型/分值不一致，原题已保留。')
                    q.clear();q.update(replacement)
                local.replace_paper(self.doc,paper)
            elif operation=='grade':
                allowed={q['id'] for q in value['payload']['entries']};grades=result.get('grades')
                if not isinstance(grades,list) or {g.get('id') for g in grades}!=allowed or len(grades)!=len(allowed):raise ValueError('AI批改题号不完整，未覆盖原结果。')
                for g in grades:
                    if type(g.get('score')) not in (int,float) or not 0<=g['score']<=1 or not isinstance(g.get('feedback'),str) or not g['feedback'].strip():raise ValueError('AI批改分值/依据无效。')
                self.doc['grading']={'at':time.time(),'grades':grades}
                practice=self.doc.get('practice',{})
                if practice.get('paper_hash')==local.fingerprint(self.doc['paper']):
                    points={q['id']:q['score'] for q in self.leaves()}
                    for g in grades:practice['results'][g['id']]={**g,'status':'correct' if g['score']==1 else 'partial' if g['score'] else 'incorrect','awarded_points':g['score']*points[g['id']]}
                local.save(self.doc)
                self.show_review_results()
            elif operation=='review':
                issues=result.get('issues');ids={q['id'] for s in self.doc['paper']['sections'] for q in s['questions']}|{q['id'] for q in self.leaves()}|{'meta'}
                if type(result.get('approved')) is not bool or not isinstance(result.get('summary'),str) or not isinstance(issues,list) or len(issues)>20:raise ValueError('审校结果格式无效。')
                for item in issues:
                    if item.get('id') not in ids or item.get('severity') not in ('error','warning','info') or not isinstance(item.get('message'),str):raise ValueError('审校问题的题号或内容无效。')
                self.doc['review']={**result,'approved':result['approved'] and not any(i['severity']=='error' for i in issues),'paper_hash':local.fingerprint(self.doc['paper']),'at':time.time()}
                local.save(self.doc);self.show_review_results()
            self.refresh_files();self.render_tree();self.render_preview();self.update_state();self.notice.setText('清卷'+{'generate':'命题','regenerate':'重出','figure':'配图','grade':'批改','review':'审校'}[operation]+'已完成并保存本机，请人工核对。用量可在设置“AI调用与用量”查看。')
            self.generation_bar.setValue(5);self.generation_text='已完成并保存';self.refresh_generation_progress()
        except Exception as exc:
            self.generation_text='校验未通过，原卷保留';self.refresh_generation_progress()
            self.notice.setText(str(exc)+' AI调用可能已产生实际用量，请先核对请求记录。')

    def finalize(self):
        self.require_applied()
        self.save_current(quiet=True)
        if QMessageBox.question(self,'清卷定稿','确认已核对所有题干、分值、答案与配图？定稿后须另存草稿才能修改。',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        local.finalize(self.doc);self.update_state();self.refresh_files();self.notice.setText('已在本机定稿。导出试卷/答案/答题卡前请选择右上角视图。')

    def import_paper(self):
        if self.busy:raise ValueError('请等待当前请求结束。')
        filename,_=QFileDialog.getOpenFileName(self,'导入清卷JSON','','JSON (*.json)')
        if not filename:return
        file=Path(filename)
        if file.stat().st_size>4*1024*1024:raise ValueError('导入文件最多4MiB。')
        raw=json.loads(file.read_text(encoding='utf-8-sig'));paper=local.normalize(raw.get('paper',raw))
        self.save_current(quiet=True);self.doc=local.new(self.owner);self.doc['paper']=paper
        cfg=raw.get('config') or paper.get('config')
        if cfg:self.doc['config']=local.config(cfg)
        else:
            self.doc['config'].update({k:paper['meta'][k] for k in ('title','school','subject','grade','term')})
            self.doc['config']['total_score']=paper['meta']['total_score']
            self.doc['config']['duration']=paper['meta'].get('duration',90)
            self.doc['config']['sections']=[{'title':s['title'],'type':s['questions'][0]['type'],'count':len(s['questions']),
              'score_each':s['questions'][0]['score'],'difficulty':'mixed','knowledge':''} for s in paper['sections']]
        if raw.get('layout'):self.doc['layout']=local.layout(raw['layout'])
        local.save(self.doc);self.populate();self.refresh_files();self.notice.setText('已导入为本机草稿，未上传或调用AI。')

    def export(self,kind):
        self.require_applied()
        self.save_current(quiet=True)
        if not self.doc.get('paper'):raise ValueError('请先命题或导入试卷。')
        view=self.export_kind.currentData();filename,_=QFileDialog.getSaveFileName(self,'导出清卷',str(Path.home()/'Documents'/('清卷-'+view+'.'+kind)),kind.upper()+' (*.'+kind+')')
        if not filename:return
        file=Path(filename)
        if file.suffix.lower()!='.'+kind:file=Path(str(file)+'.'+kind)
        if kind=='json':
            file.write_text(json.dumps({'schema':'echo.qingjuan.paper/1','paper':self.doc['paper'],'config':self.doc['config'],'layout':self.doc['layout']},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');self.notice.setText('已导出清卷JSON，不包含账户凭据或请求缓存。')
        elif kind=='html':
            from echo.widgets.qingjuan_preview import html
            file.write_text(html(self.doc['paper'],self.doc['layout'],view,standalone=True),encoding='utf-8');self.notice.setText('已导出离线HTML，含公式字体和配图；无需联网。')
        else:
            self.printing=True;self.tabs.setEnabled(False);self.export_kind.setEnabled(False)
            self._pdf_pending={'file':str(file),'paperSize':self.doc['layout']['paperSize'],'checks':0}
            self.notice.setText('正在等待本地公式、字体和分页完成，然后导出PDF…');self.preview_timer.stop();self._render_preview_now()
            self._pdf_pending['render_key']=self.preview.render_key
            QTimer.singleShot(100,self.wait_pdf_ready)

    def preview_loaded(self,ok):
        if not self._pdf_pending:return
        if not ok:return
        self.wait_pdf_ready()

    def wait_pdf_ready(self):
        if not self._pdf_pending:return
        if local.owner()!=self.owner:self.pdf_done('',False);return
        self._pdf_pending['checks']+=1
        if self._pdf_pending['checks']>150:self.pdf_done('',False);return
        def ready(ok):
            if not self._pdf_pending:return
            if not ok:QTimer.singleShot(100,self.wait_pdf_ready);return
            pending=self._pdf_pending;self._pdf_pending=None
            size=QPageSize(QSizeF(185,260),QPageSize.Millimeter) if pending['paperSize']=='16k' else QPageSize(QPageSize.A4)
            self.preview.page().printToPdf(pending['file'],QPageLayout(size,QPageLayout.Portrait,QMarginsF(0,0,0,0)))
        key=self._pdf_pending.get('render_key','')
        self.preview.page().runJavaScript('window.echoReady===true && window.echoRenderId==='+json.dumps(key),ready)

    def pdf_done(self,filename,ok):
        self.printing=False;self._pdf_pending=None;self.tabs.setEnabled(True);self.export_kind.setEnabled(True);self.update_state()
        self.notice.setText('PDF已导出：'+filename if ok else 'PDF导出失败，请核对排版并重新选择可写路径。')

    def check_owner(self):
        if self.closed:return False
        if local.owner()==self.owner:return True
        self.generation_clock.stop();self.generation_panel.hide()
        self.save_timer.stop();self.preview_timer.stop();self.owner_timer.stop();self.tabs.setEnabled(False);self.tabs.hide();self.file_list.clear();self.state_label.setText('账户已变化')
        self.generate_button.setEnabled(False);self.retry_button.setEnabled(False);self.final_button.setEnabled(False)
        self.preview.clear_content();self.preview.setHtml('<html><body>账户已变化，请重新打开清卷工作台。</body></html>')
        self.notice.setText('账户已变化。旧卷稿保留在原账户的本机目录中，请关闭后重新打开。');return False

    def reject(self):self.close()

    def closeEvent(self,event):
        if self.busy or self.printing:self.notice.setText('正在处理AI请求或导出，请完成后再关闭，避免误重复操作。');event.ignore();return
        try:
            if local.owner()==self.owner:self.save_current(quiet=True)
        except Exception as exc:self.notice.setText('本地保存失败，请先导出备份：'+str(exc));event.ignore();return
        self.closed=True;self.save_timer.stop();self.preview_timer.stop();self.owner_timer.stop();self.preview.cleanup();event.accept();QDialog.reject(self)
