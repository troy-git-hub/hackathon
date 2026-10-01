"""
Echo - Concept Timeline 组件
竖排时间轴，展示过去几个 concept，并标记断点。
左侧轨道（竖线 + 圆点）由每个节点自己绘制，保证上下严格对齐。
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush

from echo.theme import Colors, Radius, font, Spacing
from echo.mock_data import Concept


STATUS_COLOR = {
    "ok": Colors.NODE_OK,
    "warn": Colors.NODE_WARN,
    "lost": Colors.NODE_LOST,
    "now": Colors.NODE_NOW,
}
STATUS_GLYPH = {"ok": "✓", "warn": "!", "lost": "✕", "now": ""}

RAIL_X = 12          # 轨道中心 x
DOT_R = 8            # 圆点半径
CONTENT_LEFT = 32    # 文字起始 x


class TimelineNode(QWidget):
    """时间轴上的一个节点"""

    def __init__(self, concept: Concept, is_breakpoint=False, is_now=False,
                 note="", first=False, last=False, parent=None):
        super().__init__(parent)
        self.is_bp = is_breakpoint
        self.is_now = is_now
        self.first, self.last = first, last
        self.status = "now" if is_now else concept.status
        if is_breakpoint:
            self.status = "warn"
        self.color = QColor(STATUS_COLOR.get(self.status, Colors.TEXT_SECONDARY))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CONTENT_LEFT + 4, 7, 10, 7)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(Spacing.SM)
        tc = QLabel(concept.timecode)
        tc.setObjectName("Timecode")
        tc.setFixedWidth(40)
        top.addWidget(tc, 0, Qt.AlignTop)

        name = QLabel(concept.topic)
        name.setFont(font(13, QFont.DemiBold if (is_breakpoint or is_now) else QFont.Normal))
        name.setWordWrap(True)
        if not (is_breakpoint or is_now):
            name.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        top.addWidget(name, 1)

        if is_now:
            top.addWidget(self._tag("现在", Colors.PRIMARY, Colors.PRIMARY_LIGHT), 0, Qt.AlignTop)
        elif is_breakpoint:
            top.addWidget(self._tag("断点", Colors.WARNING, "#FFF4CE"), 0, Qt.AlignTop)
        layout.addLayout(top)

        if note:
            note_lbl = QLabel(note)
            note_lbl.setWordWrap(True)
            note_lbl.setStyleSheet(f"color: {Colors.WARNING}; font-size: 12px; margin-left: 48px;")
            layout.addWidget(note_lbl)

    @staticmethod
    def _tag(text, fg, bg):
        t = QLabel(text)
        t.setStyleSheet(f"color: {fg}; background: {bg}; border-radius: 9px;"
                        f"padding: 1px 8px; font-size: 11px; font-weight: 600;")
        return t

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        cy = 7 + 10   # 与第一行文字中线对齐

        # 断点行高亮背景
        if self.is_bp:
            p.setPen(QPen(QColor("#F7D58A"), 1))
            p.setBrush(QBrush(QColor("#FFF8E6")))
            p.drawRoundedRect(QRectF(CONTENT_LEFT - 4, 1, self.width() - CONTENT_LEFT + 3, h - 2),
                              Radius.MD, Radius.MD)

        # 轨道
        p.setPen(QPen(QColor(Colors.BORDER_STRONG), 2))
        if not self.first:
            p.drawLine(QPointF(RAIL_X, 0), QPointF(RAIL_X, cy - DOT_R))
        if not self.last:
            p.drawLine(QPointF(RAIL_X, cy + DOT_R), QPointF(RAIL_X, h))

        # 圆点
        if self.is_now:
            halo = QColor(self.color)
            halo.setAlphaF(0.18)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(RAIL_X, cy), DOT_R + 3, DOT_R + 3)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(QPointF(RAIL_X, cy), DOT_R, DOT_R)
        glyph = STATUS_GLYPH.get(self.status, "")
        if glyph:
            p.setPen(QColor("#FFFFFF"))
            f = font(10, QFont.Bold)
            p.setFont(f)
            p.drawText(QRectF(RAIL_X - DOT_R, cy - DOT_R, DOT_R * 2, DOT_R * 2),
                       Qt.AlignCenter, glyph)
        else:
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(RAIL_X, cy), 3, 3)
        p.end()


class ConceptTimeline(QWidget):
    """完整的 Concept Timeline"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def set_concepts(self, concepts, breakpoint_tc=None, note="老师快速跳过了推导"):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        n = len(concepts)
        for i, c in enumerate(concepts):
            is_now = (i == n - 1)
            is_bp = bool(breakpoint_tc and c.timecode == breakpoint_tc)
            node = TimelineNode(c, is_breakpoint=is_bp, is_now=is_now,
                                note=note if is_bp else "",
                                first=(i == 0), last=(i == n - 1))
            self._layout.addWidget(node)
