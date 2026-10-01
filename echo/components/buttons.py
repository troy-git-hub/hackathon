"""
Echo - WinUI 风格按钮组件
"""
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCursor, QFont

from echo.theme import Colors, Radius, font


class StateButton(QPushButton):
    """三个状态按钮：✓跟上了 / ?有点懵 / !我掉队了"""

    def __init__(self, icon: str, text: str, kind: str = "default", parent=None):
        super().__init__(parent)
        self.setText(f" {icon}  {text}")
        self.kind = kind
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(32)
        self._style_normal()
        self.setFont(font(12, QFont.Medium))

    def _style_normal(self):
        # (前景色, 悬停底色, 悬停边框)
        base = {
            "default": (Colors.TEXT_PRIMARY, Colors.SURFACE_HOVER, Colors.BORDER_STRONG),
            "ok":      (Colors.SUCCESS, Colors.SUCCESS_BG, Colors.SUCCESS_BORDER),
            "warn":    (Colors.WARNING, Colors.WARNING_SOFT, Colors.WARNING_BORDER),
            "lost":    (Colors.DANGER, Colors.DANGER_BG, Colors.DANGER_BORDER),
        }
        fg, hover_bg, hover_border = base.get(self.kind, base["default"])
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
                color: {fg};
                padding: 6px 12px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border-color: {hover_border};
            }}
            QPushButton:pressed {{
                background-color: {hover_bg};
                border-color: {fg};
            }}
        """)


class PrimaryButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Primary")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(32)
        self.setFont(font(12, QFont.Medium))


class GhostButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Ghost")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(32)
