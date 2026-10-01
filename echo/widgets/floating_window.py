"""
Echo - 悬浮主窗口（学习工具风格）

页面：
  0 listen   默认听课卡片：当前知识点 + 实时字幕 + 始终可见的「我掉队了」
  1 mini     折叠条：猫头像 + 知识点 + 「掉队」
  2 break    断点页（产品主画面）：刚才会的 → 掉队的那一步 → 老师讲到这里 + 你缺的这一步
  3 lesson   补课三段式：你已经知道 → 中间漏了这一步 → 所以现在你能听懂
  4 echo     回响：每个知识点一条掌握度条 + ✓ ? ! ；你的掉队点 ↓ 前置 ↓ 建议复习
"""
import html
import re

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QSizePolicy, QStackedWidget,
                             QProgressBar, QApplication)
from PyQt5.QtCore import Qt, QTimer, QRectF, QPoint
from PyQt5.QtGui import QFont, QCursor, QPainter, QPainterPath, QColor, QBrush, QPen

from echo.theme import Colors, Radius, font, Spacing
from echo.components.loading import PulseDots
from echo.components.study import (CatAvatar, BreakPath, LessonStep, SkillRow,
                                   ReviewChain, echo_status, echo_mark)
from echo.mock_data import Concept
from echo.backend.engine import parse_tc
from echo.backend.qt_bridge import EchoBridge

SHADOW = 14
WAIT_HINT = "播放网课后，Echo 会自动开始听"
LISTEN, MINI, BREAK, LESSON, ECHO = range(5)
# 各页内容区宽度（不含阴影与内边距）
PAGE_WIDTH = {LISTEN: 340, MINI: 300, BREAK: 380, LESSON: 400, ECHO: 380}


def _label(text="", style="", wrap=False):
    l = QLabel(text)
    l.setWordWrap(wrap)
    if style:
        l.setStyleSheet(style + "background: transparent;")
    return l


def _btn(text, obj, slot, tip=""):
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(QCursor(Qt.PointingHandCursor))
    b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


CAPTION = f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"
TITLE = f"color: {Colors.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;"

_FORMULA = re.compile(r"((?:[A-Za-z]\([^()（）]{1,24}\)|[A-Za-z]\b)"
                      r"(?:[\s·*/+\-=×÷^|∩∪A-Za-z0-9().]|&#x27;|乘|除以)*"
                      r"[A-Za-z0-9)])")


def rich(text: str) -> str:
    """纯文本 → 富文本：公式等宽高亮，行距放宽，步骤序号弱化。"""
    paras = []
    for ln in (text or "").strip().split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        esc = html.escape(ln)
        esc = _FORMULA.sub(
            lambda m: (f'<span style="font-family:Consolas,\'Cascadia Mono\',monospace;'
                       f'white-space:nowrap; background-color:{Colors.CODE_BG};">&nbsp;{m.group(1)}&nbsp;</span>')
            if ("(" in m.group(1) or "=" in m.group(1)) else m.group(1), esc)
        esc = re.sub(r"^(第[一二三四五六七八九十\d]+步[：:]|\d+[\.、．])",
                     rf'<span style="color:{Colors.TEXT_SECONDARY}">\1</span>', esc)
        paras.append(f'<p style="margin:0 0 6px 0; line-height:150%;">{esc}</p>')
    return "".join(paras)


class FloatingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("EchoRoot")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.current_tc = "00:00"
        self.current_concept = None
        self.last_bp = None
        self.last_bp_concepts = []
        self._fixed = set()          # 学生点过「补上了」的断点知识点
        self._self_look = set()      # 学生点了「我自己看看」的断点知识点
        self._drag_pos = None
        self._page = LISTEN

        self._build_ui()
        self._show_page(LISTEN)

        # 后端：transcript → concept timeline → break point → 回响
        self.echo = EchoBridge(parent=self)
        self.echo.transcript.connect(self._on_transcript)
        self.echo.concept.connect(self._on_concept)
        self.echo.breakpoint.connect(self._on_breakpoint)
        self.echo.echo.connect(self._on_echo)
        self.echo.status.connect(self._on_status)
        self.echo.error.connect(self._on_error)
        self.echo.start()

    # ================= UI 构建 =================
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW + Spacing.LG, SHADOW + Spacing.MD,
                                SHADOW + Spacing.LG, SHADOW + Spacing.LG)
        root.setSpacing(Spacing.MD)

        self.header = self._build_header()
        root.addWidget(self.header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_listen())   # 0
        self.stack.addWidget(self._build_mini())     # 1
        self.stack.addWidget(self._build_break())    # 2
        self.stack.addWidget(self._build_lesson())   # 3
        self.stack.addWidget(self._build_echo())     # 4
        root.addWidget(self.stack)

    def _build_header(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        self.cat = CatAvatar(30)
        self.cat.setToolTip("Echo")
        lay.addWidget(self.cat)

        name = _label("Echo", f"color: {Colors.TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        lay.addWidget(name)

        self.status_dot = _label("●", f"color: {Colors.OK_FG}; font-size: 8px;")
        lay.addWidget(self.status_dot)
        self.status_dots = PulseDots(Colors.ACCENT)
        self.status_dots.hide()
        lay.addWidget(self.status_dots)
        self.status_lbl = _label("正在听课", CAPTION)
        lay.addWidget(self.status_lbl)
        lay.addStretch()

        self.back_btn = _btn("← 回到课堂", "Link", self._back_to_listen)
        lay.addWidget(self.back_btn)
        self.end_btn = _btn("下课", "Link", self._go_echo, "结束这节课，生成回响")
        lay.addWidget(self.end_btn)
        self.fold_btn = _btn("–", "IconBtn", lambda: self._show_page(MINI), "折叠")
        self.fold_btn.setFixedSize(26, 26)
        lay.addWidget(self.fold_btn)
        return bar

    # ----- 0 默认听课卡片 -----
    def _build_listen(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(_label("老师正在讲", CAPTION))
        head.addStretch()
        self.tc_lbl = _label("00:00", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"
                                      "font-family: Consolas, 'Cascadia Mono', monospace;")
        head.addWidget(self.tc_lbl)
        lay.addLayout(head)

        self.topic_lbl = _label("等待老师开讲…", f"color: {Colors.TEXT_PRIMARY}; font-size: 21px;"
                                              "font-weight: 700;", wrap=True)
        lay.addWidget(self.topic_lbl)
        self.summary_lbl = _label(WAIT_HINT, f"color: {Colors.TEXT_SECONDARY}; font-size: 13px;",
                                  wrap=True)
        lay.addWidget(self.summary_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {Colors.BORDER}; border: none; border-radius: 1px; }}"
            f"QProgressBar::chunk {{ background: {Colors.TEXT_SECONDARY}; border-radius: 1px; }}")
        self.progress.hide()        # 实时听课没有总时长，只有 demo 回放显示进度
        lay.addWidget(self.progress)

        # 实时字幕：左侧细线，安静地滚动
        self.caption_lbl = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"
                                      f"border-left: 2px solid {Colors.BORDER_STRONG};"
                                      "padding: 2px 0 2px 10px;", wrap=True)
        self.caption_lbl.hide()
        lay.addWidget(self.caption_lbl)

        lay.addSpacing(Spacing.SM)
        self.btn_lost = _btn("我掉队了", "Accent", self._on_lost, "Echo 回看最近几分钟，找到你从哪一步开始没听懂")
        self.btn_lost.setMinimumHeight(46)
        lay.addWidget(self.btn_lost)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.btn_ok = _btn("✓  跟上了", "Quiet", self._on_ok)
        self.btn_warn = _btn("?  有点懵", "Quiet", self._on_warn)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_warn)
        lay.addLayout(row)
        return page

    # ----- 1 折叠条 -----
    def _build_mini(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)
        self.mini_cat = CatAvatar(28)
        lay.addWidget(self.mini_cat)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(_label("老师正在讲", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"))
        self.mini_topic = _label("等待老师开讲…", f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;"
                                                "font-weight: 600;")
        self.mini_topic.setMinimumWidth(10)
        self.mini_topic.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.mini_topic)
        lay.addLayout(col, 1)
        b = _btn("掉队了", "Accent", self._on_lost)
        b.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        lay.addWidget(b)
        ex = _btn("⌃", "IconBtn", lambda: self._show_page(LISTEN), "展开")
        ex.setFixedSize(26, 26)
        lay.addWidget(ex)
        return page

    # ----- 2 断点页（主画面）-----
    def _build_break(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        self.break_cap = _label("你可能从这里开始掉队", TITLE)
        lay.addWidget(self.break_cap)

        # 加载
        self.bp_loading = QFrame()
        self.bp_loading.setObjectName("BpLoading")
        self.bp_loading.setStyleSheet(f"QFrame#BpLoading {{ background: {Colors.SURFACE};"
                                      f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        bl = QHBoxLayout(self.bp_loading)
        bl.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self.bp_dots = PulseDots(Colors.ACCENT)
        bl.addWidget(self.bp_dots, 0, Qt.AlignVCenter)
        self.bp_loading_lbl = _label("正在回看最近几分钟的课…", f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;",
                                     wrap=True)
        bl.addWidget(self.bp_loading_lbl, 1)
        lay.addWidget(self.bp_loading)

        self.path = BreakPath()
        lay.addWidget(self.path)

        # 你缺的这一步：全页最大、最醒目
        self.miss_card = QFrame()
        self.miss_card.setObjectName("MissCard")
        self.miss_card.setStyleSheet(
            f"QFrame#MissCard {{ background: {Colors.SURFACE}; border: 1px solid {Colors.ACCENT_BORDER};"
            f"border-left: 4px solid {Colors.ACCENT}; border-radius: {Radius.MD}px; }}")
        ml = QVBoxLayout(self.miss_card)
        ml.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        ml.setSpacing(6)
        ml.addWidget(_label("你缺的这一步", f"color: {Colors.ACCENT}; font-size: 12px; font-weight: 700;"))
        self.missing_lbl = _label("", f"color: {Colors.TEXT_PRIMARY}; font-size: 19px; font-weight: 700;",
                                  wrap=True)
        ml.addWidget(self.missing_lbl)
        self.reason_lbl = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;", wrap=True)
        ml.addWidget(self.reason_lbl)
        lay.addWidget(self.miss_card)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.btn_fill = _btn("30 秒补上这一步", "Accent", self._go_lesson)
        self.btn_fill.setMinimumHeight(44)
        row.addWidget(self.btn_fill, 3)
        self.btn_self = _btn("我自己看看", "Quiet", self._on_self_look, "不用 AI 讲，收起来回到课堂")
        self.btn_self.setMinimumHeight(44)
        row.addWidget(self.btn_self, 2)
        lay.addLayout(row)
        return page

    # ----- 3 补课三段式 -----
    def _build_lesson(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label("补上这一步 · 约 30 秒", CAPTION))
        self.lesson_title = _label("", TITLE, wrap=True)
        head.addWidget(self.lesson_title)
        lay.addLayout(head)

        steps = QVBoxLayout()
        steps.setSpacing(0)
        self.step_known = LessonStep("known")
        self.step_main = LessonStep("step")
        self.step_now = LessonStep("now")
        for w in (self.step_known, self.step_main, self.step_now):
            steps.addWidget(w)
        lay.addLayout(steps)

        lay.addSpacing(Spacing.XS)
        self.btn_gotit = _btn("✓  补上了，回到课堂", "Solid", self._on_fixed)
        self.btn_gotit.setMinimumHeight(42)
        lay.addWidget(self.btn_gotit)
        return page

    # ----- 4 回响 -----
    def _build_echo(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label("今天的课", TITLE))
        self.echo_sub = _label("", CAPTION)
        head.addWidget(self.echo_sub)
        lay.addLayout(head)

        self.echo_loading = QFrame()
        self.echo_loading.setObjectName("EchoLoading")
        self.echo_loading.setStyleSheet(f"QFrame#EchoLoading {{ background: {Colors.SURFACE};"
                                        f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        el = QHBoxLayout(self.echo_loading)
        el.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self.echo_dots = PulseDots(Colors.TEXT_SECONDARY)
        el.addWidget(self.echo_dots, 0, Qt.AlignVCenter)
        self.echo_loading_lbl = _label("正在整理这节课…", f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;")
        el.addWidget(self.echo_loading_lbl, 1)
        lay.addWidget(self.echo_loading)

        self.echo_path = QWidget()
        self.echo_path_lay = QVBoxLayout(self.echo_path)
        self.echo_path_lay.setContentsMargins(0, 0, 0, 0)
        self.echo_path_lay.setSpacing(0)
        lay.addWidget(self.echo_path)

        self.review_card = ReviewChain()
        lay.addWidget(self.review_card)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(_btn("开始新的一节课", "Link", self._restart))
        lay.addLayout(row)
        return page

    # ================= 页面切换 / 尺寸 =================
    def _show_page(self, idx):
        self._page = idx
        for i in range(self.stack.count()):     # 非当前页不参与尺寸计算
            pol = QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored
            self.stack.widget(i).setSizePolicy(pol, pol)
        self.stack.setCurrentIndex(idx)

        mini = idx == MINI
        self.header.setVisible(not mini)
        self.back_btn.setVisible(idx in (BREAK, LESSON))
        self.end_btn.setVisible(idx == LISTEN)
        self.fold_btn.setVisible(idx == LISTEN)
        m = Spacing.MD if mini else Spacing.LG
        self.layout().setContentsMargins(SHADOW + m, SHADOW + (Spacing.SM if mini else Spacing.MD),
                                         SHADOW + m, SHADOW + (Spacing.SM if mini else Spacing.LG))
        self._fit()

    def _fit(self):
        """按当前页内容算窗口大小；窗口在屏幕下半部时保持底边不动（往上长），不跑出屏幕。"""
        def do():
            idx = self.stack.currentIndex()
            pl = self.stack.currentWidget().layout()
            pl.activate()
            w = PAGE_WIDTH[idx]
            h = pl.totalHeightForWidth(w) if pl.hasHeightForWidth() else pl.totalSizeHint().height()
            m = self.layout().contentsMargins()
            if self.header.isVisible():
                h += self.header.sizeHint().height() + self.layout().spacing()
            W, H = w + m.left() + m.right(), h + m.top() + m.bottom()

            old = self.geometry()
            scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            x, y = old.x(), old.y()
            if self.isVisible():
                if old.center().y() > scr.center().y():
                    y = old.bottom() + 1 - H
                if old.center().x() > scr.center().x():
                    x = old.right() + 1 - W
                x = max(scr.left() - SHADOW, min(x, scr.right() + SHADOW - W))
                y = max(scr.top() - SHADOW, min(y, scr.bottom() + SHADOW - H))
            self.setFixedSize(W, H)
            if self.isVisible() and (x, y) != (old.x(), old.y()):
                self.move(x, y)
        do()
        QTimer.singleShot(0, do)   # 换行文本需要一轮事件循环后才能算准高度
        self.update()

    def _back_to_listen(self):
        self._show_page(LISTEN)

    # 兼容旧调用
    def _switch_panel(self):
        self._show_page(LISTEN)

    def _switch_pet(self):
        self._show_page(MINI)

    def _switch_expanded(self):
        self._show_page(BREAK)

    def _go_lesson(self):
        self._show_page(LESSON)
        self._cat("thinking")

    def _go_echo(self):
        self.echo_loading_lbl.setText("正在整理这节课…")
        self.echo_dots.start()
        self.echo_loading.show()
        self.echo_path.hide()
        self.review_card.hide()
        self.echo_sub.setText("")
        self.echo.end_lesson()
        self._show_page(ECHO)

    def _restart(self):
        self.current_concept = None
        self.last_bp = None
        self._fixed.clear()
        self._self_look.clear()
        self.topic_lbl.setText("等待老师开讲…")
        self.mini_topic.setText("等待老师开讲…")
        self.summary_lbl.setText(WAIT_HINT)
        self.summary_lbl.show()
        self.caption_lbl.hide()
        self.tc_lbl.setText("00:00")
        self.progress.setValue(0)
        self.echo.start()
        self._show_page(LISTEN)

    def _cat(self, emotion, hold_ms=0):
        self.cat.set_emotion(emotion, hold_ms)
        self.mini_cat.set_emotion(emotion, hold_ms)

    # ================= 按钮 =================
    def _on_ok(self):
        self.echo.feedback("ok")
        self._ack(self.btn_ok)
        self._cat("ok", 2200)

    def _on_warn(self):
        self.echo.feedback("warn")
        self._ack(self.btn_warn)
        self._cat("warn", 3000)

    def _on_lost(self):
        # 核心：Break Point Engine（异步，结果见 _on_breakpoint）
        self._cat("lost")
        self.echo.feedback("lost")
        self.break_cap.setText("Echo 正在找你掉队的地方")
        self.path.clear()
        self.miss_card.hide()
        self.bp_loading_lbl.setText("正在回看最近几分钟的课…")
        self.bp_dots.start()
        self.bp_loading.show()
        self.btn_fill.setEnabled(False)
        self._show_page(BREAK)

    def _on_fixed(self):
        if self.last_bp:
            self._fixed.add(self.last_bp.concept)
        if hasattr(self.echo, "mark_fixed"):
            self.echo.mark_fixed()
        self._cat("fixed", 2500)
        self._show_page(LISTEN)

    def _on_self_look(self):
        # 学生自己处理：不调 LLM，收起断点页；断点还没出来就只是取消
        if self.last_bp and self.btn_fill.isEnabled():
            self._self_look.add(self.last_bp.concept)
            if hasattr(self.echo, "mark_self"):
                self.echo.mark_self()
        self.bp_dots.stop()
        self._cat("ok", 1500)
        self._show_page(LISTEN)

    def _ack(self, btn):
        """点击后短暂显示「已记录」，给学生一个确认感。"""
        if getattr(btn, "_orig_text", None) is None:
            btn._orig_text = btn.text()
        btn.setText("已记录")
        btn.setEnabled(False)

        def restore():
            btn.setText(btn._orig_text)
            btn.setEnabled(True)
        QTimer.singleShot(1000, restore)

    # ================= 后端信号 =================
    def _on_transcript(self, tc, text):
        self.current_tc = tc
        self.tc_lbl.setText(tc)
        short = text if len(text) <= 56 else text[:54] + "…"
        self.caption_lbl.setText(short)
        self.caption_lbl.show()
        total = self.echo.total_seconds
        self.progress.setVisible(bool(total))
        if total:
            self.progress.setValue(int(1000 * min(1.0, (parse_tc(tc) or 0) / total)))
        if not self.echo.engine.current_concept():
            self.summary_lbl.setText("正在听，马上识别知识点…")
        if self._page == LISTEN:   # 字幕行数会变，每句重新算高度
            self._fit()

    def _on_concept(self, c):
        cur = self.echo.engine.current_concept()
        if cur is None:
            return
        self.current_concept = cur
        self.topic_lbl.setText(cur.topic)
        self.mini_topic.setText(cur.topic)
        self.summary_lbl.setText(cur.summary)
        self.summary_lbl.setVisible(bool(cur.summary))
        if self._page in (LISTEN, MINI):
            self._fit()

    def _on_breakpoint(self, bp, concepts):
        self.last_bp = bp
        self.last_bp_concepts = list(concepts or [])
        self.bp_dots.stop()
        self.bp_loading.hide()
        self.break_cap.setText("你可能从这里开始掉队")
        self.path.set_path(self.last_bp_concepts, bp.breakpoint_tc, bp.note)
        self.missing_lbl.setText(bp.missing)
        self.reason_lbl.setText(bp.reason)
        self.reason_lbl.setVisible(bool(bp.reason))
        self.miss_card.show()
        self.btn_fill.setEnabled(True)
        self._fill_lesson(bp)
        if self._page in (BREAK, LESSON):
            self._fit()

    def _fill_lesson(self, bp):
        """三段式：优先用后端的 known / step / now，缺了就从时间轴和 micro_lesson 拼出来。"""
        cs = self.last_bp_concepts
        idx = next((i for i, c in enumerate(cs) if c.timecode == bp.breakpoint_tc), None)
        prev = cs[idx - 1] if idx else None
        now = cs[-1] if cs else None

        known = getattr(bp, "known", "") or (
            f"{prev.topic}：{prev.summary}" if prev and prev.summary else (prev.topic if prev else "前面的定义和例子"))
        step = getattr(bp, "step", "") or bp.micro_lesson
        now_txt = getattr(bp, "now", "") or (
            f"老师现在讲的「{now.topic}」就是用这一步接着往下推的。" if now else "回到课堂，继续往下听。")

        self.lesson_title.setText(bp.missing or bp.concept)
        self.step_known.setText(rich(known))
        self.step_main.setText(rich(step))
        self.step_now.setText(rich(now_txt))

    def _on_echo(self, report):
        self.echo_dots.stop()
        self.echo_loading.hide()

        while self.echo_path_lay.count():
            w = self.echo_path_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

        def hit(name, names):
            return any(n in name or name in n for n in names)

        rows = []
        for sk in report.skills:
            st = echo_status(sk.status)
            note = ""
            if st == "review" and hit(sk.name, self._fixed):
                st = "fixed"
            if st == "fixed":
                note = "掉队过 · 已补上"
            elif hit(sk.name, self._self_look):
                note = "掉队过 · 自己看了"
            rows.append((sk.name, sk.mastery, echo_mark(st, sk.mastery), note))
        for name, m, mark, note in rows:
            self.echo_path_lay.addWidget(SkillRow(name, m, mark, note))
        self.echo_path.setVisible(bool(rows))

        cnt = {k: sum(1 for r in rows if r[2] == k) for k in ("ok", "unsure", "lost")}
        self.echo_sub.setText(f"✓ 跟上了 {cnt['ok']} · ? 有点懵 {cnt['unsure']} · ! 掉队了 {cnt['lost']}")
        self.review_card.setVisible(self.review_card.set_chain(report.review_chain, report.suggestion))
        cnt["review"] = cnt["unsure"] + cnt["lost"]
        self._cat("ok" if not cnt["review"] else "idle")
        self._fit()

    STATUS = {
        "listening":   ("正在听课", False),
        "analyzing":   ("正在分析", True),
        "summarizing": ("正在整理", True),
        "loading_asr": ("正在加载语音识别", True),
        "done":        ("已下课", False),
    }

    def _on_status(self, st):
        text, busy = self.STATUS.get(st, self.STATUS["listening"])
        self.status_lbl.setText(text)
        self.status_lbl.setToolTip("")
        self.status_dot.setVisible(not busy)
        self.status_dot.setStyleSheet(
            f"color: {Colors.OK_FG if st == 'listening' else Colors.TEXT_DISABLED}; font-size: 8px;"
            "background: transparent;")
        if busy:
            self.status_dots.start()
        else:
            self.status_dots.stop()
        if not self.echo.engine.current_concept():
            if st == "loading_asr":
                self.summary_lbl.setText("首次加载约 10 秒，之后会自动开始听")
            elif st == "listening":
                self.summary_lbl.setText(WAIT_HINT)
            if self._page == LISTEN:
                self._fit()

    def _on_error(self, msg):
        self.status_lbl.setText("网络或 AI 出错")
        self.status_lbl.setToolTip(msg)
        self.status_dot.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 8px; background: transparent;")
        if self._page == BREAK and not self.btn_fill.isEnabled():
            self.bp_dots.stop()
            self.bp_loading_lbl.setText("这次没分析出来，回到课堂再点一次「我掉队了」试试")
            self._fit()
        if self._page == ECHO and self.echo_loading.isVisible():
            self.echo_dots.stop()
            self.echo_loading_lbl.setText("回响生成失败，请检查网络后重试")

    def closeEvent(self, e):
        self.echo.shutdown()
        super().closeEvent(e)

    # ================= 拖动：整张卡片任意空白处都能拖 =================
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            h = self.windowHandle()
            if h is not None and hasattr(h, "startSystemMove") and h.startSystemMove():
                e.accept()
                return
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        r = Radius.LG + 2
        p.setPen(Qt.NoPen)
        for i in range(SHADOW, 0, -1):    # 柔和阴影
            a = int(Colors.SHADOW_ALPHA * (1 - i / SHADOW) ** 2)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(rect.adjusted(-i, -i + 3, i, i + 3), r + i, r + i)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        p.fillPath(path, QBrush(QColor(Colors.WINDOW_BG)))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(Colors.WINDOW_BORDER), 1))
        p.drawPath(path)
        p.end()
