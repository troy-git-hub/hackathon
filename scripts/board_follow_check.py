"""Automatic topic boards, embedded diagram data, lesson export and cancellation."""
import copy
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ECHO_OFFLINE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from echo.backend import paths
folder = tempfile.mkdtemp(prefix="echo-follow-")
paths.config_dir = lambda: folder
from PyQt5.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
from PyQt5.QtWidgets import QApplication
from echo.backend import blackboard, store
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow


def wait(app, predicate):
    end = time.monotonic() + 3
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "operation timed out"


app = QApplication([])
apply_theme(app)
w = FloatingWindow()
w.echo.engine.active = True
# Use actual engine session and lock, with isolated classroom content.
from echo.backend.engine import Line
from echo.mock_data import Concept
concept = Concept(concepts=[], prerequisites=[], timecode="00:20", topic="三角形内角和", summary="三个内角的和为180度")
w.echo.engine.entries = [SimpleNamespace(t=20, concept=concept)]
w.echo.engine.lines = [Line(5, "上一知识点，不能混到新板书"), Line(25, "过顶点作底边的平行线，将三个内角移到一个平角上，内角和为180度。")]
# has_llm is read-only, backed by llm. Our generation is stubbed below.
w.echo.engine.llm = object()
calls = []


def generate(moment, focus, image=None):
    calls.append((copy.deepcopy(moment), focus, image))
    data = {"title": moment["current"], "gist": "三个内角可拼成平角", "pattern": "推导链",
            "steps": [{"heading": "作平行线", "body": "过顶点作平行线。", "evidence": ["T1"]}],
            "inline_html": '<button onclick="this.textContent=\'180度\'">拼成平角</button>'}
    result = blackboard.normalize(data, moment["sources"])
    result.update(created=moment["created"], course=moment["title"], focus=focus,
                  sources=moment["sources"], mode="ai")
    return result


with patch.object(blackboard, "generate_board", side_effect=generate):
    w._on_concept(concept)  # No blackboard button click is required.
    board = w._studio
    assert not board.isVisible() and board.follow_toggle.isChecked() and not hasattr(board, "export_btn")
    board.follow_current()
    board._topic_gate.since -= 3
    board.follow_current()
    wait(app, lambda: len(board._boards) == 1)
    assert calls[0][2] is None and len(calls[0][0]["sources"]) == 1
    assert "上一知识点" not in calls[0][0]["sources"][0]["text"]
    assert board._board["trigger"] == "topic" and board._board.get("inline_visual")
    assert not board.isVisible() and board._inline_view is None  # hidden auto never launches a browser
    board._topic_gate.last_attempt -= 31
    board.follow_current()
    assert len(calls) == 1  # same knowledge point is not billed repeatedly
    board.focus.setText("用HTML解释为什么是180度")
    board.generate()
    wait(app, lambda: len(board._boards) == 2)
    assert board._board["trigger"] == "manual" and board._board["inline_visual"]["html"]
    assert "用HTML" in calls[-1][1]
    assert not board.focus.text()
    # New knowledge point can produce its own board after the bounded interval.
    next_concept = Concept(concepts=[], prerequisites=[], timecode="00:40", topic="外角和", summary="三角形外角和为360度")
    w.echo.engine.entries.append(SimpleNamespace(t=40, concept=next_concept))
    w.echo.engine.lines.append(Line(45, "三角形的每个顶点取一个外角，外角和为360度。"))
    board._follow_hold_until = 0
    board._topic_gate.last_attempt -= 31
    board.follow_current()
    board._topic_gate.since -= 3
    board.follow_current()
    wait(app, lambda: len(board._boards) == 3)
    assert board._board["current_topic"] == "外角和"
    assert len(w.echo.engine.blackboards) == 3

# All boards, not just the selected one, survive storage and export.
ts = store.save_lesson("几何课", [], [], summary="几何课总结", blackboards=board._boards)
saved = store.get_lesson(ts)
assert len(saved["blackboards"]) == 3 and saved["blackboards"][0]["inline_visual"]
notes = blackboard.lesson_markdown("几何课", "本节总结", ["内角和"], saved["blackboards"])
assert "本节总结" in notes and "板书 3" in notes and "onclick" in notes
destination = Path(folder) / "lesson.md"
with patch("echo.widgets.floating_window.QFileDialog.getSaveFileName", return_value=(str(destination), "Markdown (*.md)")):
    w._export_lesson_notes(saved)
assert "板书 3" in destination.read_text(encoding="utf-8")
destination = Path(folder) / "lesson.html"
with patch("echo.widgets.floating_window.QFileDialog.getSaveFileName", return_value=(str(destination), "HTML (*.html)")):
    w._export_lesson_notes(saved)
assert 'sandbox="allow-scripts"' in destination.read_text(encoding="utf-8")

# A late answer from a previous topic is archived but cannot replace the current board.
old = copy.deepcopy(board._boards[0])
old.update(created=time.time(), trigger="topic")
board._request += 1
board.finish(board._request, old, "")
assert board._board["current_topic"] == "外角和"
count = len(w.echo.engine.blackboards)
w.echo.engine.session += 1
board.finish(board._request, old, "")
assert len(w.echo.engine.blackboards) == count
board.sync_lesson()
assert not board.generate_btn.isEnabled()
board._timer.stop()
w.echo.engine.active = False
w.echo.engine.llm = None
w.echo.shutdown()
w.hide()
print("PASS hidden automatic boards, topic deduplication, current sources, HTML question data, course isolation and full-lesson export")
