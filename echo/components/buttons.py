"""
Echo - WinUI 风格按钮组件
"""
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCursor

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
        base = {
            "default": (Colors.SURFACE, Colors.BORDER, Colors.TEXT_PRIMARY),
            "ok":      (Colors.SUCCESS_BG, "#A6E0A6", Colors.SUCCESS),
            "warn":    (Colors.WARNING_BG, "#F5D28A", Colors.WARNING),
            "lost":    (Colors.DANGER_BG, "#F3A8AD", Colors.DANGER),
        }
        bg, border, fg = base.get(self.kind, base["default"])
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {Radius.MD}px;
                color: {fg};
                padding: 6px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Colors.SURFACE_HOVER if self.kind == 'default' else bg};
                border-color: {Colors.BORDER_STRONG if self.kind == 'default' else border};
            }}
            QPushButton:pressed {{
                background-color: {Colors.SURFACE_PRESSED if self.kind == 'default' else bg};
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
