"""Choice controls whose text wraps without forcing the containing window wider."""
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QLabel, QPushButton, QRadioButton, QVBoxLayout, QSizePolicy


class _WrappedText:
    def setup_text(self, text, radio=False):
        self._choice_text = str(text)
        self.setAccessibleName(self._choice_text)
        self.caption = QLabel(self._choice_text, self)
        self.caption.setTextFormat(Qt.PlainText)
        self.caption.setWordWrap(True)
        self.caption.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.caption.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.caption.setStyleSheet("background:transparent;border:none;padding:0;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28 if radio else 10, 8, 10, 8)
        layout.addWidget(self.caption)
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def text(self):
        return self._choice_text

    def heightForWidth(self, width):
        margins = self.layout().contentsMargins()
        return max(36, self.caption.heightForWidth(max(20, width - margins.left() - margins.right())) + margins.top() + margins.bottom())

    def sizeHint(self):
        return QSize(160, self.heightForWidth(160))

    def minimumSizeHint(self):
        return QSize(0, 36)


class WrappedOption(_WrappedText, QPushButton):
    def __init__(self, text, parent=None):
        super().__init__("", parent)
        self.setup_text(text)


class WrappedRadio(_WrappedText, QRadioButton):
    def __init__(self, text, parent=None):
        super().__init__("", parent)
        self.setup_text(text, radio=True)

    def hitButton(self, point):
        return self.rect().contains(point)
