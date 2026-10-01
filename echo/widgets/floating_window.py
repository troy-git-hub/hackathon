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
from echo.mock_data import (MockStream, SAMPLE_CONCEPTS, find_breakpoint,
                            SAMPLE_ECHO_SKILLS, SAMPLE_REVIEW_CHAIN, Concept)


class FloatingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("EchoRoot")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 模拟数据
        self.stream = MockStream()
        self.current_tc = "18:42"
        self.current_concept = SAMPLE_CONCEPTS[-1]

        # 拖拽
        self._drag_pos = None

        self._build_ui()
        self._switch_pet()

        # 模拟实时 transcript
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_transcript)
        self.timer.start(3000)

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
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 10px;")
        lay.addWidget(dot)
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
        self.timeline.set_concepts(SAMPLE_CONCEPTS, breakpoint_tc="18:39")
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
        self.missing_lbl = QLabel(
            "「为什么 P(A|B) 可以反过来算？」"
        )
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
        concept_lbl = QLabel("贝叶斯公式")
        concept_lbl.setObjectName("Topic")
        lay.addWidget(concept_lbl)

        # micro lesson 内容
        self.lesson_body = QLabel(
            "其实贝叶斯公式就是条件概率定义的一个变形。\n\n"
            "第一步：由条件概率定义，P(A|B) = P(A∩B) / P(B)。\n"
            "第二步：同样，P(B|A) = P(A∩B) / P(A)，\n"
            "        所以 P(A∩B) = P(B|A)·P(A)。\n"
            "第三步：代回第一步，得到\n"
            "        P(A|B) = P(B|A)·P(A) / P(B)。\n\n"
            "只是把「A 交 B」用两种方式表示了一下。"
        )
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
        self.btn_gotit.clicked.connect(self._switch_pet)
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

        self.mastery = MasteryList()
        self.mastery.set_skills(SAMPLE_ECHO_SKILLS)
        lay.addWidget(self.mastery)

        # 掉队点复习链
        chain_card = QFrame()
        chain_card.setObjectName("SurfaceCard")
        cl = QVBoxLayout(chain_card)
        cl.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        cl.addWidget(QLabel("你的掉队点"))

        chain_lay = QVBoxLayout()
        chain_lay.setSpacing(2)
        for i, name in enumerate(SAMPLE_REVIEW_CHAIN):
            row = QHBoxLayout()
            arrow = QLabel("↓" if i > 0 else "")
            arrow.setFixedWidth(16)
            arrow.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            row.addWidget(arrow)
            lbl = QLabel(name)
            lbl.setFont(font(12, QFont.DemiBold if i == 0 else QFont.Normal))
            row.addWidget(lbl)
            row.addStretch()
            chain_lay.addLayout(row)
        cl.addLayout(chain_lay)

        suggest = QLabel(f"建议复习：{SAMPLE_REVIEW_CHAIN[-1]}")
        suggest.setObjectName("BodySecondary")
        cl.addWidget(suggest)
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
        self.adjustSize()

    def _go_echo(self):
        self.timer.stop()
        self.stack.setCurrentIndex(4)
        self.setFixedWidth(540)
        self.adjustSize()

    def _restart(self):
        self.stream.reset()
        self.timer.start(3000)
        self._switch_pet()

    # ========== 按钮回调 ==========
    def _on_ok(self):
        self._flash(self.btn_ok, Colors.SUCCESS_BG)

    def _on_warn(self):
        self._flash(self.btn_warn, Colors.WARNING_BG)

    def _on_lost(self):
        # 核心：调用 Break Point Engine
        bp = find_breakpoint("", SAMPLE_CONCEPTS, self.current_concept)
        self.missing_lbl.setText(f"「{bp.missing}」")
        self._switch_expanded()

    def _flash(self, btn, color):
        pass  # 占位：实际可加短暂高亮动画

    # ========== 模拟实时 transcript ==========
    def _tick_transcript(self):
        nxt = self.stream.next()
        if nxt is None:
            return
        tc, text = nxt
        self.current_tc = tc
        self.tc_lbl.setText(tc)
        # 同步气泡
        short = text if len(text) <= 16 else text[:15] + "…"
        self.bubble.setText(f"老师正在讲：{short}")
        # 简单滚动进度
        w = int(340 * (self.stream._idx / len(self.stream._lines)))
        self.progress.setFixedWidth(max(20, w))

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
