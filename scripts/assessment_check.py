"""Isolated assessment contract and Qt interaction checks; no paid model calls."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ECHO_OFFLINE"] = "1"
from echo.backend import paths
folder = tempfile.mkdtemp(prefix="echo-assessment-")
paths.config_dir = lambda: folder
from echo.backend import assessment as a, awareness, config, practice, prompts, quiz

questions = [
    dict(type="single_choice", question="2 + 3 = ?", options=["A. 5", "B. 6"], answer="A", explain="将两个数相加得到 5。"),
    dict(type="fill_blank", question="三角形内角和是 ____ 度。", answer="180", rubric="填出 180 度", explain="过顶点作底边平行线，可将三个内角拼成平角，所以内角和为 180 度。"),
    dict(type="true_false", question="所有正方形都是矩形。", answer=True, explain="正方形有四个直角，满足矩形定义；边长相等是额外条件。"),
    dict(type="matching", question="将图形与特征连线。", left=["正方形", "等边三角形", "圆"], right=["三边相等", "到圆心等距", "四边相等且四个直角"], answer=[2, 0, 1], explain="按定义判断：正方形有四个直角，等边三角形三边等长，圆上的点到圆心等距。"),
    dict(type="short_answer", question="为什么正方形属于矩形？", answer="因为它有四个直角，满足矩形的定义。", rubric="四个直角；满足矩形定义", explain="矩形的定义是有一个角为直角的平行四边形；正方形满足这一条件。"),
]
paper = a.clean_questions({"questions": questions}, 5)
assert len(paper) == 5
assert paper[2]["answer"] == "A"
assert a.clean_question(dict(questions[0], explain="")) is None
assert a.clean_question(dict(questions[0], answer="D")) is None
assert a.clean_question(dict(questions[3], answer=[0, 0, 1])) is None
assert a.local_grade(paper[0], "A")["score"] == 1
assert a.local_grade(paper[2], "B")["score"] == 0
assert a.local_grade(paper[3], [2, 1, 0])["score"] == 1 / 3
assert a.local_grade(paper[3], [-1, 0, 1])["status"] == "unanswered"
assert a.local_grade(paper[1], "一百八十度")["status"] == "pending"
assert a.local_grade(paper[1], "")["status"] == "unanswered"
assert practice.fallback_questions({"topic": "Echo", "missing": "电脑静音状态下，Echo 点我掉队了能不能找断点？"}) == []
assert a.clean_question(dict(questions[0], question="Echo需要获取电脑正在播放的声音还是你的键盘输入？")) is None
assert a.clean_question(dict(questions[0], question="Echo要能帮你找断点，前提是它需要获取什么？",
                             options=["A. 你的键盘输入", "B. 电脑正在播放的声音"], answer="B")) is None
awareness.note("qa", "我掉队了怎么用？", "播放网课一两分钟后再点 Echo")
assert "播放网课一两分钟" not in prompts.system("PRACTICE_SYSTEM", n=5, include_memory=False)
assert "播放网课一两分钟" not in prompts.system("ASSESSMENT_GRADE_SYSTEM", include_memory=False)


class FakeLLM:
    def json(self, system, user, **kwargs):
        assert "播放网课一两分钟" not in system
        self.system, self.user = system, user
        return {"grades": [{"id": 1, "score": 1, "feedback": "一百八十度与180度等价，数值和单位正确。"},
                           {"id": 4, "score": 0.5, "feedback": "提到了直角，还需说明有四个直角并满足矩形定义。"},
                           {"id": 99, "score": 1, "feedback": "无效题号"}]}


entries = [dict(paper[i], id=i, student_answer="一百八十度" if i == 1 else "它有直角") for i in (1, 4)]
assert a.grade_sync(entries) == {}
config.OFFLINE = False
llm = FakeLLM()
grades = a.grade_sync(entries, llm)
assert set(grades) == {1, 4} and grades[1]["score"] == 1 and grades[4]["status"] == "partial"


class QuestionsLLM:
    def json(self, system, user, **kwargs):
        assert "播放网课一两分钟" not in system
        assert "explain" in system and "matching" in system
        return {"questions": questions}


assert len(quiz.lesson_quiz_sync({"summary": "平面几何基础"}, 5, QuestionsLLM())) == 5
from unittest.mock import patch
with patch.object(practice, "LLM", return_value=QuestionsLLM()), patch.object(config, "llm_configured", return_value=True):
    assert len(practice.generate_sync({"topic": "平面几何", "step": "按图形定义分类"}, 5)) == 5
config.OFFLINE = True

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow, PRACTICE
app = QApplication([])
apply_theme(app)
w = FloatingWindow()
w._prac_item = {"topic": "数学 · 图形与定义"}
w._prac_request_id += 1
w._show_page(PRACTICE)
w._on_prac_done(paper)
w.show()
app.processEvents()
assert all(c._result.isHidden() for c in w._prac_cards)
assert all(q["explain"] for q in w._prac_qs)  # explanations ready before submission
radio = w._prac_cards[0]._radios[0]
QTest.mouseClick(radio, Qt.LeftButton, pos=radio.caption.geometry().center())
assert radio.isChecked(), "clicking the wrapped radio text must select its answer"
w._prac_cards[1]._edit.setText("一百八十度")
w._prac_cards[2]._radios[0].setChecked(True)
matching = w._prac_cards[3]._matching
for i, j in enumerate([2, 0, 1]):
    QTest.mouseClick(matching.left_buttons[i], Qt.LeftButton)
    QTest.mouseClick(matching.right_buttons[j], Qt.LeftButton)
assert matching.answers() == [2, 0, 1]
# Re-pairing frees the previous association instead of accepting duplicate right answers.
matching.select_left(0)
matching.select_right(0)
assert matching.answers() == [0, -1, 1]
for i, j in enumerate([2, 0, 1]):
    matching.select_left(i)
    matching.select_right(j)
w._prac_cards[4]._edit.setText("它有直角")
callbacks = []
original = a.grade_async
a.grade_async = lambda items, on_done: callbacks.append((items, on_done))
try:
    w._prac_submit()
    assert len(callbacks) == 1
    assert [entry["id"] for entry in callbacks[0][0]] == [1, 4]  # objective questions never sent to AI
    assert all(w._prac_grades[i]["score"] == 1 for i in (0, 2, 3))
    assert not w.btn_prac_submit.isEnabled()
    assert all(c._explain.text() for c in w._prac_cards)
    w._prac_submit()
    assert len(callbacks) == 1  # duplicate-click guard
    callbacks[0][1]({})
    app.processEvents()
    assert w.btn_prac_submit.isEnabled() and "重试" in w.btn_prac_submit.text()
    assert w._prac_answers[1] == "一百八十度"
    w._prac_submit()
    callbacks[1][1](grades)
    app.processEvents()
    assert not w.btn_prac_submit.isEnabled()
    assert "一百八十度与180度等价" in w._prac_cards[1]._explain.text()
    assert w._prac_grades[4]["status"] == "partial"
    old = w._prac_request_id
    w._prac_request_id += 1
    w._on_prac_done(paper)
    w._on_prac_graded((old, grades))
    assert not w._prac_submitted and w._prac_cards[1]._result.isHidden()
    # Render a real Qt card containing crossing connections, not an HTML mockup.
    output = Path(__file__).resolve().parents[1] / "artifacts"
    output.mkdir(exist_ok=True)
    preview = w._prac_card(3, paper[3])
    preview.setFixedWidth(360)
    preview.adjustSize()
    preview.show()
    app.processEvents()
    for i, j in enumerate([2, 0, 1]):
        preview._matching.select_left(i)
        preview._matching.select_right(j)
    app.processEvents()
    preview.grab().save(str(output / "assessment-matching.png"))
    preview.hide()
finally:
    a.grade_async = original
    w.echo.shutdown()
    w.hide()
print("PASS: five types, source isolation, prepared explanations, AI grading, retry, stale results, Qt matching")
