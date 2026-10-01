"""
Echo - Concept Timeline 组件
竖排时间轴，展示过去几个 concept，并标记断点。
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QSizePolicy)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from echo.theme import Colors, Radius, font, Spacing
from echo.mock_data import Concept


STATUS_ICON = {"ok": "✓", "warn": "⚠", "lost": "✕", "now": "●"}
STATUS_COLOR = {
    "ok": Colors.NODE_OK,
    "warn": Colors.NODE_WARN,
    "lost": Colors.NODE_LOST,
    "now": Colors.NODE_NOW,
}


class TimelineNode(QWidget):
    """时间轴上的一个节点"""

    def __init__(self, concept: Concept, is_breakpoint: bool = False,
                 is_now: bool = False, note: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SurfaceCard")
        self.setStyleSheet(f"""
            QWidget#SurfaceCard {{
                background-color: {Colors.SURFACE};
                border-radius: {Radius.MD}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)
        if is_breakpoint:
            self.setStyleSheet(f"""
                QWidget#SurfaceCard {{
                    background-color: {Colors.WARNING_BG};
                    border-radius: {Radius.MD}px;
                    border: 1px solid {Colors.WARNING};
                }}
            """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.SM)

        # 状态点
        color = STATUS_COLOR.get(concept.status, Colors.TEXT_SECONDARY)
        if is_now:
            color = Colors.NODE_NOW
        if is_breakpoint:
            color = Colors.NODE_WARN

        dot = QLabel(STATUS_ICON.get(concept.status, "●"))
        dot.setFixedWidth(20)
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 14px;")
        layout.addWidget(dot)

        # 中间：时间码 + 概念 + 备注
        mid = QVBoxLayout()
        mid.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(Spacing.SM)
        tc = QLabel(concept.timecode)
        tc.setObjectName("Timecode")
        top.addWidget(tc)

        name = QLabel(concept.topic)
        name.setFont(font(12, QFont.DemiBold))
        top.addWidget(name)
        top.addStretch()

        if is_now:
            now_tag = QLabel("← 现在")
            now_tag.setStyleSheet(f"color: {Colors.PRIMARY}; font-weight: 600;")
            top.addWidget(now_tag)

        mid.addLayout(top)

        if note:
            note_lbl = QLabel(note)
            note_lbl.setObjectName("BodySecondary")
            note_lbl.setWordWrap(True)
            mid.addWidget(note_lbl)

        layout.addLayout(mid, 1)


class ConceptTimeline(QWidget):
    """完整的 Concept Timeline"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(Spacing.SM)

    def set_concepts(self, concepts, breakpoint_tc=None):
        # 清空
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, c in enumerate(concepts):
            is_now = (i == len(concepts) - 1)
            is_bp = (breakpoint_tc and c.timecode == breakpoint_tc)
            note = ""
            if is_bp:
                note = "老师快速跳过了推导"
            node = TimelineNode(c, is_breakpoint=is_bp, is_now=is_now, note=note)
            self._layout.addWidget(node)

            # 节点之间的竖线
            if i < len(concepts) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.VLine)
                line.setStyleSheet(f"color: {Colors.BORDER};")
                line.setFixedHeight(12)
                self._layout.addWidget(line, 0, Qt.AlignHCenter)

        self._layout.addStretch()
