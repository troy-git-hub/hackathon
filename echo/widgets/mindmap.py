"""
Echo - 知识地图

一节课上完，把知识点画成一张图：节点是知识点，连线是「学这个之前得先懂那个」。
点某个节点，下面就是它的详情 —— 老师当时怎么讲的、不懂的话这一步缺在哪、以及一道题和解析。

画布是可交互的：空白处拖动平移、滚轮缩放、点节点选中、直接把节点拖到别处。
新开一张图会自动缩放到刚好放得下，之后由你自己摆。

自包含组件，宿主只要：
    map = MindMapPage(parent)
    map.show_lesson(lesson, mistakes)      # lesson 传 store.get_lesson(ts)，或 mindmap.from_report(report)
信号：
    map.practice_requested(str)            # 学生点了「出题练一练」，参数是知识点名

图上全 ok 的知识点也画，但弱化显示；掉队过/待回看的用强调色，一眼能看出卡在哪。
"""
from PyQt5.QtCore import QPointF, QRectF, QSizeF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from echo.backend import mindmap
from echo.i18n import tr
from echo.theme import Colors, Radius, Spacing, font

NODE_W, NODE_H = 118, 54
LEVEL_H = 96
GAP_X = 20
PAD = 24
MIN_SCALE, MAX_SCALE = 0.45, 2.4
DRAG_SLOP = 4          # 超过这个位移才算拖动，不然算点击


def status_style(status: str) -> tuple:
    """状态 → (描边色, 底色, 文字色)。

    已跟上的也画成正常的节点 —— 它们同样是这节课的知识点，
    只靠颜色区分「要不要回看」，不能弱到看着像不存在（否则整张图会被看成只有错题）。
    """
    if status == mindmap.STATUS_REVIEW:
        return Colors.DANGER, Colors.DANGER_BG, Colors.TEXT_PRIMARY
    if status == mindmap.STATUS_FIXED:
        return Colors.ACCENT, Colors.ACCENT_SOFT, Colors.TEXT_PRIMARY
    return Colors.BORDER_STRONG, Colors.SURFACE, Colors.TEXT_PRIMARY


class _Canvas(QWidget):
    """知识地图画布。

    画的时候把画笔平移到 _offset、缩放到 _scale，之后一律用「世界坐标」画，
    所以拖动只是改 _offset、缩放只是改 _scale，节点位置不用重算。
    """

    node_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(300)      # 太小的话自动缩放会把节点压得看不清
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._nodes = []          # [(topic, status, timecode)]
        self._pos = {}            # topic -> QPointF（世界坐标）
        self._levels = {}         # topic -> 依赖层级，重置视图时用来还原排布
        self._review_first = ""   # 复习链的根源概念，图上标出来告诉学生从哪开始补
        self._edges = []          # [(topic_a, topic_b)]
        self._world = QSizeF(1, 1)
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._selected = ""
        self._hover = ""
        self._drag = None
        self._press = None
        self._moved = False
        self._need_fit = False
        self._user_moved = False   # 学生自己拖过/缩放过之后，就别再自动改他的视图

    # ---------------- 数据 ----------------
    def set_graph(self, graph: dict, selected: str = "", keep_positions: bool = False):
        """换一张图。keep_positions=True 时保留用户拖动后的位置（只换选中态用）。"""
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        topics = [n["id"] for n in nodes]
        self._nodes = [(n["id"], n.get("status", "ok"), n.get("timecode") or "")
                       for n in nodes]
        self._levels = {n["id"]: n.get("level", 0) for n in nodes}
        self._review_first = graph.get("review_first") or ""
        self._edges = [(e["from"], e["to"]) for e in edges
                       if e.get("from") is not None and e.get("to") is not None]
        if not keep_positions or set(self._pos) != set(topics):
            self._auto_layout(nodes)
            self._need_fit = True
            self._user_moved = False
        self._selected = selected
        self.update()

    def _auto_layout(self, nodes: list):
        """默认排布：按依赖层级从上往下，同层横向均分。"""
        by_level = {}
        for n in nodes:
            by_level.setdefault(n.get("level", 0), []).append(n["id"])
        levels = sorted(by_level)
        widest = max((len(by_level[lv]) for lv in levels), default=1)
        width = max(320.0, widest * (NODE_W + GAP_X) + PAD * 2)
        self._pos = {}
        for li, lv in enumerate(levels):
            row = by_level[lv]
            step = width / len(row)
            y = PAD + li * LEVEL_H
            for i, topic in enumerate(row):
                self._pos[topic] = QPointF(step * i + (step - NODE_W) / 2, y)
        self._world = QSizeF(width, PAD * 2 + max(1, len(levels)) * LEVEL_H)

    def reset_view(self):
        """回到默认排布和缩放。"""
        self._auto_layout([{"id": t, "level": self._levels.get(t, 0)}
                           for t, _s, _tc in self._nodes])
        self._user_moved = False
        self.fit()

    def resizeEvent(self, e):
        """学生还没自己摆弄过时，跟着尺寸重新适配 —— 详情面板一长高，地图容易被挤出去。"""
        super().resizeEvent(e)
        if self._nodes and not self._user_moved:
            self.fit()

    def fit(self):
        w, h = max(self.width(), 40), max(self.height(), 40)
        sx = w / max(self._world.width(), 1.0)
        sy = h / max(self._world.height(), 1.0)
        self._scale = max(MIN_SCALE, min(MAX_SCALE, min(sx, sy, 1.0)))
        self._offset = QPointF((w - self._world.width() * self._scale) / 2,
                               (h - self._world.height() * self._scale) / 2)
        self.update()

    def _ensure_fit(self):
        if self._need_fit and self.width() > 60 and self._nodes:
            self._need_fit = False
            self.fit()

    # ---------------- 坐标 ----------------
    def _rect(self, topic: str) -> QRectF:
        p = self._pos.get(topic)
        return QRectF(p.x(), p.y(), NODE_W, NODE_H) if p else QRectF()

    def _to_world(self, pos) -> QPointF:
        return QPointF((pos.x() - self._offset.x()) / self._scale,
                       (pos.y() - self._offset.y()) / self._scale)

    def _from_world(self, pt: QPointF) -> QPointF:
        return QPointF(pt.x() * self._scale + self._offset.x(),
                       pt.y() * self._scale + self._offset.y())

    def _hit(self, pos) -> str:
        wp = self._to_world(pos)
        for topic, _status, _tc in self._nodes:
            if self._rect(topic).contains(wp):
                return topic
        return ""

    # ---------------- 交互 ----------------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._press = QPointF(e.pos())
        self._moved = False
        hit = self._hit(e.pos())
        if hit:
            self._drag = {"kind": "node", "topic": hit,
                          "start": self._to_world(e.pos()),
                          "origin": QPointF(self._pos[hit])}
        else:
            self._drag = {"kind": "pan", "origin": QPointF(self._offset)}

    def mouseMoveEvent(self, e):
        if self._drag:
            if (QPointF(e.pos()) - self._press).manhattanLength() > DRAG_SLOP:
                self._moved = True
            if self._moved:
                self._user_moved = True    # 学生自己动过视图了，之后不再自动适配
                if self._drag["kind"] == "pan":
                    self._offset = self._drag["origin"] + (QPointF(e.pos()) - self._press)
                else:
                    topic = self._drag["topic"]
                    delta = self._to_world(e.pos()) - self._drag["start"]
                    self._pos[topic] = self._drag["origin"] + delta
                self.update()
            return
        hit = self._hit(e.pos())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.OpenHandCursor if not hit else Qt.PointingHandCursor)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        drag, moved = self._drag, self._moved
        self._drag = None
        if drag and not moved and drag["kind"] == "node":
            self._selected = drag["topic"]
            self.node_clicked.emit(drag["topic"])
            self.update()
        elif not drag or not moved:
            self.update()

    def wheelEvent(self, e):
        """滚轮缩放，以光标为中心。"""
        factor = 1.12 ** (e.angleDelta().y() / 120.0)
        new = max(MIN_SCALE, min(MAX_SCALE, self._scale * factor))
        if abs(new - self._scale) < 1e-6:
            return
        cursor = QPointF(e.pos())
        self._offset = cursor - (cursor - self._offset) * (new / self._scale)
        self._scale = new
        self._user_moved = True
        self.update()

    def leaveEvent(self, e):
        self._hover = ""
        self.update()

    # ---------------- 绘制 ----------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        # 自己铺底：拖动时不会透出下面的东西
        p.fillRect(self.rect(), QColor(Colors.WINDOW_BG))
        self._ensure_fit()
        p.translate(self._offset)
        p.scale(self._scale, self._scale)

        p.setBrush(Qt.NoBrush)
        for a, b in self._edges:
            if a not in self._pos or b not in self._pos:
                continue
            ra, rb = self._rect(a), self._rect(b)
            x1, y1 = ra.center().x(), ra.bottom()
            x2, y2 = rb.center().x(), rb.top()
            if y2 < y1:                       # 目标在上方（用户拖乱了）：改从下往上连
                y1, y2 = ra.top(), rb.bottom()
            mid = (y1 + y2) / 2
            hot = self._selected and (a == self._selected or b == self._selected)
            pen = QPen(QColor(Colors.ACCENT if hot else Colors.BORDER_STRONG), 3.0 if hot else 2.0)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            path = QPainterPath(QPointF(x1, y1))
            path.cubicTo(QPointF(x1, mid), QPointF(x2, mid), QPointF(x2, y2))
            p.drawPath(path)

            direction = 1 if y2 >= y1 else -1
            tip = QPointF(x2, y2)
            arrow = QPainterPath(tip)
            arrow.lineTo(x2 - 5.5, y2 - 7.5 * direction)
            arrow.lineTo(x2 + 5.5, y2 - 7.5 * direction)
            arrow.closeSubpath()
            p.setBrush(QBrush(QColor(Colors.ACCENT if hot else Colors.BORDER_STRONG)))
            p.setPen(Qt.NoPen)
            p.drawPath(arrow)
            p.setBrush(Qt.NoBrush)

        for topic, status, timecode in self._nodes:
            rect = self._rect(topic)
            border, fill, text = status_style(status)
            selected = topic == self._selected
            hover = topic == self._hover
            first = topic == self._review_first
            if hover and not selected:
                fill = Colors.SURFACE_HOVER
            p.setBrush(QBrush(QColor(fill)))
            if selected or first:
                pen = QPen(QColor(Colors.ACCENT if selected else Colors.PRIMARY), 2.0)
                if first and not selected:
                    pen.setStyle(Qt.DashLine)      # 建议先看：虚线描边，跟选中态区分开
                p.setPen(pen)
            else:
                p.setPen(QPen(QColor(border), 1.3))
            path = QPainterPath()
            path.addRoundedRect(rect, Radius.MD, Radius.MD)
            p.drawPath(path)

            p.setPen(QPen(QColor(text)))
            p.setFont(font(11, 600 if status != mindmap.STATUS_OK else 500))
            fm = QFontMetrics(p.font())
            label = fm.elidedText(topic, Qt.ElideMiddle, int(NODE_W) - 16)
            # 有讲课时间码时，知识点名往上挪一点，下面空出来标时间
            if timecode:
                p.drawText(QRectF(rect.left(), rect.top() + 6, rect.width(), NODE_H - 22),
                           Qt.AlignCenter, label)
                p.setPen(QPen(QColor(Colors.TEXT_SECONDARY)))
                p.setFont(font(9))
                p.drawText(QRectF(rect.left(), rect.bottom() - 17, rect.width(), 14),
                           Qt.AlignCenter, timecode)
            else:
                p.drawText(rect, Qt.AlignCenter, label)

            if status != mindmap.STATUS_OK:
                p.setBrush(QBrush(QColor(border)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(rect.left() + 10, rect.top() + 11), 3.2, 3.2)
                p.setBrush(Qt.NoBrush)

            if first:                              # 右上角小标：先看这个
                p.setBrush(QBrush(QColor(Colors.PRIMARY)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(rect.right() - 10, rect.top() + 11), 3.2, 3.2)
                p.setBrush(Qt.NoBrush)
        p.end()


class MindMapPage(QWidget):
    """知识地图整页：上面是图，下面是选中知识点的详情。

    宿主接一个信号就够了：
        practice_requested(str)  —— 学生想练这个知识点，宿主跳练习页即可
    """

    practice_requested = pyqtSignal(str)
    # 页面内容变高/变矮了（换课、出题回来、展开详情），宿主据此重新适配窗口高度；
    # 不接的话出题回来那几张卡会被窗口底边截掉
    content_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lesson = {}
        self._mistakes = []
        self._graph = {"nodes": [], "edges": []}
        self._build()
        self.detail.content_changed.connect(self.content_changed.emit)

    # ---------- 构建 ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.SM)

        title = QLabel(tr("知识地图", "Knowledge map"))
        title.setFont(font(14, 600))
        self.sub = QLabel("")
        self.sub.setFont(font(11))
        self.sub.setWordWrap(True)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(title)
        head.addWidget(self.sub)
        root.addLayout(head)

        # 课程内容：光有图不够，历史课进来也得能一眼看到这节课讲了什么
        self.lesson_title = QLabel("")
        self.lesson_title.setFont(font(13, 600))
        self.lesson_title.setWordWrap(True)
        self.lesson_summary = QLabel("")
        self.lesson_summary.setWordWrap(True)
        self.lesson_summary.setFont(font(11))
        self.lesson_summary.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.lesson_points = QLabel("")
        self.lesson_points.setWordWrap(True)
        self.lesson_points.setFont(font(11))
        self.content_box = QWidget()
        cb = QVBoxLayout(self.content_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(3)
        cb.addWidget(self.lesson_title)
        cb.addWidget(self.lesson_summary)
        cb.addWidget(self.lesson_points)
        root.addWidget(self.content_box)

        self.canvas = _Canvas()
        self.canvas.node_clicked.connect(self._on_node)
        root.addWidget(self.canvas, 1)
        tools = QHBoxLayout()
        tools.setSpacing(Spacing.SM)
        self.legend = QLabel(tr("● 待回看   ● 补上了   ○ 已跟上   ⋯ 建议先看",
                                "● To review   ● Caught up   ○ Kept up   ⋯ Start here"))
        self.legend.setFont(font(10))
        self.legend.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        tools.addWidget(self.legend)
        tools.addStretch(1)
        self.reset_btn = QPushButton(tr("重置视图", "Reset view"))
        self.reset_btn.setObjectName("MapTool")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setToolTip(tr("回到自动排布的位置", "Back to the automatic layout"))
        self.reset_btn.clicked.connect(lambda: self.canvas.reset_view())
        tools.addWidget(self.reset_btn)
        root.addLayout(tools)

        hint = QLabel(tr("拖动空白处平移 · 滚轮缩放 · 点节点看讲解 · 节点也能直接拖走",
                         "Drag to pan · scroll to zoom · click a node for the explanation · nodes can be dragged too"))
        hint.setFont(font(10))
        hint.setStyleSheet(f"color:{Colors.TEXT_DISABLED};")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.detail = _DetailPanel()
        self.detail.practice_requested.connect(self.practice_requested.emit)
        root.addWidget(self.detail)

        self.empty = QLabel(tr("这节课还没有知识点记录。上完一节课，这里会长出知识地图。",
                               "No knowledge points recorded for this lesson yet. "
                               "Finish a lesson and the map grows here."))
        self.empty.setWordWrap(True)
        self.empty.setFont(font(12))
        self.empty.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        root.addWidget(self.empty)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget {{ background: transparent; }}
            QPushButton#MapTool {{
                background: {Colors.SURFACE}; color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px;
                padding: 3px 10px; font-size: 11px;
            }}
            QPushButton#MapTool:hover {{
                color: {Colors.TEXT_PRIMARY}; border-color: {Colors.ACCENT};
            }}
        """)

    # ---------- 对外 ----------
    def show_lesson(self, lesson: dict, mistakes: list = None):
        """喂一节课。lesson 传 store.get_lesson(ts) 或 mindmap.from_report(report)。"""
        self._lesson = lesson or {}
        self._mistakes = mistakes if mistakes is not None else []
        self._graph = mindmap.build(self._lesson, self._mistakes)

        # 课程内容
        title = (self._lesson.get("title") or "").strip()
        summary = (self._lesson.get("summary") or "").strip()
        if len(summary) > 90:           # 摘要太长会把地图挤没，留两句就够
            summary = summary[:90].rstrip() + "…"
        points = [str(h).strip() for h in (self._lesson.get("highlights") or []) if str(h).strip()]
        self.lesson_title.setText(title)
        self.lesson_title.setVisible(bool(title))
        self.lesson_summary.setText(summary)
        self.lesson_summary.setVisible(bool(summary))
        self.lesson_points.setText("\n".join("· " + p for p in points[:4]))
        self.lesson_points.setVisible(bool(points))
        self.content_box.setVisible(bool(title or summary or points))

        nodes = self._graph["nodes"]
        review = sum(1 for n in nodes if n["status"] == mindmap.STATUS_REVIEW)
        fixed = sum(1 for n in nodes if n["status"] == mindmap.STATUS_FIXED)
        if nodes:
            bits = [tr(f"{len(nodes)} 个知识点", f"{len(nodes)} knowledge points")]
            if review:
                bits.append(tr(f"{review} 个待回看", f"{review} to review"))
            if fixed:
                bits.append(tr(f"{fixed} 个已补上", f"{fixed} caught up"))
            if not review:
                bits.append(tr("都跟上了", "all kept up"))
            self.sub.setText(" · ".join(bits))
            self.empty.setText("")
        else:
            self.sub.setText(tr("这节课没有留下知识点记录", "No knowledge points recorded for this lesson"))
            self.empty.setText(tr("知识点没记下来，上面是这节课的内容回顾。",
                                  "Knowledge points weren't captured — the lesson recap is above.")
                               if self.content_box.isVisible()
                               else tr("这节课还没有内容记录。", "No notes for this lesson yet."))

        self.empty.setVisible(not nodes)
        self.canvas.setVisible(bool(nodes))
        self.legend.setVisible(bool(nodes))
        self.reset_btn.setVisible(bool(nodes))
        self.canvas.set_graph(self._graph)
        self.detail.clear()
        self.detail.setVisible(bool(nodes))
        self.content_changed.emit()

    def select(self, topic: str):
        """外部直接选中某个知识点（比如从别处跳进来）。"""
        self._on_node(topic)

    # ---------- 内部 ----------
    def _on_node(self, topic: str):
        # 只换选中态，别把学生拖好的位置重置掉
        self.canvas.set_graph(self._graph, selected=topic, keep_positions=True)
        self.detail.show_detail(mindmap.node_detail(
            self._lesson, topic, self._mistakes, self._graph.get("review_first", "")))
        self.detail.load_questions(self._lesson, topic, self._mistakes)


class _DetailPanel(QFrame):
    """单个知识点的详情：老师怎么讲的 + 缺的那一步 + 一道题和解析。"""

    practice_requested = pyqtSignal(str)
    content_changed = pyqtSignal()          # 详情面板变高了，宿主该重新算窗口高度
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

        self.practice_btn = QPushButton(tr("出题练一练", "Practise this"))
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
        self.body_lbl.setText(tr("点上面的知识点，这里显示讲解和题目。",
                                 "Click a knowledge point above to see its explanation and questions."))
        self.body_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.miss_lbl.setVisible(False)
        self._clear_quiz()

    def show_detail(self, detail: dict):
        self._topic = detail.get("topic") or ""
        self.topic_lbl.setText(self._topic)
        status = detail.get("status")
        label = {mindmap.STATUS_REVIEW: tr("待回看", "To review"),
                 mindmap.STATUS_FIXED: tr("已补上", "Caught up"),
                 mindmap.STATUS_OK: tr("已跟上", "Kept up")}.get(status, "")
        color = {mindmap.STATUS_REVIEW: Colors.DANGER,
                 mindmap.STATUS_FIXED: Colors.ACCENT,
                 mindmap.STATUS_OK: Colors.OK_FG}.get(status, Colors.TEXT_SECONDARY)
        self.status_lbl.setText("● " + label if label else "")
        self.status_lbl.setStyleSheet(f"color:{color};")

        taught = (detail.get("taught") or "").strip()
        tc = (detail.get("timecode") or "").strip()
        if tc:
            taught = tr(f"老师讲到 {tc}　{taught}", f"Teacher covered this at {tc}　{taught}").strip()
        self.body_lbl.setText(taught or tr("这节课没有留下这个知识点的讲解记录。",
                                           "No explanation was recorded for this knowledge point."))
        self.body_lbl.setStyleSheet("")

        # 不懂的话，把它缺的那一步说清楚
        miss_bits = []
        if detail.get("review_first"):
            miss_bits.append(tr("建议先补这个 —— 复习链追到的最根源概念。",
                                "Start here — this is the root concept the review chain leads back to."))
        if detail.get("missing"):
            miss_bits.append(tr("你可能卡在：", "You probably got stuck on: ") + detail["missing"])
        if detail.get("known"):
            miss_bits.append(tr("先确认你已经知道的：", "First, confirm what you already know: ") + detail["known"])
        if detail.get("step"):
            miss_bits.append(tr("漏掉的那一步：", "The step you missed: ") + detail["step"])
        if detail.get("micro_lesson"):
            miss_bits.append(detail["micro_lesson"])
        if miss_bits:
            self.miss_lbl.setText("\n".join(miss_bits))
            self.miss_lbl.setStyleSheet("")
        else:
            self.miss_lbl.setText(tr("这个知识点没掉队过，可以直接出题确认一下。",
                                     "You never fell behind here — try a question to confirm."))
            self.miss_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.miss_lbl.setVisible(True)
        self.content_changed.emit()

    def load_questions(self, lesson: dict, topic: str, mistakes: list = None):
        self._clear_quiz()
        asking = QLabel(tr("正在准备这道题…", "Preparing a question…"))
        asking.setFont(font(11))
        asking.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};")
        self.quiz_box.addWidget(asking)

        def done(questions):
            # 这里还在后台线程，只能发信号，不能碰控件
            self._questions_ready.emit(questions)

        mindmap.questions_for(lesson, topic, mistakes, n=2, on_done=done, on_error=lambda _m: None)
        self.content_changed.emit()

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
            head = QLabel(tr(f"第 {i} 题", f"Question {i}"))
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
            ans = QLabel(tr("答案：", "Answer: ") + (q.get("answer") or tr("见解析", "see explanation")))
            ans.setWordWrap(True)
            ans.setFont(font(11, 600))
            ans.setStyleSheet(f"color:{Colors.OK_FG}; background: transparent;")
            box.addWidget(ans)
            if q.get("explain"):
                ex = QLabel(tr("解析：", "Explanation: ") + q["explain"])
                ex.setWordWrap(True)
                ex.setFont(font(11))
                ex.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; background: transparent;")
                box.addWidget(ex)
            self.quiz_box.addWidget(card)
        self.content_changed.emit()

    def _clear_quiz(self):
        while self.quiz_box.count():
            item = self.quiz_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
