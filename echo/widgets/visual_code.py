"""Native source editor around the existing isolated HtmlLesson renderer."""
import threading
from PyQt5.QtCore import Qt, QObject, QTimer, pyqtSignal, QBuffer, QIODevice
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QPlainTextEdit, QSplitter
from echo.backend import paths, providers, visual_code
from echo.theme import Colors, dialog_qss
from echo.widgets.web_lesson import HtmlLesson
from echo.widgets.echo_line_edit import EchoLineEdit
from echo.widgets.window_chrome import install_chrome


class Bus(QObject):
    done = pyqtSignal(int, object, str)


class VisualCode(QDialog):
    def __init__(self,source='',topic='',parent=None,context_valid=lambda:True,adopt=None):
        super().__init__(parent,Qt.Window|Qt.WindowStaysOnTopHint)
        self.setWindowTitle('Echo · 图解代码工作区'); self.setWindowIcon(QIcon(paths.asset('assets','echo.ico')))
        self.resize(1040,720); self.setMinimumSize(700,460)
        self.setStyleSheet(dialog_qss()+f'QPlainTextEdit{{background:{Colors.CODE_BG};color:{Colors.TEXT_PRIMARY};border:1px solid {Colors.BORDER};border-radius:8px;padding:10px;}}QPushButton{{min-width:0;padding:7px 10px;}}')
        self.client = visual_code.Client(); self.context_valid = context_valid; self.adopt = adopt; self.topic = topic
        self.closed = False; self.busy = False; self.revision = 0; self.request_revision = 0; self.preview_ready = False
        root = QVBoxLayout(self)
        self.title = self.label(topic or '当前图解'); root.addWidget(self.title)
        self.hint = self.label('手动预览不调用模型；AI操作每次发起一次请求，按实际用量计费。'); root.addWidget(self.hint)
        tools = QHBoxLayout(); self.ai_buttons = []
        self.preview_button = self.button('手改后预览',self.apply_local); tools.addWidget(self.preview_button)
        for text,action in [('AI 写图解','write'),('AI 读代码','read'),('AI 看画面','inspect')]:
            w = self.button(text,lambda a=action:self.run(a)); tools.addWidget(w); self.ai_buttons.append(w)
        self.adopt_button = self.button('采用到黑板',self.apply_board); self.adopt_button.setEnabled(adopt is not None); tools.addWidget(self.adopt_button)
        root.addLayout(tools)
        self.instruction = EchoLineEdit(); self.instruction.setMaxLength(1000); self.instruction.setPlaceholderText('希望怎样解释或修改？例如：比较两条直线，并让动点跟随参数变化。'); root.addWidget(self.instruction)
        self.split = QSplitter(Qt.Horizontal)
        self.code = QPlainTextEdit(); code_font=QFont('Consolas');code_font.setPixelSize(12);self.code.setFont(code_font)
        self.code.setStyleSheet('font-family:Consolas,monospace;font-size:12px;')
        self.code.setPlainText(source); self.code.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.preview = HtmlLesson(self); self.preview.loaded.connect(self.loaded); self.preview.failed.connect(self.failed)
        self.split.addWidget(self.code); self.split.addWidget(self.preview); self.split.setSizes([450,550]); root.addWidget(self.split,1)
        self.reply = self.label(); self.reply.setMaximumHeight(130); root.addWidget(self.reply)
        self.notice = self.label(); root.addWidget(self.notice)
        self.code.textChanged.connect(self.edited)
        self.instruction.textChanged.connect(self.edited)
        self.bus = Bus(self); self.bus.done.connect(self.finished)
        self.timer = QTimer(self); self.timer.timeout.connect(self.check_context); self.timer.start(1000)
        install_chrome(self,root)
        if source: QTimer.singleShot(0,self.apply_local)

    @staticmethod
    def label(text=''):
        w = QLabel(text); w.setTextFormat(Qt.PlainText); w.setWordWrap(True); return w

    def button(self,text,fn):
        w = QPushButton(text); w.clicked.connect(lambda checked=False:fn()); return w

    def edited(self): self.revision += 1

    def loaded(self,ok): self.preview_ready = bool(ok)

    def failed(self,message): self.preview_ready = False; self.notice.setText(message)

    def apply_local(self):
        try: fragment = visual_code.checked(self.code.toPlainText(),80000)
        except ValueError as exc: self.notice.setText(str(exc)); return
        self.preview_ready = False; self.preview.display({'html':fragment}); self.revision += 1
        self.notice.setText('已更新本地预览。范围检查不代表数学结论已核验。')

    def check_context(self):
        if not self.client.current():
            self.code.clear(); self.instruction.clear(); self.reply.clear(); self.preview.stop(); self.close(); return
        valid = self.context_valid()
        self.adopt_button.setEnabled(valid and self.adopt is not None and not self.busy)
        for w in self.ai_buttons: w.setEnabled(valid and not self.busy)
        if not valid: self.notice.setText('原板书内容已变化，保留本机预览；请从新板书重新打开后再使用AI或采用。')

    def run(self,action):
        if self.busy or self.closed: return
        self.check_context()
        if self.closed or not self.context_valid(): return
        source = self.code.toPlainText(); image = None
        if action=='inspect':
            if not self.preview_ready or not self.preview.view or self.preview.fragment!=source:
                self.notice.setText('请先点击“手改后预览”，等待当前画面显示，再检查。'); return
        from echo.widgets import dialogs
        if not dialogs.confirm(self,'AI图解工作区',('将这一块图解的实际画面和代码交给视觉模型核对？' if action=='inspect' else '将当前代码与要求交给文字模型？')+'本次产生一次模型请求用量。'): return
        if not self.client.current() or not self.context_valid(): self.check_context(); return
        if action=='inspect':
            buffer = QBuffer(); buffer.open(QIODevice.WriteOnly)
            pixmap = self.preview.view.grab()
            if pixmap.width()>1000: pixmap = pixmap.scaledToWidth(1000,Qt.SmoothTransformation)
            pixmap.save(buffer,'PNG'); image = bytes(buffer.data())
        self.busy = True; self.request_revision = self.revision; self.check_context()
        spec = dict(providers.vision() if image else providers.text()); instruction = self.instruction.text(); revision = self.revision
        self.notice.setText('正在核对实际画面…' if image else '正在读取当前代码…')
        def work():
            try: result,error = self.client.run(action,source,instruction,self.topic,image,spec),''
            except Exception as exc: result,error = None,str(exc)
            try: self.bus.done.emit(revision,result,error)
            except RuntimeError: pass
        threading.Thread(target=work,daemon=True).start()

    def finished(self,revision,result,error):
        if self.closed: return
        self.busy = False; self.check_context()
        if self.closed or not self.context_valid(): return
        if revision!=self.revision:
            self.notice.setText('代码或预览已变化，本次回复没有覆盖新内容；请求可能已产生用量。'); return
        if error: self.notice.setText(error); return
        self.reply.setText(result['reply'])
        if result.get('html'):
            self.code.setPlainText(result['html']); self.apply_local()
        self.notice.setText('已回复；请结合教材核对。只有点击“采用到黑板”才替换原图。')

    def apply_board(self):
        self.check_context()
        if self.closed or self.busy or not self.context_valid() or not self.adopt: return
        if self.preview.fragment!=self.code.toPlainText() or not self.preview_ready:
            self.notice.setText('请先预览当前代码。'); return
        self.adopt(self.preview.fragment); self.notice.setText('已采用到黑板。')

    def closeEvent(self,event):
        self.closed = True; self.timer.stop(); self.preview.stop(); super().closeEvent(event)
