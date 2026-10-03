"""回归：进入错题复习、出题及三档打分不应产生额外顶层窗口。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
work_dir = tempfile.TemporaryDirectory(prefix="echo-review-check-")

from echo.backend import paths
paths.config_dir = lambda: work_dir.name

runtime = os.getenv("ECHO_QT_RUNTIME")
if runtime:
    runtime = Path(runtime).resolve()
    os.add_dll_directory(str(runtime / "bin"))
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(runtime / "plugins" / "platforms")
    import PyQt5
    PyQt5.__path__.append(str(runtime.parent))

from PyQt5.QtCore import QObject, Qt, QEvent, QCoreApplication, pyqtSignal
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget
from echo import i18n
from echo.theme import apply_theme
from echo.backend import store, why_matters
from echo.backend import practice
from echo.widgets import floating_window as ui

i18n.lang = lambda: "zh"
why_calls = []


def fake_why(items, on_done=None, on_error=None):
    why_calls.append([it.get("topic") for it in items])
    on_done({})  # 模拟 AI 没有返回说明；以前每次打分都会再次请求


why_matters.generate_async = fake_why
practice.generate = lambda item, count, on_done=None, on_error=None: on_error("test")


class FakeEngine:
    active = False


class FakeBridge(QObject):
    transcript = pyqtSignal(str, str)
    concept = pyqtSignal(object)
    breakpoint = pyqtSignal(object, object)
    echo = pyqtSignal(object)
    status = pyqtSignal(str)
    thinking = pyqtSignal(bool, str)
    error = pyqtSignal(str)
    mode = pyqtSignal(str, bool)
    level = pyqtSignal(float)
    checkin = pyqtSignal(object)
    checkin_result = pyqtSignal(object)
    quiz_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = FakeEngine()
        self.source_kind = "system"

    def answer_checkin(self, index):
        pass

    def skip_checkin(self):
        pass

    def shutdown(self):
        pass


class GeometryTrace(QObject):
    def __init__(self):
        super().__init__()
        self.changes = []

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show, QEvent.Hide):
            self.changes.append((event.type(), obj.geometry().getRect(),
                                 obj.stack.height(), obj.stack.minimumHeight(),
                                 obj.review_list_lay.count()))
        return False


class PopupTrace(QObject):
    """记录瞬时顶层窗口；事后数 topLevelWidgets 会漏掉它们。"""

    def __init__(self, expected):
        super().__init__()
        self.expected = expected
        self.unexpected = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget):
            if obj.isWindow() and obj is not self.expected:
                self.unexpected.append((type(obj).__name__, obj.windowTitle()))
        return False


with work_dir:
    store.add([{"topic": "极限", "missing": "无限逼近", "micro_lesson": "逐步缩小区间。"},
               {"topic": "导数", "missing": "瞬时变化率", "micro_lesson": "先看平均变化率。"}])
    ui.EchoBridge = FakeBridge
    app = QApplication([])
    apply_theme(app)
    window = ui.FloatingWindow()
    window.show()
    app.processEvents()
    trace = GeometryTrace()
    window.installEventFilter(trace)
    popups = PopupTrace(window)
    app.installEventFilter(popups)

    def visible_windows():
        return [w for w in app.topLevelWidgets() if w.isVisible()]

    assert visible_windows() == [window], visible_windows()
    assert not popups.unexpected, popups.unexpected
    QTest.mouseClick(window.home_review_card.btn, Qt.LeftButton)
    app.processEvents()
    assert window._page == ui.REVIEW
    assert visible_windows() == [window], visible_windows()
    assert len(why_calls) == 1, why_calls
    trace.changes.clear()

    for label in ("还是没懂", "有点模糊", "记得很清楚"):
        card = next(w for w in window.review_list.findChildren(QPushButton)
                    if w.text() == label)
        QTest.mouseClick(card, Qt.LeftButton)
        app.processEvents()
        assert visible_windows() == [window], (label, visible_windows())
        assert not popups.unexpected, (label, popups.unexpected)
        assert all(rect[3] >= 400 for _, rect, *_ in trace.changes), (label, trace.changes)
        assert len(why_calls) == 1, (label, why_calls)
        trace.changes.clear()
        store.grade("极限", store.AGAIN, now=0)
        window._render_review()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()

    # AI 结果恰好在打分后回来，也只能更新原窗口，不得再闪成小窗。
    trace.changes.clear()
    window._why_ready.emit({"极限": "后续推导会再次用到。"})
    app.processEvents()
    assert visible_windows() == [window], visible_windows()
    assert not popups.unexpected, popups.unexpected
    assert all(rect[3] >= 400 for _, rect, *_ in trace.changes), trace.changes

    question = next(w for w in window.review_list.findChildren(QPushButton)
                    if "出道题试试" in w.text() and w.isVisible())
    question.click()
    app.processEvents()
    assert window._page == ui.PRACTICE
    assert visible_windows() == [window], visible_windows()
    assert not popups.unexpected, popups.unexpected

    window.close()
    app.processEvents()
    print("review popup check passed")
