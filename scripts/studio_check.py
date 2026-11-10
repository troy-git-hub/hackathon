"""In-class blackboard acceptance; all models, files and settings are isolated."""
import copy
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
sys.stdout.reconfigure(encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def fixture_board():
    return {"title": "从武昌起义到清帝退位", "gist": "先分清起义的发生、革命的扩展和清朝统治结束，三者处在不同阶段。",
            "pattern": "时间线", "steps": [
                {"label": "1911年10月10日", "heading": "武昌起义", "body": "先确定事件发生的时间与地点，再沿着老师的讲解看它如何影响后续局势。", "evidence": ["T1", "S1"]},
                {"label": "起义之后", "heading": "革命继续扩展", "body": "武昌起义之后，多省相继宣布独立。起义的发生与革命的扩展，是相连但不同的阶段。", "evidence": ["T2"]},
                {"label": "1912年2月", "heading": "清帝退位", "body": "老师把清帝退位作为清朝统治结束的节点。不要把这一节点与武昌起义的日期混为一谈。", "evidence": ["T3"]}],
            "pitfall": "时间上的先后不能单独证明因果。为什么会扩展到多省，还需要结合老师给出的背景与材料。",
            "check": {"question": "武昌起义发生和清朝统治结束，为什么不能当成同一个时间点？",
                      "answer": "前者是起义发生，后者以清帝退位为节点；二者之间还有革命扩展的过程。"}}


def sample_engine():
    return SimpleNamespace(session=7, active=True, _lock=threading.RLock(), title="中国近代史 · 辛亥革命（演示课堂）",
        entries=[], has_llm=False, _online_llm=None, blackboards=[],
        lines=[SimpleNamespace(t=12, tc="00:12", text="1911年10月10日，武昌起义发生。"),
               SimpleNamespace(t=32, tc="00:32", text="武昌起义之后，多省相继宣布独立，革命继续扩展。"),
               SimpleNamespace(t=58, tc="00:58", text="1912年2月，清帝退位，清朝统治结束。注意这与起义发生不是同一个节点。")])


def wait_ui(app, predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate(), "UI operation timed out"


with tempfile.TemporaryDirectory(prefix="echo-board-") as folder:
    from echo.backend import paths
    paths.config_dir = lambda: folder
    from PyQt5.QtCore import QSettings, Qt, QRect, QRectF
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtGui import QFontDatabase, QPixmap, QPainter, QColor, QFont, QPen, QPainterPath
    from echo.backend import blackboard, knowledge, config, store, vision, awareness, providers
    from echo.theme import apply_theme
    from echo.widgets.blackboard import BlackboardWindow
    from echo.widgets.learning_studio import KnowledgeLibrary
    from echo.widgets import snip

    ident = knowledge.add("辛亥革命讲义", "武昌起义发生于1911年10月10日。之后多省宣布独立。")
    assert knowledge.add("重复", "武昌起义发生于1911年10月10日。之后多省宣布独立。") == ident
    assert knowledge.retrieve("武昌起义") and not knowledge.retrieve("quantum physics")
    knowledge.update(ident, "辛亥革命课堂讲义", "武昌起义发生于1911年10月10日。之后多省相继宣布独立。")
    assert len(knowledge.documents()) == 1 and "课堂讲义" in knowledge.documents()[0]["title"]
    note = Path(folder) / "补充.md"
    note.write_text("清帝退位发生于1912年2月。", encoding="utf-8-sig")
    knowledge.import_file(note)
    print("PASS knowledge retrieval, deduplication, editing and UTF-8 import")

    engine = sample_engine()
    moment = blackboard.snapshot(engine)
    engine.lines.append(SimpleNamespace(t=90, tc="01:30", text="之后才讲的新内容"))
    assert len(moment["sources"]) == 3
    engine.active = False
    try:
        blackboard.snapshot(engine)
        raise AssertionError("pre-class access allowed")
    except ValueError:
        pass
    engine.active = True
    print("PASS lesson-only snapshot and frozen transcript sources")

    with patch.object(config, "OFFLINE", False):
        local = blackboard.generate_board(moment)
        assert local["mode"] == "excerpt" and local["steps"][0]["body"] == engine.lines[0].text
        online = dict(moment, online=True)
        with patch.object(blackboard, "LLM") as model:
            model.return_value.json.return_value = fixture_board()
            result = blackboard.generate_board(online, "梳理时间线")
            assert result["steps"][0]["evidence"] == ["T1"]  # No invented screenshot source.
            assert "K1" in model.return_value.json.call_args.args[1]
            bad = fixture_board()
            bad["steps"][0]["evidence"] = ["T999", "K999"]
            model.return_value.json.return_value = bad
            assert blackboard.generate_board(online)["steps"][0]["evidence"] == []
        sent = []
        class Completions:
            def create(self, **kwargs):
                sent.append(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=__import__('json').dumps(fixture_board(), ensure_ascii=False)))])
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        with patch.object(blackboard.providers, "configured", return_value=True), patch.object(blackboard.providers, "client", return_value=fake_client):
            visual = blackboard.generate_board(dict(online, vision_online=True), "截图里的节点有什么区别", b"sample-image")
        assert sent[0]["messages"][1]["content"][1]["type"] == "image_url"
        assert visual["has_image"] and "S1" in visual["steps"][0]["evidence"]
        assert "T1" in blackboard.markdown(visual) and "来源快照" in blackboard.markdown(visual)
    print("PASS text/vision routing, citation validation, offline excerpt and export")

    settings_env = {"ECHO_LLM_PROVIDER": "deepseek", "ECHO_LLM_API_KEY": "test-text-key",
        "ECHO_VISION_PROVIDER": "custom", "ECHO_VISION_API_KEY": "test-vision-key",
        "ECHO_VISION_MODEL": "configured-classroom-vision", "ECHO_VISION_BASE_URL": "https://vision.example.invalid/v1"}
    with patch.dict(os.environ, settings_env, clear=True), patch.object(config, "OFFLINE", False), \
            patch.object(providers, "client", return_value=fake_client) as factory:
        expected = providers.vision()
        _, selected_model, _ = vision._make_client()
        blackboard.generate_board(dict(online, vision_online=True), "设置中选定的视觉模型", b"sample-image")
        assert selected_model == sent[-1]["model"] == "configured-classroom-vision"
        assert factory.call_args.args[0] == expected
        os.environ["ECHO_VISION_MODEL"] = "changed-in-settings"
        assert vision._make_client()[1] == "changed-in-settings"
        blackboard.generate_board(dict(online, vision_online=True), "切换后立即使用", b"sample-image")
        assert sent[-1]["model"] == "changed-in-settings"
    with patch.dict(os.environ, {"ECHO_LLM_PROVIDER": "deepseek", "ECHO_VISION_PROVIDER": "same",
                    "ECHO_VISION_MODEL": "stale-qwen-model", "DASHSCOPE_API_KEY": "legacy-test-key"}, clear=True):
        assert providers.vision()["id"] == "deepseek"
        assert providers.vision()["model"] == providers.preset("deepseek")[5]
        os.environ.pop("ECHO_VISION_PROVIDER")
        assert providers.vision()["id"] == "deepseek"  # Same as the visible Settings default.
    print("PASS shared vision settings, live model switch and stale-provider isolation")
    with patch.dict(os.environ, {"ECHO_LLM_PROVIDER": "deepseek", "ECHO_LLM_MODEL": "deepseek-chat",
                    "ECHO_LLM_BASE_URL": "https://api.deepseek.com", "ECHO_LLM_API_KEY": "fixture",
                    "ECHO_VISION_PROVIDER": "qwen", "ECHO_VISION_MODEL": "qwen-vl-plus",
                    "ECHO_VISION_API_KEY": "fixture"}, clear=True):
        assert providers.text()["model"] == "deepseek-flash"
        assert providers.vision()["model"] == "qwen3-vl-plus"
        assert providers.text_extra(providers.text()) == {"thinking": {"type": "disabled"}}
        os.environ["ECHO_LLM_BASE_URL"] = "https://gateway.example/v1"
        assert providers.text()["model"] == "deepseek-chat"  # custom gateways keep their own aliases
        os.environ["ECHO_VISION_PROVIDER"] = "custom"
        os.environ["ECHO_VISION_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert providers.vision()["model"] == "qwen-vl-plus"
    class MissingModel(Exception):
        status_code = 404
    message = providers.api_error(MissingModel("secret response"),
        {"id": "qwen", "model": "qwen3-vl-plus", "api_key": "fixture-secret"})
    assert "qwen3-vl-plus" in message and "404" in message and "fixture-secret" not in message and "secret response" not in message
    print("PASS retired official models migrate; custom endpoints stay intact; diagnostic has no raw credentials")

    app = QApplication.instance() or QApplication([])
    if not QFontDatabase().families():
        for filename in ("msyh.ttc", "segoeui.ttf"):
            p = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if p.exists():
                QFontDatabase.addApplicationFont(str(p))
    apply_theme(app)
    board = BlackboardWindow(engine)
    # Opening a live demonstration generates it once, while revisiting a finished
    # design reuses the lesson's cached result rather than billing another call.
    original_board = board._board
    board._board = {"created": 999, "mode": "ai"}
    with patch.object(config, "OFFLINE", False), patch.object(providers, "configured", return_value=True), \
            patch.object(board, "generate_visual") as prepare:
        board.maybe_generate_visual()
        board.maybe_generate_visual()
        assert prepare.call_count == 1
        board._board = {"created": 1000, "mode": "ai", "visualization": {"design_version": 2}}
        board.maybe_generate_visual()
        assert prepare.call_count == 1
    board._board = original_board
    board.generate()
    wait_ui(app, lambda: not board._busy)
    assert board._board and len(engine.blackboards) == 1
    assert awareness.recent()[-1]["kind"] == "board"
    assert blackboard.snapshot(engine)["previous"]["title"] == board._board["title"]
    board.jump_source("T1")
    board.render(board._board)  # Rendering while citation highlight timer is live must be safe.
    archive_stamp = store.save_lesson(engine.title, [], [], blackboards=engine.blackboards)
    assert store.get_lesson(archive_stamp)["blackboards"][0]["sources"]
    archive = BlackboardWindow(archived=engine.blackboards)
    assert not archive.active() and not archive.composer.isVisible()
    print("PASS board generation, source interaction and read-only course archive")

    # A capture uses the existing annotation tool; confirming attaches but never sends.
    capture_args = {}
    def fake_capture(**kwargs):
        capture_args.update(kwargs)
        return True
    with patch.object(snip, "start_circle_ask", side_effect=fake_capture):
        board.capture()
    image = QPixmap(560, 290)
    image.fill(QColor("#FCFAF3"))
    painter = QPainter(image)
    painter.setPen(QColor("#253D33"))
    painter.setFont(QFont("Microsoft YaHei", 16))
    painter.drawText(QRect(30, 20, 500, 45), Qt.AlignLeft, "辛亥革命 · 关键节点")
    painter.setFont(QFont("Microsoft YaHei", 12))
    painter.drawText(QRect(30, 90, 500, 140), Qt.TextWordWrap, "1911.10.10  武昌起义\n\n多省相继宣布独立\n\n1912.02     清帝退位")
    painter.setPen(QPen(QColor("#C65B4C"), 3))
    painter.drawEllipse(22, 86, 430, 38)
    painter.end()
    before = len(engine.blackboards)
    capture_args["on_capture"](image, QRect(0, 0, 560, 290))
    assert board._capture and len(engine.blackboards) == before
    assert capture_args["confirm_text"] == "✓ 附到课堂黑板"
    print("PASS annotated capture attaches without automatic AI submission")

    class FakeScreen:
        def geometry(self):
            return QRect(0, 0, 800, 600)
        def grabWindow(self, _ident):
            pixmap = QPixmap(800, 600)
            pixmap.fill(QColor("white"))
            return pixmap
    attached, restored = [], []
    with patch.object(snip.QGuiApplication, "screenAt", return_value=FakeScreen()), patch.object(snip.QTimer, "singleShot", side_effect=lambda _delay, fn: fn()):
        assert snip.start_circle_ask(on_capture=lambda crop, rect: attached.append((crop, rect)), on_finish=lambda: restored.append(True), confirm_text="附到黑板")
        overlay = snip._alive[-1]
        path = QPainterPath()
        path.addEllipse(QRectF(100, 200, 180, 60))
        overlay.strokes.append({"tool": "pen", "color": "#FF0000", "width": 6, "path": path})
        overlay._commit()
        assert not snip._busy and attached and restored
        crop_image = attached[0][0].toImage()
        assert any(crop_image.pixelColor(x, 48).red() > 200 and crop_image.pixelColor(x, 48).green() < 80 for x in range(crop_image.width()))
        assert snip.start_circle_ask(on_capture=lambda *_: (_ for _ in ()).throw(AssertionError("cancel submitted image")))
        snip._alive[-1]._cancel()
        assert not snip._busy
    print("PASS real annotation crop, custom capture routing and cancel cleanup")

    entered, release = threading.Event(), threading.Event()
    def delayed(*args):
        entered.set()
        release.wait(2)
        return visual
    with patch.object(blackboard, "generate_board", side_effect=delayed):
        board.generate()
        assert entered.wait(1)
        engine.active = False
        board.sync_lesson()
        release.set()
        wait_ui(app, lambda: not board._busy)
        app.processEvents()
    assert len(engine.blackboards) == before and not board.generate_btn.isEnabled()
    engine.session += 1
    board.sync_lesson()
    assert board._capture is None and not board.capture_btn.isEnabled()
    print("PASS class-end cancellation, late result rejection and new-course isolation")

    library = KnowledgeLibrary()
    library.title_edit.setText("课前笔记")
    library.note_edit.setPlainText("武昌起义与清帝退位是不同的时间节点。")
    assert library.save_note()
    count = len(knowledge.documents())
    library.note_edit.setPlainText("武昌起义与清帝退位是不同的时间节点。复习时分清阶段。")
    assert library.save_note() and len(knowledge.documents()) == count
    library.search.setText("找不到的资料")
    assert all(library.sources.item(i).isHidden() for i in range(library.sources.count()))
    print("PASS preparation library editing, save state and search")

    from echo.widgets.floating_window import FloatingWindow
    from echo.backend.engine import EchoReport
    mock_window = SimpleNamespace(echo=SimpleNamespace(title=engine.title), _toast=lambda message: (_ for _ in ()).throw(AssertionError(message)))
    FloatingWindow._save_lesson(mock_window, EchoReport([], [], from_mock=True, blackboards=[local]))
    saved = store.list_lessons()[0]
    assert saved["blackboards"] and not saved["skills_detail"] and not saved.get("graph")
    print("PASS real classroom boards survive summary fallback without saving mock skills")

    if "--shots" in sys.argv:
        out = ROOT / "artifacts"
        out.mkdir(exist_ok=True)
        demo = BlackboardWindow(sample_engine())
        demo._boards = [visual]
        demo._images[visual["created"]] = image
        demo.refresh_history()
        demo.render(visual)
        demo.show()
        app.processEvents()
        demo.grab().save(str(out / "echo-classroom-board.png"))
        demo.resize(820, 640)
        app.processEvents()
        demo.grab().save(str(out / "echo-classroom-board-compact.png"))
        library.search.clear()
        library.show()
        app.processEvents()
        library.grab().save(str(out / "echo-course-library.png"))
        demo.close()
    board.close()
    archive.close()
    library.close()
    print("All in-class blackboard checks passed; no real API requests or user data changes.")
