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
STATUS_TAG_BG = {"ok": Colors.SUCCESS_BG, "warn": Colors.WARNING_SOFT, "lost": Colors.DANGER_BG}


class MasteryRow(QWidget):
    def __init__(self, skill: EchoSkill, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(Spacing.MD)

        # 名称：固定列宽，过长换行而不是截断
        name = QLabel(skill.name)
        name.setFixedWidth(128)
        name.setWordWrap(True)
        name.setToolTip(skill.name)
        name.setFont(font(13, QFont.DemiBold if skill.status == "lost" else QFont.Normal))
        layout.addWidget(name, 0, Qt.AlignVCenter)

        bar = QProgressBar()
        bar.setObjectName(STATUS_BAR_OBJ.get(skill.status, ""))
        bar.setRange(0, 100)
        bar.setValue(int(skill.mastery * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        layout.addWidget(bar, 1, Qt.AlignVCenter)

        pct = QLabel(f"{int(skill.mastery * 100)}%")
        pct.setObjectName("Timecode")
        pct.setFixedWidth(34)
        pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(pct)

        st = skill.status if skill.status in STATUS_TAG else "warn"
        tag = QLabel(STATUS_TAG[st])
        tag.setFixedSize(20, 20)
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet(
            f"color: {STATUS_TAG_COLOR[st]}; background: {STATUS_TAG_BG[st]};"
            f"border-radius: 10px; font-weight: 700; font-size: 11px;"
        )
        layout.addWidget(tag, 0, Qt.AlignVCenter)


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
        self.setVisible(bool(skills))
