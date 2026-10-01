"""
Echo - 后端 ↔ PyQt 桥接
引擎回调发生在后台线程，这里转成 Qt 信号，UI 槽函数会自动在主线程执行。

课程隔离：引擎的所有事件都带 session 号，先经内部信号排队到主线程，
在主线程再核对一次——重开课程前已经排进 Qt 队列、但还没送到的旧事件也会被丢掉。

用法：
    self.echo = EchoBridge()
    self.echo.transcript.connect(...)
    self.echo.start()
    self.echo.feedback("lost")
"""
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

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
    mode = pyqtSignal(str, bool)             # 音频来源 system/mic/demo, 是否离线

    _event = pyqtSignal(int, str, object)    # 内部：session, 事件名, 参数元组

    def __init__(self, source=None, parent=None):
        super().__init__(parent)
        self.source_kind = (source or config.SOURCE).lower()
        self._event.connect(self._dispatch)
        self.engine = EchoEngine(
            on_event=lambda sid, name, *args: self._event.emit(sid, name, args),
        )
        self._apply_interval()
        self.source = None

    @pyqtSlot(int, str, object)
    def _dispatch(self, sid, name, args):
        if sid != self.engine.session:      # 上一节课的迟到事件
            return
        getattr(self, name).emit(*args)
        if (name == "error" and config.AUTO_DEMO and self.source_kind != "demo"
                and str(args[0]).startswith("音频采集失败")):
            self.use_demo()                 # 现场声卡出问题 → 自动改放示例课，演示不中断

    def _apply_interval(self):
        # 示例讲稿时间戳是压缩过的，抽 concept 也跟着加快
        self.engine.concept_interval = (config.DEMO_LINE_INTERVAL * 3 if self.source_kind == "demo"
                                        else config.CONCEPT_INTERVAL)

    @property
    def offline(self):
        return not self.engine.has_llm

    @property
    def session(self):
        return self.engine.session

    @property
    def total_seconds(self):
        return getattr(self.source, "total", 0) or 0

    def start(self):
        """开始（或重新开始）一节课：停掉旧音频来源，新 session，新来源。"""
        if self.source:
            self.source.stop()
        self.engine.start()
        self.source = make_source(self.engine, self.source_kind)
        self.source.start()
        self.mode.emit(self.source_kind, self.offline)

    # ---------- 现场兜底 ----------
    def use_demo(self, offline: bool = None):
        """一键切到示例讲稿并重新开课；offline=True 同时断开 LLM（断网时用）。"""
        self.switch_source("demo", offline)

    def switch_source(self, kind: str, offline: bool = None):
        if offline is not None:
            self.engine.set_offline(offline)
        self.source_kind = kind.lower()
        self._apply_interval()
        self.start()

    def set_offline(self, offline: bool):
        """只切 LLM 在线/离线，不重开课程。"""
        self.engine.set_offline(offline)
        self.mode.emit(self.source_kind, self.offline)

    def feedback(self, kind: str):
        self.engine.feedback(kind)

    def mark_fixed(self):
        """学生点了「✓ 补上了，继续听课」。"""
        self.engine.mark_fixed()

    def end_lesson(self):
        if self.source:
            self.source.stop()
        self.engine.end_lesson()

    def shutdown(self):
        if self.source:
            self.source.stop()
        self.engine.shutdown()
