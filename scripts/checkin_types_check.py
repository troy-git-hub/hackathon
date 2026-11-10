"""Classroom multi-type path, semantic grading, retry/cancel and long-text Qt layout."""
import copy
import os
import re
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
folder = tempfile.mkdtemp(prefix="echo-checkin-types-")
paths.config_dir = lambda: folder
from echo.backend import quiz, assessment
from echo.backend.engine import EchoEngine, Line
from echo.mock_data import Concept

base = {"topic": "三角形", "explain": "三个内角可拼成一个平角，内角和为180度。", "rubric": "角度正确"}
fixtures = {
    "single_choice": dict(base, type="single_choice", question="三角形内角和？", options=["A. 180度", "B. 360度"], answer="A"),
    "true_false": dict(base, type="true_false", question="三角形内角和等于180度。", answer=True),
    "fill_blank": dict(base, type="fill_blank", question="三角形内角和是 ____ 度。", answer="180"),
    "matching": dict(base, type="matching", question="将图形与边数连线。", left=["三角形", "四边形"], right=["4", "3"], answer=[1, 0]),
    "short_answer": dict(base, type="short_answer", question="为什么三个内角之和为180度？", answer="作平行线，三个内角可拼成平角。"),
}


class FakeLLM:
    def json(self, system, user, **kwargs):
        kind = re.search(r"本题必须使用题型 (\w+)", user).group(1)
        assert "不得替换为单选" in user and "explain" in system
        return copy.deepcopy(fixtures[kind])


def wait(predicate, app=None):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        if app:
            app.processEvents()
        time.sleep(.01)
    assert predicate(), "operation timed out"


eng = EchoEngine(use_llm=False)
eng.active = True
eng.llm = FakeLLM()
concept = Concept(timecode="00:10", topic="三角形", concepts=[], prerequisites=[], summary="内角和")
eng.entries = [SimpleNamespace(t=10, concept=concept, is_bp=False, fixed=False)]
eng.lines = [Line(10, "过顶点作底边平行线，三个内角可以拼成平角，内角和为180度。")]
answers = {"single_choice": 0, "true_false": 0, "fill_blank": "一百八十", "matching": [1, 0], "short_answer": "平行线移角得到平角"}
with patch.object(assessment, "grade_sync", return_value={0: {"status": "correct", "score": 1, "feedback": "表达等价，关键步骤正确。"}}) as grader:
    for kind in quiz.CHECKIN_TYPES:
        eng._ask_checkin(eng.session)
        q = eng.pending_checkin
        assert q["type"] == kind and q["explain"]
        count = len(eng.checkins)
        eng.answer_checkin(answers[kind])
        wait(lambda: len(eng.checkins) == count + 1)
        assert eng.checkins[-1]["result"] == quiz.RIGHT and eng.pending_checkin is None
    assert grader.call_count == 2  # only written answers call AI

# A failed grader leaves the original answer retryable, never records a wrong answer.
q = quiz._clean_checkin(fixtures["fill_blank"])
eng.pending_checkin = q
count = len(eng.checkins)
with patch.object(assessment, "grade_sync", return_value={}):
    eng.answer_checkin("一百八十")
    wait(lambda: not q.get("_grading"))
assert eng.pending_checkin is q and len(eng.checkins) == count
with patch.object(assessment, "grade_sync", return_value={0: {"status": "partial", "score": .5, "feedback": "部分正确，补充单位。"}}):
    eng.answer_checkin("一百八十")
    wait(lambda: eng.pending_checkin is None)
assert eng.checkins[-1]["result"] == quiz.UNSURE

entered, release = threading.Event(), threading.Event()
def slow_grade(*args, **kwargs):
    entered.set()
    release.wait(2)
    return {0: {"status": "correct", "score": 1, "feedback": "正确"}}
eng.pending_checkin = quiz._clean_checkin(fixtures["fill_blank"])
count = len(eng.checkins)
with patch.object(assessment, "grade_sync", side_effect=slow_grade):
    eng.answer_checkin("180")
    assert entered.wait(1)
    assert eng.answer_checkin("180") is None  # duplicate submit guard
    eng.skip_checkin()
    release.set()
    eng._pool.submit(lambda: None).result(2)
assert len(eng.checkins) == count
eng.llm = None
eng.active = False
eng.shutdown()

from PyQt5.QtCore import QSettings, Qt
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow, LISTEN
app = QApplication([])
apply_theme(app)
w = FloatingWindow()
w.echo.engine.active = True
w._show_page(LISTEN)
w.show()
card = w.checkin_card
long = quiz._clean_checkin(dict(fixtures["single_choice"],
    question="老师刚讲的，鲁迅在日本看到幻灯片之后为什么决定弃医从文？" * 3,
    options=["A. " + "他看到围观者的麻木，认识到还需要改变国民的精神状态。" * 3,
             "B. " + "他觉得学医学不下去了，所以改行写作。" * 3]))
w._on_checkin(long)
app.processEvents()
for _ in range(3):
    app.processEvents()
assert w.stack.width() == 340
assert card.width() <= 340 and card.x() >= 0
assert card.question_lbl.wordWrap()
for btn in card._option_buttons:
    assert btn.width() <= card.width()
    assert btn.caption.height() >= btn.caption.heightForWidth(btn.caption.width()), (btn.caption.size(), btn.caption.heightForWidth(btn.caption.width()))
    assert btn.caption.height() > 30
submitted = []
card.submitted.disconnect()
card.submitted.connect(submitted.append)
for kind in ("fill_blank", "short_answer", "matching"):
    card.ask(quiz._clean_checkin(fixtures[kind]))
    app.processEvents()
    if card._input:
        card._input.setText("180")
    else:
        card._matching.select_left(0)
        card._matching.select_right(1)
        card._matching.select_left(1)
        card._matching.select_right(0)
    QTest.mouseClick(card._submit, Qt.LeftButton)
    assert submitted[-1] == ([1, 0] if kind == "matching" else "180")
    card.show_result({"result": "pending", "retry": True, "explain": "预先生成的解析"})
    assert card._submit.isEnabled()
    before = len(submitted)
    QTest.mouseClick(card._submit, Qt.LeftButton)
    assert len(submitted) == before + 1
    assert not card.note_lbl.isVisible()  # pending isn't marked as a mistake
w._on_checkin(long)
w._fit()
app.processEvents()
out = Path(__file__).resolve().parents[1] / "artifacts"
out.mkdir(exist_ok=True)
w.grab().save(str(out / "checkin-long-text.png"))
w.echo.engine.active = False
w.echo.shutdown()
w.hide()
print("PASS rotating classroom types, objective/AI grading split, retry/cancel and real long-text wrapping")
