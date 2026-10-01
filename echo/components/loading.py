"""
Echo - 加载状态组件
"""
from PyQt5.QtWidgets import QLabel, QFrame, QHBoxLayout, QWidget
from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QPainter, QColor

from echo.theme import Colors, Radius, Spacing


class PulseDots(QWidget):
    """三个依次跳动的小圆点"""

    def __init__(self, color=Colors.PRIMARY, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._phase = 0
        self.setFixedSize(30, 12)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start(160)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 1) % 6
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(3):
            c = QColor(self._color)
            c.setAlphaF(1.0 if i == self._phase % 3 else 0.3)
            p.setBrush(c)
            p.drawEllipse(QRectF(i * 10 + 1, 3, 6, 6))
        p.end()


class LoadingCard(QFrame):
    """带跳动圆点的加载提示卡片"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("LoadingCard")
        self.setStyleSheet(f"""
            QFrame#LoadingCard {{
                background-color: {Colors.PRIMARY_LIGHT};
                border: 1px solid #C7E0F4;
                border-radius: {Radius.MD}px;
            }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        lay.setSpacing(Spacing.SM)
        self.dots = PulseDots(Colors.PRIMARY)
        lay.addWidget(self.dots, 0, Qt.AlignVCenter)
        self.label = QLabel(text)
        self.label.setStyleSheet(f"color: {Colors.PRIMARY}; font-size: 13px; font-weight: 600;"
                                 "background: transparent; border: none;")
        self.label.setWordWrap(True)
        lay.addWidget(self.label, 1)

    def setText(self, text):
        self.label.setText(text)

    def start(self, text=None):
        if text:
            self.label.setText(text)
        self.dots.start()
        self.show()

    def stop(self):
        self.dots.stop()
        self.hide()
