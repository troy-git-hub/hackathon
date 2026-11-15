"""Cross-lesson revision bookshelf, with optional one-request AI composition."""
import html
import threading
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QListWidget,
                             QListWidgetItem,QTextBrowser,QCheckBox,QDialogButtonBox,QSplitter)
from echo.backend import booklets, config, providers
from echo.theme import Colors, dialog_qss
from echo.widgets.echo_combo import EchoCombo


class BookletComposer(QDialog):
    def __init__(self, topics, parent=None, current=False):
        super().__init__(parent)
        self.topics = topics
        self.setWindowTitle('我的小本 · 新建')
        self.resize(540,570)
        root = QVBoxLayout(self)
        root.addWidget(QLabel('把相关知识收在一起，按大类和章节复习。'))
        self.title = QLineEdit('这段知识' if current else '新的复习主题')
        self.group = EchoCombo()
        self.group.setEditable(True)
        self.group.addItems(sorted({t['category'] for t in topics}) or ['未分类'])
        root.addWidget(self.title)
        root.addWidget(self.group)
        self.list = QListWidget()
        for topic in topics:
            item = QListWidgetItem(topic['category']+' / '+topic['name']+(' · 当前课堂' if topic['live'] else ''))
            item.setData(Qt.UserRole,topic)
            item.setCheckState(Qt.Checked if topic['live'] or not current and self.list.count()<3 else Qt.Unchecked)
            self.list.addItem(item)
        root.addWidget(self.list,1)
        self.ai = QCheckBox('用 AI 整理知识联系和自测 · 本次一次请求')
        online = not config.OFFLINE and providers.configured(providers.text())
        if getattr(getattr(parent,'engine',None),'_online_llm',None) is not None:
            online = False
        self.ai.setChecked(online)
        self.ai.setEnabled(online)
        root.addWidget(self.ai)
        buttons = QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('生成内容' if online else '保存摘录')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.setStyleSheet(dialog_qss()+f'QListWidget{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:10px;padding:8px;}}QListWidget::item{{padding:9px;}}')

    def selected(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState()==Qt.Checked]


class BookletWindow(QDialog):
    completed = pyqtSignal(int,object,str)

    def __init__(self, engine=None, parent=None):
        super().__init__(parent,Qt.Window)
        self.engine, self._request, self._busy = engine,0,False
        self.setWindowTitle('Echo · 我的小本')
        self.resize(940,650)
        self.setMinimumSize(720,480)
        self.setStyleSheet(dialog_qss()+f'QListWidget,QTextBrowser{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:12px;padding:12px;}}QListWidget::item{{padding:12px 6px;}}QListWidget::item:selected{{background:{Colors.ACCENT_SOFT};color:{Colors.ACCENT};}}')
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel('我的小本')
        title.setStyleSheet('font-size:24px;font-weight:600;')
        header.addWidget(title,1)
        self.exam_button = QPushButton('考试机 · Beta')
        self.exam_button.setToolTip('选择几个章节，合并成完整试卷。')
        self.exam_button.clicked.connect(self.open_exam)
        header.addWidget(self.exam_button)
        self.new = QPushButton('＋ 新建小本')
        self.new.clicked.connect(lambda:self.create())
        header.addWidget(self.new)
        root.addLayout(header)
        self.filter = EchoCombo()
        self.filter.currentTextChanged.connect(self.refresh_list)
        root.addWidget(self.filter)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(8)
        split.setStyleSheet(f'QSplitter::handle{{background:{Colors.WINDOW_BG};}}')
        self.list = QListWidget()
        self.list.setMaximumWidth(260)
        self.list.currentRowChanged.connect(self.read)
        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(False)
        split.addWidget(self.list)
        split.addWidget(self.reader)
        split.setStretchFactor(1,1)
        root.addWidget(split,1)
        self.status = QLabel('按大类收集知识，跨课阅读与复习。')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.completed.connect(self.finish)
        self.refresh()

    def refresh(self):
        try: self.items = sorted(booklets.load(),key=lambda b:b.get('updated_at',0),reverse=True)
        except ValueError as exc:
            self.items=[]
            self.status.setText(str(exc))
        group = self.filter.currentText()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItems(['全部大类']+sorted({b['category'] for b in self.items}))
        self.filter.setCurrentText(group if group else '全部大类')
        self.filter.blockSignals(False)
        self.refresh_list()

    def refresh_list(self):
        self.visible_items = [b for b in self.items if self.filter.currentText()=='全部大类' or b['category']==self.filter.currentText()]
        self.list.clear()
        for item in self.visible_items:
            self.list.addItem(item['title']+'\n'+item['category']+f" · {len(item['topics'])}个知识点")
        if self.visible_items: self.list.setCurrentRow(0)
        else: self.reader.setPlainText('小本里还没有内容。\n\n新建一个主题，收集相关知识点，按“函数”“近代史”这样的大类复习。')

    def read(self, row):
        if not 0<=row<len(self.visible_items): return
        item = self.visible_items[row]
        esc = lambda text:html.escape(str(text)).replace('\n','<br>')
        parts = [f"<h1>{esc(item['title'])}</h1><p>{esc(item['category'])} · {'AI辅助整理' if item['mode']=='ai' else '课堂摘录'}</p><p>{esc(item['intro'])}</p>"]
        for i, chapter in enumerate(item['chapters'],1):
            parts += [f"<h2>{i}. {esc(chapter['title'])}</h2><p>{esc(chapter['body'])}</p>"]
            if chapter.get('question'):
                parts += [f"<h3>合上小本，试着回答</h3><p>{esc(chapter['question'])}</p><p>参考：{esc(chapter['answer'])}</p>"]
            refs = [s['label'] for s in item['sources'] if s['id'] in chapter['source_ids']]
            parts += [f"<p style='color:{Colors.TEXT_SECONDARY}'>来源：{esc(' / '.join(dict.fromkeys(refs)) or '暂无讲解，待补充')}</p>"]
        self.reader.setHtml(''.join(parts))

    def create(self, current=False):
        if self._busy: return
        topics = booklets.catalog(self.engine)
        if not topics:
            self.status.setText('先听一段课，或保存课程回响，再选择其中的知识点。')
            return
        dialog = BookletComposer(topics,self,current)
        if dialog.exec_()!=QDialog.Accepted: return
        selected = dialog.selected()
        if not selected:
            self.status.setText('至少选择一个知识点。')
            return
        title, group, ai = dialog.title.text().strip(),dialog.group.currentText(),dialog.ai.isChecked()
        if not title:
            self.status.setText('请填写主题名称。')
            return
        self._busy = True
        self.new.setEnabled(False)
        self._request += 1
        request = self._request
        self.status.setText('正在整理这组知识的主线与联系…' if ai else '正在整理课堂摘录…')
        def run():
            try: result,error = booklets.generate(title,group,selected,ai),''
            except Exception as exc: result,error = None,str(exc)
            try: self.completed.emit(request,result,error)
            except RuntimeError: pass
        threading.Thread(target=run,daemon=True,name='echo-booklet').start()

    def finish(self,request,result,error):
        if request!=self._request:return
        self._busy=False
        self.new.setEnabled(True)
        if error:
            self.status.setText('小本内容未完成：'+error)
            return
        try: saved = booklets.save(result)
        except (OSError,ValueError) as exc:
            self.status.setText('保存失败：'+str(exc));return
        self.refresh()
        self.status.setText('已保存「'+saved['title']+'」，可跨课、按大类复习。')

    def open_exam(self):
        owner = self.parentWidget()
        if owner is not None and hasattr(owner,'_open_exam'):
            owner._open_exam()
        else:
            from echo.widgets.exam_window import open_exam_window
            self._exam_window = open_exam_window(engine=self.engine,parent=self)

    def closeEvent(self,event):
        self._request+=1
        self._busy=False
        self.new.setEnabled(True)
        super().closeEvent(event)
