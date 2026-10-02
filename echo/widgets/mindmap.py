"""
Echo - 知识地图

一节课上完，把知识点画成一张图：节点是知识点，连线是「学这个之前得先懂那个」。
点某个节点，下面就是它的详情 —— 老师当时怎么讲的、不懂的话这一步缺在哪、以及一道题和解析。

自包含组件，宿主只要：
    map = MindMapPage(parent)
    map.show_lesson(lesson, mistakes)      # lesson 传 store.get_lesson(ts)，或 mindmap.from_report(report)
信号：
    map.practice_requested(str)            # 学生点了「出题练一练」，参数是知识点名

图上全 ok 的知识点也画，但弱化显示；掉队过/待回看的用强调色，一眼能看出卡在哪。
"""
from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)

from echo.backend import mindmap
from echo.theme import Colors, Radius, Spacing, font

NODE_W, NODE_H = 112, 40
LEVEL_H = 76
PAD_X, PAD_Y = 14, 16


def status_style(status: str) -> tuple:
    """状态 → (描边色, 底色, 文字色)。ok 的弱化处理，一眼扫过去能看出重点。"""
    if status == mindmap.STATUS_REVIEW:
        return Colors.DANGER, Colors.DANGER_BG, Colors.TEXT_PRIMARY
    if status == mindmap.STATUS_FIXED:
        return Colors.ACCENT, Colors.ACCENT_SOFT, Colors.TEXT_PRIMARY
    return Colors.BORDER, Colors.SURFACE, Colors.TEXT_SECONDARY


class _Canvas(QWidget):
    """只负责画图和处理点击。"""

    node_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self._nodes = []          # [(topic, status, QRectF)]
        self._edges = []          # [(from_rect, to_rect, topic)]
        self._selected = ""
        self._hover = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_graph(self, graph: dict, selected: str = ""):
        self._selected = selected
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        by_level = {}
        for n in nodes:
            by_level.setdefault(n.get("level", 0), []).append(n)
        levels = sorted(by_level)

        rects = {}
        width = max(self.width(), 320)
        height = PAD_Y * 2 + max(1, len(levels)) * LEVEL_H
        for li, lv in enumerate(levels):
            row = by_level[lv]
            n = len(row)
            # 每层横向均分，整层居中；层内节点多时压缩间距
            span = width - PAD_X * 2
            step = span / max(1, n)
            w = min(NODE_W, max(64, step - 8))
            y = PAD_Y + li * LEVEL_H + (LEVEL_H - NODE_H) / 2
            for i, node in enumerate(row):
                x = PAD_X + step * i + (step - w) / 2
                rects[node["id"]] = QRectF(x, y, w, NODE_H)

        self._nodes = [(n["id"], n.get("status", "ok"), rects[n["id"]]) for n in nodes
                       if n["id"] in rects]
        topic_rects = {n["id"]: rects[n["id"]] for n in nodes if n["id"] in rects}
        self._edges = [(topic_rects[e["from"]], topic_rects[e["to"]])
                       for e in edges
                       if e.get("from") in topic_rects and e.get("to") in topic_rects]
        self.setMinimumHeight(int(height))
        self.update()

    def _hit(self, pos) -> str:
        for topic, _status, rect in self._nodes:
            if rect.contains(QPointF(pos)):
                return topic
        return ""

    def mouseMoveEvent(self, e):
        hit = self._hit(e.pos())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            hit = self._hit(e.pos())
            if hit:
                self._selected = hit
                self.node_clicked.emit(hit)
                self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # ---- 连线：从上一层的底边中点，画到下一层的顶边中点 ----
        p.setBrush(Qt.NoBrush)
        for a, b in self._edges:
            pen = QPen(QColor(Colors.BORDER_STRONG), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            x1, y1 = a.center().x(), a.bottom()
            x2, y2 = b.center().x(), b.top()
            mid = (y1 + y2) / 2
            path = QPainterPath(QPointF(x1, y1))
            path.cubicTo(QPointF(x1, mid), QPointF(x2, mid), QPointF(x2, y2))
            # 选中节点的连线强调一下，顺着线能看清它依赖谁、被谁依赖
            if self._selected and (self._node_topic(a) == self._selected or self._node_topic(b) == self._selected):
                p.setPen(QPen(QColor(Colors.ACCENT), 2.2))
            p.drawPath(path)
            p.setPen(QPen(QColor(Colors.BORDER_STRONG), 1.6))
            # 箭头
            arrow = QPainterPath(QPointF(x2, y2))
            arrow.lineTo(x2 - 4, y2 - 6)
            arrow.lineTo(x2 + 4, y2 - 6)
            arrow.closeSubpath()
            p.setBrush(QBrush(QColor(Colors.ACCENT if self._selected and
                                     (self._node_topic(a) == self._selected or
                                      self._node_topic(b) == self._selected) else Colors.BORDER_STRONG)))
            p.setPen(Qt.NoPen)
            p.drawPath(arrow)
            p.setBrush(Qt.NoBrush)

        # ---- 节点 ----
        for topic, status, rect in self._nodes:
            border, fill, text = status_style(status)
            selected = topic == self._selected
            hover = topic == self._hover
            if hover and not selected:
                fill = Colors.SURFACE_HOVER
            p.setBrush(QBrush(QColor(fill)))
            p.setPen(QPen(QColor(Colors.ACCENT if selected else border), 2.0 if selected else 1.3))
            path = QPainterPath()
            path.addRoundedRect(rect, Radius.MD, Radius.MD)
            p.drawPath(path)

            color = QColor(text)
            if status == mindmap.STATUS_OK and not (selected or hover):
                color.setAlpha(160)          # 全 ok 的节点弱化
            p.setPen(QPen(color))
            p.setFont(font(11, 600 if status != mindmap.STATUS_OK else 400))
            fm = QFontMetrics(p.font())
            label = fm.elidedText(topic, Qt.ElideMiddle, int(rect.width()) - 14)
            p.drawText(rect, Qt.AlignCenter, label)

            # 状态小圆点
            if status != mindmap.STATUS_OK:
                p.setBrush(QBrush(QColor(border)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(rect.left() + 9, rect.top() + 9), 3.0, 3.0)
                p.setBrush(Qt.NoBrush)
        p.end()

    def _node_topic(self, rect: QRectF) -> str:
        for topic, _s, r in self._nodes:
            if r is rect:
                return topic
        return ""


class MindMapPage(QWidget):
    """知识地图整页：上面是图，下面是选中知识点的详情。

    宿主接一个信号就够了：
        practice_requested(str)  —— 学生想练这个知识点，宿主跳练习页即可
    """

    practice_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lesson = {}
        self._mistakes = []
        self._graph = {"nodes": [], "edges": []}
        self._detail_topic = ""
        self._build()

    # ---------- 构建 ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.SM)

        title = QLabel("知识地图")
        title.setFont(font(14, 600))
        self.sub = QLabel("")
        self.sub.setFont(font(11))
        self.sub.setWordWrap(True)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(title)
        head.addWidget(self.sub)
        root.addLayout(head)

        self.canvas = _Canvas()
        self.canvas.node_clicked.connect(self._on_node)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("MapViewport")
        self.scroll.viewport().setStyleSheet("QWidget#MapViewport { background: transparent; }")
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setMinimumHeight(200)
        root.addWidget(self.scroll, 1)

        self.legend = QLabel("● 待回看   ● 补上了   ○ 已跟上")
        self.legend.setFont(font(10))
        self.legend.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        root.addWidget(self.legend)

        self.detail = _DetailPanel()
        self.detail.practice_requested.connect(self.practice_requested.emit)
        root.addWidget(self.detail)

        self.empty = QLabel("这节课还没有知识点记录。上完一节课，这里会长出知识地图。")
        self.empty.setWordWrap(True)
        self.empty.setFont(font(12))
        self.empty.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        root.addWidget(self.empty)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget {{ background: transparent; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; }}
            QScrollBar::handle:vertical {{
                background: {Colors.BORDER_STRONG}; border-radius: 3px; min-height: 24px;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

    # ---------- 对外 ----------
    def show_lesson(self, lesson: dict, mistakes: list = None):
        """喂一节课。lesson 传 store.get_lesson(ts) 或 mindmap.from_report(report)。"""
        self._lesson = lesson or {}
        self._mistakes = mistakes if mistakes is not None else []
        self._graph = mindmap.build(self._lesson, self._mistakes)
        self._detail_topic = ""

        nodes = self._graph["nodes"]
        review = sum(1 for n in nodes if n["status"] == mindmap.STATUS_REVIEW)
        fixed = sum(1 for n in nodes if n["status"] == mindmap.STATUS_FIXED)
        bits = [f"{len(nodes)} 个知识点"]
        if review:
            bits.append(f"{review} 个待回看")
        if fixed:
            bits.append(f"{fixed} 个已补上")
        if not review and nodes:
            bits.append("都跟上了")
        self.sub.setText(" · ".join(bits) + "　（点知识点看讲解和题目）")

        self.empty.setVisible(not nodes)
        self.canvas.setVisible(bool(nodes))
        self.legend.setVisible(bool(nodes))
        self.canvas.set_graph(self._graph)
        self.detail.clear()
        self.detail.setVisible(bool(nodes))

    def select(self, topic: str):
        """外部直接选中某个知识点（比如从别处跳进来）。"""
        self._on_node(topic)

    # ---------- 内部 ----------
    def _on_node(self, topic: str):
        self._detail_topic = topic
        self.canvas.set_graph(self._graph, selected=topic)
        detail = mindmap.node_detail(self._lesson, topic, self._mistakes)
        self.detail.show_detail(detail)
        self.detail.load_questions(self._lesson, topic, self._mistakes)


class _DetailPanel(QFrame):
    """单个知识点的详情：老师怎么讲的 + 缺的那一步 + 一道题和解析。"""

    practice_requested = pyqtSignal(str)
    # 出题在后台线程，出好后必须回到主线程再动控件（PyQt 信号跨线程会自动排队）
    _questions_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MindDetail")
        self._topic = ""
        self._build()
        self._questions_ready.connect(self._render_questions)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.MD, Spacing.SM + 2, Spacing.MD, Spacing.MD)
        root.setSpacing(6)

        head = QHBoxLayout()
        self.topic_lbl = QLabel("")
        self.topic_lbl.setFont(font(13, 600))
        self.status_lbl = QLabel("")
        self.status_lbl.setFont(font(11, 600))
        head.addWidget(self.topic_lbl)
        head.addStretch(1)
        head.addWidget(self.status_lbl)
        root.addLayout(head)

        self.body_lbl = QLabel("")
        self.body_lbl.setWordWrap(True)
        self.body_lbl.setFont(font(12))
        root.addWidget(self.body_lbl)

        self.miss_lbl = QLabel("")
        self.miss_lbl.setWordWrap(True)
        self.miss_lbl.setFont(font(12))
        root.addWidget(self.miss_lbl)

        self.quiz_box = QVBoxLayout()
        self.quiz_box.setSpacing(4)
        root.addLayout(self.quiz_box)

        self.practice_btn = QPushButton("出题练一练")
        self.practice_btn.setCursor(Qt.PointingHandCursor)
        self.practice_btn.clicked.connect(lambda: self.practice_requested.emit(self._topic))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.practice_btn)
        root.addLayout(row)

        self.setStyleSheet(f"""
            QFrame#MindDetail {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.LG}px;
            }}
            QFrame#MindDetail QLabel {{ background: transparent; color: {Colors.TEXT_PRIMARY}; }}
            QPushButton {{
                background: {Colors.ACCENT}; color: {Colors.ON_ACCENT};
                border: none; border-radius: {Radius.MD}px; padding: 6px 16px;
                font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {Colors.ACCENT_HOVER}; }}
            QPushButton:disabled {{ background: {Colors.SURFACE_HOVER}; color: {Colors.TEXT_DISABLED}; }}
        """)

    def clear(self):
        self._topic = ""
        self.topic_lbl.setText("")
        self.status_lbl.setText("")
        self.body_lbl.setText("点上面的知识点，这里显示讲解和题目。")
        self.body_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.miss_lbl.setVisible(False)
        self._clear_quiz()

    def show_detail(self, detail: dict):
        self._topic = detail.get("topic") or ""
        self.topic_lbl.setText(self._topic)
        status = detail.get("status")
        label = {mindmap.STATUS_REVIEW: "待回看",
                 mindmap.STATUS_FIXED: "已补上",
                 mindmap.STATUS_OK: "已跟上"}.get(status, "")
        color = {mindmap.STATUS_REVIEW: Colors.DANGER,
                 mindmap.STATUS_FIXED: Colors.ACCENT,
                 mindmap.STATUS_OK: Colors.OK_FG}.get(status, Colors.TEXT_SECONDARY)
        self.status_lbl.setText("● " + label if label else "")
        self.status_lbl.setStyleSheet(f"color:{color};")

        taught = (detail.get("taught") or "").strip()
        self.body_lbl.setText(taught or "这节课没有留下这个知识点的讲解记录。")
        self.body_lbl.setStyleSheet("")

        # 不懂的话，把它缺的那一步说清楚
        miss_bits = []
        if detail.get("missing"):
            miss_bits.append("你可能卡在：" + detail["missing"])
        if detail.get("known"):
            miss_bits.append("先确认你已经知道的：" + detail["known"])
        if detail.get("step"):
            miss_bits.append("漏掉的那一步：" + detail["step"])
        if detail.get("micro_lesson"):
            miss_bits.append(detail["micro_lesson"])
        if miss_bits:
            self.miss_lbl.setText("\n".join(miss_bits))
            self.miss_lbl.setStyleSheet("")
        else:
            self.miss_lbl.setText("这个知识点没掉队过，可以直接出题确认一下。")
            self.miss_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.miss_lbl.setVisible(True)

    def load_questions(self, lesson: dict, topic: str, mistakes: list = None):
        self._clear_quiz()
        asking = QLabel("正在准备这道题…")
        asking.setFont(font(11))
        asking.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.quiz_box.addWidget(asking)

        def done(questions):
            # 这里还在后台线程，只能发信号，不能碰控件
            self._questions_ready.emit(questions)

        mindmap.questions_for(lesson, topic, mistakes, n=2, on_done=done, on_error=lambda _m: None)

    def _render_questions(self, questions: list):
        # 这个槽跑在主线程（信号跨线程排队过来的），可以安全动控件
        self._clear_quiz()
        if not questions:
            return
        for i, q in enumerate(questions[:2], 1):
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background:{Colors.CODE_BG}; border-radius:{Radius.MD}px; }}")
            box = QVBoxLayout(card)
            box.setContentsMargins(Spacing.SM + 2, Spacing.SM, Spacing.SM + 2, Spacing.SM)
            box.setSpacing(3)
            head = QLabel(f"第 {i} 题")
            head.setFont(font(10, 600))
            head.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; background: transparent;")
            box.addWidget(head)
            ql = QLabel(q.get("question") or "")
            ql.setWordWrap(True)
            ql.setFont(font(12))
            ql.setStyleSheet("background: transparent;")
            box.addWidget(ql)
            for opt in (q.get("options") or []):
                ol = QLabel(str(opt))
                ol.setWordWrap(True)
                ol.setFont(font(11))
                ol.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; background: transparent;")
                box.addWidget(ol)
            ans = QLabel("答案：" + (q.get("answer") or "见解析"))
            ans.setWordWrap(True)
            ans.setFont(font(11, 600))
            ans.setStyleSheet(f"color:{Colors.OK_FG}; background: transparent;")
            box.addWidget(ans)
            if q.get("explain"):
                ex = QLabel("解析：" + q["explain"])
                ex.setWordWrap(True)
                ex.setFont(font(11))
                ex.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; background: transparent;")
                box.addWidget(ex)
            self.quiz_box.addWidget(card)

    def _clear_quiz(self):
        while self.quiz_box.count():
            item = self.quiz_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
