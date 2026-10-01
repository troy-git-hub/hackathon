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
    """桌宠本体（点击发射 clicked 信号）"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 130)
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

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 + 6

        # 身体：圆润胶囊形，淡蓝渐变
        body = QPainterPath()
        body.addRoundedRect(QRectF(cx - 42, cy - 48, 84, 92), 42, 42)

        grad = QLinearGradient(cx - 42, cy - 48, cx + 42, cy + 44)
        if self._hover:
            grad.setColorAt(0, QColor("#B8E0FF"))
            grad.setColorAt(1, QColor("#8FD0F5"))
        else:
            grad.setColorAt(0, QColor("#A8D8FF"))
            grad.setColorAt(1, QColor("#7BC8F6"))
        p.fillPath(body, QBrush(grad))

        # 身体高光（左上）
        hl = QPainterPath()
        hl.addEllipse(QPointF(cx - 18, cy - 22), 16, 22)
        p.fillPath(hl, QBrush(QColor(255, 255, 255, 90)))

        # 腮红
        p.setBrush(QBrush(QColor("#FFB3C6")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx - 24, cy + 8), 7, 5)
        p.drawEllipse(QPointF(cx + 24, cy + 8), 7, 5)

        # 眼睛（白底 + 黑瞳 + 高光）
        eye_y = cy - 8
        for ex in (cx - 14, cx + 14):
            p.setBrush(QBrush(QColor("#FFFFFF")))
            p.drawEllipse(QPointF(ex, eye_y), 9, 11)
            p.setBrush(QBrush(QColor("#2D2D2D")))
            p.drawEllipse(QPointF(ex + 1, eye_y + 1), 5, 7)
            p.setBrush(QBrush(QColor("#FFFFFF")))
            p.drawEllipse(QPointF(ex - 1, eye_y - 2), 2, 2)

        # 微笑嘴
        p.setPen(QPen(QColor("#2D2D2D"), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        mouth = QPainterPath()
        mouth.moveTo(cx - 8, cy + 14)
        mouth.quadTo(cx, cy + 22, cx + 8, cy + 14)
        p.drawPath(mouth)

        # 头顶小天线/呆毛
        p.setPen(QPen(QColor("#7BC8F6"), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx, cy - 48), QPointF(cx, cy - 60))
        p.setBrush(QBrush(QColor("#FFD166")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy - 63), 4, 4)

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
