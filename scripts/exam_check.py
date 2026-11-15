"""Isolated exam recovery, grading and exit checks; no model/network calls."""
import copy
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['ECHO_OFFLINE'] = '1'
from echo.backend import paths
folder = tempfile.TemporaryDirectory(prefix='echo-exam-')
paths.config_dir = lambda: folder.name
from PyQt5.QtCore import QSettings, Qt
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder.name)
from PyQt5.QtWidgets import QApplication, QMessageBox
from echo.backend import exam
from echo.widgets.exam_window import ExamWindow, open_exam_window

who = ['student-a']
exam.account.current_user = lambda: {'id': who[0]}
exam.chapters = lambda engine=None: []
app = QApplication.instance() or QApplication([])

def paper():
    return dict(schema='echo.exam/1', id='exam-1', owner=who[0], title='综合试卷', chapters=[],
                duration_seconds=300, anti_cheat=False, created_at=time.time(), started_at=time.time(),
                status='active', answers={'1':'A','2':'一百八十度','3':[0,1]}, events=[], results={},
                questions=[
                    dict(id='1', type='single_choice', question='相加等于几？', options=['5','6'], answer='A', explain='相加得5。', points=40),
                    dict(id='2', type='fill_blank', question='内角和？', answer='180', explain='内角和为180度。', points=40),
                    dict(id='3', type='matching', question='配对', left=['甲','乙'], right=['一','二'], answer=[0,1], explain='按对应关系配对。', points=20)])

p = paper(); exam.save(p)
public = exam.public_paper(p)
assert all('answer' not in q and 'explain' not in q for q in public['questions'])
with patch.object(exam, 'save', side_effect=OSError('disk full')):
    before = copy.deepcopy(p)
    try: exam.submit(p)
    except OSError: pass
    else: raise AssertionError('save failure was swallowed')
    assert p == before
exam.submit(p)
assert p['results']['1']['score'] == 1 and p['results']['3']['score'] == 1
assert p['results']['2']['status'] == 'pending' and p['results']['2']['score'] is None
assert exam.load()[0]['status'] == 'submitted'
who[0] = 'student-b'; assert exam.load() == []
who[0] = 'student-a'

w = open_exam_window(); assert open_exam_window() is w
p = paper(); exam.save(p); w.start(p); w.show(); app.processEvents()
w.timer.stop()
with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as ask:
    assert not w.close() and ask.call_count == 1
assert w.paper['status'] == 'active'
with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(exam, 'save', side_effect=OSError('disk full')):
    w.submit()
assert w.paper['status'] == 'active' and not w._submitting
with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes): w.submit()
assert w.paper['status'] == 'submitted' and not w.timer.isActive()
assert '60 / 60' in w.message.text() and '1 题待批改' in w.message.text()
w.close()

w = ExamWindow(); w.start(paper()); w.timer.stop()
w.paper['anti_cheat'] = True
w.record_focus_loss(); w.record_focus_loss()
assert len(w.paper['events']) == 1
w._focus_lost = False; w.record_focus_loss(); assert len(w.paper['events']) == 2
before = copy.deepcopy(w.paper)
with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as ask, patch.object(exam, 'save', side_effect=OSError('disk full')):
    w.show(); assert not w.close() and ask.call_count == 1
assert w.paper == before
with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as ask:
    w.reject(); assert ask.call_count == 1 and not w.isVisible()
assert exam.load()[0]['events'][-1]['type'] == 'exit'

w = ExamWindow(); w.start(paper()); w.show(); who[0] = 'student-b'; w.tick()
assert not w.stack.isEnabled() and not w.timer.isActive()
with patch.object(exam, 'save', side_effect=AssertionError('must not write after account switch')):
    assert w.close()
who[0] = 'student-a'
w = ExamWindow(); expired = paper(); expired['started_at'] -= 500
w.start(expired)
assert w.paper['status'] == 'submitted' and not w.timer.isActive()
w.close()

broken = paper(); broken['duration_seconds'] = float('nan')
w = ExamWindow(); w.start(broken); assert w.paper is None and '无法恢复' in w.message.text(); w.close()
exam._path().write_text('[{}]', encoding='utf-8')
try: exam.load()
except ValueError: pass
else: raise AssertionError('broken archive accepted')
assert exam._path().read_text() == '[{}]'
print('PASS: exam atomic submit/retry, pending grading, account isolation, exit confirmation, focus dedup, expiry recovery, corrupt archive')
