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
import ctypes
from ctypes import wintypes

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QSizePolicy, QStackedWidget,
                             QProgressBar, QApplication, QShortcut, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, QRectF, QPoint
from PyQt5.QtGui import QFont, QCursor, QPainter, QPainterPath, QColor, QBrush, QPen, QKeySequence, QPixmap

# Win32 常量 — 无边框窗口边缘拖拽调整大小 + 最小化
WM_NCHITTEST = 0x0084
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
SC_MINIMIZE = 0xF020
SW_MINIMIZE = 6
user32 = ctypes.windll.user32

from echo.theme import Colors, Radius, font, Spacing
from echo.components.loading import PulseDots
from echo.components.study import (CatAvatar, BreakPath, LessonStep, SkillRow,
                                   ReviewChain, echo_status, echo_mark)
from echo.mock_data import Concept
from echo.backend import config
from echo.backend.engine import parse_tc
from echo.backend.qt_bridge import EchoBridge
from echo.components.pet import EMOTION_FILES, ASSETS_DIR

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


class _DraggableHeader(QWidget):
    """可拖动标题栏：点击 QLabel/空白区域可拖动窗口；按钮正常工作（事件不冒泡）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.window().frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPos() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        super().mouseReleaseEvent(e)

_FORMULA = re.compile(r"((?:[A-Za-z]\([^()（）]{1,24}\)|[A-Za-z]\b)"
                      r"(?:[\s·*/+\-=×÷^|∩∪A-Za-z0-9().]|&#x27;|乘|除以)*"
                      r"[A-Za-z0-9)])")


def _nobreak(esc: str) -> str:
    """公式内部不许折行：Qt 富文本不认 span 上的 white-space:nowrap，
    改为在每个字符之间插入 U+2060（word joiner），换行器会尊重它。HTML 实体整体保留。"""
    return "&#8288;".join(re.findall(r"&#?\w+;|.", esc))


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
                       f'white-space:nowrap; background-color:{Colors.CODE_BG};">&nbsp;{_nobreak(m.group(1))}&nbsp;</span>')
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
        self._auto_demo_msg = ""     # 音频采集失败、bridge 自动切示例课时的原因
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
        self.echo.thinking.connect(self._on_thinking)
        self.echo.error.connect(self._on_error)
        self.echo.mode.connect(self._on_mode)
        self.echo.start()

        # 现场兜底快捷键（Echo 窗口在前台时有效）
        QShortcut(QKeySequence("Ctrl+Shift+D"), self, self._use_demo, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, self._toggle_offline, context=Qt.ApplicationShortcut)

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
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 内容放得下时不要滚动条：滚动条会吃掉宽度 → 文字多折行 → 内容比算好的高度更高 → 底部按钮被挤出可视区
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.verticalScrollBar().setStyleSheet(
            f"QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {Colors.BORDER_STRONG}; border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page "
            "{ background: transparent; height: 0; }")
        self.body_scroll.setStyleSheet("QScrollArea {background: transparent; border: none;}")
        self.body_scroll.setWidget(self.stack)
        # QScrollArea 的 viewport 默认用系统调色板填一层浅灰底（#F0F0F0），
        # 只给 QScrollArea 设透明盖不住它 —— 深色主题下会变成浅底白字。必须让 viewport 和内容都不填底。
        self.body_scroll.viewport().setAutoFillBackground(False)
        # 注意必须带选择器：不带选择器的样式会层叠到所有子控件，把按钮的琥珀底也变透明
        self.body_scroll.viewport().setObjectName("BodyViewport")
        self.body_scroll.viewport().setStyleSheet("QWidget#BodyViewport { background: transparent; }")
        self.stack.setAutoFillBackground(False)
        self.stack.setStyleSheet("QStackedWidget {background: transparent;}")
        root.addWidget(self.body_scroll)

    def _build_header(self) -> QWidget:
        bar = _DraggableHeader()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        self.cat = CatAvatar(30)
        self.cat.setToolTip("点击打开听课界面")
        self.cat.clicked.connect(self._open_from_avatar)
        lay.addWidget(self.cat)

        name = _label("Echo", f"color: {Colors.TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        lay.addWidget(name)

        self.status_dot = _label("●", f"color: {Colors.OK_FG}; font-size: 8px;")
        self.status_dots = PulseDots(Colors.ACCENT)
        self.status_dots.hide()
        self.status_lbl = _label("正在听课", CAPTION)
        # 小字标记当前模式：示例课 / 离线
        self.mode_lbl = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"
                                   f"border: 1px solid {Colors.BORDER_STRONG}; border-radius: 8px;"
                                   "padding: 0 6px;")
        self.mode_lbl.hide()
        lay.addStretch()

        self.back_btn = _btn("← 回到课堂", "Link", self._back_to_listen)
        lay.addWidget(self.back_btn)
        self.end_btn = _btn("下课", "Link", self._go_echo, "结束这节课，生成回响")
        lay.addWidget(self.end_btn)
        self.fold_btn = _btn("–", "IconBtn", lambda: self._show_page(MINI), "折叠")
        self.fold_btn.setFixedSize(26, 26)
        lay.addWidget(self.fold_btn)

        # 最小化按钮
        self.min_btn = _btn("▾", "IconBtn", self._minimize, "最小化")
        self.min_btn.setFixedSize(26, 26)
        lay.addWidget(self.min_btn)
        close_btn = _btn("×", "IconBtn", self.close, "退出 Echo")
        close_btn.setFixedSize(26, 26)
        lay.addWidget(close_btn)

        # 右上角表情包（与桌宠情绪同步，加载 assets/emojis/ 下的 PNG）
        self.emoji_lbl = QLabel(bar)
        self.emoji_lbl.setFixedSize(32, 32)
        self.emoji_lbl.setScaledContents(True)
        self._emoji_pixmaps = {}
        import os
        for emo, fname in EMOTION_FILES.items():
            path = os.path.join(ASSETS_DIR, fname)
            if os.path.exists(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    self._emoji_pixmaps[emo] = pm
        lay.addWidget(self.emoji_lbl)
        self._set_emoji("idle")

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(bar)
        status_row = QHBoxLayout()
        for widget in (self.status_dot, self.status_dots, self.status_lbl, self.mode_lbl):
            status_row.addWidget(widget)
        status_row.addStretch()
        header_layout.addLayout(status_row)
        return header

    def _set_emoji(self, emotion: str):
        """切换标题栏表情包图片"""
        pm = self._emoji_pixmaps.get(emotion)
        if pm is not None:
            self.emoji_lbl.setPixmap(pm)
            self.emoji_lbl.show()
        else:
            self.emoji_lbl.clear()

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
        self.mini_cat.setToolTip("点击展开听课界面")
        self.mini_cat.clicked.connect(self._open_from_avatar)
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
        """按当前页内容算窗口大小；扩展时尽量保持窗口中心不动，不跑出屏幕。"""
        def do():
            idx = self.stack.currentIndex()
            pl = self.stack.currentWidget().layout()
            pl.activate()
            w = PAGE_WIDTH[idx]
            h = pl.totalHeightForWidth(w) if pl.hasHeightForWidth() else pl.totalSizeHint().height()
            m = self.layout().contentsMargins()
            scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            header_h = 0 if self.header.isHidden() else self.header.sizeHint().height() + self.layout().spacing()
            # 钉死成当前页的高度：QStackedWidget 的 heightForWidth 取的是所有页里最高的那页，
            # 放进 QScrollArea 后会把短页撑高，底部的「我掉队了」就被挤出可视区
            self.stack.setFixedHeight(h)
            limit = max(80, scr.height() - m.top() - m.bottom() - header_h - 24)
            fits = h + 4 <= limit
            # 只有内容比屏幕还高时才允许滚动（此时滚动条只有 6px，并多留出这点宽度）
            self.body_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff if fits else Qt.ScrollBarAsNeeded)
            if not fits:
                w += 8
            body_h = min(h + 4, limit)
            self.body_scroll.setFixedHeight(body_h)
            h = body_h + header_h
            W, H = w + m.left() + m.right(), h + m.top() + m.bottom()

            old = self.geometry()
            scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            x, y = old.x(), old.y()
            if self.isVisible():
                # 默认保持窗口中心不动（居中扩展）；窗口贴近视边缘时改贴该边
                cx, cy = old.center().x(), old.center().y()
                # 距离各边小于阈值 → 贴边
                near_right = old.right() > scr.right() - 40
                near_bottom = old.bottom() > scr.bottom() - 40
                near_left = old.left() < scr.left() + 40
                near_top = old.top() < scr.top() + 40
                if near_right and not near_left:
                    x = old.right() + 1 - W
                elif near_left and not near_right:
                    x = old.x()
                else:
                    x = cx - W // 2
                if near_bottom and not near_top:
                    y = old.bottom() + 1 - H
                elif near_top and not near_bottom:
                    y = old.y()
                else:
                    y = cy - H // 2
                # 不跑出屏幕
                x = max(scr.left() - SHADOW, min(x, scr.right() + SHADOW - W))
                y = max(scr.top() - SHADOW, min(y, scr.bottom() + SHADOW - H))
                # 用 setGeometry 原子地设置位置+大小，避免 resize 先向右下长再 move 的闪烁/边界问题
                self.setMinimumSize(W, H)
                self.setGeometry(x, y, W, H)
            else:
                self.setMinimumSize(W, H)
                self.resize(W, H)
        do()
        QTimer.singleShot(0, do)   # 换行文本需要一轮事件循环后才能算准高度
        self.update()

    def _back_to_listen(self):
        self._show_page(LISTEN)

    def _open_from_avatar(self):
        self._show_page(ECHO if self._page == ECHO else LISTEN)

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
        self._reset_ui()
        self.echo.start()

    def _use_demo(self):
        self._reset_ui()
        self.echo.use_demo()

    def _toggle_offline(self):
        self.echo.set_offline(not self.echo.offline)

    def _reset_ui(self):
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
        self._show_page(LISTEN)

    def _cat(self, emotion, hold_ms=0):
        self.cat.set_emotion(emotion, hold_ms)
        self.mini_cat.set_emotion(emotion, hold_ms)
        self._set_emoji(emotion)

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

    def _on_thinking(self, active: bool, text: str):
        """AI 实时思考状态：active=True 时显示思考文本+脉冲点，False 时恢复"""
        if active:
            self.status_lbl.setText(text)
            self.status_dot.hide()
            self.status_dots.start()
            self._set_emoji("thinking")
        else:
            self.status_dot.show()
            self.status_dots.stop()

    def _on_mode(self, kind, offline):
        tags = (["示例课"] if kind == "demo" else []) + (["离线"] if offline else [])
        text = " · ".join(tags)
        tip = "Ctrl+Shift+D 切示例课 · Ctrl+Shift+O 切离线/在线"
        msg, self._auto_demo_msg = self._auto_demo_msg, ""
        if msg and kind == "demo":      # 采集失败被自动切过来的：先亮几秒原因
            self.mode_lbl.setText("已切到示例课")
            QTimer.singleShot(5000, lambda: self.mode_lbl.setText(self.mode_lbl.property("base")))
            tip = f"{msg}\n{tip}"
        else:
            self.mode_lbl.setText(text)
        self.mode_lbl.setProperty("base", text)
        self.mode_lbl.setToolTip(tip)
        self.mode_lbl.setVisible(bool(tags))
        self._fit()

    def _on_error(self, msg):
        if (str(msg).startswith("音频采集失败") and config.AUTO_DEMO
                and self.echo.source_kind != "demo"):
            # bridge 紧接着会自动 use_demo()，这里只轻提示，不当大错误
            self._reset_ui()
            self._auto_demo_msg = msg
            return
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

    def _minimize(self):
        hwnd = int(self.winId())
        user32.ShowWindow(hwnd, SW_MINIMIZE)

    def nativeEvent(self, eventType, message):
        """Win32 WM_NCHITTEST → 无边框窗口边缘拖拽调整大小"""
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return super().nativeEvent(eventType, message)
        if msg.message == WM_NCHITTEST:
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            # WM_NCHITTEST 使用屏幕物理像素；Qt geometry 在高 DPI 下是逻辑像素。
            # 全程使用 Win32 窗口矩形，避免把卡片内部的按钮误判为缩放边缘。
            rect = wintypes.RECT()
            if not user32.GetWindowRect(wintypes.HWND(msg.hWnd), ctypes.byref(rect)):
                return super().nativeEvent(eventType, message)
            x -= rect.left
            y -= rect.top
            bw = max(1, round(6 * self.devicePixelRatioF()))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            # 鼠标在窗口外 → 默认处理
            if not (0 <= x < w and 0 <= y < h):
                return super().nativeEvent(eventType, message)
            # 只在边缘 bw 内返回缩放 hit code
            at_left = x < bw
            at_right = x >= w - bw
            at_top = y < bw
            at_bottom = y >= h - bw
            if at_left and at_top:
                return True, HTTOPLEFT
            if at_right and at_top:
                return True, HTTOPRIGHT
            if at_left and at_bottom:
                return True, HTBOTTOMLEFT
            if at_right and at_bottom:
                return True, HTBOTTOMRIGHT
            if at_left:
                return True, HTLEFT
            if at_right:
                return True, HTRIGHT
            if at_top:
                return True, HTTOP
            if at_bottom:
                return True, HTBOTTOM
        return super().nativeEvent(eventType, message)

    def closeEvent(self, e):
        self.echo.shutdown()
        super().closeEvent(e)

    # ================= 拖动：header 由 _DraggableHeader 接管；阴影边距走手动 fallback =================
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
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
