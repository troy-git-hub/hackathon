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
import logging
import re
import time
import datetime
import ctypes
from ctypes import wintypes

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QFrame, QSizePolicy, QStackedWidget,
                             QProgressBar, QApplication, QShortcut, QScrollArea,
                             QLineEdit, QTextBrowser, QRadioButton, QButtonGroup,
                             QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QRectF, QPoint, pyqtSignal
from PyQt5.QtGui import QFont, QCursor, QPainter, QPainterPath, QColor, QBrush, QPen, QKeySequence, QPixmap

# Win32 常量 — 无边框窗口边缘拖拽调整大小
WM_NCHITTEST = 0x0084
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
user32 = ctypes.windll.user32

from echo.widgets import dialogs
from echo.theme import Colors, Radius, font, Spacing
from echo.components.loading import PulseDots
from echo.components.wave_orb import WaveOrb
from echo.components.study import (CatAvatar, BreakPath, LessonStep, SkillRow, SkillTile,
                                   ReviewChain, echo_status, echo_mark)
from echo.mock_data import Concept
from echo.backend.engine import parse_tc
from echo.backend.qt_bridge import EchoBridge
from echo.backend import store
from echo.components.pet import EMOTION_FILES, ASSETS_DIR
from echo.i18n import tr
from echo.widgets.checkin import CheckinCard
from echo.components.avatar import AvatarView
from echo.widgets.mindmap import MindMapPage
from echo.widgets.profile_page import ProfilePage
from echo.backend import gaps, mindmap, persona, profile, recall, why_matters

log = logging.getLogger("echo.ui")

SHADOW = 14
WAIT_HINT = tr("播放网课后，Echo 会自动开始听", "Play your course and Echo will start listening automatically")
LISTEN, MINI, BREAK, LESSON, ECHO, REVIEW, HOME, PRACTICE, DETAIL, MINDMAP, COURSES, RECALL, \
    PROFILE, ASK, LEARNED, WEEKLY = range(16)
# 各页内容区宽度（不含阴影与内边距）
PAGE_WIDTH = {LISTEN: 340, MINI: 300, BREAK: 380, LESSON: 400, ECHO: 380,
              REVIEW: 380, HOME: 360, PRACTICE: 400, DETAIL: 380, MINDMAP: 480,
              COURSES: 420, RECALL: 400, PROFILE: 380, ASK: 400, LEARNED: 480,
              WEEKLY: 400}

# ← 按钮上写什么：按「退回去会到哪一页」说，别让学生猜自己会掉到哪儿。
# 页面自己说了算（练习页/回顾页记着来路）时以它们为准，这里管其余的。
BACK_LABEL = {
    LISTEN: tr("← 回到课堂", "← Back to class"),
    HOME: tr("← 主页", "← Home"),
    ECHO: tr("← 回响", "← Review"),
    REVIEW: tr("← 错题复习", "← Mistakes"),
    RECALL: tr("← 讲给 Echo 听", "← Talk it through"),
    PRACTICE: tr("← 练习", "← Practice"),
    DETAIL: tr("← 课程回顾", "← Lesson recap"),
    MINDMAP: tr("← 知识地图", "← Knowledge map"),
    COURSES: tr("← 课程管理", "← Courses"),
    PROFILE: tr("← 我的资料", "← My profile"),
    ASK: tr("← 回到课堂", "← Back to class"),
    LEARNED: tr("← 已学内容", "← Learned so far"),
    WEEKLY: tr("← 一周回响", "← Weekly review"),
}
NAV_HISTORY_MAX = 24          # 来路记最近这么多步就够，别无限长


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


def _fmt_clock(ts) -> str:
    """墙钟 epoch 秒 → 「HH:MM」。0 或异常兜底空串。"""
    try:
        ts = float(ts)
        if ts <= 0:
            return ""
        return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")
    except (OSError, ValueError, TypeError):
        return ""


def _fmt_duration(sec) -> str:
    """秒 → 「X 分钟」/「X 秒」/「X 分 Y 秒」。"""
    sec = max(0, int(sec))
    if sec < 60:
        return tr(f"{sec} 秒", f"{sec}s")
    m, s = divmod(sec, 60)
    if s == 0:
        return tr(f"{m} 分钟", f"{m} min")
    return tr(f"{m} 分 {s} 秒", f"{m}m {s}s")


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
    # 掌握验证：出题和判断都走 AI（后台线程），结果经信号回主线程
    _recall_planned = pyqtSignal(object)
    _recall_judged = pyqtSignal(object)
    _recall_voice_done = pyqtSignal(str)
    # 「为什么要复习它」是后台批量生成的，结果经信号回主线程再碰控件
    _why_ready = pyqtSignal(object)
    # 断点页的麦克风：转写在后台线程，结果经信号回主线程填进输入框
    _ask_voice_done = pyqtSignal(str)
    # 随时问：回答是流式的，回调在后台线程，经信号回主线程追加文字
    _qa_delta = pyqtSignal(str)
    _qa_done = pyqtSignal(str)
    _qa_err = pyqtSignal(str)

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
        self._detail_back = None     # 回顾页是从哪儿进来的（课程管理 / 别处），← 按钮退回那里
        self._detail_back_label = ""
        # 错题卡的折叠状态 {topic: 是否收起}。_render_review 整页重建，
        # 不记着的话学生刚展开的卡打完分就被收回去。
        self._review_folded = {}
        self._why_busy = False       # 正在批量生成「为什么要复习它」，防重复触发
        self._why_labels = {}        # {topic: 那张卡的说明标签}，生成回来后就地填字
        # 「讲给 Echo 听」这一轮的状态
        self._recall_items = []      # 本轮聊到的知识点
        self._recall_root = ""       # 它们的共同根源（有的话）
        self._recall_plan = {}       # {opening, questions}
        self._recall_answers = []    # 学生答过的 [{question, answer}]
        self._recall_results = []    # AI 的判断
        self._recall_step = 0
        self._recall_busy = False
        self._recall_recording = False      # 麦克风按一下开始、再按一下结束
        self._recall_recorder = None
        self._ask_recording = False         # 断点页的追问框也有一套（跟上面同款）
        self._ask_recorder = None
        # 「答疑（随时问）」的状态：对话实例留着，课后回来接着问
        self._qa_chat = None
        self._qa_busy = False
        self._qa_reply = None
        self._qa_started = False
        self._detail_ts = 0
        self._mindmap_lesson = {}    # 知识地图页正在看的那节课
        self._drag_pos = None
        self._page = LISTEN
        # 翻页来路。← 按钮退回上一步，而不是永远弹回主页：
        # 从「课程管理 → 看回顾 → 知识地图」一路点进来，退回去也该按原路走。
        self._nav_history = []
        self._back_navigating = False    # 正在执行「返回」，这期间的翻页不再记来路
        self._analysis_pending = False   # 掉队分析进行中，防重复触发
        self._break_failed = False       # 本次掉队分析失败，可重试

        self._build_ui()
        self._prac_done.connect(self._on_prac_done)
        self._recall_planned.connect(self._on_recall_planned)
        self._recall_judged.connect(self._on_recall_judged)
        self._recall_voice_done.connect(self._on_recall_voice_done)
        self._why_ready.connect(self._on_why_ready)
        self._ask_voice_done.connect(self._on_ask_voice_done)
        self._qa_delta.connect(self._on_qa_delta)
        self._qa_done.connect(self._on_qa_done)
        self._qa_err.connect(self._on_qa_err)
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
            # 卡片收起来后窗口要缩回去，否则听课页下面留一大块空白。
            # 分两步：先松开 stack 的固定高度（它会把页面高度顶住，量不准），
            # 等布局落定一拍再重新适配。
            self.checkin_card.closed.connect(self._on_checkin_closed)
        if hasattr(self.echo, "quiz_ready"):
            self.echo.quiz_ready.connect(self._on_quiz_ready)
        self.mindmap_page.practice_requested.connect(self._go_practice)
        # 地图页内容变高变矮时重新适配窗口（出题回来那几张卡不然会被底边截掉）
        self.mindmap_page.content_changed.connect(self._fit)
        self.learned_map.practice_requested.connect(self._go_practice)
        self.learned_map.content_changed.connect(self._fit)
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
        self.stack.addWidget(self._build_recall())   # 11
        self.stack.addWidget(self._build_profile())  # 12
        self.stack.addWidget(self._build_ask())      # 13
        self.learned_map = MindMapPage()             # 14 已学内容：全部历史知识点的大图
        self.stack.addWidget(self.learned_map)
        self.stack.addWidget(self._build_weekly())   # 15
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

        # 会自己消失的提示条：默认藏着，用的时候显示几秒。
        # 放在 header 正下方而不是借 status_lbl —— 那里显示「正在听课/已下课」，
        # 借来显示别的会让状态栏短暂说谎。
        self.toast_lbl = _label("", wrap=True)
        self.toast_lbl.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;"
            f"background: {Colors.ACCENT_SOFT}; border: 1px solid {Colors.ACCENT_BORDER};"
            f"border-radius: {Radius.MD}px; padding: 8px 12px;")
        self.toast_lbl.setVisible(False)
        root.insertWidget(1, self.toast_lbl)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)

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

        close_btn = _btn("×", "IconBtn", self.close, tr("退出 Echo", "Quit Echo"))
        close_btn.setFixedSize(26, 26)
        lay.addWidget(close_btn)

        # 右上角就是学生自己的头像：设过就显示他的图，没设过就显示 Echo 的喵喵
        # （跟着课堂情绪变）。点一下进资料页。
        self.avatar_view = AvatarView(32, bar)
        self.avatar_view.setCursor(Qt.PointingHandCursor)
        self.avatar_view.setToolTip(tr("我的资料", "My profile"))
        self.avatar_view.clicked.connect(self._show_profile)
        self._emoji_pixmaps = {}
        self._has_avatar = bool(profile.avatar_path())
        import os
        for emo, fname in EMOTION_FILES.items():
            path = os.path.join(ASSETS_DIR, fname)
            if os.path.exists(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    self._emoji_pixmaps[emo] = pm
        lay.addWidget(self.avatar_view)
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
        """标题栏头像：学生设过自己的头像就显示他的，否则显示 Echo 的喵喵（跟着情绪变）。"""
        if self._has_avatar:
            self.avatar_view.refresh()
            return
        pm = self._emoji_pixmaps.get(emotion)
        if pm is not None:
            self.avatar_view.set_pixmap(pm)

    def _refresh_avatar(self):
        """换了头像之后重读一次（资料页里改的、或首次登录时选的）。"""
        self._has_avatar = bool(profile.avatar_path())
        if self._has_avatar:
            self.avatar_view.refresh()
        else:
            self.avatar_view.set_pixmap(self._emoji_pixmaps.get("idle"))

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
        # 「我掉队了」和「答疑」并排：一个是"我没跟上"，一个是"我有问题要问" ——
        # 上课时最常见的两种动作，都放在最好点的地方。
        main_row = QHBoxLayout()
        main_row.setSpacing(Spacing.SM)
        self.btn_lost = _btn(tr("我掉队了", "I fell behind"), "Accent", self._on_lost,
                             tr("Echo 回看最近几分钟，找到你从哪一步开始没听懂", "Echo reviews the last few minutes to find where you lost track"))
        self.btn_lost.setMinimumHeight(46)
        main_row.addWidget(self.btn_lost, 1)
        # 叫「答疑」不叫「答题」：这是学生有问题要问 Echo，不是被考一道题。
        # 「答题」听着像抽问，跟右边那个「考考我」的语义撞了。
        self.btn_qa = _btn(tr("答疑", "Ask a question"), "Quiet", self._show_qa,
                           tr("随时问 Echo，它带着这节课听到的内容回答；课后回来还能接着问",
                              "Ask Echo anything — answered with this lesson's context, "
                              "and you can pick it up again after class"))
        self.btn_qa.setMinimumHeight(46)
        main_row.addWidget(self.btn_qa)
        lay.addLayout(main_row)

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
        self.mini_cap = _label(tr("老师正在讲", "Teacher is speaking"),
                               f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        col.addWidget(self.mini_cap)
        self.mini_topic = _label(tr("等待老师开讲…", "Waiting for the teacher to start…"), f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;"
                                                "font-weight: 600;")
        self.mini_topic.setMinimumWidth(10)
        self.mini_topic.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.mini_topic)
        lay.addLayout(col, 1)
        # 折叠条地方小，只留最实用的两个按钮，而且**跟着场景换**（见 _sync_mini）：
        # 上课时是「掉队了 + 答疑」，没上课时是「开始听课 + 复习」。
        # 点哪个都要先看当前在不在上课，所以槽是个转发器，不是写死某个动作。
        self.mini_main = _btn(tr("掉队了", "Fell behind"), "Accent", self._mini_primary)
        self.mini_main.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        lay.addWidget(self.mini_main)
        self.mini_second = _btn(tr("答疑", "Ask"), "Quiet", self._mini_second)
        self.mini_second.setStyleSheet("font-size: 13px; padding: 6px 10px;")
        lay.addWidget(self.mini_second)
        ex = _btn("+", "IconBtn", lambda: self._show_page(LISTEN), tr("展开", "Expand"))
        ex.setFixedSize(26, 26)
        lay.addWidget(ex)
        # 自适应声纹球：直径跟随 mini 窗口高度，显示在最右端
        self.mini_wave_orb = WaveOrb(size=None)
        lay.addWidget(self.mini_wave_orb)
        return page

    def _mini_primary(self):
        """折叠条上的主按钮：上课时「我掉队了」，没上课时「开始听课」。"""
        if self._in_class():
            self._on_lost()
        else:
            self._start_lesson_named()

    def _mini_second(self):
        """折叠条上的次按钮：上课时「答疑」，没上课时去复习。"""
        if self._in_class():
            self._show_qa()
        else:
            self._show_review()

    def _sync_mini(self):
        """折叠条按「在不在上课」换一套按钮和文案。

        学生折叠起来的时候是还在听课（想随手点「掉队了」），还是已经下课在翻别的
        （想开下一节）—— 这两种时候最该点的按钮完全不同，所以按场景换。
        """
        if not hasattr(self, "mini_main"):
            return
        in_class = self._in_class()
        if in_class:
            self.mini_cap.setText(tr("老师正在讲", "Teacher is speaking"))
            self.mini_main.setText(tr("掉队了", "Fell behind"))
            self.mini_second.setText(tr("答疑", "Ask"))
        else:
            self.mini_cap.setText(tr("Echo", "Echo"))
            self.mini_main.setText(tr("开始听课", "Start lesson"))
            self.mini_second.setText(tr("复习", "Review"))
        for b in (self.mini_main, self.mini_second):
            b.style().unpolish(b)      # 换了文案宽度会变，重新套一遍样式
            b.style().polish(b)

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
        # 按一下说话、再按一下转成文字填进输入框（不自动发送）——跟「讲给 Echo 听」
        # 那套完全一样。这里尤其值得有：学生刚掉队正烦着，开口说「我卡在哪」比打字容易。
        self.ask_mic = _btn(tr("说", "Speak"), "Quiet", self._toggle_ask_mic,
                            tr("按一下说话，Echo 把你说的话转成文字（不会自动发送）",
                               "Tap to speak — Echo converts it to text (won't send automatically)"))
        self.ask_mic.setFixedWidth(40)
        qrow.addWidget(self.ask_mic)
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

        self.overview_card, self.overview_lay = self._overview_card()
        lay.addWidget(self.overview_card)

        self.bp_card, self.bp_lay = self._breakpoint_card()
        lay.addWidget(self.bp_card)

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

    def _breakpoint_card(self):
        """「这节课的掉队」卡片：掉队的具体时间 + 时长。返回 (卡片, 容器 layout)。"""
        card = QFrame()
        card.setObjectName("BpCard")
        card.setStyleSheet(f"QFrame#BpCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(6)
        v.addWidget(_label(tr("这节课的掉队", "Where you fell behind"),
                           f"color: {Colors.ACCENT}; font-size: 12px; font-weight: 600;"))
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(4)
        v.addLayout(lay)
        card.hide()
        return card, lay

    def _fill_breakpoints(self, lay, breakpoints):
        """把掉队时间线填进卡片容器；没内容整卡隐藏（由调用方 setVisible）。"""
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        outcome_txt = {
            "fixed": tr("已补上", "caught up"),
            "self": tr("自己看了", "reviewed alone"),
            "open": tr("未补上", "not caught up"),
        }
        for bp in (breakpoints or []):
            clock = _fmt_clock(bp.get("lost_at"))
            dur = _fmt_duration(bp.get("duration") or 0)
            concept = (bp.get("concept") or "").strip()
            outcome = outcome_txt.get(bp.get("outcome"), "")
            bits = []
            if clock:
                bits.append(tr(f"{clock} 掉队", f"Fell behind at {clock}"))
            if concept:
                bits.append(f"「{concept}」")
            bits.append(tr(f"掉了 {dur}", f"lost for {dur}"))
            if outcome:
                bits.append(outcome)
            lay.addWidget(_label(" · ".join(bits),
                                 f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;"
                                 "line-height: 150%;", wrap=True))

    def _overview_card(self):
        """「本节课概览」卡片：掉队总览 / 答题情况 / 掌握概览。返回 (卡片, 容器 layout)。"""
        card = QFrame()
        card.setObjectName("OvCard")
        card.setStyleSheet(f"QFrame#OvCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(8)
        v.addWidget(_label(tr("本节课概览", "Lesson at a glance"),
                           f"color: {Colors.ACCENT}; font-size: 12px; font-weight: 600;"))
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        v.addLayout(lay)
        card.hide()
        return card, lay

    def _fill_overview(self, lay, overview) -> bool:
        """把概览三行填进卡片；返回是否有内容（供调用方 setVisible）。"""
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        any_ = False

        # 1) 掉队总览
        bp_count = overview.get("bp_count") or 0
        if bp_count:
            bits = [tr(f"掉队 {bp_count} 次", f"Fell behind {bp_count}×")]
            if overview.get("bp_total"):
                bits.append(tr(f"共 {_fmt_duration(overview['bp_total'])}",
                               f"{_fmt_duration(overview['bp_total'])} total"))
            if overview.get("bp_max"):
                bits.append(tr(f"最长 {_fmt_duration(overview['bp_max'])}",
                               f"longest {_fmt_duration(overview['bp_max'])}"))
            lay.addWidget(_label(" · ".join(bits),
                                 f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;", wrap=True))
            any_ = True

        # 2) 答题情况
        q_total = overview.get("quiz_total") or 0
        if q_total:
            q_correct = overview.get("quiz_correct") or 0
            acc = int(round(q_correct / q_total * 100))
            lay.addWidget(_label(tr(f"抽问 {q_total} 次 · 答对 {q_correct} 道 · 正确率 {acc}%",
                                    f"{q_total} asked · {q_correct} correct · {acc}% accuracy"),
                                 f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;", wrap=True))
            any_ = True

        # 3) 掌握概览（已跟上 / 待复习 进度条）
        total = overview.get("total") or 0
        if total:
            ok = overview.get("ok") or 0
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(Spacing.SM)
            bar = QProgressBar()
            bar.setRange(0, total)
            bar.setValue(ok)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"QProgressBar {{ background:{Colors.SURFACE_HOVER}; border:none; border-radius:4px; }}"
                f"QProgressBar::chunk {{ background:{Colors.OK_FG}; border-radius:4px; }}")
            h.addWidget(bar, 1, Qt.AlignVCenter)
            h.addWidget(_label(tr(f"已跟上 {ok} / {total}", f"{ok} / {total} kept up"),
                               f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"))
            lay.addWidget(row)
            any_ = True

        return any_

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

    def _show_review(self, push=True):
        """错题复习页：今天该复习的 + 过几天再复习的。"""
        self._render_review()
        self._show_page(REVIEW, push=push)

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

    def _section_label(self, text: str) -> QLabel:
        lbl = _label(text, f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        return lbl

    def _render_review(self):
        """复习页分两个区域：今天该复习的（可以直接聊）和过几天再复习的。

        答完的知识点不会消失 —— 它会落到下面那个区里，带着下次的日期。
        「复习一次就没了」是错的：掌握是慢慢确认出来的。
        """
        while self.review_list_lay.count():
            w = self.review_list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._why_labels = {}        # 旧卡片连同它们的标签一起销毁了
        try:
            due = store.due_items()
            later = store.later_items()
        except Exception:
            due, later = [], []

        self.review_title.setText(tr("错题复习", "Review mistakes"))
        self.review_sub.setText(
            tr(f"今天该复习 {len(due)} 个 · 过几天再复习 {len(later)} 个",
               f"{len(due)} due today · {len(later)} scheduled later")
            if (due or later) else tr("还没有错题。听课时点「我掉队了」就会收进来",
                                      "No mistakes yet — tap \"I fell behind\" during a lesson"))

        if due:
            self.review_list_lay.addWidget(self._section_label(
                tr(f"今天该复习 · {len(due)} 个", f"Due today · {len(due)}")))
            self.review_list_lay.addWidget(self._recall_cta(len(due)))
            for it in due:
                self.review_list_lay.addWidget(self._review_card(it, due=True))
        if later:
            self.review_list_lay.addWidget(self._section_label(
                tr(f"过几天再复习 · {len(later)} 个", f"Coming up · {len(later)}")))
            for it in later:
                self.review_list_lay.addWidget(self._review_card(it, due=False))

        self.review_empty.setVisible(not (due or later))
        self._kick_why_matters(due + later)

    def _kick_why_matters(self, items):
        """给还没有「为什么要复习它」的错题批量补一句。

        一次问一整批，不是每张卡各问一次：模型看不到彼此就容易写成一模一样的套话，
        而且 N 张卡就是 N 次往返。已经在生成中就跳过（`_why_busy`）——复习页会被
        反复重渲染（每次打分都重渲染），不挡一下会连着发起好几批。
        """
        if self._why_busy:
            return
        todo = why_matters.needs(items)
        if not todo:
            return
        self._why_busy = True
        # 回调在后台线程，只允许 emit —— 碰控件一律回主线程做（_on_why_ready）
        why_matters.generate_async(todo,
                                   on_done=lambda reasons: self._why_ready.emit(reasons),
                                   on_error=lambda msg: self._why_ready.emit({}))

    def _on_why_ready(self, reasons):
        """批量生成回来了。写进错题本，然后只把对应那几行文字填上。"""
        self._why_busy = False
        if not isinstance(reasons, dict) or not reasons:
            return
        try:
            store.set_why(reasons)
        except Exception as e:
            log.warning("写「为什么要复习它」失败: %s", e)
            return
        for topic, text in reasons.items():
            lbl = self._why_labels.get(topic)
            if lbl is not None:
                lbl.setText(text)
                lbl.setVisible(True)
        self._fit()      # 多出来的一行会改变卡片高度

    def _recall_cta(self, n: int) -> QFrame:
        """「讲给 Echo 听」的入口卡：不做题，讲一遍就够了。"""
        card = QFrame()
        card.setObjectName("RecallCta")
        card.setStyleSheet(
            f"QFrame#RecallCta {{ background: {Colors.ACCENT_SOFT};"
            f"border: 1px solid {Colors.ACCENT_BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(4)
        v.addWidget(_label(tr("讲给 Echo 听", "Talk it through with Echo"),
                           f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"))
        v.addWidget(_label(tr(f"{n} 个知识点一起聊，你先用自己的话讲一遍，再换个场景用一次",
                              f"Chat through all {n} — explain them in your own words, "
                              "then use one in a new setting"),
                           f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;", wrap=True))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(_btn(tr("开始", "Start"), "Accent", self._show_recall_session))
        v.addLayout(row)
        return card

    def _review_card(self, item, due: bool = True):
        card = QFrame()
        card.setObjectName("ReviewCard")
        card.setStyleSheet(f"QFrame#ReviewCard {{ background: {Colors.SURFACE};"
                           f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        v.setSpacing(6)

        topic_name = (item.get("topic") or "").strip()
        # 折叠状态记在实例上：_render_review 是整页清空重建的，不记的话
        # 学生刚展开一张，打完分重渲染又给收回去。默认值：今天该复习的展开
        # （自评按钮不该多一次点击），「过几天再复习」那一堆收起（错题一多
        # 就是这一堆把页面撑爆的）。
        folded = bool(self._review_folded.get(topic_name, not due))
        self._review_folded[topic_name] = folded      # 把生效值记下，_toggle 直接翻它

        head = QHBoxLayout()
        head.setSpacing(Spacing.SM)
        topic = _label(tr(f"✦ {item.get('topic', '知识点')}", f"✦ {item.get('topic', 'Knowledge point')}"),
                       f"color: {Colors.TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")
        topic.setWordWrap(True)
        head.addWidget(topic, 1)
        v.addLayout(head)

        # 「为什么要复习它」——AI 生成的，说的是这个知识点跟后面要学的东西有什么
        # 关系，不是「你为什么错了」。这一行**不随折叠隐藏**：它就是让学生觉得
        # 这步值得认真对待的那句话，收起状态尤其需要它在。
        # 即使现在还没有内容也先把控件建出来、藏起来：后台批量生成回来时只改
        # 文字、不重渲染整页（学生可能正在看列表）。
        why = (item.get("why_matters") or "").strip()
        why_lbl = _label(why, f"color: {Colors.ACCENT}; font-size: 12px;", wrap=True)
        why_lbl.setVisible(bool(why))
        v.addWidget(why_lbl)
        if topic_name:
            self._why_labels[topic_name] = why_lbl

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)

        # 为什么现在该复习它——不是随机抽的，是调度算出来的，让学生看见依据
        reason = store.due_reason(item)
        if reason:
            rl = _label(f"◷ {reason}", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;",
                       wrap=True)
            bv.addWidget(rl)
        miss = item.get("missing") or item.get("reason") or tr("这里没跟上", "Lost track here")
        ml = _label(tr(f"没跟上：{miss}", f"Missed: {miss}"),
                    f"color: {Colors.ACCENT}; font-size: 13px;")
        ml.setWordWrap(True)
        bv.addWidget(ml)
        # 老师当时讲到哪儿 —— 想回去看录像时有个抓手
        tc = (item.get("timecode") or "").strip()
        if tc:
            bv.addWidget(_label(tr(f"老师讲到 {tc}", f"Teacher covered it at {tc}"),
                               f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"))
        lesson = (item.get("micro_lesson") or "").strip()
        if lesson:
            lb = _label(lesson, f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
            lb.setWordWrap(True)
            bv.addWidget(lb)

        if not due:
            # 还没到时候：只告诉他下次什么时候来，不给按钮（不该现在就刷）
            bv.addWidget(_label(self._next_review_text(item),
                               f"color: {Colors.OK_FG}; font-size: 11px;"))
        else:
            bv.addWidget(_label(tr("想起来了吗？", "How well do you remember it?"),
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
            bv.addLayout(grades)

        prow = QHBoxLayout()
        prow.addStretch()
        prow.addWidget(_btn(tr("想不起来？出道题试试", "Not sure? Try a question"), "Link",
                           lambda it=item: self._practice_item(it)))
        bv.addLayout(prow)

        body.setVisible(not folded)
        v.addWidget(body)

        # 折叠按钮。用闭包直接改 body 的可见性、不重渲染整页 —— 重渲染会打断
        # 学生正在看的列表，而且他刚打完分的那张卡会跳位置。
        # toggle 在这里还没赋值，但 lambda 体是点击时才求值，那时它已经绑好了。
        toggle = _btn("▸" if folded else "▾", "IconBtn",
                      lambda t=topic_name, b=body: self._toggle_review_card(t, b, toggle),
                      tr("展开", "Expand") if folded else tr("收起", "Collapse"))
        toggle.setFixedSize(22, 22)
        head.addWidget(toggle, 0, Qt.AlignTop)
        return card

    def _toggle_review_card(self, topic: str, body, btn):
        """折起 / 展开一张错题卡：翻 body 的可见性、换箭头、重算窗口高度。"""
        folded = not bool(self._review_folded.get(topic))
        self._review_folded[topic] = folded
        body.setVisible(not folded)
        btn.setText("▸" if folded else "▾")
        btn.setToolTip(tr("展开", "Expand") if folded else tr("收起", "Collapse"))
        self._fit()          # 卡片高度变了，窗口要跟着重算，否则留白

    @staticmethod
    def _next_review_text(item) -> str:
        days = max(1, round((item.get("due", 0) - time.time()) / store.DAY))
        return tr(f"{days} 天后再确认一次", f"Check again in {days} days")

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
        self._maybe_refresh_persona()      # 复习攒够了，画像可以重算一次

    def _mark_reviewed(self, topic):
        store.mark_reviewed(topic)
        self._render_review()
        self._fit()

    def _toast(self, text: str, ms: int = 5000):
        """一条会自己消失的提示。不打断当前操作，所以不用弹窗。"""
        self.toast_lbl.setText(text)
        self.toast_lbl.setVisible(True)
        self._fit()
        self._toast_timer.start(ms)      # start 会顶掉上一条还没到点的隐藏

    def _hide_toast(self):
        if self.toast_lbl.isVisible():
            self.toast_lbl.setVisible(False)
            self._fit()

    def _maybe_refresh_persona(self):
        """攒够记录了就重算一次学生画像，重算了就跟学生说一声。

        「攒够没」的判据在水位线里（persona 内部），这里只管够了就提示一下。
        同一段节奏里两个触发点（下课、复习打分）可能都命中，第二次
        maybe_refresh() 会返回 None —— 天然只会提示一次。
        """
        try:
            data = persona.maybe_refresh()
        except Exception as e:
            log.warning("重算学生画像失败: %s", e)
            return
        if data:
            self._toast(tr("个人信息已更新 —— Echo 对你的了解又细了一点",
                           "Profile updated — Echo knows you a bit better now"))

    def _on_checkin_closed(self):
        """抽问卡片收起来了：把窗口缩回听课页该有的高度。

        dismiss() 里刚 hide()，此时页面布局还按卡片在的时候算着高度；
        而 stack 的固定高度又会反过来把页面撑住，量出来的永远是老尺寸。
        所以先松开固定高度，等一拍让布局落定，再重新适配。
        """
        self.stack.setFixedHeight(0)
        QTimer.singleShot(0, self._fit)


    def _save_review(self):
        """保险丝，不是主要存储路径：断点在找到的那一刻已经即时落盘了
        （engine._persist_breakpoint），这里下课时再存一遍只是兜底——万一中途有次
        落盘因为短暂的 I/O 错误失败了，下课时还能补上。

        relapse 不在这里重判：复发已经在 engine 里按每条断点找到的那一刻单独判过了，
        这时候再传 relapse=True 会把这节课自己刚存的记录当场误判成复发。
        """
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

        # 「你反复卡在 X」：跨课看出来的规律，不是今天的待办。放在「今天该回响」下面
        # —— 两者都在说「你该注意什么」，但这条是慢性的、根子上的问题。
        # 用暖色底跟回响卡区分开：上面那张催你「现在去做」，这张是「你可能一直没意识到」。
        self.home_gap_card = QFrame()
        self.home_gap_card.setObjectName("GapCard")
        self.home_gap_card.setStyleSheet(
            f"QFrame#GapCard {{ background: {Colors.WARNING_CARD};"
            f"border: 1px solid {Colors.WARNING_CARD_BORDER}; border-radius: {Radius.LG}px; }}")
        gv = QVBoxLayout(self.home_gap_card)
        gv.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        gv.setSpacing(4)
        ghead = QHBoxLayout()
        ghead.setSpacing(Spacing.SM)
        ghead.addWidget(_label(tr("反复卡住的地方", "A pattern worth noticing"),
                               f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"))
        ghead.addStretch()
        self.gap_when = _label("", f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        ghead.addWidget(self.gap_when)
        gv.addLayout(ghead)
        self.gap_lbl = _label("", f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;", wrap=True)
        gv.addWidget(self.gap_lbl)
        grow = QHBoxLayout()
        grow.addStretch()
        self.gap_btn = _btn("", "Accent", self._practice_gap,
                            tr("针对这个前置知识点出几道题，把地基补上",
                               "Practise this prerequisite and shore up the foundation"))
        grow.addWidget(self.gap_btn)
        gv.addLayout(grow)
        self.home_gap_card.setVisible(False)      # 有结论才亮出来
        lay.addWidget(self.home_gap_card)

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
        self.home_learned_card = self._home_card(
            tr("已学内容", "Learned so far"),
            tr("所有历史学过的知识点，一张按学科分区的大思维导图", "Every topic you've learned, in one subject-grouped mind map"),
            tr("查看", "View"), self._show_learned)
        lay.addWidget(self.home_learned_card)
        self.home_weekly_card = self._home_card(
            tr("一周学习回响", "Weekly review"),
            tr("最近 7 天学过的知识点，一页看全", "What you learned in the last 7 days, at a glance"),
            tr("查看", "View"), self._show_weekly)
        lay.addWidget(self.home_weekly_card)
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
        self.btn_recall = _btn(tr("讲给 Echo 听", "Talk it through with Echo"), "Accent",
                               self._show_recall_session,
                               tr("不做题，用你自己的话讲一遍，Echo 听你说完给判断",
                                  "No quiz — explain it in your own words and Echo will judge"))
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
                         lambda t=ls.get("time", 0): self._show_detail(
                             t, back=self._show_courses,
                             back_label=tr("← 课程管理", "← Courses"))),
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
        self._render_gap_card()

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

    def _render_gap_card(self):
        """填「你反复卡在 X」。没有结论就整张收起来。

        只显示**最严重的一条**：首页是行动页，而且 cards 是纵向排的，堆三条就没重点了。
        完整清单在「我的」里。排序（课次数多 → 最近还在卡）在 gaps.recurring 里做。
        """
        try:
            found = gaps.recurring()
        except Exception as e:
            log.warning("算「反复卡住的前置知识」失败: %s", e)
            found = []
        self._home_gap = found[0] if found else None
        if not self._home_gap:
            self.home_gap_card.setVisible(False)
            return
        f = self._home_gap
        self.gap_when.setText(tr(f"{f['lessons']} 节课都卡在这",
                                 f"{f['lessons']} lessons in a row"))
        self.gap_lbl.setText(f.get("sentence") or "")
        self.gap_btn.setText(tr(f"专门补一下「{f['concept']}」",
                                f"Work on \"{f['concept']}\""))
        self.home_gap_card.setVisible(True)

    def _practice_gap(self):
        """首页「专门补一下 X」：拿这个前置概念现造一道题进练习页。

        这个概念多半**不在错题本里**——它是更上游的前置，不是学生当下错的那道题。
        所以造一个临时条目喂给 practice.generate（它只认 topic/missing 这几个字段）。
        missing 得给一句话：对着一个光秃秃的词，模型出的题会空泛。
        """
        f = getattr(self, "_home_gap", None)
        if not f:
            return
        item = {
            "topic": f.get("concept", ""),
            "missing": tr(f"这个前置知识点一直没打牢，最近 {f.get('lessons', 0)} 节课都卡在这",
                          f"This prerequisite was never solid — stuck on it for "
                          f"{f.get('lessons', 0)} lessons"),
        }
        self._practice_item(item)

    def _start_today(self):
        """主页上「开始今天的学习」：名字取自输入框。"""
        name = self.title_edit.text().strip()
        self.title_edit.clear()
        self._begin_lesson(name)

    def _start_lesson_named(self):
        """折叠条上点「开始听课」：先问一句这节课叫什么，留空就用开课时间命名。

        主页那张卡片上本来就有输入框，这里是给学生**折叠状态下顺手开课**用的，
        所以弹一个小输入框，别逼他先展开再找输入框。取消就什么都不做。
        """
        from echo.widgets import dialogs
        name, ok = dialogs.ask_text(
            self, tr("开始今天的学习", "Start today's lesson"),
            tr("这节课叫什么？（留空就用开课时间命名）",
               "What's this lesson called? (leave blank to name it by start time)"), "")
        if not ok:
            return
        self._begin_lesson((name or "").strip())

    def _begin_lesson(self, name: str):
        """开一节课。name 空着不自造名字 —— 交给 store 用开课时间命名。"""
        if hasattr(self.echo, "set_title"):
            self.echo.set_title(name)
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
            self._run_back(back)        # 走 _run_back：这次翻页属于「往回走」，不记来路
        else:
            self._show_home()

    def _make_detail_quiz(self):
        """按这节历史课的要点出课后练习题。"""
        lesson = getattr(self, "_detail_lesson", {}) or {}
        if not lesson or not hasattr(self.echo, "make_lesson_quiz"):
            return
        self._prac_item = {"topic": self._lesson_name(lesson)}
        ts = getattr(self, "_detail_ts", 0)
        detail_back = self._detail_back
        detail_back_label = self._detail_back_label
        self._prac_back = (lambda: self._show_detail(
            ts, back=detail_back, back_label=detail_back_label)) if ts else None
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

    # ----- 11 讲给 Echo 听（掌握验证）-----
    def _build_recall(self) -> QWidget:
        """对话式的掌握验证：没有选项按钮，学生用自己的话讲，Echo 接着问、最后判。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(tr("讲给 Echo 听", "Talk it through with Echo"), TITLE))
        self.recall_sub = _label("", CAPTION, wrap=True)
        head.addWidget(self.recall_sub)
        lay.addLayout(head)

        self.recall_box = QWidget()
        self.recall_box_lay = QVBoxLayout(self.recall_box)
        self.recall_box_lay.setContentsMargins(0, 0, 0, 0)
        self.recall_box_lay.setSpacing(Spacing.SM)
        lay.addWidget(self.recall_box)

        # Echo 在想 → 一句话 + 呼吸点，别让界面看起来卡住
        self.recall_loading = QFrame()
        rl = QHBoxLayout(self.recall_loading)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(Spacing.SM)
        self.recall_dots = PulseDots(Colors.ACCENT)
        rl.addWidget(self.recall_dots, 0, Qt.AlignVCenter)
        self.recall_loading_lbl = _label(tr("Echo 在想…", "Echo is thinking…"),
                                         f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        rl.addWidget(self.recall_loading_lbl, 1)
        self.recall_loading.hide()
        lay.addWidget(self.recall_loading)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.recall_input = QLineEdit()
        self.recall_input.setPlaceholderText(tr("用你自己的话讲…", "Say it in your own words…"))
        self.recall_input.setStyleSheet(
            f"QLineEdit {{ background: {Colors.SURFACE}; color: {Colors.TEXT_PRIMARY};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; padding: 7px 10px;"
            "font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}")
        self.recall_input.returnPressed.connect(self._send_recall)
        row.addWidget(self.recall_input, 1)
        # 按一下录音、再按一下转成文字填进输入框——不自动发，学生看一眼再决定
        # 用文字标签不用 🎤 这种表情符号：这类象形文字在这台机器的字体栈里
        # 渲不出来，变成个看不懂的方块，跟别的图标按钮（问 AI / 发送）保持一致更稳妥。
        self.recall_mic = _btn(tr("说", "Speak"), "Quiet", self._toggle_recall_mic,
                               tr("按一下说话，Echo 把你说的话转成文字（不会自动发送）",
                                  "Tap to speak — Echo converts it to text (won't send automatically)"))
        self.recall_mic.setFixedWidth(40)
        row.addWidget(self.recall_mic)
        self.recall_send = _btn(tr("发送", "Send"), "Accent", self._send_recall)
        row.addWidget(self.recall_send)
        lay.addLayout(row)
        return page

    def _toggle_recall_mic(self):
        """「讲给 Echo 听」的麦克风：按一下开始录，再按一下结束并转成文字。

        不自动发送——转写不一定准，学生看一眼、改两个字再点「发送」更稳妥。
        """
        if getattr(self, "_recall_recording", False):
            self._recall_recording = False
            self.recall_mic.setText(tr("说", "Speak"))
            self.recall_mic.setEnabled(False)
            self.recall_input.setPlaceholderText(tr("转写中…", "Transcribing…"))
            from echo.backend import voice_input
            voice_input.transcribe_async(
                self._recall_recorder,
                on_done=lambda text: self._recall_voice_done.emit(text),
                on_error=lambda msg: self._recall_voice_done.emit(""))
            return
        try:
            from echo.backend import voice_input
            self._recall_recorder = voice_input.Recorder()
            self._recall_recorder.start()
        except Exception as e:
            log.warning("麦克风打不开: %s", e)
            dialogs.warn(self, tr("麦克风打不开", "Couldn't open the microphone"),
                        tr("检查一下有没有麦克风设备、系统有没有给 Echo 麦克风权限。",
                           "Check that a microphone is connected and Echo has permission to use it."))
            return
        self._recall_recording = True
        self.recall_mic.setText("●")
        self.recall_input.setPlaceholderText(tr("在听你说…再按一下结束", "Listening… tap again to stop"))

    def _on_recall_voice_done(self, text: str):
        self.recall_mic.setEnabled(True)
        self.recall_input.setPlaceholderText(tr("用你自己的话讲…", "Say it in your own words…"))
        if text:
            self.recall_input.setText(text)
            self.recall_input.setFocus()
        else:
            self.recall_input.setPlaceholderText(
                tr("没听清，再说一次，或者直接打字", "Didn't catch that — try again, or just type"))

    # ----- 断点页的麦克风：跟上面「讲给 Echo 听」那套是一回事，只是填另一个框 -----
    # 两处逻辑目前是重复的。留着重复也不抽公共函数：能变的点太多（占位符、目标输入框、
    # 状态字段、信号），抽出来会变成一堆参数的胶水函数，比这两段还真难读。
    # 出现第三处再抽。
    def _toggle_ask_mic(self):
        """掉队页的追问框也支持说话。学生正卡着，开口比打字容易。"""
        if getattr(self, "_ask_recording", False):
            self._ask_recording = False
            self.ask_mic.setText(tr("说", "Speak"))
            self.ask_mic.setEnabled(False)
            self.ask_input.setPlaceholderText(tr("转写中…", "Transcribing…"))
            from echo.backend import voice_input
            voice_input.transcribe_async(
                self._ask_recorder,
                on_done=lambda text: self._ask_voice_done.emit(text),
                on_error=lambda msg: self._ask_voice_done.emit(""))
            return
        try:
            from echo.backend import voice_input
            self._ask_recorder = voice_input.Recorder()
            self._ask_recorder.start()
        except Exception as e:
            log.warning("麦克风打不开: %s", e)
            dialogs.warn(self, tr("麦克风打不开", "Couldn't open the microphone"),
                        tr("检查一下有没有麦克风设备、系统有没有给 Echo 麦克风权限。",
                           "Check that a microphone is connected and Echo has permission to use it."))
            return
        self._ask_recording = True
        self.ask_mic.setText("●")
        self.ask_input.setPlaceholderText(tr("在听你说…再按一下结束", "Listening… tap again to stop"))

    def _on_ask_voice_done(self, text: str):
        self.ask_mic.setEnabled(True)
        self.ask_input.setPlaceholderText(tr("比如：为什么分母是 P(B)？",
                                            "e.g. why is the denominator P(B)?"))
        if text:
            self.ask_input.setText(text)      # 填进去但不自动问——转写会有错字，先让他看一眼
            self.ask_input.setFocus()
        else:
            self.ask_input.setPlaceholderText(
                tr("没听清，再说一次，或者直接打字", "Didn't catch that — try again, or just type"))

    def _bubble(self, box_lay: QVBoxLayout, box: QWidget, text: str, who: str, tone: str = ""):
        """往对话区放一条气泡，返回正文那个 QLabel（流式回答要往上追加文字）。

        who: echo / me / note。两个对话页（掌握验证、随时问）共用这套样式。
        """
        f = QFrame()
        f.setObjectName("RecallBubble")
        if who == "me":
            bg, border = Colors.SURFACE, Colors.BORDER
        elif who == "note":
            bg, border = Colors.CODE_BG, Colors.BORDER
        else:
            bg, border = Colors.ACCENT_SOFT, Colors.ACCENT_BORDER
        if tone == "ok":
            border = Colors.OK_FG
        elif tone == "warn":
            border = Colors.DANGER
        f.setStyleSheet(f"QFrame#RecallBubble {{ background: {bg};"
                        f"border: 1px solid {border}; border-radius: {Radius.MD}px; }}")
        v = QVBoxLayout(f)
        v.setContentsMargins(Spacing.MD, Spacing.SM + 2, Spacing.MD, Spacing.SM + 2)
        v.setSpacing(3)
        if who in ("echo", "me"):
            tag = _label(tr("Echo", "Echo") if who == "echo" else tr("你", "You"),
                         f"color: {Colors.TEXT_SECONDARY}; font-size: 10px; font-weight: 600;")
            v.addWidget(tag)
        body = _label(text, f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; line-height: 150%;",
                      wrap=True)
        v.addWidget(body)
        box_lay.addWidget(f)
        # 气泡是运行时加进来的，页面布局还按老内容算着尺寸：
        # 不主动重排一次，换行标签的高度会是 0，界面上只剩几条空条。
        box_lay.activate()
        box.adjustSize()
        self._fit()
        return body

    def _recall_bubble(self, text: str, who: str, tone: str = ""):
        return self._bubble(self.recall_box_lay, self.recall_box, text, who, tone)

    def _qa_bubble(self, text: str, who: str, tone: str = ""):
        return self._bubble(self.qa_box_lay, self.qa_box, text, who, tone)

    def _recall_clear(self):
        while self.recall_box_lay.count():
            w = self.recall_box_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _show_recall_session(self):
        """从复习页/首页进来：挑今天到期的几个，开始这一段对话。"""
        items = store.due_items()
        if not items:
            self._recall_clear()
            self.recall_sub.setText(tr("今天没有要确认的知识点", "Nothing to confirm today"))
            self._recall_bubble(tr("今天没有到期的知识点，去上课吧～",
                                   "Nothing due today — go enjoy your lesson."), "echo")
            self._show_page(RECALL)
            return

        chosen, root = recall.pick(items, n=3)
        self._recall_items = chosen
        self._recall_root = root
        self._recall_answers = []
        self._recall_results = []
        self._recall_step = 0
        self._recall_plan = {}
        self._recall_clear()
        self.recall_sub.setText(self._recall_subtitle(chosen, root))
        self._show_page(RECALL)

        self._set_recall_busy(True, tr("Echo 在想怎么问你…", "Echo is thinking how to ask…"))
        from echo.backend import recall as _r
        def done(plan):
            self._recall_planned.emit(plan)
        _r.plan_async(chosen, root, on_done=done, on_error=lambda _m: self._recall_planned.emit({}))

    @staticmethod
    def _recall_subtitle(items, root) -> str:
        names = "、".join((it.get("topic") or "") for it in items)
        if root and len(items) > 1:
            return tr(f"这一轮聊 {len(items)} 个知识点，它们都卡在「{root}」上",
                      f"{len(items)} points this round — all rooted in \"{root}\"")
        return tr(f"这一轮聊 {len(items)} 个知识点：{names}", f"This round: {names}")

    def _on_recall_planned(self, plan):
        self._set_recall_busy(False)
        self._recall_plan = plan or {}
        opening = (plan or {}).get("opening") or ""
        if opening:
            self._recall_bubble(opening, "echo")
        self._ask_next_recall()

    def _ask_next_recall(self):
        """把下一道题抛出来。题问完了就等学生答完再判。"""
        qs = self._recall_plan.get("questions") or []
        i = self._recall_step
        if i >= len(qs):
            return
        q = qs[i]
        kind = tr("讲给 Echo 听", "Talk it through") if q.get("kind") != "transfer" \
            else tr("换个场景试试", "Try it in a new setting")
        self._recall_bubble(f"{kind}\n{q.get('question', '')}", "echo")
        self.recall_input.setPlaceholderText(
            tr("用你自己的话讲…", "Say it in your own words…")
            if q.get("kind") != "transfer" else tr("试着用一下…", "Try applying it…"))
        self.recall_input.setFocus()

    def _send_recall(self):
        text = self.recall_input.text().strip()
        if not text or self._recall_busy:
            return
        self.recall_input.clear()
        self._recall_bubble(text, "me")
        qs = self._recall_plan.get("questions") or []
        q = qs[self._recall_step] if self._recall_step < len(qs) else {}
        self._recall_answers.append({"question": q.get("question", ""), "answer": text})
        self._recall_step += 1
        self._fit()
        if self._recall_step < len(qs):
            self._ask_next_recall()
            return
        self._judge_recall()

    def _judge_recall(self):
        self._set_recall_busy(True, tr("Echo 在想你说的对不对…", "Echo is thinking about your answer…"))
        from echo.backend import recall as _r
        items, answers = self._recall_items, self._recall_answers
        _r.judge_async(items, answers,
                       on_done=lambda res: self._recall_judged.emit(res),
                       on_error=lambda _m: self._recall_judged.emit({}))

    def _on_recall_judged(self, res):
        self._set_recall_busy(False)
        res = res or {}
        results = res.get("results") or []
        pinned = dict(self._recall_plan)
        pinned["qas"] = list(self._recall_answers)
        self._recall_pinned = pinned
        if not results:
            # 没判出来（没配 key / 调用失败 / 离线）：不假装判过，把决定权交回学生
            self._recall_bubble(tr("这次连不上 AI，我判断不了。你自己说说看，哪个档次更像你？",
                                   "I can't reach the AI to judge this time. "
                                   "Which of these feels right to you?"), "note")
            self._render_manual_grade(self._recall_items)
            self._recall_results = []
            self._fit()
            return
        self._recall_results = results
        if res.get("review"):
            self._recall_bubble(res["review"], "echo")
        self._render_verdicts(results)
        self._fit()

    def _render_verdicts(self, results):
        """把判断结果摊开：每个知识点一档 + 缺的关键点 + 一句反馈。"""
        self._recall_bubble(tr("我听完了，说说我的判断：", "Here's what I made of it:"), "echo")
        for r in results:
            v = r.get("verdict")
            tone = "ok" if v == "clear" else ("warn" if v == "unclear" else "")
            bits = [f"{r.get('topic', '')}　{recall.VERDICT_LABEL.get(v, '')}"]
            if r.get("feedback"):
                bits.append(r["feedback"])
            if r.get("missing"):
                bits.append(tr(f"还没说到的：{r['missing']}", f"Still missing: {r['missing']}"))
            self._recall_bubble("\n".join(bits), "note", tone)
        # 判定写进调度；学生觉得不准可以改
        recall.apply_results(results)
        self._render_manual_grade(results, override=True)
        self._sync_recall_after()

    def _render_manual_grade(self, results, override: bool = False):
        """「判断不准确？」—— 让学生自己改。一次 AI 判定不该给人贴标签。"""
        cards = QFrame()
        cards.setStyleSheet("background: transparent; border: none;")
        v = QVBoxLayout(cards)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(Spacing.SM)
        who = {r.get("topic"): r.get("verdict") for r in (results or [])}
        for it in self._recall_items:
            topic = it.get("topic") or ""
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(_label(tr(f"{topic}：", f"{topic}: "),
                                 f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;"))
            row.addStretch()
            for key, zh in recall.MANUAL_CHOICES:
                label = tr(zh, {"clear": "Clear", "fuzzy": "Fuzzy", "unclear": "Lost"}[key])
                if who.get(topic) == key:
                    label = "● " + label
                row.addWidget(_btn(label, "Quiet",
                                   lambda t=topic, k=key: self._override_verdict(t, k),
                                   tr("改成这一档", "Set this instead")))
            v.addLayout(row)
        if override:
            hint = _label(tr("我判得不准？点一下自己改，下次复习时间跟着变。",
                             "Got it wrong? Tap to set it yourself — the next review follows your call."),
                          f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;", wrap=True)
            v.addWidget(hint)
        self.recall_box_lay.addWidget(cards)

    def _override_verdict(self, topic, verdict):
        recall.apply_results([{"topic": topic, "verdict": verdict}])
        self._recall_bubble(tr(f"好，那「{topic}」按你说的记。", f"OK — noting \"{topic}\" as you said."),
                            "echo")
        self._sync_recall_after()

    def _sync_recall_after(self):
        """判完/改完之后收拾界面：更新首页计数，并把对话收个尾。"""
        self._render_recall_card()
        self.recall_sub.setText(tr("记下了，下次到期我再来问你",
                                   "Noted — I'll ask again when it's due"))
        self.recall_input.setEnabled(False)
        self.recall_send.setEnabled(False)
        self._fit()

    def _set_recall_busy(self, busy: bool, msg: str = ""):
        self._recall_busy = busy
        if busy:
            self.recall_loading_lbl.setText(msg)
            self.recall_dots.start()
            self.recall_loading.show()
        else:
            self.recall_dots.stop()
            self.recall_loading.hide()
        self.recall_input.setEnabled(not busy)
        self.recall_send.setEnabled(not busy)
        self._fit()

    # ----- 12 我的资料 -----
    def _build_profile(self) -> QWidget:
        self.profile_page = ProfilePage()
        self.profile_page.back_requested.connect(self._leave_profile)
        self.profile_page.avatar_changed.connect(self._on_avatar_changed)
        return self.profile_page

    def _show_profile(self):
        # 切进来要 refresh：统计和头像都可能变了，不刷新显示的是上次的
        self.profile_page.refresh()
        self._show_page(PROFILE)

    def _leave_profile(self):
        """资料页自己的「回到主页」链接：正在听课时不放行。

        头像在听课页也点得到（header 常驻），这条路跟 home_btn 是同一个洞——
        不堵住的话，学生照样能从「资料页」溜到主页、把一节正在听的课晾在那。
        """
        engine = getattr(getattr(self, "echo", None), "engine", None)
        if getattr(engine, "active", False):
            self._show_page(LISTEN)
        else:
            self._show_home()

    def _on_avatar_changed(self, _path=""):
        self._refresh_avatar()

    # ----- 13 答疑（随时问 Echo）-----
    def _build_ask(self) -> QWidget:
        """上课时随时能问的问答框。

        和「讲给 Echo 听」复用同一套气泡样式，但这里不是验证掌握，
        是学生真的有问题要问 —— Echo 带着这节课听到的时间轴和字幕回答。
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.SM)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(tr("问 Echo", "Ask Echo"), TITLE))
        self.qa_sub = _label("", CAPTION, wrap=True)
        head.addWidget(self.qa_sub)
        lay.addLayout(head)

        self.qa_box = QWidget()
        self.qa_box_lay = QVBoxLayout(self.qa_box)
        self.qa_box_lay.setContentsMargins(0, 0, 0, 0)
        self.qa_box_lay.setSpacing(Spacing.SM)
        lay.addWidget(self.qa_box)

        self.qa_loading = QFrame()
        al = QHBoxLayout(self.qa_loading)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(Spacing.SM)
        self.qa_dots = PulseDots(Colors.ACCENT)
        al.addWidget(self.qa_dots, 0, Qt.AlignVCenter)
        self.qa_loading_lbl = _label(tr("Echo 在想…", "Echo is thinking…"),
                                      f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        al.addWidget(self.qa_loading_lbl, 1)
        self.qa_loading.hide()
        lay.addWidget(self.qa_loading)

        row = QHBoxLayout()
        row.setSpacing(Spacing.SM)
        self.qa_input = QLineEdit()
        self.qa_input.setPlaceholderText(tr("比如：老师刚说的「虚拟语气」是什么意思？",
                                             "e.g. what does \"subjunctive\" mean here?"))
        self.qa_input.setStyleSheet(
            f"QLineEdit {{ background: {Colors.SURFACE}; color: {Colors.TEXT_PRIMARY};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; padding: 7px 10px;"
            "font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}")
        self.qa_input.returnPressed.connect(self._send_qa)
        row.addWidget(self.qa_input, 1)
        self.qa_send = _btn(tr("发送", "Send"), "Accent", self._send_qa)
        row.addWidget(self.qa_send)
        lay.addLayout(row)
        return page

    # ----- 已学内容（全部历史知识点大图，按学科分区）-----
    def _show_learned(self):
        self.learned_map.show_all(store.list_lessons(), store.load())
        self._show_page(LEARNED)

    # ----- 一周学习回响（最近 7 天知识点，两列进度条）-----
    def _build_weekly(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.MD)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(tr("一周学习回响", "Weekly review"), TITLE))
        self.weekly_sub = _label("", CAPTION, wrap=True)
        head.addWidget(self.weekly_sub)
        lay.addLayout(head)

        self.weekly_host = QWidget()
        self.weekly_grid = QGridLayout(self.weekly_host)
        self.weekly_grid.setContentsMargins(0, 0, 0, 0)
        self.weekly_grid.setHorizontalSpacing(Spacing.MD)
        self.weekly_grid.setVerticalSpacing(Spacing.SM)
        lay.addWidget(self.weekly_host)

        self.weekly_empty = _label(
            tr("最近 7 天还没有学习记录。开始听一节课，这里就会长出来。",
               "No learning recorded in the last 7 days. Start a lesson and this page fills up."),
            f"color: {Colors.TEXT_SECONDARY}; font-size: 13px;", wrap=True)
        lay.addWidget(self.weekly_empty)
        lay.addStretch(1)
        return page

    def _render_weekly(self):
        while self.weekly_grid.count():
            it = self.weekly_grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        skills = store.weekly_skills(7)
        for i, sk in enumerate(skills):
            st = echo_status(sk.get("status", "ok"))
            mark = echo_mark(st, sk.get("mastery", 0.0))
            self.weekly_grid.addWidget(
                SkillTile(sk.get("name", ""), sk.get("mastery", 0.0), mark), i // 2, i % 2)
        n = len(skills)
        self.weekly_sub.setText(
            tr(f"最近 7 天学了 {n} 个知识点", f"{n} knowledge points learned in the last 7 days")
            if n else tr("最近 7 天还没有学习记录", "Nothing learned in the last 7 days"))
        self.weekly_empty.setVisible(not n)

    def _show_weekly(self):
        self._render_weekly()
        self._show_page(WEEKLY)

    def _show_qa(self):
        """从听课页点「答疑」进来。对话本身是留着的 —— 课后回来接着问，上下文还在。"""
        if getattr(self, "_qa_chat", None) is None:
            from echo.backend.vision import LessonAsk
            engine = getattr(getattr(self, "echo", None), "engine", None)
            self._qa_chat = LessonAsk(engine)
        if not getattr(self, "_qa_started", False):
            self._qa_started = True
            self._qa_bubble(tr("想问什么就问，我带着这节课听到的内容回答你。"
                                "这节课上完回来，我们还能接着聊。",
                                "Ask me anything — I'll answer using what I've heard in this lesson. "
                                "Come back after class and we can pick this up again."), "echo")
        self.qa_sub.setText(tr("带着这节课的上下文回答；课后回来还能接着问",
                                "Answered with this lesson's context — resumable after class"))
        self._show_page(ASK)
        self.qa_input.setFocus()

    def _send_qa(self):
        q = self.qa_input.text().strip()
        if not q or getattr(self, "_qa_busy", False):
            return
        if getattr(self, "_qa_chat", None) is None:
            self._show_qa()
            return
        self.qa_input.clear()
        self._qa_bubble(q, "me")
        self._qa_busy = True
        self.qa_send.setEnabled(False)
        self.qa_dots.start()
        self.qa_loading.show()
        self._qa_reply = None
        self._qa_chat.ask(q, self._qa_delta.emit, self._qa_done.emit, self._qa_err.emit)

    def _on_qa_delta(self, piece: str):
        if self._qa_reply is None:
            self._qa_reply = self._qa_bubble("", "echo")
        self._qa_reply.setText((self._qa_reply.text() or "") + (piece or ""))
        self.qa_box_lay.activate()
        self._fit()

    def _on_qa_done(self, _full: str = ""):
        self._qa_busy = False
        self.qa_dots.stop()
        self.qa_loading.hide()
        self.qa_send.setEnabled(True)
        if self._qa_reply is not None and not (self._qa_reply.text() or "").strip():
            self._qa_reply.setText(tr("这次没答上来，再问一次试试。",
                                       "Couldn't answer that one — try asking again."))
        self._fit()

    def _on_qa_err(self, msg: str):
        self._qa_busy = False
        self.qa_dots.stop()
        self.qa_loading.hide()
        self.qa_send.setEnabled(True)
        # 别把 DEEPSEEK_API_KEY 这种内部信息甩给学生看
        low = (msg or "").lower()
        if "api_key" in low or "offline" in low or "缺少" in (msg or ""):
            text = tr("现在连不上 AI（可能没网或没配 key），等会儿再问我吧。",
                      "Can't reach the AI right now (offline or no key) — try me again later.")
        else:
            text = tr("回答不了，等会儿再问我吧。", "Couldn't answer — try me again later.")
        self._qa_bubble(text, "note")
        self._fit()

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

        self.det_overview_card, self.det_overview_lay = self._overview_card()
        lay.addWidget(self.det_overview_card)

        self.det_bp_card, self.det_bp_lay = self._breakpoint_card()
        lay.addWidget(self.det_bp_card)

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

    def _show_detail(self, ts, back=None, back_label=""):
        """打开一节历史课的回顾。

        back/back_label：← 按钮该退回哪儿。不传就按老样子退回主页——
        比如从知识地图的「出题练一练」路径再点回这节课，不需要额外的退路。
        """
        try:
            ls = store.get_lesson(float(ts))
        except Exception:
            ls = {}
        self._detail_lesson = ls
        self._detail_ts = ts
        self._detail_back = back
        self._detail_back_label = back_label
        self.det_title.setText(self._lesson_name(ls))
        self.det_sub.setText(
            tr(f"{ls.get('date', '')}　✓ 跟上了 {ls.get('ok', 0)} · 待复习 {ls.get('review', 0)}",
               f"{ls.get('date', '')}　✓ Kept up {ls.get('ok', 0)} · To review {ls.get('review', 0)}").strip())
        self.det_stat.setText(self._stat_line(ls))
        self._fill_summary(self.det_sum_card, self.det_sum_lbl, self.det_hl_lay,
                           ls.get("summary", ""), ls.get("highlights", []))
        _bps = ls.get("breakpoints") or []
        _quiz = ls.get("quiz") or {}
        _skills = ls.get("skills_detail") or []
        self.det_overview_card.setVisible(self._fill_overview(self.det_overview_lay, {
            "bp_count": len(_bps),
            "bp_total": int(sum(b.get("duration") or 0 for b in _bps)),
            "bp_max": int(max((b.get("duration") or 0 for b in _bps), default=0)),
            "quiz_total": _quiz.get("total", 0),
            "quiz_correct": _quiz.get("correct", 0),
            "ok": sum(1 for s in _skills if s.get("status") == "ok"),
            "total": len(_skills),
        }))
        self._fill_breakpoints(self.det_bp_lay, _bps)
        self.det_bp_card.setVisible(bool(_bps))

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
    def _show_page(self, idx, push=True):
        """切到某一页。push=True 时把当前页记进「来路」，← 按钮据此原路退回。

        少数几处是「替掉当前页」而不是「往前走」（比如讲完回错题复习），
        那些地方传 push=False，免得来路里留下一步会把自己弹回来的死循环。
        """
        prev = self._page
        # 断点页/补课页不进「来路」：那是课堂里被推着走的流程（掉队→补课→回课堂），
        # 不是学生自己翻的页。记进去的话，之后按返回会莫名其妙掉回补课页。
        if (push and not self._back_navigating and prev != idx
                and prev not in (BREAK, LESSON)):
            self._nav_history.append(prev)
            del self._nav_history[:-NAV_HISTORY_MAX]
        self._page = idx
        for i in range(self.stack.count()):     # 非当前页不参与尺寸计算
            pol = QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored
            self.stack.widget(i).setSizePolicy(pol, pol)
        self.stack.setCurrentIndex(idx)

        mini = idx == MINI
        self.header.setVisible(not mini)
        self.back_btn.setVisible(idx in (BREAK, LESSON, REVIEW, PRACTICE, DETAIL, MINDMAP,
                                         COURSES, RECALL, PROFILE, ASK, LEARNED, WEEKLY))
        # ← 按钮写哪儿：页面自己记着来路时听它的，否则看这一页是怎么进来的
        back_label = ""
        if idx == PRACTICE and self._prac_back_label:
            back_label = self._prac_back_label
        elif idx == DETAIL and self._detail_back_label:
            back_label = self._detail_back_label
        else:
            target = self._back_target()
            if target is not None:
                back_label = BACK_LABEL.get(target, "")
        if idx not in (BREAK, LESSON, REVIEW, PRACTICE, DETAIL, MINDMAP,
                       COURSES, RECALL, PROFILE, ASK, LEARNED, WEEKLY):
            back_label = ""                      # 这条没有 ← 按钮，随便写什么都没人看见
        self.back_btn.setText(back_label or tr("← 回到课堂", "← Back to class"))

        # 上课期间这条路锁死：不给回首页、不给进资料页。中途溜去别处等于悄悄丢下
        # 这节课没收尾——回响和错题都不会存。想离开课堂只有「下课」这一条路。
        # 断点页/补课页仍可进（那是课堂流程的一部分），折叠（fold_btn）也不受影响。
        in_class = self._in_class()
        self.home_btn.setVisible(idx == ECHO or (idx == LISTEN and not in_class))
        self.avatar_view.setVisible(not in_class)
        self.end_btn.setVisible(idx == LISTEN)
        # 折叠按钮哪一页都能点（折叠页自己除外）：学生想把这个面板收起来、只留一条
        # 小条盯着，这个诉求在任何一页都成立。折叠后的尺寸各页一致（都是 MINI）。
        self.fold_btn.setVisible(idx != MINI)
        self._sync_mini()
        m = Spacing.MD if mini else Spacing.LG
        self.layout().setContentsMargins(SHADOW + m, SHADOW + (Spacing.SM if mini else Spacing.MD),
                                         SHADOW + m, SHADOW + (Spacing.SM if mini else Spacing.LG))
        self._sync_status()
        self._fit()

    def _in_class(self) -> bool:
        """这堂课还开着没有。开着的时候页面导航锁死，只有「下课」能出去。

        __init__ 里 _show_home() 比 self.echo 还早，所以这里必须容错。
        """
        engine = getattr(getattr(self, "echo", None), "engine", None)
        return bool(getattr(engine, "active", False))

    def _sync_status(self):
        """状态栏跟着引擎真实状态走。

        原来标签初始就是「正在听课」，可应用启动停在主页、根本没开课，
        翻历史课的回顾时也一直挂着「正在听课」—— 看着像在监听，实际什么都没跑。
        """
        if self._in_class():
            return                      # 在上课：交给引擎的状态事件去更新
        self.status_lbl.setText(tr("已下课", "Class ended") if getattr(self, "_had_lesson", False)
                                else tr("还没开始上课", "Lesson not started"))
        self.status_lbl.setToolTip("")
        self.status_dot.setVisible(False)
        self.status_dots.stop()

    def _fit(self):
        """按当前页内容算窗口大小。内容变高只往下长，窗口位置钉住不动（详见下面那段）。"""
        def do():
            idx = self.stack.currentIndex()
            pl = self.stack.currentWidget().layout()
            # 量之前先把 stack 的固定高度松开。它会反过来把页面的高度撑大：
            # 「页面高度 → stack 高度 → 页面高度」互相顶住，一旦某次量高了，
            # 之后就永远是那个高个子 —— 抽问卡收起来、换个短页面都缩不回去。
            self.stack.setFixedHeight(0)
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
            # 知识地图 / 已学内容这类页面禁止上下滑动：滚轮要留给画布缩放，别跟滚动打架。
            # 它们自带「画布自适应 + 平移缩放」，内容不靠滚动看。
            no_scroll = idx in (MINDMAP, LEARNED)
            # 只有内容比屏幕还高时才允许滚动（此时滚动条只有 6px，并多留出这点宽度）
            self.body_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff if (fits or no_scroll) else Qt.ScrollBarAsNeeded)
            if not fits and not no_scroll:
                w += 8
            body_h = min(h + 4, limit)
            self.body_scroll.setFixedHeight(body_h)
            h = body_h + header_h
            W, H = w + m.left() + m.right(), h + m.top() + m.bottom()

            old = self.geometry()
            scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            if self.isVisible():
                # 内容变高时**只往下长，位置钉住不动**。
                # 原来按「窗口中心不动」缩放：卡片一多，窗口同时往上、往左撑开，
                # 看着像窗口自己在飘（用户原话「像会活的一样往左移」）；贴到屏幕
                # 右边时那套逻辑还会切成「固定右边、往左长」，越量越往左。
                # 学生盯着的是内容，窗口位置不该跟着内容跳。
                x = max(scr.left() - SHADOW, min(old.x(), scr.right() + SHADOW - W))
                # 往下放不下才整体上移，刚好放下为止；顶到屏幕上边就不再动
                y = max(scr.top() - SHADOW, min(old.y(), scr.bottom() + SHADOW - H))
                # 用 setGeometry 原子地设置位置+大小，避免 resize 先向右下长再 move 的闪烁/边界问题
                self.setMinimumSize(W, H)
                self.setGeometry(x, y, W, H)
            else:
                self.setMinimumSize(W, H)
                self.resize(W, H)
        def apply():
            # _fit 一次会改两回尺寸（现在一次、等换行文本落定再一次），中间那些帧
            # 每张大小都不一样 —— 用户看到的就是「窗口在闪、而且每次大小不同」。
            # 关掉重画把这一串并成最后那一帧。
            self.setUpdatesEnabled(False)
            try:
                do()
            finally:
                self.setUpdatesEnabled(True)

        apply()
        QTimer.singleShot(0, apply)   # 换行文本需要一轮事件循环后才能算准高度
        self.update()

    def _back_to_listen(self):
        self._show_page(LISTEN)

    def _back_target(self):
        """按「来路」算该退回哪一页；没有来路返回 None。

        倒着找第一个不等于当前页的记录：A → B → A 这样绕一圈之后，栈顶会压着
        一条 A（=当前页），直接取栈顶等于原地踏步。← 按钮的文案和 _back 的实际
        退法都得按同一条规则算，不然会出现「写着退回回顾、按下去却回主页」。
        """
        for prev in reversed(self._nav_history):
            if prev != self._page:
                return prev
        return None

    def _back(self):
        """← 按钮：按原路退回你进来的那一页。

        以前是「除了练习/回顾，其余一律回主页」—— 从课程管理 → 看回顾 → 知识地图
        一路点进来，按返回却被弹回主页，得从头再点一遍。现在统一走「来路」，
        按钮上写什么也跟着来路走（见 BACK_LABEL）。

        三条路仍然走自己的回调，因为它们除了翻页还有额外动作：
          · 练习页 → 退回地图时要重画（刚点过「我会了」，节点状态变了）
          · 回顾页 → 退回时要带上当初从哪儿进来的
          · 讲给 Echo 听 → 退回错题复习时要重算进度
        """
        if self._page == PRACTICE and self._prac_back:
            back, self._prac_back = self._prac_back, None
            self._prac_back_label = ""
            self._run_back(back)
            return
        if self._page == DETAIL and self._detail_back:
            back, self._detail_back = self._detail_back, None
            self._detail_back_label = ""
            self._run_back(back)
            return
        if self._page == RECALL:
            self._show_review(push=False)   # 讲完回错题复习，进度一眼能看见
            return
        if self._page in (BREAK, LESSON):
            self._show_page(LISTEN, push=False)   # 断点/补课在课堂流程里，退回课堂
            return
        while self._nav_history:            # 原路退回
            prev = self._nav_history.pop()
            if prev != self._page:
                self._show_page(prev, push=False)
                return
        # 没有来路（比如直接跳进来的）：课堂流程内的回课堂，其余回主页
        if self._page in (BREAK, LESSON, ASK, PROFILE):
            self._show_page(LISTEN, push=False)
        else:
            self._show_home()

    def _run_back(self, back):
        """跑一个「返回」回调（练习页要重画地图、回顾页要带来源）。

        回调内部自己会翻页，那些翻页属于往回走，不该再记进来路 ——
        否则「课程管理 → 回顾 → 点返回」会把回顾又记一遍，
        下一步返回就被弹回回顾页，退不出去。
        """
        self._back_navigating = True
        try:
            back()
        finally:
            self._back_navigating = False

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
        # 开课了，把页面装饰重刷一遍：`active` 是刚刚才变 True 的，
        # _reset_ui 里那次 _show_page 跑在它变之前，那时候还锁不上。
        self._show_page(self._page, push=False)

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
        self._nav_history.clear()       # 新的一节课，上一节的来路作废
        # 上一节没答完的抽查不能留到新的一节：后端 reset() 已经清掉了那道题，
        # 但卡片是前端自己画着的，不清就会让学生对着上节课的题目发呆。
        if hasattr(self, "checkin_card"):
            self.checkin_card.dismiss()
        self._show_page(LISTEN, push=False)

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
        _bps = getattr(report, "breakpoints", []) or []
        _quiz = getattr(report, "quiz", {}) or {}
        _skills = getattr(report, "skills", []) or []
        self.overview_card.setVisible(self._fill_overview(self.overview_lay, {
            "bp_count": len(_bps),
            "bp_total": int(sum(b.get("duration") or 0 for b in _bps)),
            "bp_max": int(max((b.get("duration") or 0 for b in _bps), default=0)),
            "quiz_total": _quiz.get("total", 0),
            "quiz_correct": _quiz.get("correct", 0),
            "ok": sum(1 for s in _skills if getattr(s, "status", "ok") == "ok"),
            "total": len(_skills),
        }))
        self._fill_breakpoints(self.bp_lay, _bps)
        self.bp_card.setVisible(bool(_bps))
        self.review_card.setVisible(self.review_card.set_chain(report.review_chain, report.suggestion))
        cnt["review"] = cnt["unsure"] + cnt["lost"]
        self._save_review()
        self._save_lesson(report)
        self._cat("ok" if not cnt["review"] else "idle")
        self._fit()
        self._maybe_refresh_persona()      # 这节课上完了，画像可能攒够该重算

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
        """把这节课存进历史，主页「课程管理」里能看到。没起名时 store 会用开课时间命名。

        **离线/兜底跑出来的课不存**：那条路（engine 的 mock）每次都产出同一套
        示例知识点，存进去就变成一节「真上过的课」，混在历史里、也污染统计和画像
        （用户就攒了 50 节内容一模一样的假课）。它什么都没真听到，不该算一节课。
        """
        if getattr(report, "from_mock", False):
            log.info("这节课是离线/兜底数据，不写进课程历史")
            return
        try:
            title = (getattr(self.echo, "title", "") or "").strip()
            store.save_lesson(title, report.skills, report.review_chain, report.suggestion,
                              summary=getattr(report, "summary", ""),
                              highlights=getattr(report, "highlights", []),
                              duration=getattr(report, "duration", 0.0),
                              line_count=getattr(report, "line_count", 0),
                              char_count=getattr(report, "char_count", 0),
                              graph=getattr(report, "graph", None),
                              breakpoints=getattr(report, "breakpoints", []),
                              quiz=getattr(report, "quiz", {}))
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
