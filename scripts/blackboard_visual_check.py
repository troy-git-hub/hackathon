"""Real embedded-browser interaction and capture timing checks, with no paid model calls.

--desktop leaves an isolated demo window open for pointer/keyboard QA.
--shots writes actual Qt/WebEngine renders to artifacts/.
"""
import copy
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if sys.platform == "win32":
    # Qt5 WebEngine requires the native Windows platform; offscreen exits in its GL setup.
    os.environ["QT_QPA_PLATFORM"] = "windows"
elif "--desktop" not in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_OPENGL"] = "software"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.stdout.reconfigure(encoding="utf-8")

from PyQt5.QtCore import Qt, QSettings, QTimer, QRect, QCoreApplication
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtGui import QPixmap, QColor, QFontDatabase, QFont, QPainter
from PyQt5.QtWebEngineWidgets import QWebEngineScript
from echo.backend import paths


def wait(app, predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("operation timed out")


def javascript(app, page, code):
    result = []
    page.runJavaScript(code, result.append)
    wait(app, lambda: bool(result))
    return result[0]


def scripts(page, frame_code):
    observer = QWebEngineScript()
    observer.setName("QA parent observer")
    observer.setInjectionPoint(QWebEngineScript.DocumentCreation)
    observer.setWorldId(QWebEngineScript.MainWorld)
    observer.setRunsOnSubFrames(False)
    observer.setSourceCode("window.qaEvents=[];window.addEventListener('message',e=>{if(e.data&&e.data.type==='qa-proof')window.qaEvents.push(e.data);});")
    page.scripts().insert(observer)
    actor = QWebEngineScript()
    actor.setName("QA iframe interaction")
    actor.setInjectionPoint(QWebEngineScript.DocumentReady)
    actor.setWorldId(QWebEngineScript.MainWorld)
    actor.setRunsOnSubFrames(True)
    actor.setSourceCode("if(window.top!==window){" + frame_code + "}")
    page.scripts().insert(actor)
    return observer, actor


with tempfile.TemporaryDirectory(prefix="echo-visual-") as folder:
    paths.config_dir = lambda: folder
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
    from echo.backend import blackboard, config
    from echo.widgets.blackboard import BlackboardWindow
    from echo.widgets.web_lesson import HtmlLesson, step_visual
    from echo.widgets import lesson_capture
    from echo.theme import apply_theme, Colors
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase().families():
        for file in ("msyh.ttc", "segoeui.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / file
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
    apply_theme(app)
    engine = SimpleNamespace(active=True, session=4, has_llm=True, _online_llm=None,
        title="数学 · 一次函数（交互验收演示）", entries=[], blackboards=[], _lock=threading.RLock(),
        lines=[SimpleNamespace(t=12, tc="00:12", text="一次函数可以写成 y=kx+b，k影响直线的倾斜方向和程度。"),
               SimpleNamespace(t=24, tc="00:24", text="固定b等于零，改变k，比较x相同时y的变化。k越大，正方向上的y增长越快。")])
    moment = blackboard.snapshot(engine)
    data = {"title": "斜率改变了什么", "gist": "固定截距，拖动斜率，看看同一个 x 对应的 y 怎样变化。", "pattern": "推导链",
        "steps": [{"label": "先固定", "heading": "固定 b = 0", "body": "把比较条件固定下来，函数成为 y = kx。", "evidence": ["T1"]},
                  {"label": "再改变", "heading": "只改变斜率 k", "body": "在相同的 x 下，比较不同的 k 对应的 y。", "evidence": ["T2"]}],
        "check": {"question": "当 x=2、b=0 时，k 从1变成2，y会怎样变？", "answer": "y从2变成4。"}}
    board = blackboard.normalize(data, moment["sources"])
    board.update(sources=moment["sources"], mode="ai", created=moment["created"], course=engine.title,
                 focus="k为什么影响倾斜程度", start="00:12", end="00:24", has_image=False)
    fixture_html = '''<style>main{padding:16px}h2{font-size:20px}input{width:100%}.card{padding:14px;background:var(--surface);border:1px solid var(--border);border-radius:12px}svg{width:100%;height:180px}label{display:block;margin:14px 0 8px}</style>
<main><h2>斜率 k，让直线怎么变？</h2><p>保持 b=0。拖动滑块，比较同一个 x 下的 y。</p>
<div class=card><svg viewBox="0 0 300 180" aria-label="一次函数示意图"><path d="M20 140H285M60 165V15" stroke="var(--muted)"/><path id=line stroke="var(--accent)" stroke-width="3"/><circle id=point r=5 fill="var(--text)"/><text x=265 y=158 fill="var(--muted)">x</text><text x=42 y=22 fill="var(--muted)">y</text></svg>
<label for=k>斜率 k：<strong id=value>1.0</strong></label><input id=k type=range min=-1 max=3 step=.1 value=1>
<p id=readout></p></div><p>固定 x=2 时，y=2k。斜率为负时，x增加而y减少。</p></main>
<script>const k=document.querySelector('#k');function draw(){const n=Number(k.value);document.querySelector('#value').textContent=n.toFixed(1);document.querySelector('#line').setAttribute('d','M20 '+(140+20*n)+' L280 '+(140-110*n));document.querySelector('#point').setAttribute('cx',140);document.querySelector('#point').setAttribute('cy',140-40*n);document.querySelector('#readout').textContent='x = 2 时，y = '+(2*n).toFixed(1);}k.oninput=draw;draw();</script>'''
    board["visualization"] = {"title": "改变斜率", "html": fixture_html, "mode": "ai"}

    gate = blackboard.ImportanceGate()
    assert gate.eligible(moment, 0)
    gate.checked(moment, 0)
    assert not gate.eligible(moment, 40)
    later = dict(moment, end="00:40")
    assert gate.eligible(later, 40)
    assert gate.accept({"important": True, "topic": "一次函数斜率"}, 40)
    assert not gate.eligible(dict(later, end="00:50"), 60)
    assert not gate.accept({"important": True, "topic": "一次函数斜率"}, 140)
    print("PASS importance check throttle, capture cooldown and topic deduplication", flush=True)

    captured_coordinates = []
    class Screen:
        def name(self): return "fixture"
        def geometry(self): return QRect(0, 0, 1000, 700)
        def grabWindow(self, ident, x, y, w, h):
            captured_coordinates.append((x, y, w, h))
            image = QPixmap(w, h)
            image.fill(QColor("#EAF2EC"))
            return image
    selection = lesson_capture.LessonRegion("fixture", QRect(0, 0, 1000, 700), QRect(60, 80, 500, 300))
    region_images, region_errors = [], []
    with patch.object(lesson_capture.QGuiApplication, "screens", return_value=[Screen()]), \
            patch.object(lesson_capture.QTimer, "singleShot", side_effect=lambda delay, callback: callback()):
        lesson_capture.grab_region(selection, region_images.append, region_errors.append)
        assert captured_coordinates == [(60, 80, 500, 300)] and len(region_images) == 1
        lesson_capture.grab_region(selection, region_images.append, region_errors.append, valid=lambda: False)
        assert len(region_images) == 1
        moved = lesson_capture.LessonRegion("fixture", QRect(0, 0, 800, 600), QRect(60, 80, 500, 300))
        lesson_capture.grab_region(moved, region_images.append, region_errors.append)
        assert region_errors
    print("PASS selected-region bounds, canceled capture and changed-display rejection", flush=True)

    window = BlackboardWindow(engine)
    assert window.width() <= 500 and window.height() <= 600
    window.show()
    app.processEvents()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    assert window.fold_btn.text() == "–" and window.hide_btn.text() == "×"
    assert not hasattr(window, "pin_btn")
    assert window.fold_btn.x() < window.hide_btn.x()
    assert window.hide_btn.geometry().right() >= window.header.width() - 2
    window.toggle_fold()
    app.processEvents()
    assert window.height() <= 65 and window.width() <= 330
    assert window.fold_btn.text() == "+"
    window.toggle_fold()
    assert window.fold_btn.text() == "–"
    assert not window.sources_scroll.isVisible()
    window._boards = [board]
    engine.blackboards = [copy.deepcopy(board)]
    window.refresh_history()
    window.render(board)
    print("PASS compact pinned window, 44px fold and hidden source divider", flush=True)

    # A board answer can embed a small interaction directly in the paper while
    # the separate, original full demonstration stays untouched.
    original_visual = copy.deepcopy(board["visualization"])
    board["inline_visual"] = {"title": "当前知识点图解", "mode": "ai", "html":
        '<p>固定 x = 2，改变斜率。</p><button id="inline-change" onclick="document.querySelector(\'#inline-value\').textContent=\'y = 4\'">令 k = 2</button><p id="inline-value">y = 2</p>'}
    window.render(board)
    assert window._inline_view is not None and window.paper.isVisible()
    scripts(window._inline_view.page, "document.querySelector('#inline-change').click();parent.postMessage({type:'qa-proof',value:document.querySelector('#inline-value').textContent},'*');")
    window._inline_view.display(board["inline_visual"])
    wait(app, lambda: javascript(app, window._inline_view.page, "window.qaEvents&&window.qaEvents.length") == 1)
    assert javascript(app, window._inline_view.page, "window.qaEvents[0].value") == "y = 4"
    assert board["visualization"] == original_visual
    archive = BlackboardWindow(archived=[copy.deepcopy(board)])
    assert archive._inline_view is None
    archive.show()
    app.processEvents()
    assert archive._inline_view and archive._inline_view.fragment == board["inline_visual"]["html"]
    archive.hide()
    print("PASS actual inline board HTML interaction, independent full demonstration and archived diagram replay", flush=True)

    html_view = HtmlLesson()
    scripts(html_view.page, "const next=document.querySelector('#next');if(next){next.click();parent.postMessage({type:'qa-proof',heading:document.querySelector('#heading').textContent},'*');}")
    html_view.resize(420, 360)
    html_view.show()
    html_view.display(step_visual(board))
    wait(app, lambda: javascript(app, html_view.page, "window.qaEvents&&window.qaEvents.length") == 1)
    proof = javascript(app, html_view.page, "window.qaEvents[0]")
    assert proof["heading"] == "只改变斜率 k"
    print("PASS actual embedded HTML next-step interaction", flush=True)

    slider_view = HtmlLesson()
    scripts(slider_view.page, "const k=document.querySelector('#k');if(k){k.value=2;k.dispatchEvent(new Event('input'));parent.postMessage({type:'qa-proof',value:document.querySelector('#readout').textContent},'*');}")
    slider_view.resize(420, 420)
    slider_view.show()
    slider_view.display(board["visualization"])
    wait(app, lambda: javascript(app, slider_view.page, "window.qaEvents&&window.qaEvents.length") == 1)
    assert "4.0" in javascript(app, slider_view.page, "window.qaEvents[0].value")
    print("PASS actual slider updates graph and numerical explanation", flush=True)

    from echo.backend.lesson_design import guided_html
    from reading_fixture import BOARD as READING_BOARD, EXPERIENCE
    reading_view = HtmlLesson()
    reading_view.resize(420, 900)
    reading_view.show()
    scripts(reading_view.page, """document.querySelector('#lenses').children[1].click();
document.querySelector('#evidence-toggle').click();document.querySelector('#answers').children[0].click();
const wrong=document.querySelector('#feedback').textContent;document.querySelector('#answers').children[1].click();
parent.postMessage({type:'qa-proof',heading:document.querySelector('#lens-title').textContent,
evidence:document.querySelector('#evidence').hidden===false,wrong,right:document.querySelector('#feedback').textContent,
fits:document.documentElement.scrollWidth<=innerWidth,
button:getComputedStyle(document.querySelector('#answers button')).backgroundColor},'*');""")
    reading = guided_html(EXPERIENCE, READING_BOARD)
    for width in (320, 420):
        reading_view.resize(width, 900)
        app.processEvents()
        reading_view.display(reading)
        wait(app, lambda: javascript(app, reading_view.page, "window.qaEvents&&window.qaEvents.length") == 1)
        proof = javascript(app, reading_view.page, "window.qaEvents[0]")
        assert proof["heading"] == "身体的疾病，与精神的麻木" and proof["evidence"] and proof["fits"]
        assert "再想一步" in proof["wrong"] and "理解对了" in proof["right"]
        color = QColor(Colors.SURFACE)
        assert proof["button"] == f"rgb({color.red()}, {color.green()}, {color.blue()})"
    print("PASS literary exploration, original evidence, contrast, answer-specific feedback, theme controls and 320px layout", flush=True)

    sandbox = HtmlLesson()
    scripts(sandbox.page, "let parentBlocked=false;try{parent.document.body.innerHTML='escape';}catch(e){parentBlocked=true;}parent.postMessage({type:'qa-proof',parentBlocked,fetch:typeof fetch,rtc:typeof RTCPeerConnection,storage:(()=>{try{localStorage.setItem('x','1');return 'allowed'}catch(e){return 'blocked'}})()},'*');")
    sandbox.display({"html": '<img src="http://127.0.0.1:1/blocked"><iframe src="file:///C:/Windows/win.ini"></iframe>'})
    wait(app, lambda: javascript(app, sandbox.page, "window.qaEvents&&window.qaEvents.length") == 1)
    security = javascript(app, sandbox.page, "window.qaEvents[0]")
    assert security["parentBlocked"] and security["fetch"] == security["rtc"] == "undefined" and security["storage"] == "blocked"
    assert sandbox.profile.isOffTheRecord()
    print("PASS opaque iframe origin, network API lockdown, disabled storage and private browser profile", flush=True)

    # A delayed text judgment must use the image and transcript frozen together, even after the teacher moves on.
    freeze_engine = copy.copy(engine)
    freeze_engine.blackboards = []
    auto = BlackboardWindow(freeze_engine)
    auto.hide()
    auto._region = lesson_capture.LessonRegion("test", QRect(0, 0, 800, 600), QRect(0, 0, 600, 400))
    entered, release = threading.Event(), threading.Event()
    frame = QPixmap(600, 400)
    frame.fill(QColor("#EAF2EC"))
    recorded = []
    def judge(frozen):
        entered.set()
        release.wait(3)
        return {"important": True, "topic": "斜率", "reason": "解释参数含义"}
    def generate(frozen, focus, image):
        recorded.append((frozen, image))
        result = copy.deepcopy(board)
        result["created"] = frozen["created"]
        return result
    with patch.object(config, "OFFLINE", False), patch.object(blackboard.providers, "configured", return_value=True), \
            patch.object(lesson_capture, "grab_region", side_effect=lambda r, done, err, valid: done(frame)), \
            patch.object(blackboard, "judge_importance", side_effect=judge), patch.object(blackboard, "generate_board", side_effect=generate):
        auto.auto_toggle.setChecked(True)
        assert entered.wait(1)
        freeze_engine.lines = engine.lines + [SimpleNamespace(t=80, tc="01:20", text="老师已经翻页，开始讲下一部分。")]
        release.set()
        wait(app, lambda: bool(auto._boards))
    assert recorded[0][0]["end"] == "00:24" and recorded[0][1] and not auto.isVisible()
    assert auto._boards[0]["trigger"] == "automatic"
    freeze_engine.active = False
    auto.sync_lesson()
    assert not auto.auto_toggle.isChecked() and auto._region is None
    print("PASS moment-aligned automatic capture, hidden background operation and class-end stop", flush=True)

    if "--shots" in sys.argv or "--desktop" in sys.argv:
        out = ROOT / "artifacts"
        out.mkdir(exist_ok=True)
        (out / "blackboard-interactive-demo.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        window.show_tab(0)
        window.resize(460, 560)
        app.processEvents()
        window.grab().save(str(out / "echo-small-board.png"))
        window.toggle_fold()
        app.processEvents()
        window.grab().save(str(out / "echo-board-folded.png"))
        window.toggle_fold()
        window.show_tab(1)
        wait(app, lambda: javascript(app, window._visual_view.page, "window.echoLessonState&&window.echoLessonState.ready") is True)
        window.grab().save(str(out / "echo-html-lesson.png"))
        reading_view.grab().save(str(out / "echo-reading-experience.png"))
    for view in (html_view, slider_view, sandbox, reading_view):
        view.stop()
        view.close()
    auto.close()
    print("All visual checks passed. Model responses used isolated fixtures; HTML ran in the real embedded browser.", flush=True)
    if "--desktop" in sys.argv:
        config.OFFLINE = True
        engine.has_llm = False
        course = QWidget()
        course.setWindowTitle("Echo · 演示课件（无模型调用）")
        course.resize(740, 500)
        course.move(32, 80)
        course.setStyleSheet("background:#F6F4EC;color:#233C31;")
        lesson_layout = QVBoxLayout(course)
        lesson_layout.setContentsMargins(30, 28, 30, 28)
        for text, size in (("一次函数：斜率改变了什么？", 26), ("y = kx + b", 34),
                           ("固定 b = 0，比较同一个 x = 2。", 20),
                           ("k = 1 → y = 2\nk = 2 → y = 4", 24),
                           ("这是本地演示课件，用于验证选区，不会调用在线模型。", 13)):
            item = QLabel(text)
            item.setWordWrap(True)
            item.setStyleSheet(f"font-size:{size}px;")
            lesson_layout.addWidget(item)
        course.show()
        window.show_tab(1)
        window.setWindowTitle("Echo · 小黑板交互验收（演示）")
        window.show()
        window.raise_()
        app.exec_()
    else:
        window.close()
        app.processEvents()
