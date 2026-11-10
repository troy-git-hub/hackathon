"""Compact, keyboard-accessible matching question with visible connections."""
import textwrap
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor
from PyQt5.QtWidgets import QWidget, QGridLayout, QPushButton
from echo.theme import Colors


class MatchingAnswer(QWidget):
    def __init__(self, left, right, parent=None):
        super().__init__(parent)
        self.pairs = [-1] * len(left)
        self.selected = None
        self.left_buttons, self.right_buttons = [], []
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(40)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for row, (a, b) in enumerate(zip(left, right)):
            for column, text, buttons in ((0, f"{row + 1}. {a}", self.left_buttons),
                                           (1, f"{chr(65 + row)}. {b}", self.right_buttons)):
                button = QPushButton("\n".join(textwrap.wrap(text, width=12)))
                button.setMinimumHeight(38)
                button.setCursor(Qt.PointingHandCursor)
                button.setToolTip(text)
                grid.addWidget(button, row, column)
                buttons.append(button)
                if column == 0:
                    button.clicked.connect(lambda checked=False, i=row: self.select_left(i))
                else:
                    button.clicked.connect(lambda checked=False, i=row: self.select_right(i))
        self.refresh()

    def select_left(self, index):
        self.selected = index
        self.refresh()

    def select_right(self, index):
        if self.selected is None:
            return
        for i, value in enumerate(self.pairs):
            if value == index:
                self.pairs[i] = -1
        self.pairs[self.selected] = index
        self.selected = None
        self.refresh()

    def answers(self):
        return list(self.pairs)

    def refresh(self):
        for side, buttons in enumerate((self.left_buttons, self.right_buttons)):
            for i, button in enumerate(buttons):
                active = (i == self.selected or self.pairs[i] >= 0) if side == 0 else i in self.pairs
                button.setStyleSheet(
                    f"QPushButton {{text-align:left; padding:6px; font-size:12px; border-radius:7px;"
                    f"color:{Colors.TEXT_PRIMARY}; background:{Colors.ACCENT_SOFT if active else Colors.SURFACE};"
                    f"border:1px solid {Colors.ACCENT if active else Colors.BORDER};}}"
                    f"QPushButton:focus {{border:2px solid {Colors.ACCENT};}}")
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(Colors.ACCENT), 2))
        for i, j in enumerate(self.pairs):
            if j < 0:
                continue
            a, b = self.left_buttons[i].geometry(), self.right_buttons[j].geometry()
            painter.drawLine(QPointF(a.right() + 2, a.center().y()), QPointF(b.left() - 2, b.center().y()))
