"""
Echo - 声纹球组件
- 不在听：7 个小圆点（横排）
- 开始听：6 条垂线随机变化高度（不超过球径），两端最短，中间最长
"""
import random
import math

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QRadialGradient

from echo.theme import Colors


class WaveOrb(QWidget):
    """声纹球：idle=7 点；listening=6 条垂线（两端最短、中间最长，随机抖动）

    size=None 时为自适应模式：直径取 min(width, height)，可在 mini 模式下垂直填满。
    """

    def __init__(self, size=72, parent=None):
        super().__init__(parent)
        self._fixed_size = size
        if size is not None:
            self.setFixedSize(size, size)
        else:
            # 自适应：垂直填满父容器，宽度跟随高度（在 resizeEvent 中调整）
            from PyQt5.QtWidgets import QSizePolicy
            self.setMinimumSize(4, 4)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self._last_h = -1
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._listening = False
        self._phase = 0.0
        self._bars = [0.0] * 6   # 6 条垂线高度 (0..1)
        # 垂线权重：两端最短、中间最长（正弦曲线）
        self._weights = [math.sin((i + 0.5) * math.pi / 6) for i in range(6)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def resizeEvent(self, e):
        """自适应模式下：宽度跟随高度，保持正方形。"""
        if self._fixed_size is None and self.height() != self._last_h:
            self._last_h = self.height()
            self.setFixedWidth(self.height())
        super().resizeEvent(e)

    def start(self):
        """开始听：声纹动画启动"""
        self._listening = True
        self._timer.start(80)
        self.update()

    def stop(self):
        """停止听：恢复 7 点静态"""
        self._listening = False
        self._timer.stop()
        self._bars = [0.0] * 6
        self.update()

    def _tick(self):
        self._phase += 0.18
        # 每条垂线在自身权重附近随机抖动
        for i in range(6):
            w = self._weights[i]
            # 在 [w*0.4, w*1.0] 范围内随机变化
            base = w * (0.55 + 0.45 * math.sin(self._phase + i * 0.9))
            jitter = random.uniform(-0.08, 0.08)
            self._bars[i] = max(0.08, min(1.0, base + jitter))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 直径取控件宽高较小值（自适应模式：宽=高=高度，固定模式：宽=高=size）
        size = min(self.width(), self.height())
        cx = self.width() / 2
        cy = self.height() / 2
        radius = size * 0.40
        diam = radius * 2

        # ---- 1. 球体（径向渐变 + 边框）----
        orb_rect = QRectF(cx - radius, cy - radius, diam, diam)
        grad = QRadialGradient(cx - radius * 0.3, cy - radius * 0.3, radius * 1.1)
        accent = QColor(Colors.ACCENT)
        grad.setColorAt(0.0, accent.lighter(130))
        grad.setColorAt(0.6, accent)
        grad.setColorAt(1.0, accent.darker(140))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(orb_rect)
        p.setPen(QPen(accent.darker(160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(orb_rect)
        # 裁切到球内（用 setClipRegion 等价的方式：手动限制绘制范围）
        p.save()
        clip_path = QPainterPath()
        clip_path.addEllipse(orb_rect)
        p.setClipPath(clip_path)

        if not self._listening:
            # ---- 2a. idle：7 个小圆点横排 ----
            n = 7
            dot_r = max(1.2, radius * 0.10)
            spacing = (radius * 1.6) / (n - 1)
            x0 = cx - spacing * (n - 1) / 2
            p.setPen(Qt.NoPen)
            for i in range(n):
                # 中心点稍亮、两端稍暗
                t = 1.0 - abs(i - (n - 1) / 2) / ((n - 1) / 2) * 0.4
                c = QColor(255, 255, 255, int(220 * t))
                p.setBrush(c)
                p.drawEllipse(QPointF(x0 + i * spacing, cy), dot_r, dot_r)
        else:
            # ---- 2b. listening：6 条垂线，两端最短、中间最长，随机抖动 ----
            n = 6
            bar_w = max(1.5, radius * 0.16)  # 垂线宽度
            spacing = (radius * 1.6) / (n - 1)
            x0 = cx - spacing * (n - 1) / 2
            max_h = diam * 0.78  # 不超过球径
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 230))
            for i in range(n):
                h = self._bars[i] * max_h
                r = QRectF(x0 + i * spacing - bar_w / 2, cy - h / 2, bar_w, h)
                p.drawRoundedRect(r, bar_w / 2, bar_w / 2)
        p.restore()
        p.end()
