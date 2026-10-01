"""
Echo - 悬浮主窗口
状态机：compact(小窗) -> expanded(掉队分析) -> lesson(30秒补上) -> compact
课程结束 -> echo(回响页)
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QSizePolicy, QStackedWidget,
                             QSpacerItem)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QRectF
from PyQt5.QtGui import QFont, QCursor, QPainter, QPainterPath, QColor, QBrush

from echo.theme import Colors, Radius, font, Spacing
from echo.components.buttons import StateButton, PrimaryButton, GhostButton
from echo.components.timeline import ConceptTimeline
from echo.components.progress_bar import MasteryList
from echo.components.pet import PetWidget, BubbleLabel
from echo.mock_data import Concept
from echo.backend.engine import parse_tc
from echo.backend.qt_bridge import EchoBridge


class FloatingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("EchoRoot")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.current_tc = "00:00"
        self.current_concept = Concept("00:00", "等待老师开讲…", [], [], "", "now")
        self.last_bp = None

        # 拖拽
        self._drag_pos = None

        self._build_ui()
        self._switch_pet()

        # 后端：transcript → concept timeline → break point → 回响
        self.echo = EchoBridge(parent=self)
        self.echo.transcript.connect(self._on_transcript)
        self.echo.concept.connect(self._on_concept)
        self.echo.breakpoint.connect(self._on_breakpoint)
        self.echo.echo.connect(self._on_echo)
        self.echo.status.connect(self._on_status)
        self.echo.error.connect(self._on_error)
        self.echo.start()

    # ========== UI 构建 ==========
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        root.setSpacing(0)

        # 标题栏
        root.addWidget(self._build_title_bar())
        root.addSpacing(Spacing.SM)

        # 内容堆叠：pet -> panel -> expanded -> lesson -> echo
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_pet())         # 0
        self.stack.addWidget(self._build_panel())       # 1
        self.stack.addWidget(self._build_expanded())    # 2
        self.stack.addWidget(self._build_lesson())      # 3
        self.stack.addWidget(self._build_echo())        # 4
        root.addWidget(self.stack)

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(28)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 2, 0)

        logo = QLabel("Echo")
        logo.setFont(font(12, QFont.DemiBold))
        lay.addWidget(logo)

        # 状态点
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 10px;")
        lay.addWidget(self.dot)
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("Caption")
        lay.addWidget(self.status_lbl)
        lay.addStretch()

        self.end_btn = QPushButton("结束课程")
        self.end_btn.setObjectName("Ghost")
        self.end_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.end_btn.clicked.connect(self._go_echo)
        lay.addWidget(self.end_btn)

        return bar

    # ----- 桌宠态（默认外壳）-----
    def _build_pet(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignCenter)

        # 知识点气泡
        self.bubble = BubbleLabel(f"老师正在讲：{self.current_concept.topic}")
        self.bubble.setMaximumWidth(200)
        lay.addWidget(self.bubble, 0, Qt.AlignCenter)

        # 桌宠本体
        self.pet = PetWidget()
        self.pet.clicked.connect(self._switch_panel)
        lay.addWidget(self.pet, 0, Qt.AlignCenter)

        hint = QLabel("点我展开")
        hint.setObjectName("Caption")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        return page

    # ----- 功能面板（点桌宠后展开）-----
    def _build_panel(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        hint = QLabel("老师正在讲")
        hint.setObjectName("Caption")
        lay.addWidget(hint)

        self.topic_lbl = QLabel(self.current_concept.topic)
        self.topic_lbl.setObjectName("Topic")
        lay.addWidget(self.topic_lbl)

        # 进度条
        self.progress = QFrame()
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet(
            f"background-color: {Colors.PRIMARY}; border-radius: 2px;"
        )
        self.progress.setFixedWidth(340)
        lay.addWidget(self.progress)

        # 时间
        self.tc_lbl = QLabel(self.current_tc)
        self.tc_lbl.setObjectName("Timecode")
        lay.addWidget(self.tc_lbl)

        lay.addSpacing(Spacing.XS)

        # 三个状态按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.SM)
        self.btn_ok = StateButton("✓", "跟上了", "ok")
        self.btn_warn = StateButton("?", "有点懵", "warn")
        self.btn_lost = StateButton("!", "我掉队了", "lost")
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_warn.clicked.connect(self._on_warn)
        self.btn_lost.clicked.connect(self._on_lost)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_warn)
        btn_row.addWidget(self.btn_lost)
        lay.addLayout(btn_row)

        # 返回桌宠
        back = GhostButton("← 收起")
        back.clicked.connect(self._switch_pet)
        lay.addWidget(back, 0, Qt.AlignRight)

        return page

    # ----- 掉队展开面板 -----
    def _build_expanded(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        header = QLabel("你可能在这里掉队了")
        header.setObjectName("Title")
        lay.addWidget(header)

        # Concept Timeline
        self.timeline = ConceptTimeline()
        lay.addWidget(self.timeline)

        # 缺失提示
        miss_card = QFrame()
        miss_card.setObjectName("SurfaceCard")
        miss_card.setStyleSheet(f"""
            QFrame#SurfaceCard {{
                background-color: {Colors.WARNING_BG};
                border: 1px solid {Colors.WARNING};
                border-radius: {Radius.MD}px;
            }}
        """)
        ml = QVBoxLayout(miss_card)
        ml.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        ml.addWidget(QLabel("可能缺失："))
        self.missing_lbl = QLabel("")
        self.missing_lbl.setFont(font(12, QFont.DemiBold))
        self.missing_lbl.setWordWrap(True)
        ml.addWidget(self.missing_lbl)
        lay.addWidget(miss_card)

        lay.addSpacing(Spacing.XS)

        # 操作按钮
        act = QHBoxLayout()
        act.setSpacing(Spacing.SM)
        self.btn_fill = PrimaryButton("30 秒帮我补上")
        self.btn_fill.clicked.connect(self._go_lesson)
        self.btn_self = GhostButton("我自己看看")
        self.btn_self.clicked.connect(self._switch_panel)
        act.addWidget(self.btn_fill)
        act.addWidget(self.btn_self)
        lay.addLayout(act)

        return page

    # ----- 30 秒补上 -----
    def _build_lesson(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        header = QLabel("补上这一步")
        header.setObjectName("Title")
        lay.addWidget(header)

        # 知识点
        self.lesson_concept_lbl = QLabel("")
        self.lesson_concept_lbl.setObjectName("Topic")
        self.lesson_concept_lbl.setWordWrap(True)
        lay.addWidget(self.lesson_concept_lbl)

        # micro lesson 内容
        self.lesson_body = QLabel("")
        self.lesson_body.setObjectName("Body")
        self.lesson_body.setWordWrap(True)
        self.lesson_body.setStyleSheet(f"background-color: {Colors.SURFACE}; "
                                       f"border-radius: {Radius.MD}px; "
                                       f"padding: {Spacing.MD}px; "
                                       f"border: 1px solid {Colors.BORDER};")
        lay.addWidget(self.lesson_body)

        lay.addStretch()

        act = QHBoxLayout()
        self.btn_gotit = PrimaryButton("✓ 补上了，继续听课")
        self.btn_gotit.clicked.connect(self._on_fixed)
        act.addWidget(self.btn_gotit)
        lay.addLayout(act)

        return page

    # ----- 回响页 -----
    def _build_echo(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        header = QLabel("今天的课")
        header.setObjectName("Title")
        lay.addWidget(header)

        self.echo_hint = QLabel("正在生成回响…")
        self.echo_hint.setObjectName("BodySecondary")
        lay.addWidget(self.echo_hint)

        self.mastery = MasteryList()
        lay.addWidget(self.mastery)

        # 掉队点复习链
        chain_card = QFrame()
        chain_card.setObjectName("SurfaceCard")
        cl = QVBoxLayout(chain_card)
        cl.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        cl.addWidget(QLabel("你的掉队点"))

        self.chain_box = QWidget()
        self.chain_lay = QVBoxLayout(self.chain_box)
        self.chain_lay.setContentsMargins(0, 0, 0, 0)
        self.chain_lay.setSpacing(2)
        cl.addWidget(self.chain_box)

        self.suggest_lbl = QLabel("")
        self.suggest_lbl.setObjectName("BodySecondary")
        self.suggest_lbl.setWordWrap(True)
        cl.addWidget(self.suggest_lbl)
        lay.addWidget(chain_card)

        lay.addStretch()

        self.btn_restart = GhostButton("重新开始一节课")
        self.btn_restart.clicked.connect(self._restart)
        lay.addWidget(self.btn_restart, 0, Qt.AlignRight)

        return page

    # ========== 状态切换 ==========
    def _switch_pet(self):
        self.stack.setCurrentIndex(0)
        self.setFixedWidth(260)
        self.pet.set_emotion("idle")
        self.adjustSize()

    def _switch_panel(self):
        self.stack.setCurrentIndex(1)
        self.setFixedWidth(420)
        self.adjustSize()

    def _switch_expanded(self):
        self.stack.setCurrentIndex(2)
        self.setFixedWidth(520)
        self.adjustSize()

    def _go_lesson(self):
        self.stack.setCurrentIndex(3)
        self.setFixedWidth(520)
        self.pet.set_emotion("thinking")
        self.adjustSize()

    def _go_echo(self):
        self.echo_hint.setText("正在生成回响…")
        self.echo_hint.show()
        self.mastery.set_skills([])
        self._render_chain([], "")
        self.echo.end_lesson()
        self.stack.setCurrentIndex(4)
        self.setFixedWidth(540)
        self.adjustSize()

    def _restart(self):
        self.current_concept = Concept("00:00", "等待老师开讲…", [], [], "", "now")
        self.topic_lbl.setText(self.current_concept.topic)
        self.bubble.setText(f"老师正在讲：{self.current_concept.topic}")
        self.tc_lbl.setText("00:00")
        self.progress.setFixedWidth(20)
        self.echo.start()
        self._switch_pet()

    # ========== 按钮回调 ==========
    def _on_ok(self):
        self.echo.feedback("ok")
        self._flash(self.btn_ok, Colors.SUCCESS_BG)
        self.pet.set_emotion("ok")
        QTimer.singleShot(2500, lambda: self.pet.set_emotion("idle"))

    def _on_warn(self):
        self.echo.feedback("warn")
        self._flash(self.btn_warn, Colors.WARNING_BG)
        self.pet.set_emotion("warn")

    def _on_lost(self):
        # 核心：调用 Break Point Engine（异步，结果见 _on_breakpoint）
        self.pet.set_emotion("lost")
        self.echo.feedback("lost")
        self.timeline.set_concepts(self.echo.engine.concepts()[-4:] or [self.current_concept])
        self.missing_lbl.setText("Echo 正在回看最近几分钟…")
        self.btn_fill.setEnabled(False)
        self._switch_expanded()

    def _on_fixed(self):
        """补上了：先开心，再缩回桌宠"""
        self.pet.set_emotion("fixed")
        QTimer.singleShot(1500, self._switch_pet)

    def _flash(self, btn, color):
        pass  # 占位：实际可加短暂高亮动画

    # ========== 后端信号 ==========
    def _on_transcript(self, tc, text):
        self.current_tc = tc
        self.tc_lbl.setText(tc)
        if not self.echo.engine.current_concept():
            short = text if len(text) <= 16 else text[:15] + "…"
            self.bubble.setText(f"老师正在讲：{short}")
        total = self.echo.total_seconds
        t = parse_tc(tc) or 0
        if total:
            self.progress.setFixedWidth(max(20, int(340 * min(1.0, t / total))))

    def _on_concept(self, c):
        cur = self.echo.engine.current_concept()
        if cur is not None:
            self.current_concept = cur
            self.topic_lbl.setText(cur.topic)
            self.bubble.setText(f"老师正在讲：{cur.topic}")

    def _on_breakpoint(self, bp, concepts):
        self.last_bp = bp
        self.timeline.set_concepts(concepts, breakpoint_tc=bp.breakpoint_tc,
                                   note=bp.note or "老师快速跳过了推导")
        self.missing_lbl.setText(f"「{bp.missing}」")
        self.lesson_concept_lbl.setText(bp.concept)
        self.lesson_body.setText(bp.micro_lesson)
        self.btn_fill.setEnabled(True)
        if self.stack.currentIndex() == 2:
            self.adjustSize()

    def _on_echo(self, report):
        self.echo_hint.hide()
        self.mastery.set_skills(report.skills)
        self._render_chain(report.review_chain, report.suggestion)
        self.adjustSize()

    def _render_chain(self, chain, suggestion):
        while self.chain_lay.count():
            item = self.chain_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, name in enumerate(chain):
            if i > 0:
                arrow = QLabel("↓")
                arrow.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
                self.chain_lay.addWidget(arrow)
            lbl = QLabel(name)
            lbl.setFont(font(12, QFont.DemiBold if i == 0 else QFont.Normal))
            self.chain_lay.addWidget(lbl)
        if suggestion:
            self.suggest_lbl.setText(suggestion)
        elif chain:
            self.suggest_lbl.setText(f"建议复习：{chain[-1]}")
        else:
            self.suggest_lbl.setText("")

    STATUS_TEXT = {"analyzing": "分析中…", "summarizing": "生成回响…",
                   "loading_asr": "加载语音识别…", "listening": "", "done": ""}

    def _on_status(self, st):
        self.status_lbl.setText(self.STATUS_TEXT.get(st, ""))

    def _on_error(self, msg):
        self.status_lbl.setText("⚠ 网络/AI 出错")
        self.status_lbl.setToolTip(msg)
        if self.stack.currentIndex() == 2 and not self.btn_fill.isEnabled():
            self.missing_lbl.setText("分析失败，请再点一次「我掉队了」")

    def closeEvent(self, e):
        self.echo.shutdown()
        super().closeEvent(e)

    # ========== 拖拽 ==========
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def paintEvent(self, e):
        """绘制 WinUI 风格圆角 + 柔和阴影背景"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)  # 留阴影空间
        # 阴影
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), Radius.LG, Radius.LG)
        # 主体背景（Mica 浅灰）
        p.fillPath(path, QBrush(QColor(Colors.MICA_LIGHT)))
        # 边框
        p.setPen(QColor(Colors.BORDER))
        p.drawPath(path)
        p.end()
