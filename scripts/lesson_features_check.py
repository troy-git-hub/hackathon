"""Isolated checks for captions, shared request spacing and capture exclusion."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'windows' if '--native-capture' in sys.argv else 'offscreen'
os.environ['ECHO_OFFLINE'] = '1'
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import QApplication, QWidget
from echo.backend import paths
from echo.backend.context import AutomaticBudget, bounded_text, recent_turns


def wait(app, seconds=.25):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(.01)


def main():
    with tempfile.TemporaryDirectory(prefix='echo-lesson-features-') as directory:
        paths.config_dir = lambda: directory
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, directory)
        budget = AutomaticBudget()
        assert budget.reserve('concept', 0)
        assert not budget.reserve('board', 46)
        assert not budget.reserve('concept', 49)
        assert not budget.reserve('concept', 50)  # fairness: the board is waiting
        assert budget.reserve('board', 50)
        assert not budget.reserve('concept', 51)
        assert budget.reserve('concept', 100)
        assert len(bounded_text('a' * 20000)) == 6000
        history = []
        for i in range(12):
            history += [{'role': 'user', 'content': [{'type': 'text', 'text': f'问题{i}'}, {'type': 'image_url', 'image_url': {'url': 'SECRET_IMAGE'}}]},
                        {'role': 'assistant', 'content': '讲解' * 1000}]
        retained = recent_turns(history)
        assert len(retained) <= 8 and sum(len(m['content']) for m in retained) <= 6000
        assert 'SECRET_IMAGE' not in str(retained) and retained[-2]['content'] == '问题11'
        from echo.backend.vision import VisionChat
        import io
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(2,2),'white').save(image,'PNG')
        chat = VisionChat(image.getvalue(), context='当前知识点：函数')
        first = chat._messages('为什么？')
        assert '当前知识点' in first[0]['content']
        chat.history = recent_turns(first[1:] + [{'role': 'assistant', 'content': '解释'}])
        follow = chat._messages('换个例子')
        assert str(follow).count('data:image/') == 1
        assert '当前知识点' in follow[0]['content']

        from echo.backend.engine import EchoEngine
        engine = EchoEngine(use_llm=False)
        engine.active = True
        engine.add_transcript('老师讲解重点' * 120, t=1)
        class Stop:
            def __init__(self): self.calls = 0
            def wait(self, seconds):
                self.calls += 1
                return self.calls > 1
        class Pool:
            calls = []
            def submit(self, *args): self.calls.append(args)
            def shutdown(self, **kwargs): pass
        engine._pool.shutdown(wait=False)
        engine._pool = Pool()
        engine._last_extract = 490
        with patch('echo.backend.engine.time.time', return_value=500), patch('echo.backend.config.CHECKIN', False):
            engine._tick_loop(engine.session, Stop())
        assert not engine._pool.calls  # 400+ characters cannot bypass the interval
        with patch('echo.backend.engine.time.time', return_value=550), patch('echo.backend.config.CHECKIN', False):
            engine._tick_loop(engine.session, Stop())
            engine._tick_loop(engine.session, Stop())
        assert len(engine._pool.calls) == 1  # queued/retrying work cannot flood requests
        from echo.backend.engine import _ConceptEntry
        from echo.mock_data import Concept
        engine.entries = [_ConceptEntry(i, Concept(timecode=f'00:{i:02d}', topic=f'知识点{i}', summary='说明' * 100,
                                                   concepts=[], prerequisites=[])) for i in range(50)]
        engine.entries[15].is_bp = True
        timeline = engine._timeline_text()
        assert len(timeline) <= 6000 and '知识点15' in timeline and '知识点49' in timeline

        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        app = QApplication([])
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.widgets.subtitles import SubtitleWindow
        closed = []
        subtitle = SubtitleWindow(engine, lambda: closed.append(True))
        subtitle.show()
        subtitle.update_caption('00:12', '<b>公式</b>是课堂原话，不执行HTML。')
        assert subtitle.caption.textFormat() == Qt.PlainText and subtitle.isVisible()
        assert '<b>' in subtitle.caption.text()
        subtitle.change_size(100)
        assert subtitle.point_size == 29
        if '--native-capture' in sys.argv:
            (ROOT / 'artifacts').mkdir(exist_ok=True)
            wait(app)
            subtitle.grab().save(str(ROOT / 'artifacts/echo-subtitles.png'))
        engine.session += 1
        assert not subtitle.check_lesson() and not subtitle.isVisible()
        subtitle.close()
        assert closed

        from echo.widgets.capture_exclusion import CaptureExclusion, native_affinity
        background = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        background.setStyleSheet('background:#22aa55')
        background.setGeometry(60, 80, 420, 240)
        background.show()
        overlay = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        overlay.setStyleSheet('background:#dd3355')
        overlay.setGeometry(140, 140, 180, 100)
        overlay.show()
        wait(app)
        with patch('echo.widgets.capture_exclusion.native_affinity', return_value=None):
            fallback = CaptureExclusion([overlay])
            assert not overlay.isVisible()
            fallback.restore()
            assert overlay.isVisible()
        wait(app)
        if '--native-capture' in sys.argv:
            original = native_affinity(overlay)
            screen = QApplication.screenAt(overlay.geometry().center())
            def pixel():
                p = overlay.geometry().center() - screen.geometry().topLeft()
                return screen.grabWindow(0, p.x(), p.y(), 1, 1).toImage().pixelColor(0, 0).name()
            assert pixel() == '#dd3355', pixel()
            excluded = CaptureExclusion([overlay])
            wait(app, .4)
            assert overlay.isVisible() and native_affinity(overlay) == 0x11
            assert pixel() == '#22aa55', 'Capture exclusion did not reveal the underlying test content: ' + pixel()
            excluded.restore()
            wait(app)
            assert native_affinity(overlay) == original and pixel() == '#dd3355'
            from echo.widgets.floating_window import FloatingWindow
            from echo.widgets.blackboard import BlackboardWindow
            window = FloatingWindow()
            window.echo.engine.active = True
            window.subtitle_btn.setChecked(True)
            window._sync_subtitles('00:30', '这是课堂字幕，不增加模型请求。')
            assert window._subtitles.isVisible()
            window.hide()
            assert window._subtitles.isVisible()  # independent from the main card
            window.show()
            board = BlackboardWindow(window.echo.engine)
            board.show()
            wait(app)
            real = CaptureExclusion([window, board, window._subtitles])
            assert not real.hidden, 'Expected native exclusion on actual Echo windows'
            assert all(widget.isVisible() and native_affinity(widget) == 0x11 for widget in (window, board, window._subtitles))
            real.restore()
            window.echo.engine.active = False
            window._sync_subtitles()
            assert not window._subtitles.isVisible()
            board._timer.stop()
            board.close()
            window.close()
            from echo.widgets.export_options import ExportOptionsDialog
            options = ExportOptionsDialog()
            options.show()
            wait(app)
            options.grab().save(str(ROOT / 'artifacts/echo-personal-export-options.png'))
            options.close()
            print('PASS native capture: Echo remains visible; capture shows underlying content')
        overlay.close()
        background.close()
        engine.shutdown()
    print('PASS captions / local context bounds / 50s fair scheduling / no character bypass / capture fallback')


if __name__ == '__main__':
    main()
