"""AI 学习助手窗口（v1）：聊天 + 工具执行的可视化。

入口：主页「更多 ▾」工具面板。阻塞的 agent 循环跑在后台线程，
工具调用与回复经信号回主线程；窗口关闭即终止（线程是 daemon）。
"""
from PyQt5.QtCore import Qt, pyqtSignal, QSettings
from PyQt5.QtGui import QKeySequence, QCursor
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)
from PyQt5.QtCore import QTimer

from echo.theme import Colors, Radius
from echo.i18n import tr
from echo.widgets.window_chrome import install_chrome

MAX_HISTORY = 24


class AgentChatWindow(QDialog):
    _status = pyqtSignal(str)       # 工具调用过程（一行）
    _reply = pyqtSignal(str)        # 最终回复
    _error = pyqtSignal(str)
    _busy_done = pyqtSignal()

    def __init__(self, engine=None, parent=None):
        super().__init__(parent, Qt.Window)
        self.engine = engine
        self.history = []               # [{'role','content'}]
        self._busy = False
        self.setWindowTitle(tr('Echo · AI 助手', 'Echo · AI assistant'))
        self.resize(480, 620)
        self.setMinimumSize(380, 420)
        self.setStyleSheet(f'''
            QDialog{{background:{Colors.WINDOW_BG};}}
            QFrame#AgentBubble{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:10px;}}
            QLabel{{color:{Colors.TEXT_PRIMARY};background:transparent;}}
        ''')
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet('QScrollArea{background:transparent;border:none;}')
        self._scroll = scroll
        self.msgs = QWidget()
        self.msgs.setStyleSheet('background: transparent;')
        self.msgs_lay = QVBoxLayout(self.msgs)
        self.msgs_lay.setContentsMargins(14, 12, 14, 12)
        self.msgs_lay.setSpacing(8)
        self.msgs_lay.addStretch(1)
        scroll.setWidget(self.msgs)
        root.addWidget(scroll, 1)

        self.status_lbl = QLabel('')
        self.status_lbl.setStyleSheet(f'color:{Colors.TEXT_SECONDARY};font-size:11px;background:transparent;')
        self.status_lbl.setWordWrap(True)
        self.status_lbl.hide()
        root.addWidget(self.status_lbl)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(14, 6, 14, 12)
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr('让助手帮你：出题 / 做计划 / 查资料…', 'Ask the assistant…'))
        self.input.setStyleSheet(f'background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};'
                                 f'border:1px solid {Colors.BORDER_STRONG};border-radius:10px;padding:9px 12px;font-size:13px;')
        self.input.returnPressed.connect(self._send)
        input_row.addWidget(self.input, 1)
        self.send_btn = QPushButton(tr('发送', 'Send'))
        self.send_btn.setObjectName('Accent')
        self.send_btn.setFixedHeight(36)
        self.send_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        root.addLayout(input_row)

        install_chrome(self, root, minimize=False)
        self._status.connect(self._on_status)
        self._reply.connect(self._on_reply)
        self._error.connect(self._on_error)
        self._busy_done.connect(self._on_done)
        self._greet()

    def _greet(self):
        self._bubble(tr('我是 Echo 的学习助手。可以让我：查你的资料和学习进度、出练习题、'
                        '做一份学习计划书——直接说就行。',
                        'I can search your notes and progress, make quizzes, or draft a study plan. Just ask.'),
                     assistant=True)

    # ---------- UI 组装 ----------
    def _bubble(self, text, assistant=True):
        frame = QFrame()
        frame.setObjectName('AgentBubble')
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        who = tr('助手', 'Assistant') if assistant else tr('我', 'Me')
        head = QLabel(who)
        head.setStyleSheet(f'color:{Colors.ACCENT if assistant else Colors.TEXT_SECONDARY};font-size:11px;font-weight:600;')
        lay.addWidget(head)
        body = QLabel(str(text))
        body.setWordWrap(True)
        body.setTextFormat(Qt.PlainText)
        body.setStyleSheet('font-size:13px;')
        lay.addWidget(body)
        row = QHBoxLayout()
        row.addWidget(frame, 1 if assistant else 0)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _status_chip(self, text):
        self.status_lbl.setText(str(text))
        self.status_lbl.show()
        self._scroll_end()

    def _scroll_end(self):
        bar = self._scroll.verticalScrollBar()
        QTimer.singleShot(30, lambda: bar.setValue(bar.maximum()))

    # ---------- 发送 / agent 循环 ----------
    def _send(self):
        if self._busy:
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._bubble(text, assistant=False)
        self.history.append({'role': 'user', 'content': text[:4000]})
        del self.history[:-MAX_HISTORY]
        self._busy = True
        self.send_btn.setEnabled(False)
        self._status_chip(tr('思考中…', 'Thinking…'))
        import threading
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            from echo.backend.ai_agent import run_agent
            def on_event(event):
                if event.get('type') == 'tool_start':
                    self._status.emit(str(event.get('label') or event.get('name', '')) + '…')
            reply = run_agent(list(self.history), on_event=on_event)
            self._reply.emit(reply)
        except Exception as exc:
            from echo.backend.llm import LLMError
            if isinstance(exc, LLMError):
                self._error.emit(str(exc) + tr('（需要配置模型：登录 Echo 账户或设置自己的 API key）',
                                               ' (configure a model: sign in or set your API key)'))
            else:
                self._error.emit(f'{type(exc).__name__}: {exc}')
        self._busy_done.emit()

    # ---------- 信号落点（主线程）----------
    def _on_status(self, text):
        self._status_chip(text)

    def _on_reply(self, text):
        self.history.append({'role': 'assistant', 'content': text[:4000]})
        self._bubble(text, assistant=True)

    def _on_error(self, text):
        self._bubble('⚠ ' + text, assistant=True)

    def _on_done(self):
        self._busy = False
        self.send_btn.setEnabled(True)
        self.status_lbl.hide()


_agent_window = None


def open_agent_chat(engine=None, parent=None):
    global _agent_window
    if _agent_window is not None:
        _agent_window.showNormal(); _agent_window.raise_(); _agent_window.activateWindow()
        return _agent_window
    win = AgentChatWindow(engine=engine, parent=parent)
    _agent_window = win
    def closed(_):
        global _agent_window
        if _agent_window is win:
            _agent_window = None
        win.deleteLater()
    win.finished.connect(closed)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
