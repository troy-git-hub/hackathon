"""User-selected lesson region and moment-aligned screenshots; no whole-desktop polling."""
from dataclasses import dataclass

from PyQt5.QtCore import Qt, QRect, QTimer, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QCursor, QPainter, QColor, QPen
from PyQt5.QtWidgets import QWidget, QApplication, QLabel, QPushButton, QHBoxLayout, QFrame
from echo.theme import Colors

_selectors = []


@dataclass
class LessonRegion:
    screen_name: str
    screen_geometry: QRect
    rect: QRect  # Logical coordinates relative to the selected screen.


def echo_windows():
    return [w for w in QApplication.topLevelWidgets()
            if type(w).__module__.startswith("echo.widgets") and w.isVisible()]


def _hide(windows):
    saved = []
    for widget in windows:
        if widget.isVisible():
            saved.append((widget, widget.testAttribute(Qt.WA_ShowWithoutActivating)))
            widget.hide()
    return saved


def _restore(saved):
    from PyQt5 import sip
    for widget, previous in saved:
        if not sip.isdeleted(widget):
            widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
            widget.show()
            widget.setAttribute(Qt.WA_ShowWithoutActivating, previous)


class RegionSelector(QWidget):
    """Drag a rectangle once; the selected scope expires when this lesson ends."""
    def __init__(self, screen, selected, cancelled):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Echo · 选择课件范围")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.screen_ = screen
        self.background = screen.grabWindow(0)
        self.selected, self.cancelled = selected, cancelled
        self.start = None
        self.rect_ = QRect()
        self._finished = False
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        bar = QFrame(self)
        bar.setStyleSheet(f"QFrame{{background:{Colors.SURFACE};border:1px solid {Colors.BORDER_STRONG};border-radius:9px;}}"
                          f"QLabel{{color:{Colors.TEXT_PRIMARY};border:0;padding:6px;}}"
                          f"QPushButton{{padding:8px 16px;color:{Colors.ON_ACCENT};background:{Colors.ACCENT};border:0;border-radius:6px;}}"
                          f"QPushButton:disabled{{background:{Colors.BORDER};color:{Colors.TEXT_DISABLED};}}")
        row = QHBoxLayout(bar)
        row.addWidget(QLabel("拖选课件区域 · 开启后仅在此范围捕捉重点 · Esc取消"))
        self.confirm = QPushButton("使用这个范围")
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.commit)
        row.addWidget(self.confirm)
        bar.adjustSize()
        bar.move(max(12, (self.width() - bar.width()) // 2), 16)
        self.bar = bar

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.bar.geometry().contains(event.pos()):
            self.start = event.pos()
            self.rect_ = QRect()
        elif event.button() == Qt.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if self.start is not None and event.buttons() & Qt.LeftButton:
            self.rect_ = QRect(self.start, event.pos()).normalized().intersected(self.rect())
            self.confirm.setEnabled(self.rect_.width() >= 160 and self.rect_.height() >= 90)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key_Enter, Qt.Key_Return) and self.confirm.isEnabled():
            self.commit()

    def commit(self):
        if self.rect_.width() < 160 or self.rect_.height() < 90:
            return
        self._finished = True
        region = LessonRegion(self.screen_.name(), QRect(self.screen_.geometry()), QRect(self.rect_))
        self.close()
        self.selected(region)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 130))
        if not self.rect_.isEmpty():
            painter.save()
            painter.setClipRect(self.rect_)
            painter.drawPixmap(self.rect(), self.background)
            painter.restore()
            painter.setPen(QPen(QColor(Colors.ACCENT), 2))
            painter.drawRect(self.rect_.adjusted(1, 1, -1, -1))

    def closeEvent(self, event):
        if not self._finished:
            self.cancelled()
        super().closeEvent(event)


def select_region(on_selected, on_cancel=None, screen=None):
    screen = screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    saved = _hide(echo_windows())

    def finish(region=None):
        _restore(saved)
        if region:
            on_selected(region)
        elif on_cancel:
            on_cancel()

    def open_selector():
        if screen is None:
            finish()
            return
        selector = RegionSelector(screen, lambda region: finish(region), finish)
        _selectors.append(selector)
        selector.destroyed.connect(lambda: _selectors.remove(selector) if selector in _selectors else None)
        selector.show()
        selector.activateWindow()
        selector.setFocus()

    QTimer.singleShot(180, open_selector)


def grab_region(region, on_done, on_error, valid=lambda: True):
    """Hide Echo briefly, grab only the chosen rectangle, and restore without activation."""
    screens = [s for s in QGuiApplication.screens() if s.name() == region.screen_name]
    if not screens or screens[0].geometry() != region.screen_geometry:
        on_error("屏幕布局已改变，请重新选择课件范围")
        return
    screen = screens[0]
    if not QRect(0, 0, screen.geometry().width(), screen.geometry().height()).contains(region.rect):
        on_error("课件范围超出屏幕，请重新选择")
        return
    saved = _hide(echo_windows())

    def grab():
        result, error = None, None
        try:
            if not valid():
                return
            rect = region.rect
            result = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
            if result.isNull():
                raise ValueError("未能截取课件区域，请检查课件是否可见")
            result.setDevicePixelRatio(1.0)
            if max(result.width(), result.height()) > 1600:
                result = result.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception as exc:
            error = str(exc)
        finally:
            _restore(saved)
        if error:
            on_error(error)
        elif result is not None and valid():
            on_done(result)

    QTimer.singleShot(180 if saved else 0, grab)
