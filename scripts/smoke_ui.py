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
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton

from echo.mock_data import SAMPLE_BREAKPOINT, SAMPLE_CONCEPTS
from echo.theme import apply_theme
from echo.widgets import floating_window as ui

# 界面支持中/英双语，这套自检是按中文按钮找控件的。上机语言设成 English 时
# 文案会变、断言全找不到按钮，所以在这里把语言钉死成中文（只影响本进程，不改用户设置）。
from echo import i18n                    # noqa: E402
i18n.lang = lambda: "zh"


class FakeEngine:
    def __init__(self):
        self.active = False

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
    # 必须带上这两个：没有它们，FloatingWindow 里「课堂抽查」那一整块接线
    # （答题、跳过、卡片收起后重排窗口）在自检里根本不会被执行到
    checkin = pyqtSignal(object)
    checkin_result = pyqtSignal(object)
    quiz_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = FakeEngine()
        self.source_kind = "system"
        self.total_seconds = 0
        self.asks = 0            # 学生按了几次「考考我」

    def ask_checkin_now(self):
        self.asks += 1
        return True

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

    def make_lesson_quiz(self, lesson, n=4):
        """课后练习：立刻回一道题，用来验「出几道题练练」能走到练习页。"""
        self.quiz_ready.emit([{"question": "试一下", "options": ["A. 甲", "B. 乙"],
                               "answer": "A", "explain": "解析示例"}])

    def answer_checkin(self, idx):
        """课堂抽问作答。回一条结果，界面据此显示判分。"""
        rec = {"result": "right", "choice": idx, "explain": "示例解析",
               "answer_text": "B. 乙"}
        self.checkin_result.emit(rec)
        return rec

    def skip_checkin(self):
        """学生把抽问关掉了。"""


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
window._show_courses()
app.processEvents()
assert window._page == ui.COURSES, "「课程管理」页打不开"
rows = [b for b in window.findChildren(QPushButton)
        if b.text() == "看回顾" and b.isVisible()]
assert rows, "课程管理页里没有「看回顾」按钮"
# 这一步必须真的点按钮：_btn 曾经把 clicked 的 checked=False 喂进 lambda 的默认参数，
# 时间戳变成 0、课程查不到 —— 回顾页打开是空的，知识地图和出题按钮跟着一起失效。
QTest.mouseClick(rows[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.DETAIL, "点「看回顾」没有打开回顾页"
assert getattr(window, "_detail_lesson", None), "点「看回顾」后详情页没拿到课程数据"
assert window.det_title.text() == "贝叶斯统计", f"回顾页标题不对：{window.det_title.text()}"
assert window.status_lbl.text() == "还没开始上课", \
    f"没在上课，状态栏却写着「{window.status_lbl.text()}」"

map_btns = [b for b in window.findChildren(QPushButton)
            if b.text() == "知识地图" and b.isVisible()]
assert map_btns, "历史课回顾页上没有可见的「知识地图」按钮"
QTest.mouseClick(map_btns[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.MINDMAP, "点「知识地图」没有打开地图页"
assert len(window.mindmap_page.canvas._nodes) == 2, "知识地图上没有画出知识点"
assert window.mindmap_page.lesson_title.text(), "知识地图页没有显示课程标题"
assert window.mindmap_page.lesson_points.text(), "知识地图页没有显示课程要点"

window._show_detail(ts)
app.processEvents()
quiz_btns = [b for b in window.findChildren(QPushButton)
             if b.text() == "出几道题练练" and b.isVisible()]
assert quiz_btns, "回顾页上没有可见的「出几道题练练」按钮"
QTest.mouseClick(quiz_btns[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.PRACTICE, "点「出几道题练练」没有打开练习页"

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

# 练习页从哪儿进来的，练完就回哪儿 —— 不能一律弹回主页
ts3 = store.save_lesson("概率复习课", [{"name": "条件概率定义", "mastery": 0.9, "status": "ok"},
                                      {"name": "贝叶斯公式", "mastery": 0.3, "status": "review"}],
                        ["贝叶斯公式", "条件概率定义"],
                        graph={"nodes": ["条件概率定义", "贝叶斯公式"],
                               "edges": [["条件概率定义", "贝叶斯公式"]]})
window._show_detail(ts3)
app.processEvents()
map_btns = [b for b in window.findChildren(QPushButton)
            if b.text() == "知识地图" and b.isVisible()]
QTest.mouseClick(map_btns[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.MINDMAP

window.mindmap_page.select("贝叶斯公式")
app.processEvents()
QTest.mouseClick(window.mindmap_page.detail.practice_btn, Qt.LeftButton)
app.processEvents()
assert window._page == ui.PRACTICE, "知识地图的「出题练一练」没进练习页"
assert window.back_btn.text() == "← 知识地图", \
    f"从地图进来的练习页，返回按钮却写着「{window.back_btn.text()}」"

window._prac_qs = [{"question": "P(A|B)=？", "options": ["A. 甲", "B. 乙"], "answer": "A"}]
master = [b for b in window.findChildren(QPushButton)
          if b.text() == "✓ 这个我会了" and b.isVisible()]
assert master, "练习页上没有「✓ 这个我会了」"
QTest.mouseClick(master[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.MINDMAP, "练完点「我会了」应该回知识地图，而不是弹回主页"
assert window.mindmap_page.canvas._selected == "贝叶斯公式", "回到地图后没选回刚才那个知识点"
assert window.back_btn.text() == "← 主页", "地图页的返回按钮被练习页的标签带跑了"

# 从课程回顾进来的，就回课程回顾
window._show_detail(ts3)
app.processEvents()
quiz_btns = [b for b in window.findChildren(QPushButton)
             if b.text() == "出几道题练练" and b.isVisible()]
QTest.mouseClick(quiz_btns[0], Qt.LeftButton)
app.processEvents()
assert window._page == ui.PRACTICE
assert window.back_btn.text() == "← 课程回顾", \
    f"返回按钮写着「{window.back_btn.text()}」"
QTest.mouseClick(window.back_btn, Qt.LeftButton)
app.processEvents()
assert window._page == ui.DETAIL, "练习页点返回没有回到课程回顾"

# 听课页「考考我」：学生主动要一道课上小题
window.echo.engine.active = True
window._show_page(ui.LISTEN)
app.processEvents()
assert window.btn_ask.isVisible(), "听课页上没有「考考我」按钮"
asks_before = window.echo.asks
QTest.mouseClick(window.btn_ask, Qt.LeftButton)
app.processEvents()
assert window.echo.asks == asks_before + 1, "点「考考我」没有跟引擎要题"
assert window.checkin_card.isVisible(), "点了「考考我」，抽问卡片没亮出来"
assert window.checkin_card.question_lbl.text(), "抽问卡片上一个字都没有"
window.checkin_card.dismiss()
window.echo.engine.active = False

# 自评题的三个选项是后端给的固定文案，英文界面要翻过来；AI 出的选择题不能被改
from echo import i18n as _i18n                      # noqa: E402
from echo.backend import quiz as _quiz              # noqa: E402
from echo.widgets.checkin import CheckinCard        # noqa: E402

_i18n.lang = lambda: "en"
card = CheckinCard()
card.ask(_quiz._self_checkin("条件概率", "03:12"))
labels = [b.text() for b in card._option_buttons]
assert any("Completely lost" in t for t in labels), f"自评题选项没翻成英文：{labels}"
card2 = CheckinCard()
card2.ask({"topic": "x", "question": "q", "options": ["A. foo", "B. bar"], "answer": "B"})
assert [b.text() for b in card2._option_buttons] == ["A. foo", "B. bar"], \
    "AI 出的选项不该被翻译"
card2._option_buttons[1].click()
assert card2._option_buttons[1].isEnabled() is False, "作答后选项应锁住"
_i18n.lang = lambda: "zh"           # 还原，别影响后面的中文断言

# 课程管理：搜索过滤 + 重命名 + 批量删除（对话框在 offscreen 下会阻塞，这里只测非交互路径）
# 课名是 AI 填的占位名时，列表上别把「（未知）」当课名摆出来
assert ui.FloatingWindow._lesson_name({"title": "贝叶斯统计"}) == "贝叶斯统计"
assert ui.FloatingWindow._lesson_name(
    {"title": "（未知）", "skills_detail": [{"name": "定义域"}]}) == "定义域", \
    "占位课名应该退回用知识点名"
assert ui.FloatingWindow._lesson_name({"title": "未知", "date": "10月2日"}) == "10月2日", \
    "没有知识点时退回用日期"

store.save_lesson("（未知）", [{"name": "函数定义域求解", "mastery": 0.8, "status": "ok"}], [])
window._show_courses()
app.processEvents()
window.courses_search.setText("函数定义域求解")
app.processEvents()
assert len(window._course_cards) == 1, "按列表上显示的名字搜不到这门课"
assert any("函数定义域求解" in w.text() for w in window._course_cards[0].findChildren(QLabel)), \
    "标题是占位名的课没有显示成知识点名"
window.courses_search.setText("")
app.processEvents()

window._show_courses()
app.processEvents()
assert window._page == ui.COURSES, "「课程管理」页打不开"
window.courses_search.setText("贝叶斯")
app.processEvents()
assert len(window._course_cards) == 1, f"搜索「贝叶斯」应只剩 1 节，实际 {len(window._course_cards)}"
window.courses_search.setText("")
app.processEvents()
assert len(window._course_cards) >= 2, "清空搜索后课程列表应恢复全部"
assert store.rename_lesson(ts, "贝叶斯统计（改名）"), "重命名失败"
assert store.get_lesson(ts)["title"] == "贝叶斯统计（改名）", "重命名没生效"
assert store.delete_lessons([ts]) == 1, "批量删除失败"
assert not store.get_lesson(ts), "删除后仍能查到这节课"

# 系统弹窗（QMessageBox / QInputDialog）必须跟随深色主题，按钮还得是中文。
# 全局 QSS 里那条 `* { color: TEXT_PRIMARY }` 会把弹窗文字染成浅色，
# 而弹窗背景仍是系统浅色 —— 白字贴白底，几乎看不见。这条断言守住那段样式。
from echo.theme import GLOBAL_QSS                    # noqa: E402
assert "QMessageBox" in GLOBAL_QSS, "弹窗深色样式从全局 QSS 里丢了"
assert "QInputDialog QLineEdit" in GLOBAL_QSS, "输入弹窗的输入框样式丢了"

from echo.widgets import dialogs                     # noqa: E402

seen = []
_orig_exec = dialogs.QMessageBox.exec_
dialogs.QMessageBox.exec_ = lambda self: (seen.append([b.text() for b in self.buttons()]), 1)[1]
try:
    dialogs.confirm(None, "批量删除", "确定删除吗？", ok_text="删除")
    dialogs.info(None, "批量删除", "先勾选要删除的课程。")
finally:
    dialogs.QMessageBox.exec_ = _orig_exec
assert seen and seen[0] == ["删除", "取消"], \
    f"确认框按钮应该是中文的「删除/取消」，实际 {seen[0] if seen else None}"
assert seen and "知道了" in seen[1], f"提示框按钮不对：{seen[1] if len(seen) > 1 else None}"

# 2.0「今天该回响」：首页卡片 → 讲给 Echo 听 → 三档自评 / 过几天再复习
import time as _t                                   # noqa: E402

from echo.backend import recall                     # noqa: E402

store._write([])
store.add([{"topic": "导数定义", "missing": "为什么是极限？", "time": _t.time() - 86400,
            "review_chain": ["导数", "极限"]},
           {"topic": "链式法则", "missing": "为什么连乘？", "time": _t.time() - 86400,
            "review_chain": ["链式法则", "极限"]}])
window._show_home()
app.processEvents()
assert window.home_recall_card.isVisible(), "有到期的知识点，首页却没弹「今天该回响」卡"
assert "2" in window.recall_title.text(), f"卡片没数对：{window.recall_title.text()}"
assert window.recall_hint.text().strip(), "卡片没给出掉队位置的提示"

# 两个知识点都挂在「极限」上 → 应该认出这个共同根源，一起聊
chosen, root = recall.pick(store.due_items(), n=3)
assert len(chosen) == 2 and root == "极限", f"没认出共同根源：chosen={len(chosen)} root={root!r}"

# 讲给 Echo 听：对话式，不是答题页
QTest.mouseClick(window.btn_recall, Qt.LeftButton)
for _ in range(40):
    app.processEvents()
    if window._recall_plan:
        break
    QTest.qWait(30)
assert window._page == ui.RECALL, "点「讲给 Echo 听」没进对话页"
assert window._recall_plan.get("questions"), "没生成问题"
assert "极限" in window.recall_sub.text() or "2 个知识点" in window.recall_sub.text(), \
    f"副标题没说清这一轮聊什么：{window.recall_sub.text()}"

n_bubbles = window.recall_box_lay.count()
assert n_bubbles >= 2, f"开场白 + 第一问至少两条气泡，实际 {n_bubbles}"
# 气泡是运行时加进来的：不主动重排一次，换行标签高度会是 0，界面只剩几条空条
for i in range(n_bubbles):
    w = window.recall_box_lay.itemAt(i).widget()
    texts = [l.text() for l in w.findChildren(QLabel) if l.text().strip() not in ("", "Echo")]
    assert texts, f"第 {i} 条气泡是空的"
    assert all(l.height() > 0 for l in w.findChildren(QLabel) if l.text().strip()), \
        f"第 {i} 条气泡的文字高度是 0（没重排）"

# 课堂抽问卡片收起来后，窗口要缩回去（原来会留一大块空白）
window._show_page(ui.LISTEN)
for _ in range(10):        # _fit() 里有个 singleShot(0)，先等它落定再量基准
    app.processEvents()
    QTest.qWait(10)
h_before = window.height()
window._on_checkin({"topic": "条件概率", "question": "P(A|B) 是什么？",
                    "options": ["A. 甲", "B. 乙"], "answer": "B", "explain": "x"})
for _ in range(15):
    app.processEvents()
assert window.height() > h_before, "弹出抽问后窗口没变高"
window.checkin_card.close_btn.click()
for _ in range(25):
    app.processEvents()
    QTest.qWait(10)
assert abs(window.height() - h_before) <= 2,     f"叉掉抽问卡片后窗口没缩回去：{h_before} → {window.height()}"
assert abs(window.stack.height() - window.stack.currentWidget().layout()
           .totalHeightForWidth(ui.PAGE_WIDTH[ui.LISTEN])) <= 2,     "stack 的固定高度还留着抽问卡在时的高度"

window.close()
print("UI smoke passed: one window, avatar and primary flow work")
