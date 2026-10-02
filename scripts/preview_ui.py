"""Render the actual Qt UI offline, without audio capture or API calls.

python -B scripts/preview_ui.py --output ../ui-preview
Use --qt-runtime PATH when the Qt DLLs live outside the Python installation.
"""
import argparse
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="../ui-preview")
parser.add_argument("--qt-runtime")
parser.add_argument("--theme", choices=("light", "dark"), default="light")
parser.add_argument("--screen-height", type=int, default=900)
args = parser.parse_args()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ECHO_THEME"] = args.theme
if args.qt_runtime:
    runtime = Path(args.qt_runtime).resolve()
    dll_handle = os.add_dll_directory(str(runtime / "bin"))
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(runtime / "plugins" / "platforms")
    import PyQt5
    PyQt5.__path__.append(str(runtime.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import QObject, pyqtSignal, QRect, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import QApplication
from echo.theme import apply_theme
from echo.mock_data import SAMPLE_BREAKPOINT, SAMPLE_CONCEPTS, EchoSkill
from echo.backend.engine import EchoReport
from echo.widgets import floating_window as ui


class PreviewBridge(QObject):
    transcript = pyqtSignal(str, str)
    concept = pyqtSignal(object)
    breakpoint = pyqtSignal(object, object)
    echo = pyqtSignal(object)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    total_seconds = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = self
        self.items = copy.deepcopy(SAMPLE_CONCEPTS)
        self.fixed = False

    def start(self):
        pass

    def shutdown(self):
        pass

    def feedback(self, kind):
        pass

    def mark_fixed(self):
        self.fixed = True

    def current_concept(self):
        return self.items[-1]

    def concepts(self):
        return self.items

    def end_lesson(self):
        self.echo.emit(EchoReport([
            EchoSkill("条件概率", 1, "ok"),
            EchoSkill("贝叶斯公式", .6, "fixed"),
            EchoSkill("后验概率", .4, "review")],
            ["后验概率", "贝叶斯公式", "条件概率"], "先回顾条件概率，再把推导连起来。"))


ui.EchoBridge = PreviewBridge
app = QApplication([])
# The Windows offscreen plugin does not enumerate system fonts automatically.
for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisb.ttf", "seguisym.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename))
apply_theme(app)
window = ui.FloatingWindow()
window.screen = lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1440, args.screen_height))
window.show()
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)


def settle():
    for _ in range(8):
        app.processEvents()


def capture(name):
    settle()
    window.grab().save(str(output / (name + ".png")))
    print(name, window.width(), window.height())


capture("01-ready")
window._on_concept(window.echo.current_concept())
window._on_transcript("18:42", "后验概率，就是观察到新的证据后，对原有判断进行更新。")
capture("02-listen")
window._show_page(ui.MINI)
capture("03-mini")
QTest.mouseClick(window.mini_cat, Qt.LeftButton)
settle()
assert window._page == ui.LISTEN, "Clicking the folded avatar must open the listen page"
window._on_lost()
window._on_error("Offline preview error")
settle()
assert window.retry_btn.isVisible()
capture("04-retry")
bp = copy.deepcopy(SAMPLE_BREAKPOINT)
bp.breakpoint_tc = window.echo.items[-2].timecode
window._on_breakpoint(bp, window.echo.items)
window._on_status("listening")
capture("05-break")
QTest.mouseClick(window.cat, Qt.LeftButton)
settle()
assert window._page == ui.LISTEN, "Clicking the header avatar must return to the listen page"
window._go_lesson()
capture("06-lesson")
window._on_fixed()
assert window.echo.fixed
window._go_echo()
window._on_status("done")
capture("07-echo")
bp.step = "\n".join(["把条件概率定义代入，逐步理解公式中的每一个项。"] * 60)
window._fill_lesson(bp)
window._go_lesson()
settle()
assert window.height() <= args.screen_height
assert window.body_scroll.verticalScrollBar().maximum() > 0
capture("08-long-content")
assert window.btn_gotit.isVisible()
assert window.btn_gotit.mapTo(window, window.btn_gotit.rect().bottomRight()).y() < window.height()
window._show_page(ui.MINI)
settle()
assert window.height() < 130
window._back_to_listen()
window._on_breakpoint(bp, window.echo.items)
settle()
assert not window.btn_fill.isVisible(), "A late breakpoint must not add its action to the listen page"
window.close()
print("UI flow and long-content checks passed")
