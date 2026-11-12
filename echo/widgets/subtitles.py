"""Local ASR captions in a compact, movable, always-on-top lesson window."""
from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication
from echo.theme import Colors


class SubtitleWindow(QWidget):
    def __init__(self, engine, on_close):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.engine, self.session, self.on_close = engine, engine.session, on_close
        self.drag = None
        self.point_size = QSettings("Echo", "Echo").value("subtitle_font_size", 19, type=int)
        self.setWindowTitle("Echo · 实时字幕")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumWidth(360)
        self.resize(680, 142)
        self.setStyleSheet(f"QWidget{{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};}}"
                           f"QPushButton{{border:0;background:transparent;padding:3px 9px;color:{Colors.TEXT_SECONDARY};}}")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 9, 18, 15)
        row = QHBoxLayout()
        self.state = QLabel("Echo 字幕 · 本地转写，可能存在延迟或识别误差")
        self.state.setStyleSheet(f"font-size:11px;color:{Colors.TEXT_SECONDARY}")
        row.addWidget(self.state, 1)
        for title, callback in (("A−", lambda: self.change_size(-2)), ("A＋", lambda: self.change_size(2)), ("×", self.close)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        root.addLayout(row)
        self.caption = QLabel("等待老师开讲…")
        self.caption.setTextFormat(Qt.PlainText)
        self.caption.setWordWrap(True)
        self.caption.setAlignment(Qt.AlignCenter)
        root.addWidget(self.caption)
        self.change_size(0)
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.setFixedWidth(max(360, min(680, area.width() - 40)))
            self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 42)
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self.check_lesson)
        self.timer.start()

    def change_size(self, delta):
        self.point_size = min(29, max(15, self.point_size + delta))
        QSettings("Echo", "Echo").setValue("subtitle_font_size", self.point_size)
        self.caption.setStyleSheet(f"font-size:{self.point_size}px;font-weight:600;background:transparent;")
        self.adjustSize()

    def update_caption(self, tc, text):
        if not self.check_lesson():
            return
        self.caption.setText(text[-180:])
        self.caption.setToolTip(text)
        self.state.setText(f"Echo 字幕 · {tc} · 本地转写")
        self.adjustSize()

    def check_lesson(self):
        active = self.engine.active and self.engine.session == self.session
        if not active:
            self.hide()
        return active

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def closeEvent(self, event):
        self.timer.stop()
        self.on_close()
        super().closeEvent(event)
