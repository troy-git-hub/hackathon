"""
Echo - 可爱桌宠组件
用 QPainter 画一个圆润的小精灵：淡蓝身体 + 大眼睛 + 腮红 + 微笑。
点击触发展开。
"""
import math
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (QPainter, QPainterPath, QColor, QBrush, QPen,
                         QRadialGradient, QLinearGradient, QFont)


class PetWidget(QWidget):
    """桌宠本体：Q 版橘猫（点击发射 clicked 信号）"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 160)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self.width() / 2
        # 头部圆心
        hx, hy = cx, 70
        hr = 46  # 头半径

        # ---- 耳朵（三角形，内耳粉色）----
        ear_color = QColor("#FFB347") if not self._hover else QColor("#FFC069")
        inner_ear = QColor("#FF9AA2")
        for side in (-1, 1):
            # 外耳
            ear = QPainterPath()
            ear.moveTo(hx + side * 18, hy - 30)
            ear.lineTo(hx + side * 44, hy - 52)
            ear.lineTo(hx + side * 38, hy - 14)
            ear.closeSubpath()
            p.fillPath(ear, QBrush(ear_color))
            # 内耳
            inner = QPainterPath()
            inner.moveTo(hx + side * 22, hy - 30)
            inner.lineTo(hx + side * 38, hy - 46)
            inner.lineTo(hx + side * 34, hy - 18)
            inner.closeSubpath()
            p.fillPath(inner, QBrush(inner_ear))

        # ---- 脑袋（橘色渐变圆）----
        head = QPainterPath()
        head.addEllipse(QPointF(hx, hy), hr, hr)
        hgrad = QRadialGradient(hx - 12, hy - 16, 60)
        if self._hover:
            hgrad.setColorAt(0, QColor("#FFD9A0"))
            hgrad.setColorAt(1, QColor("#FFA94D"))
        else:
            hgrad.setColorAt(0, QColor("#FFCE85"))
            hgrad.setColorAt(1, QColor("#F59E42"))
        p.fillPath(head, QBrush(hgrad))

        # ---- 头顶花纹（橘猫虎斑）----
        p.setPen(QPen(QColor("#E08A2E"), 3, Qt.SolidLine, Qt.RoundCap))
        for dx in (-10, 0, 10):
            p.drawLine(QPointF(hx + dx, hy - 40), QPointF(hx + dx, hy - 30))

        # ---- 脸颊腮红 ----
        p.setBrush(QBrush(QColor("#FFB3C6")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(hx - 28, hy + 12), 9, 6)
        p.drawEllipse(QPointF(hx + 28, hy + 12), 9, 6)

        # ---- 眼睛（大圆眼 + 高光）----
        eye_y = hy - 4
        for ex in (hx - 16, hx + 16):
            p.setBrush(QBrush(QColor("#FFFFFF")))
            p.drawEllipse(QPointF(ex, eye_y), 11, 13)
            p.setBrush(QBrush(QColor("#3D2817")))
            p.drawEllipse(QPointF(ex, eye_y + 1), 7, 9)
            # 瞳孔高光
            p.setBrush(QBrush(QColor("#FFFFFF")))
            p.drawEllipse(QPointF(ex - 2, eye_y - 3), 3, 3)
            p.drawEllipse(QPointF(ex + 3, eye_y + 3), 1.5, 1.5)

        # ---- 小三角粉鼻子 ----
        nose = QPainterPath()
        nose.moveTo(hx, hy + 10)
        nose.lineTo(hx - 5, hy + 4)
        nose.lineTo(hx + 5, hy + 4)
        nose.closeSubpath()
        p.fillPath(nose, QBrush(QColor("#FF8FA3")))

        # ---- 嘴（W 形小猫嘴）----
        p.setPen(QPen(QColor("#3D2817"), 2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(hx, hy + 10), QPointF(hx, hy + 15))
        mouth_l = QPainterPath()
        mouth_l.moveTo(hx, hy + 15)
        mouth_l.quadTo(hx - 8, hy + 22, hx - 14, hy + 17)
        p.drawPath(mouth_l)
        mouth_r = QPainterPath()
        mouth_r.moveTo(hx, hy + 15)
        mouth_r.quadTo(hx + 8, hy + 22, hx + 14, hy + 17)
        p.drawPath(mouth_r)

        # ---- 胡须 ----
        p.setPen(QPen(QColor("#8B6F47"), 1.5, Qt.SolidLine, Qt.RoundCap))
        for side in (-1, 1):
            base_x = hx + side * 16
            p.drawLine(QPointF(base_x, hy + 12), QPointF(base_x + side * 22, hy + 8))
            p.drawLine(QPointF(base_x, hy + 16), QPointF(base_x + side * 24, hy + 16))
            p.drawLine(QPointF(base_x, hy + 20), QPointF(base_x + side * 22, hy + 24))

        # ---- 小身体（下半身椭圆）----
        body = QPainterPath()
        body.addEllipse(QPointF(hx, hy + 64), 30, 22)
        p.fillPath(body, QBrush(hgrad))

        # ---- 两只小爪子 ----
        p.setBrush(QBrush(QColor("#FFF0DB")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(hx - 18, hy + 70), 9, 7)
        p.drawEllipse(QPointF(hx + 18, hy + 70), 9, 7)

        p.end()


class BubbleLabel(QLabel):
    """圆角对话气泡"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(QFont("Segoe UI Variable", 11, QFont.DemiBold))
        self.setStyleSheet("""
            QLabel {
                background-color: #FFFFFF;
                color: #1A1A1A;
                border-radius: 14px;
                padding: 8px 14px;
                border: 1px solid #E5E5E5;
            }
        """)
        self.adjustSize()
