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
import logging
import threading

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from echo.backend import config, quiz
from echo.backend.engine import EchoEngine
from echo.backend.sources import make_source

log = logging.getLogger("echo.bridge")


class EchoBridge(QObject):
    transcript = pyqtSignal(str, str)        # timecode, text
    concept = pyqtSignal(object)             # Concept
    breakpoint = pyqtSignal(object, object)  # BreakPoint, List[Concept]（含断点的时间轴片段）
    echo = pyqtSignal(object)                # EchoReport
    status = pyqtSignal(str)                 # listening / analyzing / summarizing / loading_asr / done
    error = pyqtSignal(str)
    thinking = pyqtSignal(bool, str)         # active, preview_text — AI 实时思考状态
    level = pyqtSignal(float)                # 真实音频响度 0..1（声纹反馈）
    mode = pyqtSignal(str, bool)             # 音频来源 system/mic, 是否离线
    checkin = pyqtSignal(object)             # 课堂抽问题 dict：topic/question/options/tc
    checkin_result = pyqtSignal(object)      # 作答结果 dict：result/choice_text/answer_text/explain
    quiz_ready = pyqtSignal(object)          # 课后练习题 list[dict]（与 practice.py 的形状一致）

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

    def _apply_interval(self):
        self.engine.concept_interval = config.CONCEPT_INTERVAL

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

    def set_offline(self, offline: bool):
        """只切 LLM 在线/离线，不重开课程。"""
        self.engine.set_offline(offline)
        self.mode.emit(self.source_kind, self.offline)

    def feedback(self, kind: str):
        self.engine.feedback(kind)

    def set_title(self, name: str):
        """给这节课命名。"""
        self.engine.set_title(name)

    def clear_title(self):
        self.engine.clear_title()

    @property
    def title(self):
        return self.engine.title

    def mark_fixed(self):
        """学生点了「✓ 补上了，继续听课」。"""
        self.engine.mark_fixed()

    def mark_self(self):
        """学生点了「我自己看看」。"""
        self.engine.mark_self()

    def answer_checkin(self, choice: int):
        """学生答了课堂抽问题（choice 为选项下标）。返回作答结果，当前没有待答题返回 None。"""
        return self.engine.answer_checkin(choice)

    def skip_checkin(self):
        """学生把抽问关掉了。"""
        self.engine.skip_checkin()

    def make_lesson_quiz(self, lesson: dict, n: int = 4):
        """按一节课的要点出课后练习题，出好后发 quiz_ready(list)。

        和「照错题出题」是两回事：这里覆盖整节课的知识点，给课后巩固用。
        出题可能要十几秒，所以放后台线程；期间重开课程就丢弃结果。
        """
        sid = self.engine.session

        def _run():
            try:
                questions = quiz.lesson_quiz_sync(lesson, n)
            except Exception as e:
                log.warning("课后练习出题失败: %s", e)
                return
            if questions and sid == self.engine.session:
                self.quiz_ready.emit(questions)

        threading.Thread(target=_run, daemon=True, name="echo-lessonquiz").start()

    def end_lesson(self):
        if self.source:
            self.source.stop()
        self.engine.end_lesson()

    def shutdown(self):
        if self.source:
            self.source.stop()
        self.engine.shutdown()
