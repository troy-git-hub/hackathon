"""
Echo - 悬浮主窗口
状态机：pet(桌宠) -> panel(听课面板) -> expanded(掉队分析) -> lesson(30秒补上) -> pet
课程结束 -> echo(回响页)
"""
import html
import re

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QSizePolicy, QStackedWidget,
                             QProgressBar)
from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QFont, QCursor, QPainter, QPainterPath, QColor, QBrush, QPen

from echo.theme import Colors, Radius, font, Spacing
from echo.components.buttons import StateButton, PrimaryButton, GhostButton
from echo.components.timeline import ConceptTimeline
from echo.components.progress_bar import MasteryList
from echo.components.pet import PetWidget, BubbleLabel
from echo.components.loading import LoadingCard, PulseDots
from echo.mock_data import Concept
from echo.backend.engine import parse_tc
from echo.backend.qt_bridge import EchoBridge

SHADOW = 14
WAIT_HINT = "播放网课后，Echo 会自动开始听"          # 窗口四周留给阴影的空间
# 各页内容区宽度（不含阴影与内边距）
PAGE_WIDTH = {0: 210, 1: 340, 2: 400, 3: 400, 4: 420}


def _card(name, bg=Colors.SURFACE, border=Colors.BORDER, extra=""):
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(f"QFrame#{name} {{ background-color: {bg}; border: 1px solid {border};"
                    f" border-radius: {Radius.MD}px; {extra} }}")
    return f


def _label(text="", obj=None, wrap=False):
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


_FORMULA = re.compile(r"((?:[A-Za-z]\([^()（）]{1,24}\)|[A-Za-z]\b)"
                      r"(?:[\s·*/+\-=×÷^|∩∪A-Za-z0-9().]|&#x27;|乘|除以)*"
                      r"[A-Za-z0-9)])")


def lesson_html(text: str) -> str:
    """micro lesson 纯文本 → 富文本：步骤序号加粗着色，公式等宽高亮，行距放宽。"""
    paras = []
    for ln in (text or "").strip().split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        esc = html.escape(ln)
        esc = _FORMULA.sub(
            lambda m: (f'<span style="font-family:Consolas,\'Cascadia Mono\',monospace;'
                       f'background-color:#F3F3F3;">{m.group(1)}</span>')
            if ("(" in m.group(1) or "=" in m.group(1)) else m.group(1), esc)
        esc = re.sub(r"^(第[一二三四五六七八九十]+步[：:]|\d+[\.、．])",
                     rf'<b style="color:{Colors.PRIMARY}">\1</b>', esc)
        paras.append(f'<p style="margin:0 0 8px 0; line-height:155%;">{esc}</p>')
    return "".join(paras)


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
        root.setContentsMargins(SHADOW + Spacing.MD, SHADOW + Spacing.SM,
                                SHADOW + Spacing.MD, SHADOW + Spacing.MD)
        root.setSpacing(0)

        # 标题栏
        self.title_bar = self._build_title_bar()
        root.addWidget(self.title_bar)
        self.title_gap = QWidget()
        self.title_gap.setFixedHeight(Spacing.SM)
        root.addWidget(self.title_gap)

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
        bar.setFixedHeight(32)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        logo = QLabel("Echo")
        logo.setFont(font(14, QFont.Bold))
        logo.setStyleSheet(f"color: {Colors.PRIMARY};")
        lay.addWidget(logo)

        # 状态胶囊：● 正在听课 / 分析中 ··· / 出错
        self.status_pill = QFrame()
        self.status_pill.setObjectName("StatusPill")
        sp = QHBoxLayout(self.status_pill)
        sp.setContentsMargins(8, 2, 10, 2)
        sp.setSpacing(5)
        self.dot = QLabel("●")
        sp.addWidget(self.dot)
        self.status_lbl = QLabel("")
        sp.addWidget(self.status_lbl)
        self.status_dots = PulseDots(Colors.WARNING)
        self.status_dots.hide()
        sp.addWidget(self.status_dots)
        lay.addWidget(self.status_pill)
        lay.addStretch()

        self.end_btn = QPushButton("结束课程")
        self.end_btn.setObjectName("Small")
        self.end_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.end_btn.clicked.connect(self._go_echo)
        lay.addWidget(self.end_btn)

        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("Small")
        self.min_btn.setToolTip("收起成桌宠")
        self.min_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.min_btn.clicked.connect(self._switch_pet)
        lay.addWidget(self.min_btn)

        self._set_status("正在听课", Colors.SUCCESS, "#E9F7E8")
        return bar

    def _set_status(self, text, color, bg, busy=False):
        self.status_pill.setStyleSheet(
            f"QFrame#StatusPill {{ background: {bg}; border-radius: 10px; }}"
            f"QLabel {{ color: {color}; font-size: 12px; font-weight: 600; background: transparent; }}")
        self.dot.setStyleSheet(f"color: {color}; font-size: 9px; background: transparent;")
        self.status_lbl.setText(text)
        self.dot.setVisible(not busy)
        if busy:
            self.status_dots._color = QColor(color)
            self.status_dots.start()
        else:
            self.status_dots.stop()

    # ----- 桌宠态（默认外壳）-----
    def _build_pet(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.setAlignment(Qt.AlignCenter)

        # 知识点气泡
        self.bubble = BubbleLabel("")
        self.bubble.setFixedWidth(196)
        self._set_bubble(self.current_concept.topic)
        lay.addWidget(self.bubble, 0, Qt.AlignCenter)

        # 桌宠本体
        self.pet = PetWidget()
        self.pet.setToolTip("点我展开，按住拖动")
        self.pet.clicked.connect(self._switch_panel)
        lay.addWidget(self.pet, 0, Qt.AlignCenter)

        return page

    def _set_bubble(self, topic, caption="老师正在讲"):
        self.bubble.setText(
            f'<span style="font-size:11px; font-weight:400; color:{Colors.TEXT_SECONDARY};">'
            f'{caption}</span><br>{html.escape(topic)}')

    # ----- 功能面板（点桌宠后展开）-----
    def _build_panel(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        head = QHBoxLayout()
        head.addWidget(_label("老师正在讲", "Caption"))
        head.addStretch()
        self.tc_lbl = _label(self.current_tc, "Timecode")
        head.addWidget(self.tc_lbl)
        lay.addLayout(head)

        self.topic_lbl = _label(self.current_concept.topic, "Topic", wrap=True)
        lay.addWidget(self.topic_lbl)

        self.summary_lbl = _label(WAIT_HINT, "BodySecondary", wrap=True)
        lay.addWidget(self.summary_lbl)

        # 课程进度
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()        # 实时听课没有总时长，只有 demo 回放才显示进度
        lay.addWidget(self.progress)

        # 实时字幕
        self.caption_lbl = _label("", wrap=True)
        self.caption_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; background: {Colors.SURFACE};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; padding: 8px 10px;")
        self.caption_lbl.hide()
        lay.addWidget(self.caption_lbl)

        lay.addSpacing(Spacing.XS)

        # 次要反馈 + 主行动「我掉队了」
        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.SM)
        self.btn_ok = StateButton("✓", "跟上了", "ok")
        self.btn_warn = StateButton("?", "有点懵", "warn")
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_warn.clicked.connect(self._on_warn)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_warn)
        lay.addLayout(btn_row)

        self.btn_lost = QPushButton("!   我掉队了")
        self.btn_lost.setObjectName("Lost")
        self.btn_lost.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_lost.setMinimumHeight(42)
        self.btn_lost.clicked.connect(self._on_lost)
        lay.addWidget(self.btn_lost)

        return page

    # ----- 掉队展开面板 -----
    def _build_expanded(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label("你可能在这里掉队了", "Title"))
        self.bp_reason_lbl = _label("", "BodySecondary", wrap=True)
        self.bp_reason_lbl.hide()
        head.addWidget(self.bp_reason_lbl)
        lay.addLayout(head)

        # Concept Timeline
        self.timeline = ConceptTimeline()
        lay.addWidget(self.timeline)

        # 加载中
        self.bp_loading = LoadingCard("Echo 正在回看最近几分钟")
        self.bp_loading.hide()
        lay.addWidget(self.bp_loading)

        # 缺失提示
        self.miss_card = _card("MissCard", "#FFF8E6", "#F7D58A",
                               f"border-left: 4px solid {Colors.NODE_WARN};")
        ml = QVBoxLayout(self.miss_card)
        ml.setContentsMargins(Spacing.MD, Spacing.SM + 2, Spacing.MD, Spacing.SM + 2)
        ml.setSpacing(4)
        cap = _label("可能缺失的一步")
        cap.setStyleSheet(f"color: {Colors.WARNING}; font-size: 12px; font-weight: 600;"
                          "background: transparent; border: none;")
        ml.addWidget(cap)
        self.missing_lbl = _label("", wrap=True)
        self.missing_lbl.setStyleSheet("font-size: 15px; font-weight: 600;"
                                       "background: transparent; border: none;")
        ml.addWidget(self.missing_lbl)
        lay.addWidget(self.miss_card)

        # 操作按钮
        act = QHBoxLayout()
        act.setSpacing(Spacing.SM)
        self.btn_fill = PrimaryButton("30 秒帮我补上")
        self.btn_fill.setMinimumHeight(38)
        self.btn_fill.clicked.connect(self._go_lesson)
        self.btn_self = GhostButton("我自己看看")
        self.btn_self.setMinimumHeight(38)
        self.btn_self.clicked.connect(self._switch_panel)
        act.addWidget(self.btn_fill, 3)
        act.addWidget(self.btn_self, 2)
        lay.addLayout(act)

        return page

    # ----- 30 秒补上 -----
    def _build_lesson(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        lay.addWidget(_label("补上这一步 · 约 30 秒", "Caption"))

        self.lesson_concept_lbl = _label("", "Topic", wrap=True)
        lay.addWidget(self.lesson_concept_lbl)

        self.lesson_missing_lbl = _label("", wrap=True)
        self.lesson_missing_lbl.setStyleSheet(f"color: {Colors.WARNING}; font-size: 13px;")
        lay.addWidget(self.lesson_missing_lbl)

        # micro lesson 内容
        card = _card("LessonCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(Spacing.LG, Spacing.MD + 2, Spacing.LG, Spacing.SM)
        self.lesson_body = _label("", "Body", wrap=True)
        self.lesson_body.setTextFormat(Qt.RichText)
        self.lesson_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lesson_body.setStyleSheet("font-size: 13px; background: transparent; border: none;")
        cl.addWidget(self.lesson_body)
        lay.addWidget(card)

        lay.addSpacing(Spacing.XS)

        self.btn_gotit = PrimaryButton("✓  补上了，继续听课")
        self.btn_gotit.setMinimumHeight(38)
        self.btn_gotit.clicked.connect(self._on_fixed)
        lay.addWidget(self.btn_gotit)

        return page

    # ----- 回响页 -----
    def _build_echo(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label("今天的课", "Title"))
        self.echo_sub = _label("", "Caption")
        head.addWidget(self.echo_sub)
        lay.addLayout(head)

        self.echo_hint = LoadingCard("Echo 正在生成课堂回响")
        lay.addWidget(self.echo_hint)

        self.mastery_card = _card("MasteryCard")
        mc = QVBoxLayout(self.mastery_card)
        mc.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        self.mastery = MasteryList()
        mc.addWidget(self.mastery)
        lay.addWidget(self.mastery_card)

        # 掉队点复习链
        self.chain_card = _card("ChainCard")
        cl = QVBoxLayout(self.chain_card)
        cl.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        cl.setSpacing(Spacing.SM)
        cap = _label("你的掉队点 → 复习路径", "Caption")
        cap.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;")
        cl.addWidget(cap)

        self.chain_box = QWidget()
        self.chain_lay = QVBoxLayout(self.chain_box)
        self.chain_lay.setContentsMargins(0, 0, 0, 0)
        self.chain_lay.setSpacing(0)
        cl.addWidget(self.chain_box)

        self.suggest_lbl = _label("", wrap=True)
        self.suggest_lbl.setStyleSheet(
            f"color: {Colors.PRIMARY}; background: {Colors.PRIMARY_LIGHT}; font-size: 12px;"
            f"border-radius: {Radius.SM}px; padding: 6px 8px;")
        cl.addWidget(self.suggest_lbl)
        lay.addWidget(self.chain_card)

        self.btn_restart = QPushButton("重新开始一节课")
        self.btn_restart.setObjectName("Small")
        self.btn_restart.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_restart.clicked.connect(self._restart)
        lay.addWidget(self.btn_restart, 0, Qt.AlignRight)

        return page

    # ========== 状态切换 ==========
    def _show_page(self, idx):
        # 非当前页设为 Ignored，避免 QStackedWidget 按最高的页面撑高窗口
        for i in range(self.stack.count()):
            self.stack.widget(i).setSizePolicy(
                QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored,
                QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored)
        self.stack.setCurrentIndex(idx)
        is_pet = idx == 0
        if is_pet:
            self.layout().setContentsMargins(4, 4, 4, 4)
        else:
            self.layout().setContentsMargins(SHADOW + Spacing.MD, SHADOW + Spacing.SM,
                                             SHADOW + Spacing.MD, SHADOW + Spacing.MD)
        self.title_bar.setVisible(not is_pet)
        self.title_gap.setVisible(not is_pet)
        self.min_btn.setVisible(idx in (1, 2, 3))
        self.end_btn.setVisible(idx != 4)
        m = self.layout().contentsMargins()
        self.setFixedWidth(PAGE_WIDTH[idx] + m.left() + m.right())
        self._fit()

    def _fit(self):
        # 只按当前页计算高度（QStackedLayout 的 heightForWidth 会取所有页的最大值）
        def do():
            idx = self.stack.currentIndex()
            page = self.stack.currentWidget()
            pl = page.layout()
            pl.activate()
            w = PAGE_WIDTH[idx]
            h = pl.totalHeightForWidth(w) if pl.hasHeightForWidth() else pl.totalSizeHint().height()
            m = self.layout().contentsMargins()
            if self.title_bar.isVisible():
                h += self.title_bar.height() + self.title_gap.height()
            self.setFixedHeight(h + m.top() + m.bottom())
        do()
        QTimer.singleShot(0, do)   # 换行文本需要一轮事件循环后才能算准高度
        self.update()

    def _switch_pet(self):
        self._show_page(0)
        self.pet.set_emotion("idle")

    def _switch_panel(self):
        self._show_page(1)

    def _switch_expanded(self):
        self._show_page(2)

    def _go_lesson(self):
        self._show_page(3)
        self.pet.set_emotion("thinking")

    def _go_echo(self):
        self.echo_hint.start("Echo 正在生成课堂回响")
        self.echo_sub.setText("")
        self.mastery_card.hide()
        self.chain_card.hide()
        self._render_chain([], "")
        self.echo.end_lesson()
        self._show_page(4)

    def _restart(self):
        self.current_concept = Concept("00:00", "等待老师开讲…", [], [], "", "now")
        self.topic_lbl.setText(self.current_concept.topic)
        self.summary_lbl.setText(WAIT_HINT)
        self.summary_lbl.show()
        self.caption_lbl.hide()
        self._set_bubble(self.current_concept.topic)
        self.tc_lbl.setText("00:00")
        self.progress.setValue(0)
        self._set_status("正在听课", Colors.SUCCESS, "#E9F7E8")
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
        self.bp_reason_lbl.hide()
        self.miss_card.hide()
        self.bp_loading.start("Echo 正在回看最近几分钟，寻找你的知识断点")
        self.btn_fill.setEnabled(False)
        self._switch_expanded()

    def _on_fixed(self):
        """补上了：先开心，再缩回桌宠"""
        self.pet.set_emotion("fixed")
        QTimer.singleShot(1500, self._switch_pet)

    def _flash(self, btn, color):
        """点击后短暂显示「已记录」，给学生一个确认感。"""
        if getattr(btn, "_orig_text", None) is None:
            btn._orig_text = btn.text()
        btn.setText("  已记录")
        btn.setEnabled(False)

        def restore():
            btn.setText(btn._orig_text)
            btn.setEnabled(True)
        QTimer.singleShot(900, restore)

    # ========== 后端信号 ==========
    def _on_transcript(self, tc, text):
        self.current_tc = tc
        self.tc_lbl.setText(tc)
        short = text if len(text) <= 60 else text[:58] + "…"
        self.caption_lbl.setText(f"“{short}”")
        if self.caption_lbl.isHidden():
            self.caption_lbl.show()
            if self.stack.currentIndex() == 1:
                self._fit()
        if not self.echo.engine.current_concept():
            s = text if len(text) <= 16 else text[:15] + "…"
            self._set_bubble(s)
            if self.stack.currentIndex() == 0:
                self._fit()
        total = self.echo.total_seconds
        t = parse_tc(tc) or 0
        self.progress.setVisible(bool(total))
        if total:
            self.progress.setValue(int(1000 * min(1.0, t / total)))

    def _on_concept(self, c):
        cur = self.echo.engine.current_concept()
        if cur is not None:
            self.current_concept = cur
            self.topic_lbl.setText(cur.topic)
            self.summary_lbl.setText(cur.summary)
            self.summary_lbl.setVisible(bool(cur.summary))
            self._set_bubble(cur.topic)
            if self.stack.currentIndex() in (0, 1):
                self._fit()

    def _on_breakpoint(self, bp, concepts):
        self.last_bp = bp
        self.timeline.set_concepts(concepts, breakpoint_tc=bp.breakpoint_tc,
                                   note=bp.note or "老师快速跳过了推导")
        self.bp_loading.stop()
        self.bp_reason_lbl.setText(bp.reason)
        self.bp_reason_lbl.setVisible(bool(bp.reason))
        self.missing_lbl.setText(f"「{bp.missing}」")
        self.miss_card.show()
        self.lesson_concept_lbl.setText(bp.concept)
        self.lesson_missing_lbl.setText(f"「{bp.missing}」")
        self.lesson_body.setText(lesson_html(bp.micro_lesson))
        self.btn_fill.setEnabled(True)
        if self.stack.currentIndex() in (2, 3):
            self._fit()

    def _on_echo(self, report):
        self.echo_hint.stop()
        self.mastery.set_skills(report.skills)
        self.mastery_card.setVisible(bool(report.skills))
        weak = sum(1 for s in report.skills if s.status != "ok")
        self.echo_sub.setText(f"{len(report.skills)} 个知识点 · {weak} 个需要复习")
        self._render_chain(report.review_chain, report.suggestion)
        self.chain_card.setVisible(bool(report.review_chain or report.suggestion))
        self._fit()

    def _render_chain(self, chain, suggestion):
        while self.chain_lay.count():
            item = self.chain_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        n = len(chain)
        for i, name in enumerate(chain):
            if i > 0:
                arrow = QLabel("↓")
                arrow.setFixedWidth(28)
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; font-size: 13px;")
                self.chain_lay.addWidget(arrow)
            row = QHBoxLayout()
            row.setSpacing(Spacing.SM)
            if i == 0:
                fg, bg, tag = Colors.DANGER, Colors.DANGER_BG, "掉队点"
            elif i == n - 1:
                fg, bg, tag = Colors.PRIMARY, Colors.PRIMARY_LIGHT, "先复习这里"
            else:
                fg, bg, tag = Colors.TEXT_PRIMARY, Colors.SURFACE_PRESSED, ""
            chip = QLabel(name)
            if len(name) > 18:
                chip.setWordWrap(True)
                chip.setFixedWidth(300)
            chip.setStyleSheet(f"color: {fg}; background: {bg}; border-radius: {Radius.SM}px;"
                               f"padding: 4px 10px; font-size: 13px;"
                               f"font-weight: {600 if tag else 400};")
            row.addWidget(chip, 0)
            if tag:
                t = QLabel(tag)
                t.setStyleSheet(f"color: {fg}; font-size: 11px;")
                row.addWidget(t)
            row.addStretch()
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self.chain_lay.addWidget(holder)
        if suggestion:
            self.suggest_lbl.setText(suggestion)
        elif chain:
            self.suggest_lbl.setText(f"建议复习：{chain[-1]}")
        else:
            self.suggest_lbl.setText("")
        self.suggest_lbl.setVisible(bool(self.suggest_lbl.text()))

    STATUS_STYLE = {
        "listening":   ("正在听课", Colors.SUCCESS, "#E9F7E8", False),
        "analyzing":   ("分析中", Colors.WARNING, "#FFF4CE", True),
        "summarizing": ("生成回响", Colors.PRIMARY, Colors.PRIMARY_LIGHT, True),
        "loading_asr": ("正在加载语音识别", Colors.PRIMARY, Colors.PRIMARY_LIGHT, True),
        "done":        ("已下课", Colors.TEXT_SECONDARY, Colors.SURFACE_PRESSED, False),
    }

    def _on_status(self, st):
        text, color, bg, busy = self.STATUS_STYLE.get(st, self.STATUS_STYLE["listening"])
        self._set_status(text, color, bg, busy)
        self.status_pill.setToolTip("")
        # 还没有知识点时，桌宠气泡和面板也同步提示启动状态
        if not self.echo.engine.current_concept():
            if st == "loading_asr":
                self._set_bubble("正在加载语音识别…", caption="Echo 准备中")
                self.summary_lbl.setText("首次加载约 10 秒，之后会自动开始听")
            elif st == "listening":
                self._set_bubble(self.current_concept.topic)
                self.summary_lbl.setText(WAIT_HINT)
            if self.stack.currentIndex() in (0, 1):
                self._fit()

    def _on_error(self, msg):
        self._set_status("AI 出错", Colors.DANGER, Colors.DANGER_BG)
        self.status_pill.setToolTip(msg)
        if self.stack.currentIndex() == 2 and not self.btn_fill.isEnabled():
            self.bp_loading.stop()
            self.missing_lbl.setText("分析失败，请再点一次「我掉队了」")
            self.miss_card.show()
            self._fit()
        if self.stack.currentIndex() == 4 and self.echo_hint.isVisible():
            self.echo_hint.setText("回响生成失败，请检查网络后重试")

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
        """WinUI 风格圆角卡片 + 柔和阴影；桌宠态完全透明。"""
        if self.stack.currentIndex() == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        # 阴影：多层半透明圆角矩形向外扩散，略向下偏移
        p.setPen(Qt.NoPen)
        for i in range(SHADOW, 0, -1):
            a = int(22 * (1 - i / SHADOW) ** 2)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(rect.adjusted(-i, -i + 3, i, i + 3), Radius.LG + i, Radius.LG + i)
        path = QPainterPath()
        path.addRoundedRect(rect, Radius.LG, Radius.LG)
        p.fillPath(path, QBrush(QColor("#F9F9F9")))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#DADADA"), 1))
        p.drawPath(path)
        p.end()
