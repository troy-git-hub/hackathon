"""离线检查窗口数量、页面切换和主要按钮，不启动音频或调用 API。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

# 这套自检要用到课程/错题记录，指到临时目录，别动用户真实的 review.json / lessons.json
from echo.backend import paths          # noqa: E402
_SMOKE_DIR = tempfile.mkdtemp(prefix="echo-smoke-")
paths.config_dir = lambda: _SMOKE_DIR

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

# 主页「AI 出题练习」：没有错题时要进练习页说清楚，不能默默弹回主页
window._show_home()
app.processEvents()
QTest.mouseClick(window.home_practice_card.btn, Qt.LeftButton)
app.processEvents()
assert window._page == ui.PRACTICE, "没有错题时点「开始练」应该进练习页说明，而不是弹回主页"
assert window.prac_loading_lbl.text().strip(), "练习页没有给出说明文案"

# 历史课回顾 → 知识地图：要能进得去，图上有节点，并且显示课程内容
from echo.backend import store                     # noqa: E402
ts = store.save_lesson(
    "贝叶斯统计",
    [{"name": "条件概率定义", "mastery": 0.9, "status": "ok"},
     {"name": "贝叶斯公式", "mastery": 0.3, "status": "review"}],
    ["贝叶斯公式", "条件概率定义"], "多练贝叶斯公式",
    summary="从条件概率讲到贝叶斯公式。",
    highlights=["贝叶斯公式 P(A|B)=P(B|A)P(A)/P(B)"],
    graph={"nodes": ["条件概率定义", "贝叶斯公式"],
           "edges": [["条件概率定义", "贝叶斯公式"]]})
window._show_detail(ts)
app.processEvents()
map_btns = [b for b in window.findChildren(type(window.back_btn))
            if b.text() == "知识地图" and b.isVisible()]
assert map_btns, "历史课回顾页上没有可见的「知识地图」按钮"
QTest.mouseClick(map_btns[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.MINDMAP, "点「知识地图」没有打开地图页"
assert len(window.mindmap_page.canvas._nodes) == 2, "知识地图上没有画出知识点"
assert window.mindmap_page.lesson_title.text(), "知识地图页没有显示课程标题"
assert window.mindmap_page.lesson_points.text(), "知识地图页没有显示课程要点"

# 没有 graph 的老课程也要能画（退回按复习链 + 讲课顺序推导）
ts2 = store.save_lesson("老课程", [{"name": "甲", "mastery": 0.5, "status": "review"},
                                   {"name": "乙", "mastery": 0.5, "status": "ok"}],
                        ["乙", "甲"], summary="老数据，没有 graph")
window._show_detail(ts2)
app.processEvents()
map_btns = [b for b in window.findChildren(type(window.back_btn))
            if b.text() == "知识地图" and b.isVisible()]
assert map_btns, "老课程的回顾页上没有「知识地图」按钮"
QTest.mouseClick(map_btns[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.MINDMAP, "老课程打不开知识地图"
assert len(window.mindmap_page.canvas._nodes) == 2, "老课程没画出知识点"
assert window.mindmap_page.lesson_summary.text(), "老课程没显示课程摘要"

window.close()
print("UI smoke passed: one window, avatar and primary flow work")
