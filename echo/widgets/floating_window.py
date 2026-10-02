"""
Echo - 悬浮主窗口（学习工具风格）

页面：
  0 listen   默认听课卡片：当前知识点 + 实时字幕 + 始终可见的「我掉队了」
  1 mini     折叠条：猫头像 + 知识点 + 「掉队」
  2 break    断点页（产品主画面）：刚才会的 → 掉队的那一步 → 老师讲到这里 + 你缺的这一步
  3 lesson   补课三段式：你已经知道 → 中间漏了这一步 → 所以现在你能听懂
  4 echo     回响：每个知识点一条掌握度条 + ✓ ? ! ；你的掉队点 ↓ 前置 ↓ 建议复习
  5 review   错题复习：历次掉队点的列表，可回看 / AI 出题 / 标记掌握
  6 home     主页（启动页）：命名并开始今天的学习 + 错题复习 + AI 出题 + 历史课程
  7 practice AI 出题练习：照着错题出题，选择/填写答案 → 交卷 → 答案比对 + 订正解析
  8 detail   历史课程详情：这节课讲了什么 + 要点 + 每个知识点掌握度
"""
import html
import re
import time
import ctypes
from ctypes import wintypes

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QSizePolicy, QStackedWidget,
                             QProgressBar, QApplication, QShortcut, QScrollArea,
                             QLineEdit, QTextBrowser, QRadioButton, QButtonGroup,
                             QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QRectF, QPoint, pyqtSignal
from PyQt5.QtGui import QFont, QCursor, QPainter, QPainterPath, QColor, QBrush, QPen, QKeySequence, QPixmap

# Win32 常量 — 无边框窗口边缘拖拽调整大小 + 最小化
WM_NCHITTEST = 0x0084
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
SC_MINIMIZE = 0xF020
SW_MINIMIZE = 6
user32 = ctypes.windll.user32

from echo.widgets import dialogs
from echo.theme import Colors, Radius, font, Spacing
from echo.components.loading import PulseDots
from echo.components.wave_orb import WaveOrb
from echo.components.study import (CatAvatar, BreakPath, LessonStep, SkillRow,
                                   ReviewChain, echo_status, echo_mark)
from echo.mock_data import Concept
from echo.backend.engine import parse_tc
from echo.backend.qt_bridge import EchoBridge
from echo.backend import store
from echo.components.pet import EMOTION_FILES, ASSETS_DIR
from echo.i18n import tr
from echo.widgets.checkin import CheckinCard
from echo.widgets.mindmap import MindMapPage
from echo.backend import mindmap

SHADOW = 14
WAIT_HINT = tr("播放网课后，Echo 会自动开始听", "Play your course and Echo will start listening automatically")
LISTEN, MINI, BREAK, LESSON, ECHO, REVIEW, HOME, PRACTICE, DETAIL, MINDMAP, COURSES = range(11)
# 各页内容区宽度（不含阴影与内边距）
PAGE_WIDTH = {LISTEN: 340, MINI: 300, BREAK: 380, LESSON: 400, ECHO: 380,
              REVIEW: 380, HOME: 360, PRACTICE: 400, DETAIL: 380, MINDMAP: 480,
              COURSES: 420}


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
    # QPushButton.clicked 带一个 checked=False 参数。直接 connect 的话，带默认参数的写法
    # （lambda t=ls["time"]: ...）声明的那个参数会收到 False，默认值被顶掉——
    # 「看回顾」拿到的时间戳就变成 0，详情页永远是空的，知识地图和出题按钮跟着一起失效。
    # 统一把信号参数丢掉，槽一律无参调用。
    b.clicked.connect(lambda *_: slot())
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
    _ask_delta = pyqtSignal(str)
    _ask_done = pyqtSignal(str)
    _ask_err = pyqtSignal(str)
    _prac_done = pyqtSignal(object)
    _prac_err = pyqtSignal(str)

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
        self._ask = None             # 断点追问会话（LessonAsk）
        self._ask_buf = ""
        self._prac_item = None       # 当前在练的错题
        self._prac_qs, self._prac_cards = [], []
        self._prac_submitted = False
        # 练习页是从哪儿进来的。在里面点「✓ 这个我会了」或左上角返回时退回那里，
        # 而不是一律弹回主页 —— 从知识地图点进来，练完就该回到地图上那个知识点。
        self._prac_back = None
        self._prac_back_label = ""
        self._last_report = None     # 最近一次回响（回响页「知识地图」用）
        self._detail_lesson = {}     # 当前正在看的这节历史课
        self._review_due_only = False   # 复习页是在过「今天到期的」还是整本错题
        self._detail_ts = 0
        self._mindmap_lesson = {}    # 知识地图页正在看的那节课
        self._drag_pos = None
        self._page = LISTEN
        self._analysis_pending = False   # 掉队分析进行中，防重复触发
        self._break_failed = False       # 本次掉队分析失败，可重试

        self._build_ui()
        self._prac_done.connect(self._on_prac_done)
        self._prac_err.connect(self._on_prac_err)
        self._show_home()

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
        self.echo.level.connect(self._on_level)
        # 课堂抽查
        if hasattr(self.echo, "checkin"):
            self.echo.checkin.connect(self._on_checkin)
            self.echo.checkin_result.connect(self._on_checkin_result)
            self.checkin_card.answered.connect(self.echo.answer_checkin)
            self.checkin_card.skipped.connect(self.echo.skip_checkin)
        if hasattr(self.echo, "quiz_ready"):
            self.echo.quiz_ready.connect(self._on_quiz_ready)
        self.mindmap_page.practice_requested.connect(self._go_practice)
        # 地图页内容变高变矮时重新适配窗口（出题回来那几张卡不然会被底边截掉）
        self.mindmap_page.content_changed.connect(self._fit)
        # 注意：不在这里 echo.start()。启动停在主页，等用户点「开始今天的学习」才真正开课+抓音频。

        # 现场兜底快捷键（Echo 窗口在前台时有效）
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
        self.stack.addWidget(self._build_review())   # 5
        self.stack.addWidget(self._build_home())     # 6
        self.stack.addWidget(self._build_practice()) # 7
        self.stack.addWidget(self._build_detail())   # 8
        self.mindmap_page = MindMapPage()
        self.stack.addWidget(self.mindmap_page)      # 9
        self.stack.addWidget(self._build_courses())  # 10
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
        self.cat.setToolTip(tr("点击打开听课界面", "Open the lesson panel"))
        self.cat.clicked.connect(self._open_from_avatar)
        lay.addWidget(self.cat)

        name = _label("Echo", f"color: {Colors.TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        lay.addWidget(name)

        self.status_dot = _label("●", f"color: {Colors.OK_FG}; font-size: 8px;")
        self.status_dots = PulseDots(Colors.ACCENT)
        self.status_dots.hide()
        self._had_lesson = False        # 有没有上过课，决定状态栏写「还没开始上课」还是「已下课」
        self.status_lbl = _label(tr("还没开始上课", "Lesson not started"), CAPTION)
        # 小字标记当前模式：示例课 / 离线
        self.mode_lbl = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"
                                   f"border: 1px solid {Colors.BORDER_STRONG}; border-radius: 8px;"
                                   "padding: 0 6px;")
        self.mode_lbl.hide()
        lay.addStretch()

        self.back_btn = _btn(tr("← 回到课堂", "← Back to class"), "Link", self._back)
        lay.addWidget(self.back_btn)
        self.home_btn = _btn(tr("⌂ 主页", "⌂ Home"), "Link", self._show_home, tr("回到主页", "Back to home"))
        lay.addWidget(self.home_btn)
        self.end_btn = _btn(tr("下课", "End class"), "Link", self._go_echo, tr("结束这节课，生成回响", "End this lesson and generate the review"))
        lay.addWidget(self.end_btn)
        self.fold_btn = _btn("–", "IconBtn", lambda: self._show_page(MINI), tr("折叠", "Collapse"))
        self.fold_btn.setFixedSize(26, 26)
        lay.addWidget(self.fold_btn)

        # 最小化按钮
        self.min_btn = _btn("▾", "IconBtn", self._minimize, tr("最小化", "Minimize"))
        self.min_btn.setFixedSize(26, 26)
        lay.addWidget(self.min_btn)
        close_btn = _btn("×", "IconBtn", self.close, tr("退出 Echo", "Quit Echo"))
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

        # 顶部行：左侧声纹球 + 右侧时间码
        head = QHBoxLayout()
        self.wave_orb = WaveOrb(size=48)
        head.addWidget(self.wave_orb)
        head.addSpacing(Spacing.SM)
        head.addWidget(_label(tr("老师正在讲", "Teacher is speaking"), CAPTION))
        head.addStretch()
        self.tc_lbl = _label("00:00", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"
                                      "font-family: Consolas, 'Cascadia Mono', monospace;")
        head.addWidget(self.tc_lbl)
        lay.addLayout(head)

        # 课堂抽查浮层：默认隐藏，抽问触发时出现在听课页顶部
        self.checkin_card = CheckinCard(page)
        lay.addWidget(self.checkin_card)

        self.topic_lbl = _label(tr("等待老师开讲…", "Waiting for the teacher to start…"), f"color: {Colors.TEXT_PRIMARY}; font-size: 21px;"
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
        self.progress.hide()        # 实时听课没有总时长
        lay.addWidget(self.progress)

        # 实时字幕：左侧细线，安静地滚动
        self.caption_lbl = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"
                                      f"border-left: 2px solid {Colors.BORDER_STRONG};"
                                      "padding: 2px 0 2px 10px;", wrap=True)
        self.caption_lbl.hide()
        lay.addWidget(self.caption_lbl)

        lay.addSpacing(Spacing.SM)
        self.btn_lost = _btn(tr("我掉队了", "I fell behind"), "Accent", self._on_lost,
                             tr("Echo 回看最近几分钟，找到你从哪一步开始没听懂", "Echo reviews the last few minutes to find where you lost track"))
        self.btn_lost.setMinimumHeight(46)
        lay.addWidget(self.btn_lost)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.btn_ok = _btn(tr("✓  跟上了", "✓  Got it"), "Quiet", self._on_ok)
        self.btn_warn = _btn(tr("?  有点懵", "?  A bit lost"), "Quiet", self._on_warn)
        row.addWidget(self.btn_ok)
        row.addWidget(self.btn_warn)
        # 课上想自测一下：不用等 Echo 自己来找你，随时可以要一道
        self.btn_ask = _btn(tr("考考我", "Quiz me"), "Link", self._ask_checkin_now,
                            tr("让 Echo 拿老师刚讲过的东西出一道小题，看看你跟没跟上",
                               "Ask Echo for a quick question on what the teacher just covered"))
        row.addWidget(self.btn_ask)
        lay.addLayout(row)

        # 掉队分析出结果后，从这里一键回到刚才那节补课
        self.resume_btn = _btn(tr("继续查看刚才的补课  ↗", "Resume the catch-up lesson  ↗"),
                               "Link", self._go_lesson)
        self.resume_btn.hide()
        lay.addWidget(self.resume_btn)
        return page

    def _ask_checkin_now(self):
        """听课页「考考我」：学生主动要一道课上小题。"""
        engine = getattr(getattr(self, "echo", None), "engine", None)
        if not getattr(engine, "active", False):
            self.status_lbl.setText(tr("先开始上课，Echo 才知道该考你什么",
                                       "Start the lesson first — then Echo knows what to quiz you on"))
            return
        if not hasattr(self.echo, "ask_checkin_now") or not self.echo.ask_checkin_now():
            return          # 已经有一道在等着答，或者正在出 —— 不打断
        self.checkin_card.preparing()

    # ----- 1 折叠条 -----
    def _build_mini(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)
        self.mini_cat = CatAvatar(28)
        self.mini_cat.setToolTip(tr("点击展开听课界面", "Expand the lesson panel"))
        self.mini_cat.clicked.connect(self._open_from_avatar)
        lay.addWidget(self.mini_cat)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(_label(tr("老师正在讲", "Teacher is speaking"), f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"))
        self.mini_topic = _label(tr("等待老师开讲…", "Waiting for the teacher to start…"), f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;"
                                                "font-weight: 600;")
        self.mini_topic.setMinimumWidth(10)
        self.mini_topic.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.mini_topic)
        lay.addLayout(col, 1)
        b = _btn(tr("掉队了", "Fell behind"), "Accent", self._on_lost)
        b.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        lay.addWidget(b)
        ex = _btn("⌃", "IconBtn", lambda: self._show_page(LISTEN), tr("展开", "Expand"))
        ex.setFixedSize(26, 26)
        lay.addWidget(ex)
        # 自适应声纹球：直径跟随 mini 窗口高度，显示在最右端
        self.mini_wave_orb = WaveOrb(size=None)
        lay.addWidget(self.mini_wave_orb)
        return page

    # ----- 2 断点页（主画面）-----
    def _build_break(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        self.break_cap = _label(tr("你可能从这里开始掉队", "You probably lost track here"), TITLE)
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
        self.bp_loading_lbl = _label(tr("正在回看最近几分钟的课…", "Reviewing the last few minutes…"),
                                     f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;",
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
        ml.addWidget(_label(tr("你缺的这一步", "The step you're missing"),
                            f"color: {Colors.ACCENT}; font-size: 12px; font-weight: 700;"))
        self.missing_lbl = _label("", f"color: {Colors.TEXT_PRIMARY}; font-size: 19px; font-weight: 700;",
                                  wrap=True)
        ml.addWidget(self.missing_lbl)
        self.reason_lbl = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;", wrap=True)
        ml.addWidget(self.reason_lbl)
        lay.addWidget(self.miss_card)

        # 追问：学生针对自己的困惑继续问，带上课堂上下文问 DeepSeek
        self.ask_frame = QFrame()
        self.ask_frame.setObjectName("AskFrame")
        self.ask_frame.setStyleSheet(
            f"QFrame#AskFrame {{ background: {Colors.SURFACE}; border: 1px solid {Colors.BORDER};"
            f"border-radius: {Radius.MD}px; }}")
        al = QVBoxLayout(self.ask_frame)
        al.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        al.setSpacing(6)
        al.addWidget(_label(tr("还有哪里不懂？直接问我", "Anything else unclear? Just ask"),
                            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"))
        qrow = QHBoxLayout()
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText(tr("比如：为什么分母是 P(B)？",
                                             "e.g. why is the denominator P(B)?"))
        self.ask_input.setStyleSheet(f"background:{Colors.SURFACE}; color:{Colors.TEXT_PRIMARY};"
                                     f"border:1px solid {Colors.BORDER}; border-radius:6px; padding:7px 10px;")
        self.ask_input.returnPressed.connect(self._ask_breakpoint)
        qrow.addWidget(self.ask_input, 1)
        self.ask_btn = _btn(tr("问 AI", "Ask AI"), "Accent", self._ask_breakpoint)
        self.ask_btn.setFixedHeight(34)
        qrow.addWidget(self.ask_btn)
        al.addLayout(qrow)
        self.ask_view = QTextBrowser()
        self.ask_view.setFixedHeight(150)
        self.ask_view.setOpenExternalLinks(False)
        self.ask_view.setStyleSheet(f"QTextBrowser {{ background:{Colors.CODE_BG}; border:1px solid {Colors.BORDER};"
                                    f"border-radius:6px; padding:6px; color:{Colors.TEXT_PRIMARY}; }}")
        self.ask_view.hide()
        al.addWidget(self.ask_view)
        lay.addWidget(self.ask_frame)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.btn_fill = _btn(tr("30 秒补上这一步", "Catch up in 30 seconds"), "Accent", self._go_lesson)
        self.btn_fill.setMinimumHeight(44)
        row.addWidget(self.btn_fill, 3)
        self.btn_self = _btn(tr("我自己看看", "I'll figure it out"), "Quiet", self._on_self_look,
                             tr("不用 AI 讲，收起来回到课堂", "Skip the AI explanation and go back to class"))
        self.btn_self.setMinimumHeight(44)
        row.addWidget(self.btn_self, 2)
        lay.addLayout(row)

        # 分析失败时显示「重新分析」，不用退回听课页再点一次
        self.retry_btn = _btn(tr("重新分析", "Retry analysis"), "Quiet", self._on_lost)
        self.retry_btn.setMinimumHeight(40)
        self.retry_btn.hide()
        lay.addWidget(self.retry_btn)
        return page

    # ----- 3 补课三段式 -----
    def _build_lesson(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(tr("补上这一步 · 约 30 秒", "Catch up in one step · ~30s"), CAPTION))
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
        self.btn_gotit = _btn(tr("✓  补上了，回到课堂", "✓  Got it, back to class"), "Solid", self._on_fixed)
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
        self.echo_title = _label(tr("今天的课", "Today's lesson"), TITLE)
        self.echo_title.setWordWrap(True)
        head.addWidget(self.echo_title)
        self.echo_sub = _label("", CAPTION)
        head.addWidget(self.echo_sub)
        self.echo_stat = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        head.addWidget(self.echo_stat)
        lay.addLayout(head)

        self.echo_loading = QFrame()
        self.echo_loading.setObjectName("EchoLoading")
        self.echo_loading.setStyleSheet(f"QFrame#EchoLoading {{ background: {Colors.SURFACE};"
                                        f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        el = QHBoxLayout(self.echo_loading)
        el.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self.echo_dots = PulseDots(Colors.TEXT_SECONDARY)
        el.addWidget(self.echo_dots, 0, Qt.AlignVCenter)
        self.echo_loading_lbl = _label(tr("正在整理这节课…", "Summarizing this lesson…"), f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;")
        el.addWidget(self.echo_loading_lbl, 1)
        lay.addWidget(self.echo_loading)

        # 「这节课讲了什么」：学生最想知道的一段
        self.echo_sum_card, self.echo_sum_lbl, self.echo_hl_lay = self._summary_card()
        lay.addWidget(self.echo_sum_card)

        self.echo_path = QWidget()
        self.echo_path_lay = QVBoxLayout(self.echo_path)
        self.echo_path_lay.setContentsMargins(0, 0, 0, 0)
        self.echo_path_lay.setSpacing(0)
        lay.addWidget(self.echo_path)

        self.review_card = ReviewChain()
        self.review_card.review_requested.connect(self._review_root)
        lay.addWidget(self.review_card)

        row = QHBoxLayout()
        row.addWidget(_btn(tr("知识地图", "Knowledge map"), "Accent", self._show_mindmap_report))
        row.addStretch()
        row.addWidget(_btn(tr("错题复习", "Review mistakes"), "Quiet", self._show_review))
        row.addWidget(_btn(tr("回到主页", "Back to home"), "Link", self._show_home))
        lay.addLayout(row)
        return page

    def _summary_card(self):
        """「这节课讲了什么」卡片：一段话总结 + 要点列表。返回 (卡片, 总结 label, 要点 layout)。"""
        card = QFrame()
        card.setObjectName("SumCard")
        card.setStyleSheet(f"QFrame#SumCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(6)
        v.addWidget(_label(tr("这节课讲了什么", "What this lesson covered"),
                           f"color: {Colors.ACCENT}; font-size: 12px; font-weight: 600;"))
        text = _label("", f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; line-height: 165%;", wrap=True)
        v.addWidget(text)
        hl = QVBoxLayout()
        hl.setContentsMargins(0, 2, 0, 0)
        hl.setSpacing(3)
        v.addLayout(hl)
        card.hide()
        return card, text, hl

    def _fill_summary(self, card, text_lbl, hl_lay, summary, highlights):
        """把总结 + 要点填进 _summary_card 做出来的卡片；都没有就整张隐藏。"""
        while hl_lay.count():
            it = hl_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        summary = (summary or "").strip()
        text_lbl.setText(summary)
        text_lbl.setVisible(bool(summary))
        for h in (highlights or [])[:5]:
            h = str(h).strip()
            if h:
                hl_lay.addWidget(_label(f"· {h}",
                                        f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;"
                                        "line-height: 150%;", wrap=True))
        card.setVisible(bool(summary) or hl_lay.count() > 0)

    # ----- 5 错题复习（主页）-----
    def _build_review(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        self.review_title = _label(tr("错题复习", "Review mistakes"), TITLE)
        head.addWidget(self.review_title)
        self.review_sub = _label("", CAPTION)
        head.addWidget(self.review_sub)
        lay.addLayout(head)

        self.review_list = QWidget()
        self.review_list_lay = QVBoxLayout(self.review_list)
        self.review_list_lay.setContentsMargins(0, 0, 0, 0)
        self.review_list_lay.setSpacing(Spacing.SM)
        lay.addWidget(self.review_list)

        self.review_empty = _label(tr("还没有错题。听完一节课、点「我掉队了」之后，这里会收集你没跟上的地方。",
                                      "No mistakes yet. After a lesson, tap \"I fell behind\" and this will collect what you missed."),
                                   f"color: {Colors.TEXT_SECONDARY}; font-size: 13px;", wrap=True)
        lay.addWidget(self.review_empty)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(_btn(tr("回到主页", "Back to home"), "Link", self._show_home))
        lay.addLayout(row)
        return page

    def _show_review(self):
        """整本错题（所有没过的），不限今天到期。"""
        self._review_due_only = False
        self._render_review()
        self._show_page(REVIEW)

    def _review_root(self, topic):
        """回响页点「去复习」：针对最该复习的根源概念，让 AI 出题练一下。"""
        item = None
        for it in store.load():
            if (it.get("topic") or "").strip() == (topic or "").strip():
                item = it
                break
        if item is None:
            item = {"topic": (topic or "").strip()}
        self._practice_item(item)

    def _render_review(self):
        while self.review_list_lay.count():
            w = self.review_list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if getattr(self, "_review_due_only", False):
            items = store.due_items()
            self.review_title.setText(tr("今天的回响", "Today's recall"))
            self.review_sub.setText(
                tr(f"今天要确认 {len(items)} 个知识点", f"{len(items)} points to confirm today")
                if items else tr("今天的都过完了，好样的 🎉", "Done for today — nice work 🎉"))
        else:
            items = [it for it in store.load() if not it.get("reviewed")]
            self.review_title.setText(tr("错题复习", "Review mistakes"))
            self.review_sub.setText(
                tr(f"还有 {len(items)} 个知识点要回看", f"{len(items)} knowledge points left to review")
                if items else tr("都复习过了，好样的 🎉", "All reviewed — nice work 🎉"))
        self.review_empty.setVisible(not items)
        for it in items:
            self.review_list_lay.addWidget(self._review_card(it))

    def _review_card(self, item):
        card = QFrame()
        card.setObjectName("ReviewCard")
        card.setStyleSheet(f"QFrame#ReviewCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(6)
        topic = _label(tr(f"✦ {item.get('topic', '知识点')}", f"✦ {item.get('topic', 'Knowledge point')}"),
                       f"color: {Colors.TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")
        topic.setWordWrap(True)
        v.addWidget(topic)
        miss = item.get("missing") or item.get("reason") or tr("这里没跟上", "Lost track here")
        ml = _label(tr(f"没跟上：{miss}", f"Missed: {miss}"),
                    f"color: {Colors.ACCENT}; font-size: 13px;")
        ml.setWordWrap(True)
        v.addWidget(ml)
        lesson = (item.get("micro_lesson") or "").strip()
        if lesson:
            lb = _label(lesson, f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
            lb.setWordWrap(True)
            v.addWidget(lb)

        topic_name = item.get("topic", "")
        v.addWidget(_label(tr("想起来了吗？", "How well do you remember it?"),
                           f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"))
        # 三档自评决定下次什么时候再问。没有「永久掌握」这个终态：
        # 答得越稳，Echo 把下次确认推得越远；答崩了明天就回来。
        # 三个按钮一律用同一种样式 —— 把「记得很清楚」做得更醒目会诱导学生选它，
        # 而这个功能的全部价值就建立在自评是诚实的之上。
        grades = QHBoxLayout()
        grades.setSpacing(Spacing.SM)
        for result, zh, en in ((store.AGAIN, "还是没懂", "Still lost"),
                               (store.FUZZY, "有点模糊", "A bit fuzzy"),
                               (store.CLEAR, "记得很清楚", "I remember it")):
            b = _btn(tr(zh, en), "Quiet",
                     lambda t=topic_name, r=result: self._grade_review(t, r),
                     self._next_due_tip(item, result))
            grades.addWidget(b)
        v.addLayout(grades)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(_btn(tr("想不起来？出道题试试", "Not sure? Try a question"), "Link",
                           lambda it=item: self._practice_item(it)))
        v.addLayout(row)
        return card

    @staticmethod
    def _next_due_tip(item, result) -> str:
        """按钮上的悬停提示：选这一档的话，下次什么时候再问。"""
        now = time.time()
        _, due = store.next_due(item.get("level", 0), result, now)
        days = max(1, round((due - now) / store.DAY))
        return tr(f"选这个 → {days} 天后再确认一次", f"Pick this → next check in {days} days")

    def _grade_review(self, topic, result):
        """学生给一个知识点打了分：记下来，顺手算出下次复习时间。"""
        try:
            store.grade(topic, result)
        except ValueError:
            return
        self._render_review()
        self._fit()

    def _mark_reviewed(self, topic):
        store.mark_reviewed(topic)
        self._render_review()
        self._fit()

    def _save_review(self):
        try:
            store.add(store.from_breakpoints(self.echo.engine))
        except Exception:
            pass

    # ----- 6 主页 -----
    def _build_home(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        self.home_hello = _label(tr("今天也来听课", "Ready for another lesson?"), TITLE)
        head.addWidget(self.home_hello)
        self.home_sub = _label("", CAPTION)
        self.home_sub.setWordWrap(True)
        head.addWidget(self.home_sub)
        lay.addLayout(head)

        # 「今天该回响」：进门第一眼就该看到的东西。没有到期的知识点时整张卡隐藏，
        # 别拿「今天没有待办」占着最显眼的位置。
        self.home_recall_card = self._recall_card()
        lay.addWidget(self.home_recall_card)

        # 开课前先给这节课起个名，下课后在历史里一眼能认出来
        lay.addWidget(_label(tr("这节课叫什么？", "What's this lesson called?"), CAPTION))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(
            tr("例如：初二数学 · 正比例函数（留空默认用开课时间命名）",
               "e.g. Grade 8 Math · Direct proportion (leave blank to name by start time)"))
        self.title_edit.setStyleSheet(
            f"QLineEdit {{ background: {Colors.SURFACE}; color: {Colors.TEXT_PRIMARY};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; padding: 7px 10px;"
            "font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}")
        self.title_edit.returnPressed.connect(self._start_today)
        lay.addWidget(self.title_edit)

        self.btn_today = _btn(tr("开始今天的学习", "Start today's learning"), "Accent", self._start_today,
                              tr("开一节新课，Echo 开始听你的网课", "Start a new lesson and Echo will begin listening"))
        self.btn_today.setMinimumHeight(46)
        lay.addWidget(self.btn_today)

        self.home_review_card = self._home_card(
            tr("错题复习", "Review mistakes"), tr("把掉队过的知识点再过一遍", "Go over the points you missed"),
            tr("去复习", "Review"), self._show_review)
        lay.addWidget(self.home_review_card)
        self.home_practice_card = self._home_card(
            tr("AI 出题练习", "AI practice quiz"), tr("让 AI 按你的错题出题，真的练一下", "Let AI turn your mistakes into practice questions"),
            tr("开始练", "Practice"), self._start_practice)
        lay.addWidget(self.home_practice_card)
        self.home_courses_card = self._home_card(
            tr("课程管理", "Course manager"), tr("回看、搜索、重命名、批量管理历史课程", "Review, search, rename, and manage past lessons"),
            tr("管理", "Manage"), self._show_courses)
        lay.addWidget(self.home_courses_card)
        return page

    def _recall_card(self):
        """主页顶部的「今天该回响」卡：几个知识点要确认 + 当时在哪掉的队 + 预计几分钟。

        用强调色描边，和下面三张普通功能卡拉开层次 —— 这是进来最该先做的事。
        """
        card = QFrame()
        card.setObjectName("RecallCard")
        card.setStyleSheet(
            f"QFrame#RecallCard {{ background: {Colors.ACCENT_SOFT};"
            f"border: 1px solid {Colors.ACCENT_BORDER}; border-radius: {Radius.LG}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(4)

        self.recall_title = _label("", f"color: {Colors.TEXT_PRIMARY}; font-size: 16px;"
                                      "font-weight: 700;", wrap=True)
        v.addWidget(self.recall_title)
        self.recall_hint = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;", wrap=True)
        v.addWidget(self.recall_hint)
        self.recall_time = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        v.addWidget(self.recall_time)

        row = QHBoxLayout()
        row.addStretch()
        self.btn_recall = _btn(tr("看看我还记不记得", "See what I still remember"), "Accent",
                               self._show_recall,
                               tr("只过今天到期的知识点，答完 Echo 会安排下次复习时间",
                                  "Go through today's due points — Echo schedules the next check for you"))
        self.btn_recall.setMinimumHeight(40)
        row.addWidget(self.btn_recall)
        v.addLayout(row)
        return card

    def _home_card(self, title, desc, action, slot):
        """主页上的一张功能卡：标题 + 说明 + 右侧按钮；副标题文字后面会被动态更新。"""
        card = QFrame()
        # 选择器必须带 objectName：QLabel 继承自 QFrame，不限定就会被套上一层框
        card.setObjectName("HomeCard")
        card.setStyleSheet(f"QFrame#HomeCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        h = QHBoxLayout(card)
        h.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.MD, Spacing.MD)
        h.setSpacing(Spacing.SM)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = _label(title, f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        col.addWidget(t)
        d = _label(desc, f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;", wrap=True)
        col.addWidget(d)
        h.addLayout(col, 1)
        b = _btn(action, "Quiet", slot)
        h.addWidget(b, 0, Qt.AlignVCenter)
        card.sub_lbl, card.btn = d, b
        return card

    # ----- 课程管理（历史课程列表 + 搜索 + 批量操作）-----
    def _build_courses(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(tr("课程管理", "Course manager"), TITLE))
        self.courses_sub = _label("", CAPTION)
        head.addWidget(self.courses_sub)
        lay.addLayout(head)

        self.courses_search = QLineEdit()
        self.courses_search.setPlaceholderText(
            tr("搜索课程名或日期，例如「数学」或「10-02」…",
               "Search by lesson name or date, e.g. \"Math\" or \"10-02\"…"))
        self.courses_search.setStyleSheet(
            f"QLineEdit {{ background: {Colors.SURFACE}; color: {Colors.TEXT_PRIMARY};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; padding: 7px 10px;"
            "font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}")
        self.courses_search.textChanged.connect(self._render_courses)
        lay.addWidget(self.courses_search)

        bar = QHBoxLayout()
        bar.setSpacing(Spacing.SM)
        self.courses_sel_btn = _btn(tr("全选", "Select all"), "Quiet", self._courses_toggle_all)
        bar.addWidget(self.courses_sel_btn)
        self.courses_del_btn = _btn(tr("批量删除", "Delete selected"), "Quiet",
                                    self._courses_delete_selected,
                                    tr("删除勾选的课程（不可恢复）",
                                       "Delete the checked lessons (cannot be undone)"))
        bar.addWidget(self.courses_del_btn)
        self.courses_ren_btn = _btn(tr("批量重命名", "Rename selected"), "Quiet",
                                    self._courses_rename_selected,
                                    tr("给勾选的课程统一改名", "Rename all checked lessons at once"))
        bar.addWidget(self.courses_ren_btn)
        bar.addStretch()
        lay.addLayout(bar)

        self.courses_list = QWidget()
        self.courses_list_lay = QVBoxLayout(self.courses_list)
        self.courses_list_lay.setContentsMargins(0, 0, 0, 0)
        self.courses_list_lay.setSpacing(Spacing.SM)
        lay.addWidget(self.courses_list, 1)

        self.courses_empty = _label(tr("还没有上过课。", "No lessons yet."),
                                    f"color: {Colors.TEXT_SECONDARY};"
                                    "font-size: 12px;", wrap=True)
        lay.addWidget(self.courses_empty)
        return page

    def _show_courses(self):
        self._render_courses()
        self._show_page(COURSES)

    def _render_courses(self, _query=None):
        """列出全部课程，按搜索词过滤；勾选状态每次重建。"""
        try:
            all_lessons = store.list_lessons(limit=None)
        except Exception:
            all_lessons = []
        query = (self.courses_search.text() or "").strip()
        q = query.lower()
        # 按列表上显示的名字搜：标题是占位名的那节课显示的是知识点名，
        # 搜列表上看得见的字才找得到它
        shown = [ls for ls in all_lessons
                 if not q or q in self._lesson_name(ls).lower()
                 or q in (ls.get("title") or "").lower() or q in (ls.get("date") or "").lower()]

        self.courses_sub.setText(
            tr(f"共 {len(all_lessons)} 节课", f"{len(all_lessons)} lessons")
            + (tr(f" · 匹配 {len(shown)} 节", f" · {len(shown)} matched") if q else ""))

        while self.courses_list_lay.count():
            w = self.courses_list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._course_cards = []
        for ls in shown:
            card = self._courses_row(ls)
            self._course_cards.append(card)
            self.courses_list_lay.addWidget(card)
        self.courses_empty.setVisible(not shown)
        if getattr(self, "_page", None) == COURSES:
            self._fit()

    @staticmethod
    def _lesson_name(ls: dict) -> str:
        """课程在列表里显示的名字。

        AI 偶尔会把标题也写成「（未知）」这种占位名（老数据里就有一节），
        与其把「（未知）」当课名摆出来，不如退回用这节课的知识点或日期。
        """
        title = (ls.get("title") or "").strip()
        if title and not mindmap.is_placeholder_topic(title):
            return title
        first = next((s.get("name") for s in (ls.get("skills_detail") or []) if s.get("name")), "")
        if first:
            return first
        return (ls.get("date") or "").strip() or tr("一节课", "A lesson")

    def _courses_row(self, ls):
        """一节历史课一行：勾选框 + 名称/日期 + 重命名 + 看回顾。"""
        card = QFrame()
        card.setObjectName("CoursesRow")
        card.setStyleSheet(f"QFrame#CoursesRow {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        h = QHBoxLayout(card)
        h.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        h.setSpacing(Spacing.SM)

        chk = QCheckBox()
        chk.setCursor(QCursor(Qt.PointingHandCursor))
        chk.setStyleSheet(
            "QCheckBox { background: transparent; }"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;"
            f"border: 2px solid {Colors.BORDER_STRONG}; background: {Colors.SURFACE}; }}"
            f"QCheckBox::indicator:checked {{ border: 2px solid {Colors.ACCENT};"
            f"background: {Colors.ACCENT}; }}")
        h.addWidget(chk, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = _label(self._lesson_name(ls),
                       f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        title.setWordWrap(True)
        col.addWidget(title)
        mins = int((ls.get("duration") or 0) // 60)
        bits = [ls.get("date", ""),
                tr(f"{ls.get('total', 0)} 个知识点", f"{ls.get('total', 0)} knowledge points")]
        if mins:
            bits.append(tr(f"{mins} 分钟", f"{mins} min"))
        if ls.get("review"):
            bits.append(tr(f"{ls['review']} 个待复习", f"{ls['review']} to review"))
        col.addWidget(_label(" · ".join(b for b in bits if b),
                             f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"))
        h.addLayout(col, 1)
        h.addWidget(_btn(tr("重命名", "Rename"), "Link",
                         lambda t=ls.get("time", 0): self._course_rename(t)))
        h.addWidget(_btn(tr("看回顾", "Review"), "Quiet",
                         lambda t=ls.get("time", 0): self._show_detail(t)),
                    0, Qt.AlignVCenter)

        card._chk = chk
        card._ts = ls.get("time", 0)
        return card

    def _courses_selected(self):
        """当前课程列表里勾选的时间戳。"""
        return [c._ts for c in getattr(self, "_course_cards", []) if c._chk.isChecked()]

    def _courses_toggle_all(self):
        cards = getattr(self, "_course_cards", [])
        if not cards:
            return
        target = not all(c._chk.isChecked() for c in cards)
        for c in cards:
            c._chk.setChecked(target)

    def _courses_delete_selected(self):
        ts_list = self._courses_selected()
        if not ts_list:
            dialogs.info(self, tr("批量删除", "Delete selected"),
                         tr("先勾选要删除的课程。", "Check the lessons you want to delete first."))
            return
        n = len(ts_list)
        if not dialogs.confirm(self, tr("批量删除", "Delete selected"),
                               tr(f"确定删除选中的 {n} 节课吗？删除后不可恢复。",
                                  f"Delete the {n} selected lessons? This cannot be undone."),
                               ok_text=tr("删除", "Delete")):
            return
        store.delete_lessons(ts_list)
        self._render_courses()

    def _courses_rename_selected(self):
        ts_list = self._courses_selected()
        if not ts_list:
            dialogs.info(self, tr("批量重命名", "Rename selected"),
                         tr("先勾选要重命名的课程。", "Check the lessons you want to rename first."))
            return
        default = store.get_lesson(ts_list[0]).get("title", "") if len(ts_list) == 1 else ""
        name, ok = dialogs.ask_text(self, tr("重命名", "Rename"),
                                    tr("新的课程名：", "New lesson name:"), default)
        name = (name or "").strip()
        if not ok or not name:
            return
        if len(ts_list) == 1:
            store.rename_lesson(ts_list[0], name)
        else:
            for i, ts in enumerate(ts_list, 1):
                store.rename_lesson(ts, f"{name}（{i}）")
        self._render_courses()

    def _course_rename(self, ts):
        """单节课程重命名。"""
        cur = store.get_lesson(ts).get("title", "")
        name, ok = dialogs.ask_text(self, tr("重命名", "Rename"),
                                    tr("新的课程名：", "New lesson name:"), cur)
        name = (name or "").strip()
        if ok and name:
            store.rename_lesson(ts, name)
            self._render_courses()

    def _show_home(self):
        self._render_home()
        self._show_page(HOME)

    def _render_home(self):
        try:
            st = store.stats()
        except Exception:
            st = {"lessons": 0, "pending": 0, "mastered": 0}
        pending, mastered, n_lesson = st.get("pending", 0), st.get("mastered", 0), st.get("lessons", 0)

        bits = []
        if n_lesson:
            bits.append(tr(f"已经听过 {n_lesson} 节课", f"{n_lesson} lessons so far"))
        if mastered:
            bits.append(tr(f"补上了 {mastered} 个知识点", f"{mastered} knowledge points caught up"))
        bits.append(tr(f"还有 {pending} 个错题要复习", f"{pending} mistakes left to review")
                    if pending else tr("错题都复习完了 🎉", "All mistakes reviewed 🎉"))
        self.home_sub.setText(" · ".join(bits))
        self._render_recall_card()

        self.home_review_card.sub_lbl.setText(
            tr(f"{pending} 个掉队过的知识点等你回看", f"{pending} knowledge points waiting for review")
            if pending else tr("暂时没有错题，听课时点「我掉队了」就会收进来",
                               "No mistakes yet — tap \"I fell behind\" during a lesson and they'll show up here"))
        self.home_practice_card.sub_lbl.setText(
            tr(f"让 AI 照着这 {pending} 个错题出题，真的练一下",
               f"Have AI write questions from these {pending} mistakes and actually practise")
            if pending else tr("有错题之后，AI 就能照着出题",
                               "Once you have mistakes, AI can write questions from them"))
        self.home_courses_card.sub_lbl.setText(
            tr(f"{n_lesson} 节历史课，可搜索、重命名、批量删除",
               f"{n_lesson} past lessons — search, rename, bulk delete")
            if n_lesson else tr("还没有历史课，开一节就有了",
                                "No past lessons yet — start one and it'll appear here"))

    def _render_recall_card(self):
        """填「今天该回响」卡。没有到期的就整张收起来。"""
        try:
            s = store.due_summary()
        except Exception:
            s = {"count": 0, "topics": [], "minutes": 0, "hint": ""}
        n = s.get("count", 0)
        self.home_recall_card.setVisible(bool(n))
        if not n:
            return
        self.recall_title.setText(
            tr(f"今天有 {n} 个知识点需要确认", f"{n} knowledge points to confirm today"))
        hint = (s.get("hint") or "").strip()
        if not hint:
            topics = s.get("topics") or []
            shown = "、".join(topics[:3]) + ("…" if len(topics) > 3 else "")
            hint = tr(f"包括：{shown}", f"Including: {shown}")
        self.recall_hint.setText(hint)
        self.recall_hint.setVisible(bool(hint))
        self.recall_time.setText(
            tr(f"预计 {s.get('minutes', n)} 分钟", f"About {s.get('minutes', n)} min"))

    def _show_recall(self):
        """「看看我还记不记得」：只过今天到期的那几个，不是整本错题。"""
        self._review_due_only = True
        self._render_review()
        self._show_page(REVIEW)

    def _start_today(self):
        """给这节课命名并开课。"""
        name = self.title_edit.text().strip()
        if hasattr(self.echo, "set_title"):
            self.echo.set_title(name)
        self.title_edit.clear()
        self._restart()
        if name:
            self.topic_lbl.setText(name)

    # ----- 7 AI 出题练习 -----
    def _build_practice(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(tr("AI 出题练习", "AI practice quiz"), TITLE))
        self.prac_sub = _label("", CAPTION)
        head.addWidget(self.prac_sub)
        lay.addLayout(head)

        self.prac_loading = QFrame()
        self.prac_loading.setObjectName("PracLoading")
        self.prac_loading.setStyleSheet(f"QFrame#PracLoading {{ background: {Colors.SURFACE};"
                                        f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        pl = QHBoxLayout(self.prac_loading)
        pl.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self.prac_dots = PulseDots(Colors.TEXT_SECONDARY)
        pl.addWidget(self.prac_dots, 0, Qt.AlignVCenter)
        self.prac_loading_lbl = _label(tr("AI 正在照着你的错题出题…", "AI is writing questions from your mistakes…"),
                                       f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;")
        pl.addWidget(self.prac_loading_lbl, 1)
        lay.addWidget(self.prac_loading)

        self.prac_body = QWidget()
        self.prac_body_lay = QVBoxLayout(self.prac_body)
        self.prac_body_lay.setContentsMargins(0, 0, 0, 0)
        self.prac_body_lay.setSpacing(Spacing.SM)
        lay.addWidget(self.prac_body, 1)

        self.btn_prac_submit = _btn(tr("交卷", "Submit"), "Accent", self._prac_submit,
                                    tr("全部作答后交卷，看答案比对和订正", "Submit when done to compare answers and review corrections"))
        self.btn_prac_submit.setMinimumHeight(42)
        lay.addWidget(self.btn_prac_submit)

        self.prac_score = _label("", f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        self.prac_score.hide()
        lay.addWidget(self.prac_score)

        row2 = QHBoxLayout()
        row2.addWidget(_btn(tr("✓ 这个我会了", "✓  I got this"), "Link", self._prac_mastered))
        row2.addStretch()
        row2.addWidget(_btn(tr("换一题练", "Practice another"), "Link", self._start_practice))
        lay.addLayout(row2)
        return page

    def _start_practice(self):
        """挑第一个待复习的错题，让 AI 出题。"""
        pending = [it for it in store.load() if not it.get("reviewed")]
        if not pending:
            self._show_practice_empty()
            return
        self._practice_item(pending[0])

    def _show_practice_empty(self):
        """没有错题时也要进练习页说明白。

        原来这里直接 _show_home() 弹回主页，点下去什么也没发生 —— 用户会以为按钮坏了。
        """
        self._prac_item = {}
        self._prac_back, self._prac_back_label = None, ""
        self._prac_qs, self._prac_cards = [], []
        self._prac_submitted = False
        self.prac_sub.setText(tr("还没有可以出题的错题", "No mistakes to build questions from yet"))
        self._show_page(PRACTICE)
        self._on_prac_err(tr("听课时点「我掉队了」，Echo 找到的知识断点会收进错题本，"
                             "这里就能照着它出题了。",
                             "During a lesson, tap \"I fell behind\". Echo files the gap it finds "
                             "into your mistakes, and this page writes questions from it."))

    def _practice_item(self, item, back=None, back_label=""):
        """针对某一个错题让 AI 出题（后台线程，结果经信号回主线程）。

        back 是练完之后该回哪儿；不传就回主页。
        """
        self._prac_item = item
        self._prac_back, self._prac_back_label = back, back_label
        self._prac_qs, self._prac_cards = [], []
        self._prac_submitted = False
        self.prac_sub.setText(tr(f"针对：{item.get('topic', '')}", f"On: {item.get('topic', '')}"))
        self.prac_loading_lbl.setText(tr("AI 正在照着你的错题出题…", "AI is writing questions from your mistakes…"))
        self.prac_dots.start()
        self.prac_loading.show()
        self.prac_body.hide()
        self.prac_score.hide()
        self.btn_prac_submit.setEnabled(False)
        self._show_page(PRACTICE)
        from echo.backend import practice
        practice.generate(item, 3,
                          on_done=lambda qs: self._prac_done.emit(qs),
                          on_error=lambda m: self._prac_err.emit(m))

    def _on_prac_done(self, qs):
        self.prac_dots.stop()
        self.prac_loading.hide()
        self._prac_qs = list(qs or [])
        if not self._prac_qs:
            self._on_prac_err(tr("这次没出出题来，待会儿再试试",
                                 "Couldn't write questions this time — try again in a moment"))
            return
        self.prac_body.show()
        self._render_paper()

    def _on_prac_err(self, msg):
        self.prac_dots.stop()
        self.prac_loading_lbl.setText(msg)
        self.prac_loading.show()
        self.prac_body.hide()
        self.btn_prac_submit.setEnabled(False)
        self._fit()

    def _render_paper(self):
        """把整套题铺成一张卷子：每道题一张卡，选项是选择按钮。"""
        while self.prac_body_lay.count():
            w = self.prac_body_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._prac_cards = []
        self._prac_submitted = False
        for i, q in enumerate(self._prac_qs):
            card = self._prac_card(i, q)
            self._prac_cards.append(card)
            self.prac_body_lay.addWidget(card)
        topic = (self._prac_item or {}).get("topic", "")
        self.prac_sub.setText(tr(f"针对：{topic}　共 {len(self._prac_qs)} 题",
                                 f"On: {topic} · {len(self._prac_qs)} questions"))
        self.prac_score.hide()
        self.btn_prac_submit.setEnabled(True)
        self._fit()

    def _prac_card(self, idx, q):
        """一道题一张卡：题干 + 选择按钮（选择题）/ 输入框（简答题）+ 隐藏的答案比对区。"""
        radio_qss = (
            f"QRadioButton {{ color: {Colors.TEXT_PRIMARY}; font-size: 13px; spacing: 8px; background: transparent; }}"
            f"QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px;"
            f"border: 2px solid {Colors.BORDER_STRONG}; background: {Colors.SURFACE}; }}"
            f"QRadioButton::indicator:checked {{ border: 2px solid {Colors.ACCENT}; background: {Colors.ACCENT}; }}"
        )
        card = QFrame()
        card.setObjectName("PracCard")
        card.setStyleSheet(f"QFrame#PracCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(8)

        v.addWidget(_label(tr(f"第 {idx + 1} 题", f"Question {idx + 1}"),
                           f"color: {Colors.ACCENT}; font-size: 11px; font-weight: 700;"))
        v.addWidget(_label(str(q.get("question", "")),
                           f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
                           "line-height: 150%;", wrap=True))

        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        group = QButtonGroup(card)
        group.setExclusive(True)
        radios = []
        edit = None
        if opts:
            for o in opts:
                r = QRadioButton(o)
                r.setStyleSheet(radio_qss)
                r.setCursor(QCursor(Qt.PointingHandCursor))
                group.addButton(r)
                v.addWidget(r)
                radios.append(r)
        else:
            # 简答题：没有选项，让学生把答案写出来，交卷后与参考答案比对
            edit = QLineEdit()
            edit.setPlaceholderText(tr("把你的答案写在这里…", "Type your answer here…"))
            edit.setStyleSheet(
                f"QLineEdit {{ background: {Colors.SURFACE}; color: {Colors.TEXT_PRIMARY};"
                f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; padding: 7px 10px;"
                "font-size: 13px; }"
                f"QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}")
            v.addWidget(edit)

        result = QFrame()
        result.setStyleSheet("background: transparent; border: none;")
        rv = QVBoxLayout(result)
        rv.setContentsMargins(0, 4, 0, 0)
        rv.setSpacing(3)
        verdict = _label("", "font-size: 13px; font-weight: 700;")
        rv.addWidget(verdict)
        compare = _label("", "font-size: 12px; line-height: 150%;", wrap=True)
        rv.addWidget(compare)
        explain = _label("", "font-size: 12px; line-height: 160%;", wrap=True)
        rv.addWidget(explain)
        result.hide()
        v.addWidget(result)

        card._group = group
        card._radios = radios
        card._edit = edit
        card._result = result
        card._verdict = verdict
        card._compare = compare
        card._explain = explain
        return card

    @staticmethod
    def _opt_letter(text):
        """从选项文字里取 A/B/C/D 字母（「A. …」「B、…」「B」都行），取不到返回空。"""
        text = (text or "").strip()
        m = re.match(r"([A-Za-z])\s*[.、:：)\]]", text)
        if m:
            return m.group(1).upper()
        if re.fullmatch(r"[A-Za-z]", text):
            return text.upper()
        return ""

    def _prac_submit(self):
        """交卷：比对每道题的答案，原地显示对错 + 订正解析。"""
        if self._prac_submitted or not self._prac_qs:
            return
        self._prac_submitted = True
        correct = 0
        mc_total = 0
        has_free = False
        for card, q in zip(self._prac_cards, self._prac_qs):
            verdict, compare, ok, kind = self._grade(card, q)
            is_mc = bool(card._radios)
            if is_mc:
                mc_total += 1
                if ok:
                    correct += 1
            else:
                has_free = True
            color = {"ok": Colors.OK_FG, "free": Colors.ACCENT,
                     "unanswered": Colors.TEXT_DISABLED}.get(kind, Colors.DANGER)
            card._verdict.setText(verdict)
            card._verdict.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: 700; background: transparent;")
            card._compare.setText(compare)
            card._compare.setVisible(bool(compare))
            card._explain.setText(str(q.get("explain") or ""))
            card._explain.setVisible(bool(q.get("explain")))
            card._result.show()
            for r in card._radios:
                r.setEnabled(False)
            if card._edit:
                card._edit.setEnabled(False)

        if has_free:
            self.prac_score.setText(tr(f"选择题答对 {correct} / {mc_total} 题，简答题对照参考答案订正",
                                       f"Multiple choice: {correct} / {mc_total} correct — compare the rest with the reference answers"))
        else:
            self.prac_score.setText(tr(f"答对 {correct} / {mc_total} 题", f"{correct} / {mc_total} correct") +
                                    (tr("，全对 👍", " — all correct 👍") if correct == mc_total
                                     else tr("，错的看下面订正", " — see corrections below")))
        self.prac_score.show()
        self.btn_prac_submit.setEnabled(False)
        self._fit()

    def _grade(self, card, q):
        """给一道题判分：返回 (verdict, compare, ok, kind)。kind ∈ ok/wrong/free/unanswered。"""
        answer = str(q.get("answer") or "").strip()
        radios = card._radios
        if radios:
            chosen = next((r.text() for r in radios if r.isChecked()), "")
            if not chosen:
                return (tr("未作答", "No answer"), tr("正确答案：", "Correct answer: ") + answer,
                        False, "unanswered")
            if self._opt_letter(chosen) and self._opt_letter(answer):
                ok = self._opt_letter(chosen) == self._opt_letter(answer)
            else:
                ok = chosen == answer
            if ok:
                return (tr("✓ 答对了", "✓ Correct"), tr("你的答案：", "Your answer: ") + chosen,
                        True, "ok")
            return (tr("✗ 答错了", "✗ Wrong"),
                    tr("你的答案：", "Your answer: ") + chosen + "\n" + tr("正确答案：", "Correct answer: ") + answer,
                    False, "wrong")
        yours = (card._edit.text().strip() if card._edit else "")
        if not yours:
            return (tr("未作答", "No answer"), tr("参考答案：", "Reference answer: ") + answer,
                    False, "unanswered")
        return (tr("简答题 · 自行比对", "Short answer · self-check"),
                tr("你的答案：", "Your answer: ") + yours + "\n" + tr("参考答案：", "Reference answer: ") + answer,
                False, "free")

    def _prac_mastered(self):
        """「✓ 这个我会了」：把错题标成已掌握，然后退回到进来的那一页。"""
        topic = (getattr(self, "_prac_item", None) or {}).get("topic", "")
        if topic:
            store.mark_reviewed(topic)
        back, self._prac_back = self._prac_back, None
        self._prac_back_label = ""
        if back:
            back()
        else:
            self._show_home()

    def _make_detail_quiz(self):
        """按这节历史课的要点出课后练习题。"""
        lesson = getattr(self, "_detail_lesson", {}) or {}
        if not lesson or not hasattr(self.echo, "make_lesson_quiz"):
            return
        self._prac_item = {"topic": self._lesson_name(lesson)}
        ts = getattr(self, "_detail_ts", 0)
        self._prac_back = (lambda: self._show_detail(ts)) if ts else None
        self._prac_back_label = tr("← 课程回顾", "← Lesson review") if ts else ""
        self._prac_qs, self._prac_cards = [], []
        self._prac_submitted = False
        self.prac_loading_lbl.setText(tr("正在按这节课的要点出题…",
                                         "Writing questions from this lesson's key points…"))
        self.prac_dots.start()
        self.prac_loading.show()
        self.prac_body.hide()
        self.prac_score.hide()
        self.btn_prac_submit.setEnabled(False)
        self._show_page(PRACTICE)
        self.echo.make_lesson_quiz(lesson, 4)

    def _on_quiz_ready(self, questions):
        lesson = getattr(self, "_detail_lesson", {}) or {}
        self._prac_item = {"topic": self._lesson_name(lesson)}
        self._show_page(PRACTICE)
        self._on_prac_done(questions)

    # ----- 8 历史课程详情 -----
    def _build_detail(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        self.det_title = _label("", TITLE)
        self.det_title.setWordWrap(True)
        head.addWidget(self.det_title)
        self.det_sub = _label("", CAPTION)
        head.addWidget(self.det_sub)
        self.det_stat = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        head.addWidget(self.det_stat)
        lay.addLayout(head)

        self.det_sum_card, self.det_sum_lbl, self.det_hl_lay = self._summary_card()
        lay.addWidget(self.det_sum_card)

        self.det_path = QWidget()
        self.det_path_lay = QVBoxLayout(self.det_path)
        self.det_path_lay.setContentsMargins(0, 0, 0, 0)
        self.det_path_lay.setSpacing(0)
        lay.addWidget(self.det_path)

        self.det_review = ReviewChain()
        lay.addWidget(self.det_review)

        row = QHBoxLayout()
        row.addWidget(_btn(tr("知识地图", "Knowledge map"), "Quiet", self._show_mindmap_lesson))
        row.addWidget(_btn(tr("出几道题练练", "Practice a few questions"), "Accent", self._make_detail_quiz))
        row.addStretch()
        row.addWidget(_btn(tr("回到主页", "Back to home"), "Link", self._show_home))
        lay.addLayout(row)
        return page

    def _show_detail(self, ts):
        """打开一节历史课的回顾。"""
        try:
            ls = store.get_lesson(float(ts))
        except Exception:
            ls = {}
        self._detail_lesson = ls
        self._detail_ts = ts
        self.det_title.setText(self._lesson_name(ls))
        self.det_sub.setText(
            tr(f"{ls.get('date', '')}　✓ 跟上了 {ls.get('ok', 0)} · 待复习 {ls.get('review', 0)}",
               f"{ls.get('date', '')}　✓ Kept up {ls.get('ok', 0)} · To review {ls.get('review', 0)}").strip())
        self.det_stat.setText(self._stat_line(ls))
        self._fill_summary(self.det_sum_card, self.det_sum_lbl, self.det_hl_lay,
                           ls.get("summary", ""), ls.get("highlights", []))

        while self.det_path_lay.count():
            w = self.det_path_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        skills = ls.get("skills_detail") or []
        for sk in skills:
            st = echo_status(sk.get("status", "ok"))
            m = sk.get("mastery", 0.0)
            note = tr("掉队过 · 已补上", "Fell behind · caught up") if st == "fixed" else ""
            self.det_path_lay.addWidget(SkillRow(sk.get("name", ""), m, echo_mark(st, m), note))
        self.det_path.setVisible(bool(skills))
        self.det_review.setVisible(
            self.det_review.set_chain(ls.get("review_chain") or [], ls.get("suggestion", "")))
        self._show_page(DETAIL)

    # ----- 9 知识地图 -----
    def _show_mindmap_report(self):
        """回响页 → 知识地图：刚下课，用这节的报告画图。"""
        report = getattr(self, "_last_report", None)
        if report is None:
            return
        title = (getattr(self.echo, "title", "") or "").strip()
        self._show_mindmap(mindmap.from_report(report, title=title))

    def _show_mindmap_lesson(self):
        """历史课回顾 → 知识地图。"""
        lesson = getattr(self, "_detail_lesson", {}) or {}
        if not lesson:
            return
        self._show_mindmap(lesson)

    def _show_mindmap(self, lesson):
        self._mindmap_lesson = lesson or {}
        self.mindmap_page.show_lesson(lesson, store.load())
        self._show_page(MINDMAP)

    def _back_to_mindmap(self, topic: str = ""):
        """从练习页退回地图：重画一遍（刚点过「我会了」，节点状态可能变了），
        并把学生刚才在练的那个知识点重新选中，视线不用自己找回去。"""
        lesson = getattr(self, "_mindmap_lesson", None) or {}
        if not lesson:
            self._show_home()
            return
        self.mindmap_page.show_lesson(lesson, store.load())
        self._show_page(MINDMAP)
        if topic:
            self.mindmap_page.select(topic)

    def _go_practice(self, topic):
        """思维导图里点「出题练一练」→ 针对这个知识点去练习页。"""
        topic = (topic or "").strip()
        if not topic:
            return
        item = next((it for it in store.load() if it.get("topic") == topic), None)
        if item is None:
            item = {"topic": topic, "missing": "", "reason": "", "micro_lesson": "",
                    "known": "", "step": "", "now": "", "status": "review", "reviewed": False}
        self._practice_item(item, back=lambda: self._back_to_mindmap(topic),
                            back_label=tr("← 知识地图", "← Knowledge map"))

    # ================= 页面切换 / 尺寸 =================
    def _show_page(self, idx):
        self._page = idx
        for i in range(self.stack.count()):     # 非当前页不参与尺寸计算
            pol = QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored
            self.stack.widget(i).setSizePolicy(pol, pol)
        self.stack.setCurrentIndex(idx)

        mini = idx == MINI
        self.header.setVisible(not mini)
        self.back_btn.setVisible(idx in (BREAK, LESSON, REVIEW, PRACTICE, DETAIL, MINDMAP, COURSES))
        back_label = tr("← 主页", "← Home")
        if idx == PRACTICE and self._prac_back_label:
            back_label = self._prac_back_label     # 从地图/回顾进来的，返回到那儿
        self.back_btn.setText(back_label if idx in (REVIEW, PRACTICE, DETAIL, MINDMAP, COURSES)
                              else tr("← 回到课堂", "← Back to class"))
        self.home_btn.setVisible(idx in (LISTEN, ECHO))
        self.end_btn.setVisible(idx == LISTEN)
        self.fold_btn.setVisible(idx == LISTEN)
        m = Spacing.MD if mini else Spacing.LG
        self.layout().setContentsMargins(SHADOW + m, SHADOW + (Spacing.SM if mini else Spacing.MD),
                                         SHADOW + m, SHADOW + (Spacing.SM if mini else Spacing.LG))
        self._sync_status()
        self._fit()

    def _sync_status(self):
        """状态栏跟着引擎真实状态走。

        原来标签初始就是「正在听课」，可应用启动停在主页、根本没开课，
        翻历史课的回顾时也一直挂着「正在听课」—— 看着像在监听，实际什么都没跑。
        """
        # __init__ 里 _show_home() 比 self.echo 还早，这里必须容错
        engine = getattr(getattr(self, "echo", None), "engine", None)
        if getattr(engine, "active", False):
            return                      # 在上课：交给引擎的状态事件去更新
        self.status_lbl.setText(tr("已下课", "Class ended") if getattr(self, "_had_lesson", False)
                                else tr("还没开始上课", "Lesson not started"))
        self.status_lbl.setToolTip("")
        self.status_dot.setVisible(False)
        self.status_dots.stop()

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

    def _back(self):
        """← 按钮：复习/练习/回顾/课程页回主页，断点/补课页回课堂。

        练习页特殊：从知识地图/课程回顾进来的，退回到进来的那一页。
        """
        if self._page == PRACTICE and self._prac_back:
            back, self._prac_back = self._prac_back, None
            self._prac_back_label = ""
            back()
            return
        if self._page in (REVIEW, PRACTICE, DETAIL, MINDMAP, COURSES):
            self._show_home()
        else:
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
        self.echo_loading_lbl.setText(tr("正在整理这节课…", "Summarizing this lesson…"))
        self.echo_dots.start()
        self.echo_loading.show()
        self.echo_path.hide()
        self.echo_sum_card.hide()
        self.review_card.hide()
        self.echo_sub.setText("")
        self.echo_stat.setText("")
        self.echo_title.setText((getattr(self.echo, "title", "") or "").strip() or tr("今天的课", "Today's lesson"))
        self.echo.end_lesson()
        self._show_page(ECHO)

    def _restart(self):
        self._reset_ui()
        self.echo.start()

    def _toggle_offline(self):
        self.echo.set_offline(not self.echo.offline)

    def _reset_ui(self):
        self.current_concept = None
        self.last_bp = None
        self._fixed.clear()
        self._self_look.clear()
        self._ask = None
        self._ask_buf = ""
        self._analysis_pending = False
        self._break_failed = False
        self.resume_btn.hide()
        self.retry_btn.hide()
        self.topic_lbl.setText(tr("等待老师开讲…", "Waiting for the teacher to start…"))
        self.mini_topic.setText(tr("等待老师开讲…", "Waiting for the teacher to start…"))
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
        if self._analysis_pending:      # 已经在分析，别重复触发
            self._show_page(BREAK)
            return
        self._analysis_pending = True
        self._break_failed = False
        self.retry_btn.hide()
        self._cat("lost")
        self.echo.feedback("lost")
        self.break_cap.setText(tr("Echo 正在找你掉队的地方", "Echo is looking for where you lost track"))
        self.path.clear()
        self.miss_card.hide()
        self.bp_loading_lbl.setText(tr("正在回看最近几分钟的课…", "Reviewing the last few minutes…"))
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
        self.resume_btn.hide()
        self._show_page(LISTEN)

    def _on_self_look(self):
        # 学生自己处理：不调 LLM，收起断点页；断点还没出来就只是取消
        if self.last_bp and self.btn_fill.isEnabled():
            self._self_look.add(self.last_bp.concept)
            if hasattr(self.echo, "mark_self"):
                self.echo.mark_self()
        self.bp_dots.stop()
        self._cat("ok", 1500)
        self.resume_btn.hide()
        self._show_page(LISTEN)

    # ================= 断点追问 =================
    def _ask_breakpoint(self):
        q = self.ask_input.text().strip()
        if not q or not self.ask_btn.isEnabled():
            return
        self.ask_input.clear()
        self.ask_view.show()
        self.ask_view.setHtml(f"<span style='color:{Colors.TEXT_SECONDARY}'>"
                              f"{tr('Echo 正在想…', 'Echo is thinking…')}</span>")
        self.ask_btn.setEnabled(False)
        self._ask_buf = ""
        bp = self.last_bp
        if self._ask is None:
            from echo.backend.vision import LessonAsk
            extra = ""
            if bp:
                extra = (f"刚才定位到的知识断点：{bp.concept}\n缺失的这一步：{bp.missing}"
                         f"\n为什么容易掉队：{bp.reason}")
            self._ask = LessonAsk(self.echo.engine, extra)
        self._ask.ask(q, self._ask_delta.emit, self._ask_done.emit, self._ask_err.emit)

    def _on_ask_delta(self, d):
        self._ask_buf += d
        self._render_ask()

    def _on_ask_done(self, a):
        self._ask_buf = a
        self._render_ask()
        self.ask_btn.setEnabled(True)

    def _on_ask_err(self, m):
        self._ask_buf = f"<span style='color:{Colors.DANGER}'>{html.escape(m)}</span>"
        self.ask_view.setHtml(self._ask_buf)
        self.ask_btn.setEnabled(True)

    def _render_ask(self):
        body = html.escape(self._ask_buf).replace("\n", "<br>")
        self.ask_view.setHtml(body)
        self.ask_view.verticalScrollBar().setValue(self.ask_view.verticalScrollBar().maximum())

    def _ack(self, btn):
        """点击后短暂显示「已记录」，给学生一个确认感。"""
        if getattr(btn, "_orig_text", None) is None:
            btn._orig_text = btn.text()
        btn.setText(tr("已记录", "Noted"))
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
            self.summary_lbl.setText(tr("正在听，马上识别知识点…",
                                        "Listening — spotting knowledge points shortly…"))
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
        self._analysis_pending = False
        self.last_bp = bp
        self.last_bp_concepts = list(concepts or [])
        self._ask = None             # 新断点 = 新一轮追问
        self._ask_buf = ""
        if hasattr(self, "ask_view"):
            self.ask_view.hide()
        if hasattr(self, "ask_input"):
            self.ask_input.clear()
            self.ask_btn.setEnabled(True)
        self.bp_dots.stop()
        self.bp_loading.hide()
        self.break_cap.setText(tr("你可能从这里开始掉队", "You probably lost track here"))
        self.path.set_path(self.last_bp_concepts, bp.breakpoint_tc, bp.note)
        self.missing_lbl.setText(bp.missing)
        self.reason_lbl.setText(bp.reason)
        self.reason_lbl.setVisible(bool(bp.reason))
        self.miss_card.show()
        self.btn_fill.setEnabled(True)
        self._fill_lesson(bp)
        self.resume_btn.show()      # 回听课页后还能一键跳回这节补课
        if self._page in (BREAK, LESSON):
            self._fit()

    def _fill_lesson(self, bp):
        """三段式：优先用后端的 known / step / now，缺了就从时间轴和 micro_lesson 拼出来。"""
        cs = self.last_bp_concepts
        idx = next((i for i, c in enumerate(cs) if c.timecode == bp.breakpoint_tc), None)
        prev = cs[idx - 1] if idx else None
        now = cs[-1] if cs else None

        known = getattr(bp, "known", "") or (
            tr(f"{prev.topic}：{prev.summary}", f"{prev.topic}: {prev.summary}")
            if prev and prev.summary else (prev.topic if prev else tr("前面的定义和例子", "earlier definitions and examples")))
        step = getattr(bp, "step", "") or bp.micro_lesson
        now_txt = getattr(bp, "now", "") or (
            tr(f"老师现在讲的「{now.topic}」就是用这一步接着往下推的。",
               f"What the teacher is covering now (\"{now.topic}\") builds straight on this step.")
            if now else tr("回到课堂，继续往下听。", "Back to class — keep listening."))

        self.lesson_title.setText(bp.missing or bp.concept)
        self.step_known.setText(rich(known))
        self.step_main.setText(rich(step))
        self.step_now.setText(rich(now_txt))

    def _on_echo(self, report):
        self._last_report = report
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
                note = tr("掉队过 · 已补上", "Fell behind · caught up")
            elif hit(sk.name, self._self_look):
                note = tr("掉队过 · 自己看了", "Fell behind · reviewed it alone")
            rows.append((sk.name, sk.mastery, echo_mark(st, sk.mastery), note))
        for name, m, mark, note in rows:
            self.echo_path_lay.addWidget(SkillRow(name, m, mark, note))
        self.echo_path.setVisible(bool(rows))

        cnt = {k: sum(1 for r in rows if r[2] == k) for k in ("ok", "unsure", "lost")}
        self.echo_sub.setText(f"✓ {tr('跟上了', 'kept up')} {cnt['ok']} · ? {tr('有点懵', 'a bit lost')} {cnt['unsure']} · ! {tr('掉队了', 'fell behind')} {cnt['lost']}")
        title = (getattr(self.echo, "title", "") or "").strip()
        self.echo_title.setText(title or tr("今天的课", "Today's lesson"))
        self.echo_stat.setText(self._stat_line(report))
        self._fill_summary(self.echo_sum_card, self.echo_sum_lbl, self.echo_hl_lay,
                           getattr(report, "summary", ""), getattr(report, "highlights", []))
        self.review_card.setVisible(self.review_card.set_chain(report.review_chain, report.suggestion))
        cnt["review"] = cnt["unsure"] + cnt["lost"]
        self._save_review()
        self._save_lesson(report)
        self._cat("ok" if not cnt["review"] else "idle")
        self._fit()

    @staticmethod
    def _stat_line(src) -> str:
        """时长 · 知识点数 · 转写字数，src 可以是 EchoReport 或归档 dict。"""
        get = src.get if isinstance(src, dict) else lambda k, d=0: getattr(src, k, d)
        mins = int((get("duration", 0) or 0) // 60)
        total = get("total", 0) if isinstance(src, dict) else len(getattr(src, "skills", []) or [])
        bits = []
        if mins:
            bits.append(tr(f"听了 {mins} 分钟", f"{mins} min listened"))
        if total:
            bits.append(tr(f"{total} 个知识点", f"{total} knowledge points"))
        chars = get("char_count", 0) or 0
        if chars:
            bits.append(tr(f"转写 {chars} 字", f"{chars} chars transcribed"))
        return " · ".join(bits)

    def _save_lesson(self, report):
        """把这节课存进历史，主页「课程管理」里能看到。没起名时 store 会用开课时间命名。"""
        try:
            title = (getattr(self.echo, "title", "") or "").strip()
            store.save_lesson(title, report.skills, report.review_chain, report.suggestion,
                              summary=getattr(report, "summary", ""),
                              highlights=getattr(report, "highlights", []),
                              duration=getattr(report, "duration", 0.0),
                              line_count=getattr(report, "line_count", 0),
                              char_count=getattr(report, "char_count", 0),
                              graph=getattr(report, "graph", None))
        except Exception:
            pass

    STATUS = {
        "listening":   (tr("正在听课", "Listening"), False),
        "analyzing":   (tr("正在分析", "Analyzing"), True),
        "summarizing": (tr("正在整理", "Summarizing"), True),
        "loading_asr": (tr("正在加载语音识别", "Loading speech recognition"), True),
        "done":        (tr("已下课", "Class ended"), False),
    }

    def _on_status(self, st):
        self._had_lesson = True         # 引擎发了状态，说明这节课真的在跑
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
        # 声纹球：仅 listening 时启动；loading_asr 时也启动（表示在准备听）
        if st == "listening":
            self.wave_orb.start()
            self.mini_wave_orb.start()
        elif st in ("done", "summarizing"):
            self.wave_orb.stop()
            self.mini_wave_orb.stop()
        if not self.echo.engine.current_concept():
            if st == "loading_asr":
                self.summary_lbl.setText(tr("首次加载约 10 秒，之后会自动开始听",
                                            "First load takes ~10s, then it starts listening automatically"))
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

    def _on_level(self, level):
        self.wave_orb.set_level(level)
        self.mini_wave_orb.set_level(level)

    def _on_checkin(self, question):
        """课堂抽问：展开到听课页让卡片可见，并让窗口随之变高。"""
        if self._page == MINI:
            self._show_page(LISTEN)
        self.checkin_card.ask(question)
        if self._page == LISTEN:
            self._fit()

    def _on_checkin_result(self, record):
        self.checkin_card.show_result(record)
        if self._page == LISTEN:
            self._fit()

    def _on_mode(self, kind, offline):
        tags = [tr("离线", "Offline")] if offline else []
        text = " · ".join(tags)
        tip = tr("Ctrl+Shift+O 切离线/在线", "Ctrl+Shift+O toggles offline/online")
        self.mode_lbl.setText(text)
        self.mode_lbl.setProperty("base", text)
        self.mode_lbl.setToolTip(tip)
        self.mode_lbl.setVisible(bool(tags))
        self._fit()

    def _on_error(self, msg):
        self._analysis_pending = False   # 分析失败/出错，允许重试
        self.status_lbl.setText(tr("网络或 AI 出错", "Network or AI error"))
        self.status_lbl.setToolTip(msg)
        self.status_dot.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 8px; background: transparent;")
        if self._page == BREAK and not self.btn_fill.isEnabled():
            self._break_failed = True
            self.bp_dots.stop()
            self.bp_loading_lbl.setText(tr("这次没分析出来，可以直接重试", "That didn't work — you can retry"))
            self.retry_btn.show()
            self._fit()
        if self._page == ECHO and self.echo_loading.isVisible():
            self.echo_dots.stop()
            self.echo_loading_lbl.setText(tr("回响生成失败，请检查网络后重试",
                                             "Couldn't generate the review — check your connection and try again"))

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
