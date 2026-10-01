"""
Echo - 掌握度进度条（回响页用）
"""
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from echo.theme import Colors, font, Spacing
from echo.mock_data import EchoSkill


STATUS_TAG = {"ok": "✓", "warn": "?", "lost": "!"}
STATUS_BAR_OBJ = {"ok": "Ok", "warn": "Warn", "lost": "Lost"}
STATUS_TAG_COLOR = {"ok": Colors.SUCCESS, "warn": Colors.WARNING, "lost": Colors.DANGER}


class MasteryRow(QWidget):
    def __init__(self, skill: EchoSkill, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, Spacing.SM, 0, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        name = QLabel(skill.name)
        name.setFixedWidth(100)
        name.setFont(font(12, QFont.Medium))
        layout.addWidget(name)

        bar = QProgressBar()
        bar.setObjectName(STATUS_BAR_OBJ.get(skill.status, ""))
        bar.setRange(0, 100)
        bar.setValue(int(skill.mastery * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        layout.addWidget(bar, 1)

        pct = QLabel(f"{int(skill.mastery * 100)}%")
        pct.setObjectName("BodySecondary")
        pct.setFixedWidth(40)
        pct.setAlignment(Qt.AlignRight)
        layout.addWidget(pct)

        tag = QLabel(STATUS_TAG.get(skill.status, ""))
        tag.setFixedWidth(20)
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet(
            f"color: {STATUS_TAG_COLOR.get(skill.status, Colors.TEXT_SECONDARY)};"
            f"font-weight: 700;"
        )
        layout.addWidget(tag)


class MasteryList(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def set_skills(self, skills):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for s in skills:
            self._layout.addWidget(MasteryRow(s))
        self._layout.addStretch()
