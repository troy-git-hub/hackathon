"""离线检查窗口数量、页面切换和主要按钮，不启动音频或调用 API。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

# 当前机器的 PyQt5 Python 包与 Qt DLL 分开安装时，可显式指定本地运行库。
runtime = os.getenv("ECHO_QT_RUNTIME")
if runtime:
    runtime = Path(runtime).resolve()
    os.add_dll_directory(str(runtime / "bin"))
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(runtime / "plugins" / "platforms")
    import PyQt5
    PyQt5.__path__.append(str(runtime.parent))

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from echo.mock_data import SAMPLE_BREAKPOINT, SAMPLE_CONCEPTS
from echo.theme import apply_theme
from echo.widgets import floating_window as ui


class FakeEngine:
    def current_concept(self):
        return SAMPLE_CONCEPTS[-1]

    def concepts(self):
        return SAMPLE_CONCEPTS


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = FakeEngine()
        self.source_kind = "system"
        self.total_seconds = 0

    def start(self):
        pass

    def shutdown(self):
        pass

    def feedback(self, kind):
        pass

    def mark_fixed(self):
        pass

    def mark_self(self):
        pass

    def end_lesson(self):
        pass


ui.EchoBridge = FakeBridge
app = QApplication([])
apply_theme(app)
window = ui.FloatingWindow()
window.show()
for _ in range(4):
    app.processEvents()

top = [w for w in app.topLevelWidgets() if w.isVisible()]
assert top == [window], f"启动后出现了额外顶层窗口：{top}"

window._show_page(ui.MINI)
QTest.mouseClick(window.mini_cat, Qt.LeftButton)
app.processEvents()
assert window._page == ui.LISTEN, "点击折叠头像没有打开听课页面"

QTest.mouseClick(window.btn_lost, Qt.LeftButton)
app.processEvents()
assert window._page == ui.BREAK, "点击我掉队了没有打开断点页面"

window._on_breakpoint(SAMPLE_BREAKPOINT, SAMPLE_CONCEPTS)
app.processEvents()
assert window.btn_fill.isEnabled(), "断点结果返回后补课按钮不可用"
QTest.mouseClick(window.btn_fill, Qt.LeftButton)
app.processEvents()
assert window._page == ui.LESSON, "点击补课按钮没有打开补课页面"

QTest.mouseClick(window.back_btn, Qt.LeftButton)
app.processEvents()
assert window._page == ui.LISTEN, "返回课堂按钮失效"

screen_h = app.primaryScreen().availableGeometry().height()
assert window.height() <= screen_h, f"窗口高度 {window.height()} 超出屏幕 {screen_h}"

# 主页 / 错题复习（上下文保存）
window._show_home()
app.processEvents()
assert window._page == ui.HOME, "主页打不开"
assert window.home_sub.text(), "主页统计行为空"
# 两张功能卡的按钮任何时候都能点（没错题时进去看空状态提示）
assert window.home_review_card.btn.isEnabled(), "「去复习」按钮不可点"
assert window.home_practice_card.btn.isEnabled(), "「开始练」按钮不可点"
window.title_edit.setText("初二数学 · 正比例函数")
QTest.mouseClick(window.btn_today, Qt.LeftButton)
app.processEvents()
assert window._page == ui.LISTEN, "「开始今天的学习」没有进入听课页"

window._show_review()
app.processEvents()
assert window._page == ui.REVIEW, "错题复习页打不开"

window._show_detail(0)          # 不存在的归档：应安全退化，不崩
app.processEvents()
assert window._page == ui.DETAIL, "历史课程回顾页打不开"

window.close()
print("UI smoke passed: one window, avatar and primary flow work")
