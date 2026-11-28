"""AI 学习助手面板。

气泡对话 + 圆点步骤条 + 工具预览卡。快捷建议用灰色文字，不弹按钮条。
多会话由宿主窗口侧栏管理；本面板暴露 reset / load_transcript / chat_id。
"""
import re
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSettings
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from echo.theme import Colors
from echo.i18n import tr

VIEW_ALIASES = {
    "错题复习": "review", "复习": "review",
    "练习": "practice", "错题练习": "practice",
    "课程管理": "courses", "课程": "courses", "课堂记录": "courses",
    "知识地图": "mindmap", "地图": "mindmap",
    "已学内容": "learned",
    "一周回响": "weekly", "周报": "weekly",
    "主页": "home",
}

QUICK_ACTIONS = [
    ("我的进度", "看看我的学习进度和薄弱点"),
    ("出几道题", "针对我的薄弱知识点出 5 道练习题"),
    ("做学习计划", "帮我做一份考前两周的复习学习计划"),
    ("上一节 AI 课", "帮我上一节 AI 互动课：一次函数的斜率"),
]


class DotsSpinner(QWidget):
    """三枚小点依次亮起，占位小、不挡对话。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 12)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(280)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self):
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 1) % 3
        self.update()

    def paintEvent(self, _ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(Colors.ACCENT)
        for i in range(3):
            c = QColor(color)
            c.setAlpha(220 if i == self._phase else 70)
            painter.setBrush(c)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(4 + i * 9, 3, 6, 6)


def _no_enter_default(button):
    """QDialog 里 QPushButton 默认吃回车。助手窗口回车必须发给输入框。"""
    button.setAutoDefault(False)
    button.setDefault(False)
    return button


class AgentPanel(QWidget):
    open_view_requested = pyqtSignal(str)     # 主窗口切页
    start_lesson_requested = pyqtSignal(str)  # 主窗口开课
    open_ai_class_requested = pyqtSignal(str)  # 打开 AI 互动课堂
    create_paper_requested = pyqtSignal(str, str)  # 主窗口打开清卷并开始 AI 命题
    open_booklets_requested = pyqtSignal()    # 主窗口：打开我的小本
    open_plans_requested = pyqtSignal()       # 主窗口：打开学习计划
    _event = pyqtSignal(dict)
    _reply = pyqtSignal(str)
    _error = pyqtSignal(str)
    _done = pyqtSignal()
    _voice = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AgentPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#AgentPanel{{background:{Colors.WINDOW_BG};}}")
        self.history = []
        self._busy = False
        self._recorder = None
        self._recording = False
        self._turn_steps = []
        self._turn_message = ""
        self._step_frame = None
        self._step_lay = None
        self._think_row = None
        self._step_by_name = {}
        self._chat_id = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._scroll = scroll
        self.msgs = QWidget()
        self.msgs.setStyleSheet("background: transparent;")
        self.msgs_lay = QVBoxLayout(self.msgs)
        self.msgs_lay.setContentsMargins(16, 12, 16, 12)
        self.msgs_lay.setSpacing(8)
        self.msgs_lay.addStretch(1)
        scroll.setWidget(self.msgs)
        root.addWidget(scroll, 1)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(
            f"color:{Colors.TEXT_SECONDARY};font-size:11px;background:transparent;padding:0 16px;")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.hide()
        root.addWidget(self.status_lbl)
        # 状态条转点动画（Echo 风格，不用 emoji）
        self._spinner = QTimer(self, interval=400, timeout=self._spin_status)
        self._spin_frame = 0

        chips = QHBoxLayout()
        chips.setContentsMargins(16, 2, 16, 0)
        chips.setSpacing(8)
        hint = QLabel(tr("试试", "Try"))
        hint.setStyleSheet(f"color:{Colors.TEXT_DISABLED};font-size:11px;background:transparent;")
        chips.addWidget(hint)
        for label, prompt in QUICK_ACTIONS:
            chips.addWidget(self._ghost_link(label, prompt, send=False))
        chips.addStretch(1)
        root.addLayout(chips)

        row = QHBoxLayout()
        row.setContentsMargins(16, 6, 16, 12)
        row.setSpacing(8)
        self.mic = QPushButton(tr("语音", "Voice"))
        self.mic.setToolTip(tr("按一下开始说，再按一下转成文字", "Tap to record, tap again to transcribe"))
        self.mic.setFixedHeight(36)
        self.mic.setMinimumWidth(52)
        self.mic.setCursor(QCursor(Qt.PointingHandCursor))
        self.mic.setStyleSheet(
            f"QPushButton{{border:1px solid {Colors.BORDER};border-radius:10px;background:{Colors.SURFACE};"
            f"color:{Colors.TEXT_SECONDARY};font-size:12px;}}")
        self.mic.clicked.connect(self._toggle_mic)
        row.addWidget(self.mic)
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("让助手帮你出题 / 做计划 / 查资料…", "Ask the assistant…"))
        self.input.setStyleSheet(
            f"background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};"
            f"border:1px solid {Colors.BORDER_STRONG};border-radius:10px;padding:9px 12px;font-size:13px;")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.send_btn = QPushButton(tr("发送", "Send"))
        self.send_btn.setObjectName("Accent")
        self.send_btn.setFixedHeight(36)
        self.send_btn.setCursor(QCursor(Qt.PointingHandCursor))
        _no_enter_default(self.send_btn)
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)
        _no_enter_default(self.mic)
        root.addLayout(row)

        self._event.connect(self._on_event)
        self._reply.connect(self._on_reply)
        self._error.connect(self._on_error)
        self._done.connect(self._on_done)
        self._voice.connect(self._on_voice)
        self._greet()

    def _spin_status(self):
        pass  # 圆环自己转；思考文案由 _tick_think 更新秒数

    def _greet(self):
        self._bubble(tr("我是 Echo 的学习助手。出练习题、写学习计划、查资料和学习进度都可以，"
                        "说一声就行；也能帮你直接打开错题复习、清卷这些界面。",
                        "I can quiz you, draft study plans, search your notes, or open any view."),
                     assistant=True)

    def _ghost_link(self, label, prompt, send=False):
        """灰色文字按钮：不弹条、不描边。send=True 时直接发出。"""
        btn = QPushButton(label)
        _no_enter_default(btn)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setFlat(True)
        btn.setStyleSheet(
            f"QPushButton{{padding:0;border:0;background:transparent;"
            f"color:{Colors.TEXT_DISABLED};font-size:11px;text-align:left;}}"
            f"QPushButton:hover{{color:{Colors.ACCENT};}}")
        def _go(checked=False, p=prompt, fire=send):
            self.input.setText(p)
            if fire:
                self._send()
        btn.clicked.connect(_go)
        return btn

    def chat_id(self):
        if not self._chat_id:
            settings = QSettings("Echo", "Echo")
            cid = settings.value("assistant/chat_id", "")
            if not cid:
                import uuid as _uuid
                cid = "desktop_" + _uuid.uuid4().hex[:20]
                settings.setValue("assistant/chat_id", cid)
            self._chat_id = str(cid)
        return self._chat_id

    def new_chat_id(self):
        import uuid as _uuid
        self._chat_id = "desktop_" + _uuid.uuid4().hex[:20]
        QSettings("Echo", "Echo").setValue("assistant/chat_id", self._chat_id)
        return self._chat_id

    def reset_conversation(self, greet=True):
        while self.msgs_lay.count() > 1:
            item = self.msgs_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.history = []
        self._step_frame = None
        self._think_row = None
        if greet:
            self._greet()

    def load_transcript(self, messages, steps=None):
        self.reset_conversation(greet=False)
        for msg in messages or []:
            role = str(msg.get("role", ""))
            content = str(msg.get("content") or "")
            if not content:
                continue
            assistant = role != "user"
            self._bubble(content, assistant=assistant)
            self.history.append({"role": "assistant" if assistant else "user", "content": content[:4000]})
        for step in (steps or [])[-6:]:
            if step.get('kind') == 'quiz' or step.get('tool') == 'make_quiz':
                self._quiz_card(str(step.get('result') or ''))

    def _begin_steps(self):
        frame = QFrame()
        frame.setObjectName("AgentSteps")
        frame.setStyleSheet("QFrame#AgentSteps{background:transparent;border:0;}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 2, 16, 2)
        lay.setSpacing(4)
        think = QWidget()
        think.setStyleSheet("background:transparent;")
        trow = QHBoxLayout(think)
        trow.setContentsMargins(0, 2, 0, 2)
        trow.setSpacing(8)
        self._ring = DotsSpinner(think)
        trow.addWidget(self._ring)
        self._think_row = QLabel("思考中")
        self._think_row.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};font-size:12px;background:transparent;")
        trow.addWidget(self._think_row)
        trow.addStretch(1)
        lay.addWidget(think)
        self._ring.start()
        self._think_started = __import__('time').time()
        self._think_clock = QTimer(self, interval=1000, timeout=self._tick_think)
        self._think_clock.start()
        self._step_frame = frame
        self._step_lay = lay
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)

    def _tick_think(self):
        if self._think_row is None:
            return
        elapsed = int(__import__('time').time() - getattr(self, '_think_started', 0))
        self._think_row.setText("思考中  " + (str(elapsed) + " 秒" if elapsed else ""))

    def _add_step(self, label):
        if self._step_lay is None:
            self._begin_steps()
        row = QLabel("○  " + label)
        row.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};font-size:12px;background:transparent;")
        idx = self._step_lay.count() - 1
        if idx < 0:
            idx = self._step_lay.count()
        self._step_lay.insertWidget(idx, row)
        return row

    def _finish_step(self, row):
        if row is None:
            return
        text = row.text()
        if text.startswith("○"):
            row.setText("●" + text[1:])
        row.setStyleSheet(f"color:{Colors.TEXT_PRIMARY};font-size:12px;background:transparent;")

    def _end_steps(self):
        clock = getattr(self, '_think_clock', None)
        if clock is not None:
            clock.stop()
        ring = getattr(self, '_ring', None)
        if ring is not None:
            ring.stop()
        if self._think_row is not None:
            parent = self._think_row.parentWidget()
            if parent is not None:
                parent.hide()
            self._think_row = None
        self._step_frame = None
        self._step_lay = None

    # ---------- 气泡 / 卡片 ----------
    def _scroll_end(self):
        bar = self._scroll.verticalScrollBar()
        QTimer.singleShot(30, lambda: bar.setValue(bar.maximum()))

    def _bubble(self, text, assistant=True, animate=False):
        frame = QFrame()
        frame.setObjectName("AgentBubble")
        if assistant:
            frame.setStyleSheet(f"QFrame#AgentBubble{{background:{Colors.SURFACE};"
                                f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        else:
            frame.setStyleSheet(f"QFrame#AgentBubble{{background:{Colors.ACCENT_SOFT};"
                                f"border:1px solid {Colors.ACCENT_BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        who = tr("助手", "Assistant") if assistant else tr("我", "Me")
        head = QLabel(who)
        head.setStyleSheet(f"color:{Colors.ACCENT if assistant else Colors.TEXT_SECONDARY};"
                           "font-size:11px;font-weight:600;")
        lay.addWidget(head)
        body = QLabel(str(text))
        body.setWordWrap(True)
        body.setTextFormat(Qt.PlainText)
        if animate:
            full = str(text)
            body.setText('')
            timer = QTimer(frame); timer.setInterval(25)
            position = [0]; chunk = max(8, (len(full) + 44) // 45)
            def reveal():
                position[0] += chunk
                body.setText(full[:position[0]])
                if position[0] >= len(full): timer.stop()
            timer.timeout.connect(reveal); timer.start()
        body.setStyleSheet("font-size:13px;")
        lay.addWidget(body)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()
        return frame

    def _card(self, title, body_text):
        """工具结果预览卡：浅金底、标题、等宽正文。"""
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QLabel(title)
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        body = QLabel(str(body_text))
        body.setWordWrap(True)
        body.setTextFormat(Qt.PlainText)
        body.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
        lay.addWidget(body)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _plan_card(self, result):
        """计划书预览：标题 + 按天分节（天标 + 重点 + 任务列表）。"""
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QLabel(tr("学习计划书", "Study plan"))
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        lines = [ln for ln in result.splitlines()]
        for ln in lines:
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped.startswith("学习计划"):
                title = QLabel(stripped)
                title.setWordWrap(True)
                title.setStyleSheet(f"font-size:13px;font-weight:600;color:{Colors.TEXT_PRIMARY};")
                lay.addWidget(title)
                continue
            if stripped.startswith("第") and " · " in stripped:
                day, rest = stripped.split(" · ", 1)
                day_lbl = QLabel(day)
                day_lbl.setStyleSheet(f"color:{Colors.ACCENT};font-size:12px;font-weight:600;")
                lay.addWidget(day_lbl)
                if "：" in rest:
                    focus, tasks = rest.split("：", 1)
                    focus_lbl = QLabel(focus)
                    focus_lbl.setWordWrap(True)
                    focus_lbl.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
                    lay.addWidget(focus_lbl)
                    for task in tasks.split("；"):
                        task = task.strip()
                        if task:
                            t = QLabel("· " + task)
                            t.setWordWrap(True)
                            t.setStyleSheet(f"font-size:11px;color:{Colors.TEXT_SECONDARY};padding-left:10px;")
                            lay.addWidget(t)
                else:
                    r = QLabel(rest)
                    r.setWordWrap(True)
                    r.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
                    lay.addWidget(r)
                continue
            body = QLabel(stripped)
            body.setWordWrap(True)
            body.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
            lay.addWidget(body)
        if result.strip().endswith("（计划未保存：写入小册失败，内容见预览。）"):
            warn = QLabel(tr("计划未能写入小册，内容见上。", "Plan not saved to notebook; shown above."))
            warn.setStyleSheet(f"font-size:11px;color:{Colors.TEXT_SECONDARY};")
            lay.addWidget(warn)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _progress_card(self, result):
        """进度/复习清单：逐行成条。"""
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QLabel(tr("学习进度", "Progress"))
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        for ln in result.splitlines():
            stripped = ln.strip()
            if not stripped:
                continue
            row = QLabel(stripped)
            row.setWordWrap(True)
            row.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
            lay.addWidget(row)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _link_button(self, text, handler):
        btn = QPushButton(text)
        _no_enter_default(btn)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton{{padding:2px 8px;border:0;background:transparent;"
            f"color:{Colors.ACCENT};font-size:11px;}}")
        btn.clicked.connect(handler)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, btn)
        self._scroll_end()

    def _collapsed_card(self, title, summary, detail):
        """工具结果默认折叠：一行摘要 + 展开详情按钮。"""
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QLabel(title)
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        summary_lbl = QLabel(summary)
        summary_lbl.setWordWrap(True)
        summary_lbl.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
        lay.addWidget(summary_lbl)
        detail_lbl = QLabel(detail)
        detail_lbl.setWordWrap(True)
        detail_lbl.setTextFormat(Qt.PlainText)
        detail_lbl.setStyleSheet(f"font-size:11px;color:{Colors.TEXT_SECONDARY};")
        detail_lbl.hide()
        lay.addWidget(detail_lbl)
        toggle = QPushButton(tr("展开详情", "Show details"))
        toggle.setCursor(QCursor(Qt.PointingHandCursor))
        toggle.setStyleSheet(
            f"QPushButton{{padding:2px 8px;border:0;background:transparent;"
            f"color:{Colors.ACCENT};font-size:11px;}}")
        def _toggle(checked=False):
            detail_lbl.setVisible(not detail_lbl.isVisible())
            toggle.setText(tr("收起详情", "Hide details") if detail_lbl.isVisible() else tr("展开详情", "Show details"))
        toggle.clicked.connect(_toggle)
        lay.addWidget(toggle)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _open_view_card(self, result):
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QLabel(tr("已打开界面", "View opened"))
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        body = QLabel(str(result))
        body.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
        lay.addWidget(body)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _note_card(self, title, body_text):
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QLabel(title)
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        body = QLabel(str(body_text))
        body.setWordWrap(True)
        body.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
        lay.addWidget(body)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    def _quiz_card(self, result):
        """练习题预览：逐题渲染，答案默认折起，按钮展开。"""
        from echo.backend.assistant_quiz import load_quiz
        data = load_quiz(result)
        if data is not None:
            from PyQt5.QtWidgets import QComboBox
            frame = QFrame()
            frame.setObjectName('AgentQuiz')
            frame.setStyleSheet(f'QFrame#AgentQuiz{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:12px;padding:8px;}}')
            layout = QVBoxLayout(frame)
            layout.addWidget(QLabel('练习 · ' + str(data.get('topic', ''))))
            for index, question in enumerate(data['questions'][:5], 1):
                title = QLabel(str(index) + '. ' + str(question.get('question', '')))
                title.setTextFormat(Qt.PlainText); title.setWordWrap(True); layout.addWidget(title)
                options = question.get('options') or []
                if options:
                    entry = QComboBox(); entry.addItem('请选择答案')
                    entry.addItems([str(v) for v in options])
                else:
                    entry = QLineEdit(); entry.setPlaceholderText('先写下你的答案')
                layout.addWidget(entry)
                submit = QPushButton('提交这题')
                feedback = QLabel(); feedback.setTextFormat(Qt.PlainText); feedback.setWordWrap(True)
                feedback.hide()
                def check(checked=False, q=question, field=entry, choices=options, label=feedback):
                    answer = field.currentIndex() - 1 if choices else field.text().strip()
                    if (choices and answer < 0) or (not choices and not answer): return
                    expected = q.get('answer', '')
                    reference = choices[expected] if choices and type(expected) is int and 0 <= expected < len(choices) else str(expected)
                    verdict = ('答对了' if answer == expected else '再看一下解题依据') if choices else '已作答，请结合参考答案核对'
                    label.setText(verdict + '\n参考答案：' + reference + '\n' + str(q.get('explanation', '')))
                    label.show()
                submit.clicked.connect(check)
                layout.addWidget(submit); layout.addWidget(feedback)
            self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
            self._scroll_end()
            return
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setStyleSheet(f"QFrame#AgentCard{{background:{Colors.SURFACE};"
                            f"border:1px solid {Colors.BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QLabel(tr("练习题", "Practice quiz"))
        head.setStyleSheet(f"color:{Colors.ACCENT};font-size:11px;font-weight:600;")
        lay.addWidget(head)
        question_no = 0
        for line in result.splitlines()[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[0].isdigit() and ". " in stripped[:4]:
                question_no += 1
                q = QLabel(stripped)
                q.setWordWrap(True)
                q.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_PRIMARY};")
                lay.addWidget(q)
                if "答案：" in stripped:
                    answer = stripped.split("答案：", 1)[1]
                    btn = QPushButton(tr("显示答案", "Show answer"))
                    btn.setCursor(QCursor(Qt.PointingHandCursor))
                    btn.setStyleSheet(
                        f"QPushButton{{padding:2px 8px;border:0;background:transparent;"
                        f"color:{Colors.ACCENT};font-size:11px;}}")
                    answer_lbl = QLabel(tr("答案：", "Answer: ") + answer)
                    answer_lbl.setWordWrap(True)
                    answer_lbl.setStyleSheet(f"font-size:12px;color:{Colors.TEXT_SECONDARY};")
                    answer_lbl.hide()
                    def toggle(checked=False, lbl=answer_lbl, b=btn):
                        lbl.setVisible(not lbl.isVisible())
                        b.setText(tr("收起答案", "Hide answer") if lbl.isVisible() else tr("显示答案", "Show answer"))
                    btn.clicked.connect(toggle)
                    lay.addWidget(btn)
                    lay.addWidget(answer_lbl)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, frame)
        self._scroll_end()

    # ---------- 事件落点 ----------
    def _on_event(self, evt):
        kind = evt.get("type")
        if kind == "tool_start":
            self._status_base = str(evt.get("label", ""))
            row = self._add_step(self._status_base)
            self._step_by_name[str(evt.get("name", ""))] = row
            self.status_lbl.hide()
            self._scroll_end()
        elif kind == "tool_result":
            # collect for cloud upload (best effort; see _upload_turn)
            try:
                self._turn_steps.append({
                    "tool": str(evt.get("name", "")),
                    "args": {},
                    "result": str(evt.get("result", ""))[:6000] if evt.get('kind')=='quiz' else str(evt.get("result", ""))[:1500],
                    "kind": str(evt.get("kind", "text")),
                })
            except AttributeError:
                pass
            self.status_lbl.hide()
            name = evt.get("name", "")
            result = str(evt.get("result", ""))
            k = evt.get("kind", "text")
            self._finish_step(self._step_by_name.get(name))
            lines = [ln.strip() for ln in result.splitlines() if ln.strip()]
            if k == "quiz":
                self._quiz_card(result)                      # 逐题渲染，答案折起
            elif k == "plan":
                summary = lines[0] if lines else tr("学习计划书", "Study plan")
                self._collapsed_card(tr("学习计划书", "Study plan"), summary, result)
                if "已保存到学习计划" in result:
                    self._link_button(tr("打开学习计划", "Open study plan"),
                                      lambda checked=False: self.open_plans_requested.emit())
            elif k == "progress":
                summary = lines[0] if lines else tr("已读取学习记录。", "Progress read.")
                self._collapsed_card(tr("已读取学习记录", "Progress read"), summary, result)
            elif k == "search":
                hits = sum(1 for ln in lines if ln.startswith("【"))
                self._collapsed_card(tr("已检索资料", "Searched library"),
                                     (tr("命中 ", "Hit ") + str(hits) + tr(" 条相关内容，展开查看。", " results; expand for details.")),
                                     result)
            elif k == "today_reviews":
                summary = lines[0] if lines else tr("复习清单已读取。", "Reviews read.")
                self._collapsed_card(tr("今天的复习清单", "Today's reviews"), summary, result)
            elif k == "view":
                self._open_view_card(result)
            elif k == "paper":
                self._note_card(tr("清卷 · 出卷中", "Qingjuan · composing"), result)
            elif k == "material":
                self._note_card(tr("已存入资料库", "Saved to library"), result)
            elif k == "docx":
                summary = lines[0] if lines else tr("已写成 Word", "Word file ready")
                self._note_card(tr("Word 文档", "Word document"), summary)
                doc = lines[-1] if lines else ""
                if doc.lower().endswith(".docx"):
                    self._link_button(tr("打开文档", "Open document"),
                                      lambda checked=False, path=doc: __import__("os").startfile(path))
            elif k == "booklet":
                summary = lines[0] if lines else tr("已生成复习小册", "Booklet generated")
                self._collapsed_card(tr("复习小册", "Notebook"), summary, result)
                self._link_button(tr("打开小本查看", "Open in notebook"),
                                  lambda checked=False: self.open_booklets_requested.emit())
            else:
                self._collapsed_card(tr("Echo 执行了", "Echo ran ") + name, result[:80], result)
        elif kind == "error":
            self._last_error = str(evt.get("text", ""))
            self._bubble("⚠ " + self._last_error, assistant=True)

    def _on_reply(self, text):
        if getattr(self, "_last_error", None) and str(text) == self._last_error:
            self._last_error = None
            return
        self._last_error = None
        self._bubble(text, assistant=True, animate=True)
        self._attach_followups(text)

    def _attach_followups(self, text):
        """从回复里抽出编号选项，用灰色文字挂在对话流里，不弹条。"""
        items = []
        for match in re.finditer(r"(?m)^\s*(?:\d+[.、、]|[-·])\s+(.+)$", str(text)):
            item = match.group(1).strip().rstrip("；;。")
            if 4 <= len(item) <= 48:
                items.append(item)
        if not items:
            return
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(16, 0, 16, 6)
        lay.setSpacing(12)
        for item in items[:4]:
            lay.addWidget(self._ghost_link(item, item, send=True))
        lay.addStretch(1)
        self.msgs_lay.insertWidget(self.msgs_lay.count() - 1, holder)
        self._scroll_end()

    def _on_error(self, text):
        self._bubble("⚠ " + text, assistant=True)

    def _on_done(self):
        self._busy = False
        self.send_btn.setEnabled(True)
        self._spinner.stop()
        self.status_lbl.hide()
        self._end_steps()

    def _on_voice(self, text):
        text = str(text or "").strip()
        self.mic.setText(tr("语音", "Voice"))
        self.mic.setEnabled(True)
        if text:
            self.input.setText(text)
            self.input.setFocus()

    # ---------- 语音 ----------
    def _toggle_mic(self):
        if self._recording:
            self._recording = False
            self.mic.setText(tr("语音", "Voice"))
            self.mic.setEnabled(False)
            self.input.setPlaceholderText(tr("转写中…", "Transcribing…"))
            from echo.backend import voice_input
            voice_input.transcribe_async(
                self._recorder,
                on_done=lambda text: self._voice.emit(text),
                on_error=lambda msg: self._voice.emit(""))
            return
        try:
            from echo.backend import voice_input
            self._recorder = voice_input.Recorder()
            self._recorder.start()
        except Exception:
            self.mic.setEnabled(True)
            self.input.setPlaceholderText(tr("麦克风打不开", "No microphone"))
            return
        self._recording = True
        self.mic.setText("● 录音中")
        self.input.setPlaceholderText(tr("在听你说…再按一下结束", "Listening… tap again to stop"))

    # ---------- 发送 / agent 循环 ----------
    def _send(self):
        if self._busy:
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._bubble(text, assistant=False)
        self.history.append({"role": "user", "content": text[:4000]})
        del self.history[:-24]
        self._busy = True
        self.send_btn.setEnabled(False)
        self._status_base = tr("思考中", "Thinking")
        self.status_lbl.hide()
        self._spinner.start()
        self._step_by_name = {}
        self._begin_steps()
        self._turn_steps = []
        self._turn_message = text[:4000]
        self._turn_chat_id = self.chat_id()
        from echo.backend import account
        self._turn_user_id = str((account.current_user() or {}).get('id') or '')
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            from echo.backend.ai_agent import run_agent
            ctx = {
                "open_view": self._emit_open_view,
                "start_lesson": self._emit_start_lesson,
                "open_ai_class": self._emit_open_ai_class,
                "create_paper": self._emit_create_paper,
            }
            steps = []
            def on_event(evt):
                if evt.get('type') == 'tool_result':
                    steps.append({'tool': str(evt.get('name', ''))[:40], 'args': {},
                                  'result': str(evt.get('result', ''))[:6000] if evt.get('kind')=='quiz' else str(evt.get('result', ''))[:1500],
                                  'kind': str(evt.get('kind', 'text'))})
                self._event.emit(evt)
            reply = run_agent(list(self.history), on_event=on_event, ctx=ctx)
            self._reply.emit(reply)
            turn = {'chat_id': self._turn_chat_id, 'user_id': self._turn_user_id,
                    'message': self._turn_message}
            # Cloud persistence must not keep the chat disabled for its HTTP timeout.
            threading.Thread(target=self._upload_turn, args=(reply, steps, turn), daemon=True).start()
        except Exception as exc:
            self._error.emit(type(exc).__name__ + ": " + str(exc))
        self._done.emit()

    # ---------- 对话上云（网页端历史里可见） ----------
    def _upload_turn(self, reply, steps=None, turn=None):
        """把刚完成的一轮（消息+回复+工具步骤）追加到云端会话。静默失败，不打扰聊天。"""
        try:
            from echo.backend import account
            turn = turn or {'chat_id': self._turn_chat_id, 'user_id': self._turn_user_id,
                            'message': self._turn_message}
            if not account.token() or not account.current_user():
                return
            uid = str((account.current_user() or {}).get('id') or '')
            if not uid or uid != turn['user_id']:
                return  # Never upload the previous account's turn to a newly signed-in account.
            account.request(
                '/v1/me/assistant/chats/' + turn['chat_id'] + '/messages',
                {"origin": "desktop",
                 "message": turn['message'][:4000],
                 "reply": str(reply)[:4000],
                 "steps": list(steps or [])[:12]},
                timeout=30, max_bytes=65536)
        except Exception:
            pass  # 未登录/离线/限流都不影响本地对话

    def _emit_create_paper(self, subject, goal):
        self.create_paper_requested.emit(subject, goal)
        return tr("已打开清卷工作台，Echo 正在帮你出卷（AI 命题约 1-2 分钟），完成后在清卷窗口导出。",
                  "Qingjuan opened; AI is composing the paper (1-2 min).")

    def _emit_open_view(self, view):
        name = VIEW_ALIASES.get(view, view)
        self.open_view_requested.emit(name)
        return tr("已切换到「", "Switched to \"") + view + tr("」。", "\".")

    def _emit_start_lesson(self, title):
        self.start_lesson_requested.emit(title)
        return tr("开课请求已发出：「", "Lesson start requested: \"") + title + tr("」。", "\".")

    def _emit_open_ai_class(self, topic):
        self.open_ai_class_requested.emit(topic)
        return tr("正在打开 AI 互动课堂：「", "Opening AI classroom: \"") + topic + tr("」。可选知识库讲义和兴趣场景，备课后试听；课后接练习、清卷或今日计划，点击生成才调用模型。", "\". Choose notes and interests, review the lesson, then continue with practice or today's plan. Generation starts only when requested.")
