"""A lesson-only, source-backed board beside the course, with optional screen annotations."""
import copy
import threading
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt5 import sip
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                             QVBoxLayout, QPushButton, QScrollArea, QWidget,
                             QLineEdit, QComboBox, QProgressBar, QFileDialog,
                             QSplitter, QSizePolicy, QCheckBox, QSizeGrip)

from echo.backend import blackboard, awareness, providers, config
from echo.theme import Colors, apply_native_titlebar
from echo.widgets.web_lesson import HtmlLesson, step_visual


class DragHeader(QWidget):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._origin = event.globalPos() - self.window().pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, "_origin"):
            self.window().move(event.globalPos() - self._origin)


def label(text, size=13, color=None, bold=False):
    widget = QLabel(str(text))
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    widget.setStyleSheet(f"color:{color or Colors.TEXT_PRIMARY};font-size:{size}px;"
                        f"font-weight:{600 if bold else 400};background:transparent;")
    return widget


def button(text, slot, name=""):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.PointingHandCursor)
    widget.clicked.connect(lambda _checked=False: slot())
    return widget


def clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())


class ImagePreview(QLabel):
    def __init__(self):
        super().__init__()
        self.original = None

    def setPixmap(self, pixmap):
        self.original = pixmap
        self.fit_image()

    def fit_image(self):
        if self.original and not self.original.isNull():
            super().setPixmap(self.original.scaled(max(40, self.width() - 20), max(40, self.height() - 20),
                                                   Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def clear(self):
        self.original = None
        super().clear()

    def resizeEvent(self, event):
        self.fit_image()
        super().resizeEvent(event)


class BlackboardWindow(QDialog):
    completed = pyqtSignal(int, object, str)
    judged = pyqtSignal(int, object, object, object, str)
    visual_completed = pyqtSignal(int, object, str)
    board_ready = pyqtSignal(object)

    def __init__(self, engine=None, parent=None, archived=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.engine = engine
        self.archived = archived is not None
        self.session = getattr(engine, "session", None)
        self._request = 0
        self._busy = False
        self._capture = None
        self._board = None
        self._moment = None
        self._boards = copy.deepcopy(archived if self.archived else getattr(engine, "blackboards", []))
        self._images = {}
        self._source_widgets = {}
        self._folded = False
        self._region = None
        self._selecting_region = False
        self._capture_moment = None
        self._auto_request = 0
        self._auto_working = False
        self._auto_errors = 0
        self._gate = blackboard.ImportanceGate()
        self._visual_request = 0
        self._visual_busy = False
        self._visual_view = None
        self._visual_attempted = set()
        self._inline_view = None
        self._topic_gate = blackboard.TopicBoardGate()
        self._follow_hold_until = 0
        self._topic_pending = ""
        self.setWindowTitle("Echo · 课堂黑板" + (" · 课后回看" if self.archived else ""))
        self.setMinimumSize(360, 380)
        self.resize(460, 560)
        self.setStyleSheet(f"""
            QDialog {{background:{Colors.WINDOW_BG};border:1px solid {Colors.BORDER_STRONG};border-radius:12px;}}
            QSplitter::handle {{background:{Colors.WINDOW_BG};border:0;width:0px;height:0px;}}
            QWidget#BoardPaper {{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:14px;}}
            QFrame#BoardHero {{background:{Colors.ACCENT_SOFT};border:1px solid {Colors.ACCENT_BORDER};border-radius:12px;}}
            QFrame#StepCard {{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:10px;}}
            QFrame#EvidenceCard {{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:8px;}}
            QFrame#Composer {{background:{Colors.SURFACE};border:1px solid {Colors.BORDER_STRONG};border-radius:12px;}}
            QLineEdit {{background:transparent;border:none;padding:8px 0;color:{Colors.TEXT_PRIMARY};font-size:14px;}}
            QPushButton {{font-size:13px;padding:8px 12px;border-radius:7px;}}
            QPushButton#BoardPrimary {{background:{Colors.ACCENT};color:{Colors.ON_ACCENT};border:none;font-weight:600;}}
            QPushButton#BoardPrimary:hover {{background:{Colors.ACCENT_HOVER};}}
            QPushButton#BoardPrimary:pressed {{background:{Colors.ACCENT_PRESSED};}}
            QPushButton#BoardPrimary:disabled {{background:{Colors.BORDER};color:{Colors.TEXT_DISABLED};}}
            QPushButton#Citation {{background:transparent;border:none;color:{Colors.ACCENT};padding:2px 0;text-align:left;font-size:11px;}}
            QPushButton#Chip {{background:{Colors.SURFACE_HOVER};border:1px solid {Colors.BORDER};font-size:11px;padding:5px 9px;}}
            QPushButton#Chip:checked {{background:{Colors.ACCENT_SOFT};color:{Colors.ACCENT};border-color:{Colors.ACCENT_BORDER};}}
            QPushButton#BoardWindowButton {{background:transparent;border:none;color:{Colors.TEXT_SECONDARY};padding:0;font-size:16px;}}
            QPushButton#BoardWindowButton:hover {{background:{Colors.SURFACE_HOVER};color:{Colors.TEXT_PRIMARY};}}
            QCheckBox {{color:{Colors.TEXT_SECONDARY};font-size:11px;spacing:5px;}}
            QCheckBox::indicator {{width:13px;height:13px;background:{Colors.SURFACE};border:1px solid {Colors.BORDER_STRONG};border-radius:3px;}}
            QCheckBox::indicator:checked {{background:{Colors.ACCENT};border-color:{Colors.ACCENT};}}
            QComboBox {{background:{Colors.SURFACE};border:1px solid {Colors.BORDER};border-radius:6px;
                padding:5px 10px;color:{Colors.TEXT_PRIMARY};font-size:12px;}}
            QComboBox QAbstractItemView {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};
                selection-background-color:{Colors.ACCENT_SOFT};selection-color:{Colors.TEXT_PRIMARY};}}
            QScrollArea {{background:transparent;border:none;}}
            QScrollArea > QWidget > QWidget {{background:transparent;}}
            QToolTip {{background:{Colors.SURFACE};color:{Colors.TEXT_PRIMARY};}}
        """)
        apply_native_titlebar(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(8)
        self.header = DragHeader()
        top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.fold_btn = button("–", self.toggle_fold, "BoardWindowButton")
        self.fold_btn.setToolTip("收起")
        self.fold_btn.setFixedSize(26, 26)
        self.hide_btn = button("×", self.hide, "BoardWindowButton")
        self.hide_btn.setFixedSize(26, 26)
        self.hide_btn.setToolTip("关闭黑板；已开启的重点捕捉可继续。停止捕捉请取消开关。")
        name = QVBoxLayout()
        name.addWidget(label("Echo · 课堂黑板", 16, bold=True))
        top.addLayout(name)
        top.addStretch()
        self.live = label("● 课后回看" if self.archived else "● 跟随这节课", 12, Colors.OK_FG)
        self.live.setWordWrap(False)
        self.live.hide()
        top.addWidget(self.fold_btn)
        top.addWidget(self.hide_btn)
        root.addWidget(self.header)
        self.course = label(getattr(engine, "title", "") or "本节课程", 12, Colors.TEXT_SECONDARY)
        root.addWidget(self.course)
        self.nav = QWidget()
        nav = QHBoxLayout(self.nav)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        self.tabs = []
        for index, title in enumerate(("板书", "演示", "来源")):
            tab = button(title, lambda i=index: self.show_tab(i), "Chip")
            tab.setCheckable(True)
            nav.addWidget(tab)
            self.tabs.append(tab)
        nav.addStretch()
        self.history = QComboBox()
        self.history.setMinimumContentsLength(4)
        self.history.setMaximumWidth(150)
        self.history.currentIndexChanged.connect(self.select_board)
        nav.addWidget(self.history)
        root.addWidget(self.nav)
        self.auto_bar = QWidget()
        auto = QHBoxLayout(self.auto_bar)
        auto.setContentsMargins(0, 0, 0, 0)
        auto.setSpacing(4)
        self.auto_toggle = QCheckBox("捕捉重点")
        self.auto_toggle.setToolTip("选定课件范围后开启：按讲解判断重点，后台整理，不弹窗打断。每节课最多12次，间隔至少90秒。")
        self.auto_toggle.toggled.connect(self.toggle_auto)
        auto.addWidget(self.auto_toggle)
        self.region_btn = button("选择课件范围", self.choose_region, "Citation")
        auto.addWidget(self.region_btn)
        auto.addStretch()
        root.addWidget(self.auto_bar)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(0)
        root.addWidget(self.splitter, 1)

        paper = QWidget()
        self.paper = paper
        paper.setObjectName("BoardPaper")
        paper.setMinimumWidth(0)
        left = QVBoxLayout(paper)
        left.setContentsMargins(12, 10, 12, 10)
        left.setSpacing(8)
        tools = QHBoxLayout()
        self.range_label = label("最近讲解 · 随时收起，继续听课", 10, Colors.TEXT_SECONDARY)
        tools.addWidget(self.range_label, 1)
        self.follow_toggle = QCheckBox("跟随知识点")
        self.follow_toggle.setChecked(not self.archived)
        self.follow_toggle.setToolTip("自动整理当前知识点，无需截图；关闭后可停留在历史板书。")
        self.follow_toggle.setVisible(not self.archived)
        tools.addWidget(self.follow_toggle)
        left.addLayout(tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 3, 0)
        self.body_layout.setSpacing(14)
        self.scroll.setWidget(self.body)
        left.addWidget(self.scroll, 1)
        self.splitter.addWidget(paper)

        rail = QWidget()
        rail.setMinimumWidth(0)
        right = QVBoxLayout(rail)
        right.setContentsMargins(0, 2, 0, 0)
        right.setSpacing(10)
        right.addWidget(label("这块黑板从哪里来", 15, bold=True))
        right.addWidget(label("先看老师怎么讲，再看 Echo 怎么整理。", 11, Colors.TEXT_SECONDARY))
        self.vision_model_label = label("", 10, Colors.TEXT_SECONDARY)
        right.addWidget(self.vision_model_label)
        image_header = QHBoxLayout()
        image_header.addWidget(label("课件截图", 12, bold=True))
        image_header.addStretch()
        self.remove_btn = button("移除", self.remove_capture, "Citation")
        self.remove_btn.hide()
        image_header.addWidget(self.remove_btn)
        right.addLayout(image_header)
        self.preview = ImagePreview()
        self.preview.setText("圈一下课件里的公式、图表或历史事件\n也可以写上你的批注")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setFixedHeight(150)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.preview.setStyleSheet(f"border:1px dashed {Colors.BORDER_STRONG};border-radius:10px;"
                                  f"color:{Colors.TEXT_SECONDARY};font-size:12px;padding:8px;background:{Colors.SURFACE};")
        right.addWidget(self.preview)
        self.capture_btn = button("＋ 圈选课件 / 写批注", self.capture)
        self.capture_btn.setToolTip("只在你点击时截图。确认圈选后，截图会随本次提问发送给配置的视觉模型。")
        right.addWidget(self.capture_btn)
        self.image_note = label("手动圈选用于当前问题；重点捕捉仅截取选定范围。", 10, Colors.TEXT_SECONDARY)
        right.addWidget(self.image_note)
        right.addSpacing(6)
        self.sources_title = label("老师原话与参考资料", 12, bold=True)
        right.addWidget(self.sources_title)
        source_body = QWidget()
        self.sources_layout = QVBoxLayout(source_body)
        self.sources_layout.setContentsMargins(0, 0, 2, 0)
        self.sources_layout.setSpacing(8)
        right.addWidget(source_body)
        right.addStretch()
        self.sources_scroll = QScrollArea()
        self.sources_scroll.setWidgetResizable(True)
        self.sources_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sources_scroll.setWidget(rail)
        self.sources_scroll.setMinimumWidth(245)
        self.sources_scroll.setMaximumWidth(16777215)
        self.splitter.addWidget(self.sources_scroll)
        self.sources_scroll.hide()
        self.visual_page = QWidget()
        visual_layout = QVBoxLayout(self.visual_page)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        visual_header = QHBoxLayout()
        self.visual_label = label("读懂这段课", 12, Colors.TEXT_SECONDARY)
        visual_header.addWidget(self.visual_label, 1)
        self.visual_btn = button("深入讲解", self.generate_visual, "Chip")
        visual_header.addWidget(self.visual_btn)
        visual_layout.addLayout(visual_header)
        self.visual_host = QVBoxLayout()
        visual_layout.addLayout(self.visual_host, 1)
        self.splitter.addWidget(self.visual_page)
        self.visual_page.hide()

        self.composer = QFrame()
        self.composer.setObjectName("Composer")
        compose = QVBoxLayout(self.composer)
        compose.setContentsMargins(10, 4, 8, 6)
        compose.setSpacing(4)
        self.focus = QLineEdit()
        self.focus.setMaxLength(500)
        self.focus.setPlaceholderText("问当前知识点，也可说「用图解讲明白」")
        self.focus.returnPressed.connect(self.generate)
        compose.addWidget(self.focus)
        action_row = QHBoxLayout()
        self.chips = []
        action_row.addWidget(button("圈课件", self.capture, "Citation"))
        action_row.addStretch()
        self.cancel_btn = button("停止整理", self.cancel)
        self.cancel_btn.hide()
        action_row.addWidget(self.cancel_btn)
        self.generate_btn = button("讲清楚 →", self.generate, "BoardPrimary")
        self.generate_btn.setMinimumWidth(100)
        action_row.addWidget(self.generate_btn)
        compose.addLayout(action_row)
        root.addWidget(self.composer)
        self.footer = QWidget()
        footer = QHBoxLayout(self.footer)
        footer.setContentsMargins(0, 0, 0, 0)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedSize(64, 3)
        self.progress.hide()
        footer.addWidget(self.progress)
        self.status = label("板书自动跟随当前知识点；提问也可直接用图解演示。", 10, Colors.TEXT_SECONDARY)
        footer.addWidget(self.status, 1)
        footer.addWidget(QSizeGrip(self))
        root.addWidget(self.footer)
        self.completed.connect(self.finish)
        self.judged.connect(self.on_judged)
        self.visual_completed.connect(self.on_visual)
        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self.sync_lesson)
        self._timer.start()
        self._auto_timer = QTimer(self, interval=5000)
        self._auto_timer.timeout.connect(self.auto_tick)
        self._auto_timer.start()
        self.refresh_history()
        if self._boards:
            self.history.setCurrentIndex(len(self._boards) - 1)
            self.render(self._boards[-1])
        else:
            self.empty()
            self.show_live_sources()
        self.sync_lesson()
        self.show_tab(0)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(460, available.width() - 30), min(560, available.height() - 30))
        self.move(available.right() - self.width() - 18, available.top() + 48)
        if self.archived:
            self.composer.hide()
            self.capture_btn.hide()
            self.auto_bar.hide()
            self.image_note.setText("课后仅保留文字与来源，原始截图不保存。")

    def toggle_fold(self):
        self._folded = not self._folded
        if self._folded:
            self._expanded_size = self.size()
            for widget in (self.course, self.nav, self.auto_bar, self.splitter, self.composer, self.footer):
                widget.hide()
            self.fold_btn.setText("+")
            self.fold_btn.setToolTip("展开")
            self.setMinimumSize(270, 44)
            self.resize(300, 44)
        else:
            for widget in (self.course, self.nav, self.splitter, self.footer):
                widget.show()
            self.composer.setVisible(not self.archived)
            self.auto_bar.setVisible(not self.archived)
            self.fold_btn.setText("–")
            self.fold_btn.setToolTip("收起")
            self.setMinimumSize(360, 380)
            self.resize(self._expanded_size)

    def show_tab(self, index):
        self.paper.setVisible(index == 0)
        self.visual_page.setVisible(index == 1)
        self.sources_scroll.setVisible(index == 2)
        for i, tab in enumerate(self.tabs):
            tab.setChecked(i == index)
        if index == 1:
            self.display_visual()
            self.maybe_generate_visual()
        elif index == 2:
            spec = providers.vision()
            self.vision_model_label.setText(f"视觉模型 · {providers.label(spec['id'])} / {spec['model']}")

    def display_visual(self):
        if not self._board:
            self.visual_label.setText("先整理一段讲解，再用交互演示理解它。")
            self.visual_btn.setEnabled(False)
            return
        self.visual_btn.setEnabled(self.active())
        if self._visual_view is None:
            self._visual_view = HtmlLesson(self)
            self._visual_view.failed.connect(self.status.setText)
            self.visual_host.addWidget(self._visual_view)
        visual = self._board.get("visualization") or step_visual(self._board)
        self.visual_label.setText("多角度理解 · 对照依据 · 检查理解" if visual.get("layout") == "guided"
                                  else "探索变化，理解关系" if visual.get("mode") == "ai" else "先梳理脉络，再展开理解")
        self._visual_view.display(visual)

    def maybe_generate_visual(self):
        board = self._board or {}
        identity = board.get("created")
        visual = board.get("visualization") or {}
        if (not self.active() or self._visual_busy or visual.get("design_version", 0) >= 2 or board.get("mode") != "ai"
                or identity in self._visual_attempted or config.OFFLINE or not providers.configured(providers.text())):
            return
        self._visual_attempted.add(identity)
        self.generate_visual()

    def generate_visual(self):
        if self._visual_busy:
            self._visual_request += 1
            self._visual_busy = False
            self.visual_btn.setText("深入讲解")
            self.status.setText("已停止等待，本次讲解结果不会写入课堂。")
            return
        if not self._board or not self.active():
            return
        self._visual_busy = True
        self._visual_request += 1
        request = self._visual_request
        board = copy.deepcopy(self._board)
        self._visual_attempted.add(board.get("created"))
        self.visual_btn.setText("停止制作")
        self.status.setText("正在把这个难点做成可操作的讲解，可先收起继续听课。")

        def run():
            result, error = None, ""
            try:
                result = {"board_id": board["created"], "visual": blackboard.generate_visual(board)}
            except Exception as exc:
                error = (providers.api_error(exc, providers.text()) if getattr(exc, "status_code", None)
                         else "深入讲解暂未完成，课堂脉络已保留，可点击重试讲解。")
            try:
                self.visual_completed.emit(request, result, error)
            except RuntimeError:
                pass
        threading.Thread(target=run, daemon=True, name="echo-html-lesson").start()

    def on_visual(self, request, result, error):
        if request != self._visual_request:
            return
        self._visual_busy = False
        self.visual_btn.setText("重新讲解" if not error else "重试讲解")
        self.visual_btn.setEnabled(self.active())
        if not self.active():
            return
        if error:
            self.status.setText("演示未能生成：" + error)
            return
        for board in self._boards:
            if board["created"] == result["board_id"]:
                board["visualization"] = result["visual"]
        with self.engine._lock:
            for board in self.engine.blackboards:
                if board["created"] == result["board_id"]:
                    board["visualization"] = copy.deepcopy(result["visual"])
        if self._board and self._board["created"] == result["board_id"]:
            self._board["visualization"] = result["visual"]
            self.display_visual()
        self.status.setText("交互讲解已就绪 · 可点击、拖动或分步查看，课后可回放。")

    def choose_region(self, enable_after=False):
        if not self.active() or self._busy or self._auto_working or self._selecting_region:
            return
        from echo.widgets.lesson_capture import select_region
        sid = self.session
        self._selecting_region = True

        def selected(region):
            if sip.isdeleted(self):
                return
            self._selecting_region = False
            if not self.active() or self.session != sid:
                return
            self._region = region
            self.region_btn.setText(f"课件范围 {region.rect.width()}×{region.rect.height()}")
            self.status.setText("范围已选择。开启重点捕捉后，请把课件保持在这个位置；本节课结束后范围失效。")
            if enable_after:
                self.auto_toggle.setChecked(True)
        def cancelled():
            if not sip.isdeleted(self):
                self._selecting_region = False
                self.status.setText("已取消修改课件范围。")
        select_region(selected, cancelled)

    def toggle_auto(self, enabled):
        self._auto_request += 1
        self._auto_working = False
        if not enabled:
            self.status.setText("重点捕捉已关闭，不再按讲解截取课件。")
            return
        if not self.active():
            self.auto_toggle.setChecked(False)
            return
        if self._region is None:
            self.auto_toggle.blockSignals(True)
            self.auto_toggle.setChecked(False)
            self.auto_toggle.blockSignals(False)
            self.choose_region(enable_after=True)
            return
        moment = blackboard.snapshot(self.engine)
        if not moment.get("online") or not moment.get("vision_online"):
            self.auto_toggle.setChecked(False)
            self.status.setText("重点捕捉需要已连接的文字模型和视觉模型。可先手动圈选课件。")
            return
        self._auto_errors = 0
        self.status.setText("重点捕捉已开启 · 仅选定区域，后台整理，不弹窗。每节最多12块，至少间隔90秒。")
        self.auto_tick()

    def auto_tick(self):
        if (not self.active() or not self.auto_toggle.isChecked() or self._region is None
                or self._auto_working or self._busy or self._visual_busy or self._selecting_region):
            return
        try:
            moment = blackboard.snapshot(self.engine, seconds=90)
        except ValueError:
            return
        if not self._gate.eligible(moment, time.monotonic()):
            return
        self._gate.checked(moment, time.monotonic())
        self._auto_request += 1
        request = self._auto_request
        self._auto_working = True
        from echo.widgets.lesson_capture import grab_region

        def captured(image):
            if request != self._auto_request or not self.active() or not self.auto_toggle.isChecked():
                return
            # Freeze transcription at the same instant as this frame, BEFORE model latency.
            try:
                frozen = blackboard.snapshot(self.engine, seconds=90)
            except ValueError:
                self._auto_working = False
                return
            self.status.setText("正在判断刚才这段是否值得留作重点…")

            def judge():
                decision, error = None, ""
                try:
                    decision = blackboard.judge_importance(frozen)
                except Exception as exc:
                    error = str(exc)
                try:
                    self.judged.emit(request, frozen, image, decision, error)
                except RuntimeError:
                    pass
            threading.Thread(target=judge, daemon=True, name="echo-important-moment").start()

        def failed(error):
            self._auto_working = False
            self.auto_toggle.setChecked(False)
            self.status.setText(error)

        grab_region(self._region, captured, failed,
                    valid=lambda: self.active() and self.auto_toggle.isChecked() and request == self._auto_request)

    def on_judged(self, request, moment, image, decision, error):
        if request != self._auto_request or not self.active() or not self.auto_toggle.isChecked():
            return
        self._auto_working = False
        if error:
            self._auto_errors += 1
            if self._auto_errors >= 3:
                self.auto_toggle.setChecked(False)
            self.status.setText("重点判断暂未完成：" + error + ("；已暂停捕捉。" if self._auto_errors >= 3 else ""))
            return
        self._auto_errors = 0
        if self._busy or not self._gate.accept(decision, time.monotonic()):
            self.status.setText("继续听课 · 这段暂不新增重点。")
            return
        self._start_generation(moment, decision["topic"] + "：" + decision["reason"], image, automatic=True)

    def set_focus(self, text):
        self.focus.setText(text)
        self.focus.setFocus()

    def active(self):
        return (not self.archived and self.engine is not None
                and getattr(self.engine, "active", False)
                and getattr(self.engine, "session", None) == self.session)

    def sync_lesson(self):
        if self.archived:
            return
        active = self.active()
        self.generate_btn.setEnabled(active and not self._busy)
        self.capture_btn.setEnabled(active and not self._busy)
        self.focus.setEnabled(active and not self._busy)
        self.region_btn.setEnabled(active and not self._busy and not self._auto_working)
        self.auto_toggle.setEnabled(active)
        self.visual_btn.setEnabled(active and self._board is not None)
        for chip in self.chips:
            chip.setEnabled(active and not self._busy)
        if not active:
            state = (getattr(self.engine, "session", None), getattr(self.engine, "active", False))
            if getattr(self, "_inactive_state", None) == state:
                return
            self._inactive_state = state
            if self.auto_toggle.isChecked():
                self.auto_toggle.setChecked(False)
            self._auto_request += 1
            self._auto_working = False
            self._region = None
            if self._visual_busy:
                self._visual_request += 1
                self._visual_busy = False
            if self._busy:
                self.cancel()
            self._capture = None
            self.remove_btn.hide()
            if self.session != getattr(self.engine, "session", None):
                self._images.clear()
                self.preview.clear()
                self.preview.setText("课程已切换，上一节的图片已清除")
                self.live.setText("上一节课 · 已结束")
                self.status.setText("请从新课堂的「AI 黑板」打开本节黑板，旧内容不会带入新课。")
            else:
                self.live.setText("本节课已结束 · 只读回看")
                self.status.setText("课堂已结束。这里可回看和导出，不能继续截图或生成。")
        elif not self._busy:
            self._inactive_state = None
            self.live.setText("● 正在上课 · 跟随知识点")
            QTimer.singleShot(0, self.follow_current)

    def follow_current(self):
        """Runs while hidden/folded too; never captures a screen or opens a window."""
        if (not self.active() or not self.follow_toggle.isChecked() or self._busy or self._auto_working
                or self._visual_busy or self._selecting_region or self._capture is not None
                or self.focus.text().strip() or time.monotonic() < self._follow_hold_until):
            return
        try:
            moment = blackboard.snapshot(self.engine, current_only=True)
        except ValueError:
            return
        if self._topic_gate.ready(moment, time.monotonic()):
            self._topic_gate.started(time.monotonic())
            self._start_generation(moment, "整理当前知识点：" + moment["current"], automatic=True, topic_follow=True)

    def refresh_history(self):
        self.history.blockSignals(True)
        self.history.clear()
        for i, board in enumerate(self._boards):
            self.history.addItem(f"{i+1:02d}  {board.get('title', '课堂黑板')}")
        self.history.setVisible(bool(self._boards))
        self.history.blockSignals(False)

    def select_board(self, index):
        if 0 <= index < len(self._boards) and not self._busy:
            self._follow_hold_until = time.monotonic() + 45
            self.render(self._boards[index])

    def empty(self):
        clear(self.body_layout)
        self.body_layout.addSpacing(12)
        self.body_layout.addWidget(label("跟着老师，记下当前知识点", 19, bold=True))
        self.body_layout.addWidget(label("识别到知识点后，板书会自动整理。无需截图，也不用点生成。", 13, Colors.TEXT_SECONDARY))
        self.body_layout.addSpacing(12)
        self.body_layout.addWidget(label("难懂的地方可以直接问，图解会嵌入板书；完整演示仍在「演示」。", 12, Colors.TEXT_SECONDARY))
        self.body_layout.addStretch()

    def show_live_sources(self):
        if self.active():
            try:
                moment = blackboard.snapshot(self.engine)
                title, topic = moment["title"], moment["current"]
                self.course.setText(title if title.strip().casefold() == topic.strip().casefold() else title + "   /   " + topic)
                self.render_sources(moment["sources"][-4:])
            except ValueError:
                pass

    def render_sources(self, sources):
        clear(self.sources_layout)
        self._source_widgets = {}
        if not sources:
            self.sources_layout.addWidget(label("老师开讲后，这里会出现带时间的原话。", 12, Colors.TEXT_SECONDARY))
        for source in sources:
            if source["kind"] == "image":
                continue
            card = QFrame()
            card.setObjectName("EvidenceCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(5)
            layout.addWidget(label(f"{source['id']}  /  {source['label']}", 10, Colors.ACCENT, True))
            layout.addWidget(label(source["text"], 12, Colors.TEXT_SECONDARY))
            self.sources_layout.addWidget(card)
            self._source_widgets[source["id"]] = card
        self.sources_layout.addStretch()

    def jump_source(self, ident):
        self.show_tab(2)
        widget = self._source_widgets.get(ident)
        if widget:
            self.sources_scroll.ensureWidgetVisible(widget)
            widget.setStyleSheet(f"QFrame#EvidenceCard {{border:2px solid {Colors.ACCENT};}}")
            QTimer.singleShot(1400, lambda: widget.setStyleSheet("") if not sip.isdeleted(widget) else None)
        elif ident == "S1":
            self.status.setText("S1 是本次圈选课件；图片预览在右上方。课后仅保存文字和来源标记。")

    def render(self, board):
        self._board = board
        if self._inline_view:
            self._inline_view.stop()
        self._inline_view = None
        clear(self.body_layout)
        self.course.setText(board.get("course", "本节课") + "   /   " + ("原话摘录" if board.get("mode") == "excerpt" else "AI 辅助板书"))
        self.range_label.setText(f"{board.get('start') or '课件'} — {board.get('end') or '截图'}  ·  {board.get('pattern', '概念脉络')}")
        hero = QFrame()
        hero.setObjectName("BoardHero")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(label("这一段，抓住一条主线", 10, Colors.ACCENT, True))
        layout.addWidget(label(board["title"], 20, bold=True))
        layout.addWidget(label(board.get("gist", ""), 14))
        self.body_layout.addWidget(hero)
        self.body_layout.addWidget(label(board.get("pattern", "概念脉络") + "  /  一步一步看", 12, Colors.TEXT_SECONDARY, True))
        sources = {s["id"]: s for s in board.get("sources", [])}
        for i, step in enumerate(board["steps"]):
            card = QFrame()
            card.setObjectName("StepCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(10, 10, 10, 10)
            number = label(f"{i+1:02d}", 23, Colors.ACCENT, True)
            number.setFixedWidth(34)
            row.addWidget(number, 0, Qt.AlignTop)
            content = QVBoxLayout()
            content.setSpacing(6)
            if step.get("label"):
                content.addWidget(label(step["label"], 10, Colors.TEXT_SECONDARY, True))
            content.addWidget(label(step["heading"], 16, bold=True))
            content.addWidget(label(step["body"], 14))
            evidence = step.get("evidence", [])
            if evidence:
                cite = QHBoxLayout()
                for ident in evidence[:3]:
                    source = sources.get(ident)
                    if source:
                        caption = source["label"][:22] + ("…" if len(source["label"]) > 22 else "")
                        link = button("↗ " + caption, lambda key=ident: self.jump_source(key), "Citation")
                        link.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                        link.setToolTip(source["text"])
                        cite.addWidget(link)
                cite.addStretch()
                content.addLayout(cite)
            else:
                content.addWidget(label("推断 / 补充 · 待核对", 10, Colors.WARNING))
            row.addLayout(content, 1)
            self.body_layout.addWidget(card)
        if board.get("pitfall"):
            self.body_layout.addWidget(label("别把这两件事混在一起", 13, Colors.WARNING, True))
            self.body_layout.addWidget(label(board["pitfall"], 13))
        check = board.get("check", {})
        if check.get("question"):
            self.body_layout.addWidget(label("合上黑板，想一想", 13, bold=True))
            self.body_layout.addWidget(label(check["question"], 14))
            answer = label(check.get("answer", ""), 13, Colors.TEXT_SECONDARY)
            answer.hide()
            reveal = button("看看参考思路", lambda: answer.setVisible(not answer.isVisible()), "Citation")
            self.body_layout.addWidget(reveal, 0, Qt.AlignLeft)
            self.body_layout.addWidget(answer)
        self.inline_host = QVBoxLayout()
        self.body_layout.addLayout(self.inline_host)
        self.show_inline()
        self.body_layout.addStretch()
        self.render_sources(board.get("sources", []))
        if self.visual_page.isVisible():
            self.display_visual()
            self.maybe_generate_visual()
        self.scroll.verticalScrollBar().setValue(0)
        image = self._images.get(board.get("created"))
        if image:
            self.preview.setPixmap(image)
            self.image_note.setText("本块黑板对应的课件画面 · 图片仅在本次会话保留")
        elif board.get("has_image"):
            self.preview.clear()
            self.preview.setText("这块黑板参考了课件截图\n课后保留解释，原始图片不保存")
        elif self._capture is None:
            self.preview.clear()
            self.preview.setText("这块黑板根据老师原话整理\n可再圈选课件，问得更具体")

    def show_inline(self):
        visual = (self._board or {}).get("inline_visual")
        if not visual or self._inline_view is not None or not self.isVisible():
            return
        self._inline_view = HtmlLesson(self)
        self._inline_view.setFixedHeight(240)
        self._inline_view.failed.connect(lambda text: self.status.setText("板书图解暂不可用，正文仍可阅读：" + text))
        self.inline_host.addWidget(label("看图理解 · 可操作", 12, Colors.ACCENT, True))
        self.inline_host.addWidget(self._inline_view)
        self._inline_view.display(visual)

    def showEvent(self, event):
        super().showEvent(event)
        if self._board:
            self.show_inline()

    def capture(self):
        if not self.active() or self._busy:
            return
        from echo.widgets.snip import start_circle_ask
        hidden = [w for w in QApplication.topLevelWidgets()
                  if type(w).__module__.startswith("echo.widgets")]
        sid = self.session

        def received(pixmap, _rect):
            if not self.active() or self.session != sid:
                return
            self._capture = pixmap.copy()
            self._capture_moment = blackboard.snapshot(self.engine)
            self.preview.setPixmap(pixmap)
            self.remove_btn.show()
            self.image_note.setText("已附上圈选截图 · 发送前可移除")
            self.status.setText("截图与此刻讲解已一起保留。写下疑问，再点「讲清楚」。")
            self.show()
            self.raise_()
            self.focus.setFocus()

        if not start_circle_ask(hide=hidden, on_capture=received, confirm_text="✓ 附到课堂黑板"):
            self.status.setText("已有截图操作进行中，请先完成或取消它。")

    def remove_capture(self):
        self._capture = None
        self._capture_moment = None
        self.preview.clear()
        self.preview.setText("未附加截图\n将根据老师原话整理")
        self.remove_btn.hide()
        self.image_note.setText("手动圈选用于当前问题；重点捕捉仅截取选定范围。")

    def set_busy(self, busy):
        self._busy = busy
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        self.history.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)
        self.generate_btn.setText("正在整理…" if busy else "讲清楚 →")
        self.sync_lesson()

    def generate(self):
        if not self.active() or self._busy:
            return
        try:
            moment = self._capture_moment if self._capture is not None and self._capture_moment else blackboard.snapshot(self.engine)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        image = self._capture.copy() if self._capture else None
        if not moment["sources"] and image is None:
            self.status.setText("还没听到讲解。可以先圈选课件，或等老师讲几句再整理。")
            return
        self._follow_hold_until = time.monotonic() + 45
        self._start_generation(moment, self.focus.text().strip(), image)

    def _start_generation(self, moment, focus, image=None, automatic=False, topic_follow=False):
        if not self.active() or moment["session"] != self.session or self._busy:
            return
        image_png = None
        if image:
            from echo.widgets.snip import _png_bytes
            image_png = _png_bytes(image)
        self._moment = moment
        self._topic_pending = blackboard.TopicBoardGate.key(moment) if topic_follow else ""
        self._request += 1
        request = self._request
        self._pending_image = image
        self.set_busy(True)
        self.status.setText("正在读圈选课件，并结合这段讲解…" if image else "正在梳理这段讲解与参考资料…")

        def run():
            try:
                result = blackboard.generate_board(moment, focus, image_png)
                result["trigger"] = "automatic" if automatic else "manual"
                result["topic_key"] = blackboard.TopicBoardGate.key(moment)
                result["current_topic"] = moment.get("current", "")
                if topic_follow:
                    result["trigger"] = "topic"
                error = ""
            except Exception as exc:
                result, error = None, str(exc)
            try:
                self.completed.emit(request, result, error)
            except RuntimeError:
                pass  # The lesson window may have been destroyed while the request finished.
        threading.Thread(target=run, daemon=True, name="echo-lesson-board").start()

    def cancel(self):
        self._request += 1
        self._busy = False
        self._topic_pending = ""
        self._follow_hold_until = time.monotonic() + 45
        self._pending_image = None
        self.progress.hide()
        self.cancel_btn.hide()
        self.history.setEnabled(True)
        self.remove_btn.setEnabled(True)
        self.generate_btn.setText("讲清楚 →")
        self.status.setText("已停止等待。本次结果不会写入黑板，可调整问题后重新整理。")
        # The provider request may finish remotely; its result is invalidated locally.
        self.generate_btn.setEnabled(self.active())
        self.capture_btn.setEnabled(self.active())
        self.focus.setEnabled(self.active())

    def finish(self, request, result, error):
        if request != self._request:
            return
        self.set_busy(False)
        if not self.active():
            return
        if error:
            self._topic_pending = ""
            self.status.setText("这次未能整理：" + error)
            return
        self._topic_gate.completed(result.get("topic_key"))
        self._topic_pending = ""
        with self.engine._lock:
            if not self.active():
                return
            if not hasattr(self.engine, "blackboards"):
                self.engine.blackboards = []
            self.engine.blackboards.append(copy.deepcopy(result))
            self.engine.blackboards[:] = self.engine.blackboards[-80:]
        awareness.note("board", result.get("focus") or result["title"],
                       result.get("gist", "") + " → ".join(step["heading"] for step in result["steps"]))
        self._boards.append(result)
        self._boards = self._boards[-80:]
        if self._pending_image:
            self._images[result["created"]] = self._pending_image
        self._pending_image = None
        valid = {b["created"] for b in self._boards}
        self._images = {key: value for key, value in self._images.items() if key in valid}
        self._capture = None
        self._capture_moment = None
        self.remove_btn.hide()
        self.refresh_history()
        self.history.blockSignals(True)
        self.history.setCurrentIndex(len(self._boards) - 1)
        self.history.blockSignals(False)
        current_key = blackboard.TopicBoardGate.key(blackboard.snapshot(self.engine, seconds=120))
        if result.get("trigger") != "topic" or result.get("topic_key") == current_key:
            self.render(result)
        if result.get("trigger") == "manual":
            self.focus.clear()
        self.board_ready.emit(result)
        self.status.setText("已整理原话摘录 · 当前离线，未进行 AI 理解。" if result["mode"] == "excerpt"
                            else "板书已保存到本节课 · 下课后可在回响页导出整节笔记。")

    def export(self):
        if not self._board:
            return
        filename, selected = QFileDialog.getSaveFileName(self, "导出课堂黑板", "Echo-课堂黑板.md", "Markdown (*.md);;交互讲解 (*.html)")
        if filename:
            try:
                if "*.html" in selected or filename.lower().endswith(".html"):
                    from echo.widgets.web_lesson import sandbox_document
                    visual = self._board.get("visualization") or step_visual(self._board)
                    content = sandbox_document(visual["html"])
                else:
                    content = blackboard.markdown(self._board)
                Path(filename).write_text(content, encoding="utf-8")
                self.status.setText("已导出本块黑板和来源快照。")
            except OSError as exc:
                self.status.setText("导出失败：" + str(exc))

    def closeEvent(self, event):
        self.auto_toggle.setChecked(False)
        if self._busy:
            self.cancel()
        super().closeEvent(event)

    def reject(self):
        if self._busy:
            self.cancel()
        super().reject()
