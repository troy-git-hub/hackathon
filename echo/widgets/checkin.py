"""
Echo - 课堂抽查卡片

课上学生可能在走神。Echo 每隔一阵拿「老师刚讲过的知识点」抽一道小题，
显在听课页上：答对就过去，答不上来的一句话讲清，并记进错题本等课后复习。

自包含组件：自己管自己的样式和状态，宿主只要
    card.ask(question)            # 弹题
    card.show_result(record)      # 显示判分和讲解
    card.dismiss()                # 收起
并接两个信号：
    card.answered(int)            # 学生选了第几个选项 → bridge.answer_checkin(i)
    card.skipped()                # 学生点了关闭 → bridge.skip_checkin()
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from echo.i18n import tr
from echo.theme import Colors, Radius, Spacing, font


class CheckinCard(QFrame):
    """课堂抽查浮层。默认隐藏，ask() 时才出现。"""

    answered = pyqtSignal(int)
    skipped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CheckinCard")
        self._question = {}
        self._option_buttons = []
        self._locked = False
        self._build()
        self.hide()

    # ---------- 构建 ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.MD + 2, Spacing.SM + 4, Spacing.MD + 2, Spacing.MD)
        root.setSpacing(Spacing.SM)

        head = QHBoxLayout()
        head.setSpacing(Spacing.SM)
        self.tag = QLabel(tr("课堂抽查", "Quick check"))
        self.tag.setObjectName("CheckinTag")
        self.tag.setFont(font(11, 600))
        self.topic = QLabel("")
        self.topic.setFont(font(11))
        head.addWidget(self.tag)
        head.addWidget(self.topic)
        head.addStretch(1)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("CheckinClose")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip(tr("知道了，继续听课", "Got it, back to class"))
        self.close_btn.clicked.connect(self._on_skip)
        head.addWidget(self.close_btn)
        root.addLayout(head)

        self.question_lbl = QLabel("")
        self.question_lbl.setWordWrap(True)
        self.question_lbl.setFont(font(13, 600))
        root.addWidget(self.question_lbl)

        self.options_box = QVBoxLayout()
        self.options_box.setSpacing(6)
        root.addLayout(self.options_box)

        # 判分结果：答完才显示
        self.result_box = QWidget()
        rl = QVBoxLayout(self.result_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.verdict = QLabel("")
        self.verdict.setFont(font(12, 600))
        self.answer_lbl = QLabel("")
        self.answer_lbl.setWordWrap(True)
        self.answer_lbl.setFont(font(12))
        self.explain_lbl = QLabel("")
        self.explain_lbl.setWordWrap(True)
        self.explain_lbl.setFont(font(12))
        self.note_lbl = QLabel("")
        self.note_lbl.setWordWrap(True)
        self.note_lbl.setFont(font(11))
        for w in (self.verdict, self.answer_lbl, self.explain_lbl, self.note_lbl):
            rl.addWidget(w)
        self.result_box.hide()
        root.addWidget(self.result_box)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QFrame#CheckinCard {{
                background: {Colors.ACCENT_SOFT};
                border: 1px solid {Colors.ACCENT_BORDER};
                border-radius: {Radius.LG}px;
            }}
            QFrame#CheckinCard QLabel {{ color: {Colors.TEXT_PRIMARY}; background: transparent; }}
            QLabel#CheckinTag {{ color: {Colors.ACCENT}; }}
            QLabel#CheckinHint {{ color: {Colors.TEXT_SECONDARY}; }}
            QPushButton#CheckinClose {{
                background: transparent; border: none;
                color: {Colors.TEXT_SECONDARY}; font-size: 12px;
            }}
            QPushButton#CheckinClose:hover {{
                color: {Colors.TEXT_PRIMARY}; background: {Colors.SURFACE_HOVER};
                border-radius: {Radius.SM}px;
            }}
            QPushButton#CheckinOption {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
                padding: 7px 10px;
                text-align: left;
                font-size: 12px;
            }}
            QPushButton#CheckinOption:hover {{
                background: {Colors.SURFACE_HOVER};
                border-color: {Colors.ACCENT};
            }}
            QPushButton#CheckinOption:disabled {{ color: {Colors.TEXT_SECONDARY}; }}
            QPushButton#CheckinOption[state="right"] {{
                background: {Colors.OK_SOFT};
                border-color: {Colors.OK_FG};
                color: {Colors.OK_FG};
            }}
            QPushButton#CheckinOption[state="wrong"] {{
                background: {Colors.DANGER_BG};
                border-color: {Colors.DANGER};
                color: {Colors.DANGER};
            }}
        """)

    # ---------- 对外 ----------
    @property
    def asking(self) -> bool:
        """是否正等着学生作答（宿主可用来判断要不要拦别的交互）。"""
        return self.isVisible() and not self._locked

    def preparing(self, text: str = ""):
        """学生自己按了「考考我」：先把卡片亮出来，题目回来再填进去。

        否则点了按钮要等好几秒才出东西，学生会以为没反应。
        """
        text = text or tr("Echo 正在看老师刚讲了什么…", "Echo is checking what the teacher just covered…")
        self._question = {}
        self._locked = True
        self.topic.setText("")
        self.question_lbl.setText(text)
        self.result_box.hide()
        self._clear_options()
        hint = QLabel(tr("出题中…", "Writing a question…"))
        hint.setObjectName("CheckinHint")
        hint.setFont(font(11))
        self.options_box.addWidget(hint)
        self.show()
        self.raise_()

    def ask(self, question: dict):
        """弹出一道抽问题。question 来自 bridge.checkin 信号。"""
        self._question = question or {}
        self._locked = False
        self.topic.setText(self._question.get("topic") or "")
        self.question_lbl.setText(self._question.get("question") or "")
        self.result_box.hide()
        self._clear_options()

        options = self._question.get("options") or []
        for i, text in enumerate(options):
            btn = QPushButton(str(text))
            btn.setObjectName("CheckinOption")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._on_answer(idx))
            self.options_box.addWidget(btn)
            self._option_buttons.append(btn)
        if not options:      # 兜底：没有选项时给一个「知道了」
            btn = QPushButton(tr("知道了", "Got it"))
            btn.setObjectName("CheckinOption")
            btn.clicked.connect(lambda: self._on_answer(0))
            self.options_box.addWidget(btn)
            self._option_buttons.append(btn)

        self.show()
        self.raise_()

    def show_result(self, record: dict):
        """显示判分：标出对错选项，答错时给一句话讲解。"""
        record = record or {}
        self._locked = True
        choice = record.get("choice", -1)
        result = record.get("result")
        right_letter = (self._question.get("answer") or "").upper()[:1]

        for i, btn in enumerate(self._option_buttons):
            btn.setEnabled(False)
            state = ""
            if not self._question.get("self_report") and right_letter:
                if str(btn.text()).strip().upper().startswith(right_letter):
                    state = "right"
            if i == choice:
                state = "right" if result == "right" else "wrong"
            btn.setProperty("state", state)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if result == "right":
            self.verdict.setText(tr("✓ 跟上了", "✓  Got it"))
            self.verdict.setStyleSheet(f"color:{Colors.OK_FG};")
        elif result == "unsure":
            self.verdict.setText(tr("≈ 有点模糊", "≈  A bit fuzzy"))
            self.verdict.setStyleSheet(f"color:{Colors.ACCENT};")
        else:
            self.verdict.setText(tr("✗ 这里没跟上", "✗  Lost track here"))
            self.verdict.setStyleSheet(f"color:{Colors.DANGER};")

        answer = record.get("answer_text") or ""
        self.answer_lbl.setText(tr(f"正确答案：{answer}", f"Correct answer: {answer}")
                                if answer and result != "right" else "")
        self.answer_lbl.setVisible(bool(self.answer_lbl.text()))
        explain = record.get("explain") or ""
        self.explain_lbl.setText(explain)
        self.explain_lbl.setVisible(bool(explain))
        if result == "right":
            self.note_lbl.setText("")
        else:
            self.note_lbl.setText(tr("已记进错题本，课后复习时会带上它。",
                                     "Saved to your mistakes — it'll come up in review."))
        self.note_lbl.setVisible(bool(self.note_lbl.text()))
        self.result_box.show()

    def dismiss(self):
        self._locked = False
        self._clear_options()
        self.hide()

    # ---------- 内部 ----------
    def _clear_options(self):
        while self.options_box.count():
            item = self.options_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._option_buttons = []

    def _on_answer(self, idx: int):
        if self._locked:
            return
        self._locked = True
        for btn in self._option_buttons:      # 先锁住，避免重复点
            btn.setEnabled(False)
        self.answered.emit(idx)

    def _on_skip(self):
        if self._locked:
            self.dismiss()
            return
        self.skipped.emit()
        self.dismiss()
