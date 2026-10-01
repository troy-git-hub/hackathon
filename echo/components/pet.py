"""
Echo - 可爱桌宠组件
优先加载 assets/emojis/ 下的表情包 PNG，按情绪切换；
图片缺失时回退到 BongoCat 手绘猫。
点击触发展开。
"""
import os
import math
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer
from PyQt5.QtGui import (QPainter, QPainterPath, QColor, QBrush, QPen,
                         QRadialGradient, QLinearGradient, QFont, QPixmap)

from echo.theme import Colors

# 情绪 -> 表情包文件名（对应 split_emojis.py 切出的 8 张）
EMOTION_FILES = {
    "idle": "smug.png",
    "ok": "happy.png",
    "warn": "confused.png",
    "lost": "cry.png",
    "thinking": "key.png",
    "fixed": "happy.png",
}

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "emojis")


class PetWidget(QWidget):
    """桌宠本体：优先显示表情包，回退手绘 BongoCat"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(160, 160)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._tap_phase = 0.0
        self._tap_dir = 1
        self._emotion = "idle"

        # 预加载所有表情包
        self._pixmaps = {}
        for emo, fname in EMOTION_FILES.items():
            path = os.path.join(ASSETS_DIR, fname)
            if os.path.exists(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    self._pixmaps[emo] = pm

        # 敲击动画定时器（仅手绘模式用）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    def set_emotion(self, emotion: str):
        """切换情绪表情包。emotion: idle/ok/warn/lost/thinking/fixed"""
        if emotion in self._pixmaps:
            self._emotion = emotion
            self.update()

    @property
    def has_emoji(self):
        return bool(self._pixmaps)

    def _tick(self):
        self._tap_phase += 0.25 * self._tap_dir
        if self._tap_phase >= 1.0:
            self._tap_phase = 1.0
            self._tap_dir = -1
        elif self._tap_phase <= 0.0:
            self._tap_phase = 0.0
            self._tap_dir = 1
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    # 轻点 = 展开；按住拖动 = 移动整个窗口
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_global = e.globalPos()
            self._win_origin = self.window().pos()
            self._dragged = False

    def mouseMoveEvent(self, e):
        if getattr(self, "_press_global", None) is not None and e.buttons() & Qt.LeftButton:
            delta = e.globalPos() - self._press_global
            if delta.manhattanLength() > 4:
                self._dragged = True
            if self._dragged:
                self.window().move(self._win_origin + delta)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and getattr(self, "_press_global", None) is not None:
            if not self._dragged:
                self.clicked.emit()
            self._press_global = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # ---- 有表情包图片则直接绘制 ----
        pm = self._pixmaps.get(self._emotion)
        if pm is not None:
            # 等比缩放到控件大小，居中
            target_w = self.width()
            target_h = self.height()
            scaled = pm.scaled(target_w, target_h,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
            p.end()
            return

        # ---- 回退：手绘 BongoCat ----
        cx = self.width() / 2
        hx, hy = cx, 56
        hr = 40  # 头半径

        white = QColor("#FFFFFF")
        outline = QColor("#2D2D2D")
        pink = QColor("#FF9AA2")
        paw_pad = QColor("#FFB3C6")

        # ---- 耳朵（白色三角，内耳粉色）----
        for side in (-1, 1):
            ear = QPainterPath()
            ear.moveTo(hx + side * 16, hy - 26)
            ear.lineTo(hx + side * 38, hy - 46)
            ear.lineTo(hx + side * 32, hy - 12)
            ear.closeSubpath()
            p.fillPath(ear, QBrush(white))
            p.setPen(QPen(outline, 2))
            p.drawPath(ear)
            # 内耳
            inner = QPainterPath()
            inner.moveTo(hx + side * 20, hy - 26)
            inner.lineTo(hx + side * 33, hy - 40)
            inner.lineTo(hx + side * 30, hy - 16)
            inner.closeSubpath()
            p.fillPath(inner, QBrush(pink))

        # ---- 脑袋（白色圆 + 描边）----
        head = QPainterPath()
        head.addEllipse(QPointF(hx, hy), hr, hr)
        p.fillPath(head, QBrush(white))
        p.setPen(QPen(outline, 2.5))
        p.drawPath(head)

        # ---- 眼睛（两个黑圆点，BongoCat 经典呆萌眼）----
        p.setBrush(QBrush(outline))
        p.setPen(Qt.NoPen)
        for ex in (hx - 14, hx + 14):
            p.drawEllipse(QPointF(ex, hy - 2), 4.5, 5.5)
            # 眼睛高光
            p.setBrush(QBrush(QColor("#FFFFFF")))
            p.drawEllipse(QPointF(ex - 1, hy - 4), 1.5, 1.5)
            p.setBrush(QBrush(outline))

        # ---- 粉色小鼻子 ----
        nose = QPainterPath()
        nose.moveTo(hx, hy + 8)
        nose.lineTo(hx - 4.5, hy + 3)
        nose.lineTo(hx + 4.5, hy + 3)
        nose.closeSubpath()
        p.fillPath(nose, QBrush(pink))

        # ---- 微笑嘴 ----
        p.setPen(QPen(outline, 2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        mouth = QPainterPath()
        mouth.moveTo(hx - 7, hy + 12)
        mouth.quadTo(hx, hy + 18, hx + 7, hy + 12)
        p.drawPath(mouth)

        # ---- 胡须 ----
        p.setPen(QPen(outline, 1.5, Qt.SolidLine, Qt.RoundCap))
        for side in (-1, 1):
            bx = hx + side * 14
            p.drawLine(QPointF(bx, hy + 10), QPointF(bx + side * 20, hy + 6))
            p.drawLine(QPointF(bx, hy + 14), QPointF(bx + side * 22, hy + 14))

        # ---- 身体（白色椭圆，连接头部下方）----
        body_top = hy + hr - 6
        body = QPainterPath()
        body.addEllipse(QPointF(hx, body_top + 22), 34, 26)
        p.fillPath(body, QBrush(white))
        p.setPen(QPen(outline, 2.5))
        p.drawPath(body)

        # ---- 两只前爪（交替敲击，核心 BongoCat 动作）----
        base_y = body_top + 8
        # 左爪：phase 0 在上，phase 1 在下
        left_y = base_y + self._tap_phase * 14
        right_y = base_y + (1.0 - self._tap_phase) * 14

        for side, py in ((-1, left_y), (1, right_y)):
            px = hx + side * 22
            # 手臂（从身体到爪子的连线）
            p.setPen(QPen(outline, 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(hx + side * 12, body_top + 10), QPointF(px, py))
            # 爪子（椭圆）
            paw = QPainterPath()
            paw.addEllipse(QPointF(px, py), 11, 9)
            p.fillPath(paw, QBrush(white))
            p.drawPath(paw)
            # 肉垫
            p.setBrush(QBrush(paw_pad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(px, py + 1), 5, 4)
            # 爪尖小肉垫
            for dx in (-5, 0, 5):
                p.drawEllipse(QPointF(px + dx, py - 4), 2, 2)
            p.setBrush(Qt.NoBrush)

        p.end()


class BubbleLabel(QLabel):
    """圆角对话气泡"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {Colors.BUBBLE_BG};
                color: {Colors.TEXT_PRIMARY};
                border-radius: 14px;
                padding: 8px 14px;
                border: 1px solid {Colors.BUBBLE_BORDER};
                font-size: 13px;
                font-weight: 600;
            }}
        """)
        self.adjustSize()
