"""
Echo - 后端 ↔ PyQt 桥接
引擎回调发生在后台线程，这里转成 Qt 信号，UI 槽函数会自动在主线程执行。

用法：
    self.echo = EchoBridge()
    self.echo.transcript.connect(...)
    self.echo.start()
    self.echo.feedback("lost")
"""
from PyQt5.QtCore import QObject, pyqtSignal

from echo.backend import config
from echo.backend.engine import EchoEngine
from echo.backend.sources import make_source


class EchoBridge(QObject):
    transcript = pyqtSignal(str, str)        # timecode, text
    concept = pyqtSignal(object)             # Concept
    breakpoint = pyqtSignal(object, object)  # BreakPoint, List[Concept]（含断点的时间轴片段）
    echo = pyqtSignal(object)                # EchoReport
    status = pyqtSignal(str)                 # listening / analyzing / summarizing / loading_asr / done
    error = pyqtSignal(str)

    def __init__(self, source=None, parent=None):
        super().__init__(parent)
        self.source_kind = (source or config.SOURCE).lower()
        interval = config.DEMO_LINE_INTERVAL * 3 if self.source_kind == "demo" else None
        self.engine = EchoEngine(
            on_transcript=self.transcript.emit,
            on_concept=self.concept.emit,
            on_breakpoint=self.breakpoint.emit,
            on_echo=self.echo.emit,
            on_status=self.status.emit,
            on_error=self.error.emit,
            concept_interval=interval,
        )
        self.source = None

    @property
    def total_seconds(self):
        return getattr(self.source, "total", 0) or 0

    def start(self):
        if self.source:
            self.source.stop()
        self.engine.start()
        self.source = make_source(self.engine, self.source_kind)
        self.source.start()

    def feedback(self, kind: str):
        self.engine.feedback(kind)

    def end_lesson(self):
        if self.source:
            self.source.stop()
        self.engine.end_lesson()

    def shutdown(self):
        if self.source:
            self.source.stop()
        self.engine.shutdown()
