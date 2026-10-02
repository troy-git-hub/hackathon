"""
Echo - 挂边小球点开的小窗：声纹 + 文字追问（聊天）

桌宠收起成侧边加速球后，单击小球弹出这个小窗：
  · 顶部一条声纹，实时反映老师声音大小
  · 下面是聊天区：输入问题，Echo 带上课堂上下文用 DeepSeek 流式回答
"""
import math
import time

from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from echo.theme import Colors, Radius, Spacing, font
from echo.components.study import CatAvatar
from echo.backend.vision import LessonAsk


class _Waveform(QWidget):
    """一条横向声纹：柱子高度随音频响度起伏，中间高两边低。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._level = 0.0
        self._env = 0.0
        self._phase = 0.0
        self._bars = [0.05] * 14
        self._timer = QTimer(self, interval=33, timeout=self._tick)
        self._timer.start()

    def set_level(self, level):
        self._level = max(0.0, min(1.0, float(level)))

    def _tick(self):
        if self._level > self._env:
            self._env += (self._level - self._env) * 0.6
        else:
            self._env += (self._level - self._env) * 0.18
        self._phase += 0.5
        n = len(self._bars)
        for i in range(n):
            x = i / (n - 1)
            w = 1.0 - abs(x - 0.5) * 2.0
            v = self._env * (0.4 + 0.6 * w) * (0.85 + 0.15 * math.sin(self._phase + x * 5.0))
            self._bars[i] = max(0.05, min(1.0, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self._bars)
        gap = 3
        bw = (self.width() - gap * (n - 1)) / n
        for i in range(n):
            h = (self.height() - 6) * self._bars[i]
            x = i * (bw + gap)
            c = QColor(Colors.ACCENT)
            c.setAlpha(int(90 + 140 * (1.0 - abs(i / (n - 1) - 0.5) * 2.0)))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, (self.height() - h) / 2, bw, max(3.0, h)), bw / 2, bw / 2)
        p.end()


class DockChat(QWidget):
    """挂边小球点开的小窗。engine 可为 None（无课堂上下文，只提示不能回答）。"""

    W, H = 260, 360
    _delta = pyqtSignal(str)
    _done = pyqtSignal(str)
    _error = pyqtSignal(str)
    left = pyqtSignal()          # 鼠标移出小窗（让桌宠判断要不要收起）

    def __init__(self, engine=None, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.engine = engine
        self._ask = LessonAsk(engine) if engine is not None else None
        self._stream_lbl = None

        self._delta.connect(self._on_delta)
        self._done.connect(self._on_done)
        self._error.connect(self._on_error)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        root = QFrame()
        root.setObjectName("DockChat")
        root.setStyleSheet(
            f"QFrame#DockChat {{ background: {Colors.WINDOW_BG}; border: 1px solid {Colors.BORDER};"
            f"border-radius: {Radius.LG}px; }}")
        outer.addWidget(root)
        self.setFixedSize(self.W, self.H)

        lay = QVBoxLayout(root)
        lay.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.MD)
        lay.setSpacing(6)

        # 头部：猫头 + 标题 + 关闭
        head = QHBoxLayout()
        self.cat = CatAvatar(26, root)
        self.cat.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        head.addWidget(self.cat)
        head.addWidget(QLabel("Echo"))
        head.addStretch(1)
        close = QPushButton("×")
        close.setObjectName("IconBtn")
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("收起")
        close.clicked.connect(self.hide)
        head.addWidget(close)
        lay.addLayout(head)

        # 声纹
        self.wave = _Waveform(root)
        lay.addWidget(self.wave)

        # 聊天区
        self.scroll = QScrollArea(root)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.msgs = QWidget()
        self.msgs.setStyleSheet("background: transparent;")
        self.msgs_lay = QVBoxLayout(self.msgs)
        self.msgs_lay.setContentsMargins(0, 0, 0, 0)
        self.msgs_lay.setSpacing(6)
        self.scroll.setWidget(self.msgs)
        lay.addWidget(self.scroll, 1)

        # 输入行
        row = QHBoxLayout()
        self.input = QLineEdit(root)
        self.input.setPlaceholderText("问一下这节课的内容…")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {Colors.SURFACE}; color: {Colors.TEXT_PRIMARY};"
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; padding: 7px 10px;"
            "font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.btn_send = QPushButton("发送")
        self.btn_send.setObjectName("Accent")
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        lay.addLayout(row)

        self._add_msg("有不懂的就问我，我给你讲讲～", False)

    # ================= 对外 =================
    def set_level(self, level):
        self.wave.set_level(level)

    def set_emotion(self, emotion):
        self.cat.set_emotion(emotion)

    def show_near(self, pet, side=None):
        """贴着挂边小球弹出来：球在左就弹右边，在右就弹左边。side 不给就用 pet.dock_side。"""
        side = side or getattr(pet, "dock_side", "")
        g = QApplication.primaryScreen().availableGeometry()
        if side == "left":
            x = pet.x() + pet.width() + 8
        else:
            x = pet.x() - self.width() - 8
        y = max(g.top(), min(pet.y(), g.bottom() - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()
        self.input.setFocus()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.left.emit()

    # ================= 聊天 =================
    def _add_msg(self, text, mine):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lb.setMaximumWidth(196)
        bg = Colors.ACCENT if mine else Colors.SURFACE
        fg = Colors.ON_ACCENT if mine else Colors.TEXT_PRIMARY
        lb.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 10px; padding: 7px 10px;"
            f"font-size: 13px; border: 1px solid {Colors.BORDER};")
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(0)
        if mine:
            wrap.addStretch(1)
            wrap.addWidget(lb)
        else:
            wrap.addWidget(lb)
            wrap.addStretch(1)
        self.msgs_lay.addLayout(wrap)
        return lb

    def _send(self):
        text = self.input.text().strip()
        if not text or not self.btn_send.isEnabled():
            return
        self.input.clear()
        if self._ask is None:
            self._add_msg("还没连上课堂（离线 / 未配置 key），暂时回答不了", False)
            return
        self._add_msg(text, True)
        lb = self._add_msg("", False)
        self._stream_lbl = lb
        self.btn_send.setEnabled(False)
        self._ask.ask(text, self._delta.emit, self._done.emit, self._error.emit)

    def _on_delta(self, d):
        if self._stream_lbl is not None:
            self._stream_lbl.setText(self._stream_lbl.text() + d)
            self._scroll_bottom()

    def _on_done(self, full):
        if self._stream_lbl is not None and not self._stream_lbl.text():
            self._stream_lbl.setText(full)
        self._stream_lbl = None
        self.btn_send.setEnabled(True)
        self._scroll_bottom()

    def _on_error(self, m):
        if self._stream_lbl is not None:
            self._stream_lbl.setText(f"⚠ {m}")
            self._stream_lbl.setStyleSheet(
                f"color: {Colors.DANGER}; background: transparent; font-size: 12px;")
        self._stream_lbl = None
        self.btn_send.setEnabled(True)

    def _scroll_bottom(self):
        sb = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))
