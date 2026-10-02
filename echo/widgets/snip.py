"""
Echo - 「圈一下问 AI」界面

    start_circle_ask(bridge, hide=[...])
        ① 截当前屏幕（鼠标所在屏），全屏变暗
        ② 学生像截图工具一样：用画笔圈 / 荧光笔标 / 写文字批注（右键或 Esc 取消）
        ③ 确认后，把圈过、批注过的区域截图 + 课堂上下文 → AskPanel 流式回答，可追问

画笔 / 批注真的画进截图里，AI 看到的就是学生圈的那张图。
"""
import html
import logging
import re

from PyQt5.QtCore import Qt, QPoint, QRect, QRectF, QTimer, QBuffer, QByteArray, QIODevice, pyqtSignal
from PyQt5.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath,
                         QPen, QPixmap)
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from echo.backend.vision import QUICK_QUESTIONS, VisionChat, lesson_context
from echo.theme import Colors, font

log = logging.getLogger("echo.snip")

PALETTE = {
    "红": "#FF4D4F", "橙": "#FA8C16", "黄": "#FADB14", "绿": "#52C41A", "蓝": "#1677FF",
}
WIDTHS = {"细": 3, "中": 6, "粗": 11}
_alive = []                      # 防止顶层窗口被 GC


# ================= ① 全屏圈选 + 批注 =================
class SnipOverlay(QWidget):
    def __init__(self, screen, on_done, on_cancel):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.screen_ = screen
        self.on_done, self.on_cancel = on_done, on_cancel
        self.shot = screen.grabWindow(0)
        self.dpr = self.shot.devicePixelRatio() or 1.0
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)

        self.tool = "pen"            # pen / highlighter / text
        self.color = PALETTE["红"]
        self.line_w = WIDTHS["中"]
        self.strokes = []            # [{tool, color, width, path}]  path 为逻辑坐标 QPainterPath
        self.notes = []              # [{pos: QPoint, text, color}]
        self.cur = None              # 正在画的一笔
        self._text_edit = None
        self._last_note_pt = None

        self._build_toolbar()
        self.setCursor(Qt.CrossCursor)

    # ---------------- 工具栏 ----------------
    def _build_toolbar(self):
        bar = QFrame(self)
        bar.setObjectName("snipBar")
        bar.setStyleSheet(f"""
            #snipBar {{ background:rgba(22,22,26,235); border-radius:12px; }}
            QPushButton {{ color:#FFFFFF; background:transparent; border:none; border-radius:8px;
                           padding:5px 10px; font-size:13px; }}
            QPushButton:hover {{ background:rgba(255,255,255,0.14); }}
            QPushButton:checked {{ background:rgba(242,169,59,0.28); color:#FFD08A; }}
            QPushButton#confirm {{ background:#F2A93B; color:#1B1406; font-weight:600; padding:6px 16px; }}
            QPushButton#confirm:hover {{ background:#F5B755; }}
            QPushButton#confirm:disabled {{ background:rgba(255,255,255,0.16); color:rgba(255,255,255,0.5); }}
            QPushButton#sw {{ border-radius:9px; }}
            QPushButton#sw:checked {{ border:2px solid #FFFFFF; }}
            QLabel {{ color:#B9B9BE; font-size:12px; }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)

        self.tools = QButtonGroup(self, exclusive=True)
        for key, label in (("pen", "✏️ 画笔"), ("highlighter", "🖍️ 荧光笔"), ("text", "🅃 批注")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.tools.addButton(b)
            lay.addWidget(b)
            b.clicked.connect(lambda _, k=key: self._set_tool(k))
        self.tools.buttons()[0].setChecked(True)

        lay.addSpacing(8)
        self.colors = QButtonGroup(self, exclusive=True)
        for name, c in PALETTE.items():
            b = QPushButton()
            b.setObjectName("sw")
            b.setFixedSize(20, 20)
            b.setCheckable(True)
            b.setToolTip(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"background:{c}; border-radius:9px;")
            self.colors.addButton(b)
            lay.addWidget(b)
            b.clicked.connect(lambda _, cc=c: self._set_color(cc))
        self.colors.buttons()[0].setChecked(True)

        lay.addSpacing(8)
        self.widths = QButtonGroup(self, exclusive=True)
        for name, w in WIDTHS.items():
            b = QPushButton("●")
            b.setToolTip(f"{name}线（{w}px）")
            b.setStyleSheet(f"font-size:{9 + w}px; padding:2px 8px;")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.widths.addButton(b)
            lay.addWidget(b)
            b.clicked.connect(lambda _, ww=w: self._set_width(ww))
        self.widths.buttons()[1].setChecked(True)

        lay.addStretch()
        undo = QPushButton("↶ 撤销")
        undo.setCursor(Qt.PointingHandCursor)
        undo.clicked.connect(self._undo)
        lay.addWidget(undo)
        clear = QPushButton("清空")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear)
        lay.addWidget(clear)
        cancel = QPushButton("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self._cancel)
        lay.addWidget(cancel)
        self.confirm = QPushButton("✓ 问 AI")
        self.confirm.setObjectName("confirm")
        self.confirm.setCursor(Qt.PointingHandCursor)
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self._commit)
        lay.addWidget(self.confirm)

        self.bar = bar
        bar.adjustSize()
        bar.move((self.width() - bar.width()) // 2, 14)
        self.hint = QLabel("用画笔圈出看不懂的地方，或点「批注」写下你的问题，再点「问 AI」", self)
        self.hint.setStyleSheet("color:#E6E6E8; font-size:13px; background:rgba(22,22,26,200);"
                                "border-radius:8px; padding:4px 12px;")
        self.hint.adjustSize()

    def _hint_pos(self):
        self.hint.move((self.width() - self.hint.width()) // 2, self.bar.y() + self.bar.height() + 8)

    def showEvent(self, e):
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self._hint_pos()

    # ---------------- 工具状态 ----------------
    def _set_tool(self, tool):
        self.tool = tool
        if tool == "text":
            self.setCursor(Qt.IBeamCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def _set_color(self, c):
        self.color = c

    def _set_width(self, w):
        self.line_w = w

    def _refresh_confirm(self):
        self.confirm.setEnabled(bool(self.strokes or self.notes))
        self.hint.setText("点「✓ 问 AI」让 Echo 讲解" if (self.strokes or self.notes)
                          else "用画笔圈出看不懂的地方，或点「批注」写下你的问题，再点「问 AI」")
        self.hint.adjustSize()
        self._hint_pos()

    def _undo(self):
        if self.notes:
            self.notes.pop()
        elif self.strokes:
            self.strokes.pop()
        self._refresh_confirm()
        self.update()

    def _clear(self):
        self.strokes.clear()
        self.notes.clear()
        self._refresh_confirm()
        self.update()

    # ---------------- 交互 ----------------
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            if self._text_edit is not None:
                self._text_edit.close()
                self._text_edit = None
            else:
                self._cancel()

    def mousePressEvent(self, e):
        if self.bar.geometry().contains(e.pos()) or self._text_edit is not None:
            return
        if e.button() == Qt.RightButton:
            self._cancel()
            return
        if e.button() != Qt.LeftButton:
            return
        if self.tool == "text":
            self._place_text(e.pos())
            return
        path = QPainterPath(e.pos())
        self.cur = {"tool": self.tool, "color": self.color, "width": self.line_w, "path": path}

    def mouseMoveEvent(self, e):
        if self.cur is not None and e.buttons() & Qt.LeftButton:
            self.cur["path"].lineTo(e.pos())
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.cur is not None:
            self.strokes.append(self.cur)
            self.cur = None
            self._refresh_confirm()
            self.update()

    def _place_text(self, pos):
        self._last_note_pt = pos
        ed = QLineEdit(self)
        ed.setFont(font(14))
        ed.setPlaceholderText("写下你的问题…")
        ed.setStyleSheet(f"background:#FFFFFF; color:#1A1A1A; border:1px solid {self.color};"
                         "border-radius:6px; padding:4px 8px;")
        ed.setFixedWidth(260)
        ed.move(pos.x(), pos.y())
        ed.returnPressed.connect(lambda: self._commit_text(ed))
        ed.editingFinished.connect(lambda: self._commit_text(ed))
        self._text_edit = ed
        ed.show()
        ed.setFocus()

    def _commit_text(self, ed):
        text = ed.text().strip()
        ed.close()
        self._text_edit = None
        if text:
            self.notes.append({"pos": self._last_note_pt, "text": text, "color": self.color})
            self._refresh_confirm()
        self._set_tool("pen")
        self.tools.buttons()[0].setChecked(True)
        self.update()

    def _cancel(self):
        self.close()
        self.on_cancel()

    # ---------------- 选区与裁剪 ----------------
    def _bounds(self) -> QRect:
        """所有笔迹 + 批注的包围盒，加一点边距。"""
        r = QRect()
        for s in self.strokes:
            r = r.united(s["path"].boundingRect().toAlignedRect())
        fm = QFontMetrics(font(14))
        for n in self.notes:
            w = fm.horizontalAdvance(n["text"]) + 16
            r = r.united(QRect(n["pos"], QPoint(n["pos"].x() + w, n["pos"].y() + 22)))
        if r.isEmpty():
            return QRect()
        return r.adjusted(-48, -48, 48, 60).intersected(self.rect())

    def _commit(self):
        rect = self._bounds()
        if rect.width() < 16 or rect.height() < 16:
            return
        crop = self._render_crop(rect)
        global_rect = QRect(self.mapToGlobal(rect.topLeft()), rect.size())
        self.close()
        self.on_done(crop, global_rect)

    def _render_crop(self, rect: QRect) -> QPixmap:
        d = self.dpr
        src = QRect(int(rect.x() * d), int(rect.y() * d), int(rect.width() * d), int(rect.height() * d))
        crop = self.shot.copy(src)
        crop.setDevicePixelRatio(1.0)
        p = QPainter(crop)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(d, d)
        p.translate(-rect.topLeft())
        self._draw_marks(p)
        p.end()
        if max(crop.width(), crop.height()) > 1600:
            crop = crop.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return crop

    def _draw_marks(self, p: QPainter):
        """把笔迹和批注画出来（屏幕预览和烧进截图共用）。"""
        for s in self.strokes:
            if s["tool"] == "highlighter":
                pen = QPen(QColor(s["color"]))
                pen.setWidth(s["width"] * 3)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                col = QColor(s["color"])
                col.setAlpha(120)
                pen.setColor(col)
                p.setPen(pen)
                p.drawPath(s["path"])
            else:
                p.setPen(QPen(QColor(s["color"]), s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(s["path"])
        p.setFont(font(14))
        for n in self.notes:
            fm = QFontMetrics(p.font())
            w = fm.horizontalAdvance(n["text"]) + 12
            box = QRectF(n["pos"].x(), n["pos"].y(), w, fm.height() + 8)
            bg = QColor("#FFFFFF")
            bg.setAlpha(225)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QPen(QColor(n["color"]), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor("#1A1A1A"))
            p.drawText(box.adjusted(6, 4, -6, -4), Qt.AlignVCenter | Qt.AlignLeft, n["text"])

    # ---------------- 绘制 ----------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 96))
        self._draw_marks(p)
        # 高亮正在画的这一笔（还没松手，不属于 strokes）
        if self.cur is not None:
            s = self.cur
            if s["tool"] == "highlighter":
                col = QColor(s["color"]); col.setAlpha(120)
                p.setPen(QPen(col, s["width"] * 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            else:
                p.setPen(QPen(QColor(s["color"]), s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(s["path"])


# ================= ② 问答面板 =================
def _png_bytes(pm: QPixmap) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(ba)


def _plain(text: str) -> str:
    """去掉模型偶尔夹带的 Markdown / LaTeX 记号，面板里按纯文本显示。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = text.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    return text


class AskPanel(QWidget):
    _delta = pyqtSignal(str)
    _done = pyqtSignal(str)
    _error = pyqtSignal(str)

    W = 400

    def __init__(self, crop: QPixmap, anchor: QRect, bridge=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.bridge = bridge
        engine = getattr(bridge, "engine", None)
        self.chat = VisionChat(_png_bytes(crop), lesson_context(engine))
        self.answer = ""
        self.transcript_html = ""
        self._drag = None
        self._delta.connect(self._on_delta)
        self._done.connect(self._on_done)
        self._error.connect(self._on_error)
        self._build(crop)
        self._place(anchor)

    # ---- UI ----
    def _build(self, crop):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        card = QFrame(self)
        card.setObjectName("askCard")
        card.setStyleSheet(f"""
            #askCard {{ background:{Colors.WINDOW_BG}; border:1px solid {Colors.WINDOW_BORDER}; border-radius:14px; }}
            QLabel {{ color:{Colors.TEXT_PRIMARY}; background:transparent; }}
            QPushButton#chip {{ background:{Colors.SURFACE}; color:{Colors.TEXT_PRIMARY}; border:1px solid {Colors.BORDER};
                               border-radius:13px; padding:4px 10px; }}
            QPushButton#chip:hover {{ border-color:{Colors.ACCENT}; color:{Colors.ACCENT}; }}
            QPushButton#ghost {{ background:transparent; color:{Colors.TEXT_SECONDARY}; border:none; padding:4px 8px; }}
            QPushButton#ghost:hover {{ color:{Colors.ACCENT}; }}
            QPushButton#send {{ background:{Colors.ACCENT}; color:{Colors.ON_ACCENT}; border:none; border-radius:8px; padding:6px 14px; }}
            QPushButton#send:hover {{ background:{Colors.ACCENT_HOVER}; }}
            QPushButton#send:disabled {{ background:{Colors.BORDER_STRONG}; }}
            QLineEdit {{ background:{Colors.SURFACE}; color:{Colors.TEXT_PRIMARY}; border:1px solid {Colors.BORDER};
                        border-radius:8px; padding:6px 10px; }}
            QLineEdit:focus {{ border-color:{Colors.ACCENT}; }}
            QTextBrowser {{ background:transparent; color:{Colors.TEXT_PRIMARY}; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:6px; margin:0; }}
            QScrollBar::handle:vertical {{ background:{Colors.BORDER_STRONG}; border-radius:3px; min-height:24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; height:0; }}
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, Colors.SHADOW_ALPHA + 30))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel("问问 Echo")
        self.title.setFont(font(14, QFont.DemiBold))
        head.addWidget(self.title)
        head.addStretch()
        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close)
        head.addWidget(close)
        v.addLayout(head)

        thumb = QLabel()
        pm = crop.scaled(self.W - 60, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        thumb.setPixmap(pm)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet(f"background:{Colors.CODE_BG}; border-radius:8px; padding:6px;")
        v.addWidget(thumb)

        self.chips = QWidget()
        cl = QVBoxLayout(self.chips)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        for i, q in enumerate(QUICK_QUESTIONS):
            if i % 2 == 0:
                row = QHBoxLayout()
                row.setSpacing(6)
                cl.addLayout(row)
            b = QPushButton(q)
            b.setObjectName("chip")
            b.setFont(font(12))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, q=q: self.send(q))
            row.addWidget(b)
        v.addWidget(self.chips)

        self.view = QTextBrowser()
        self.view.setFont(font(13))
        self.view.setOpenExternalLinks(False)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.hide()
        v.addWidget(self.view)

        inp = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setFont(font(13))
        self.input.setPlaceholderText("想问什么？比如：为什么分母是 P(B)？")
        self.input.returnPressed.connect(lambda: self.send(self.input.text()))
        inp.addWidget(self.input, 1)
        self.btn_send = QPushButton("问")
        self.btn_send.setObjectName("send")
        self.btn_send.setFont(font(13, QFont.DemiBold))
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.clicked.connect(lambda: self.send(self.input.text()))
        inp.addWidget(self.btn_send)
        v.addLayout(inp)

        foot = QHBoxLayout()
        self.btn_mark = QPushButton("记为「有点懵」")
        self.btn_mark.setObjectName("ghost")
        self.btn_mark.setToolTip("记到课堂时间轴，下课的回响里会提醒你复习")
        self.btn_mark.setCursor(Qt.PointingHandCursor)
        self.btn_mark.clicked.connect(self._mark_warn)
        self.btn_copy = QPushButton("复制回答")
        self.btn_copy.setObjectName("ghost")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.answer))
        for b in (self.btn_mark, self.btn_copy):
            b.setFont(font(12))
            b.hide()
            foot.addWidget(b)
        foot.addStretch()
        v.addLayout(foot)

        self.setFixedWidth(self.W)
        self.input.setFocus()

    def _place(self, anchor: QRect):
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.adjustSize()
        x = anchor.right() + 8
        if x + self.width() > g.right():
            x = anchor.left() - self.width() - 8
        x = max(g.left(), min(x, g.right() - self.width()))
        y = max(g.top(), min(anchor.top() - 14, g.bottom() - 600))
        self.move(x, y)

    # ---- 问答 ----
    def send(self, q: str):
        q = (q or "").strip()
        if not q or not self.btn_send.isEnabled():
            return
        self.input.clear()
        self.chips.hide()
        self.view.show()
        self.view.setMinimumHeight(300)
        self.transcript_html += (f"<p style='color:{Colors.ACCENT}; font-weight:600; margin:10px 0 4px 0'>"
                                 f"你：{html.escape(q)}</p>")
        self.answer = ""
        self._set_busy(True)
        self._render(thinking=True)
        self.chat.ask(q, self._delta.emit, self._done.emit, self._error.emit)
        self.adjustSize()

    def _set_busy(self, busy):
        self.btn_send.setEnabled(not busy)
        self.title.setText("Echo 正在看你圈的地方…" if busy else "问问 Echo")

    def _render(self, thinking=False):
        body = html.escape(_plain(self.answer)).replace("\n", "<br>")
        if thinking and not self.answer:
            body = f"<span style='color:{Colors.TEXT_SECONDARY}'>Echo 正在看你圈的地方…</span>"
        self.view.setHtml(self.transcript_html + f"<p style='line-height:150%; margin:0'>{body}</p>")
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_delta(self, d):
        self.answer += d
        self._render()

    def _on_done(self, answer):
        self.answer = answer
        body = html.escape(_plain(answer)).replace("\n", "<br>")
        self.transcript_html += f"<p style='line-height:150%; margin:0'>{body}</p>"
        self.view.setHtml(self.transcript_html)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self._set_busy(False)
        self.input.setPlaceholderText("还有哪里不懂？接着问")
        self.btn_copy.show()
        if self.bridge is not None and self.btn_mark.isEnabled():
            self.btn_mark.show()
        self.input.setFocus()

    def _on_error(self, msg):
        self.answer = ""
        self.transcript_html += f"<p style='color:{Colors.DANGER}; margin:0'>{html.escape(msg)}</p>"
        self.view.setHtml(self.transcript_html)
        self._set_busy(False)

    def _mark_warn(self):
        try:
            self.bridge.feedback("warn")
            self.btn_mark.setText("已记下 ✓")
            self.btn_mark.setEnabled(False)
        except Exception as e:
            log.warning("记录有点懵失败: %s", e)

    # ---- 窗口 ----
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().y() < 60:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def closeEvent(self, e):
        self.chat.cancel()
        if self in _alive:
            _alive.remove(self)
        super().closeEvent(e)


# ================= 入口 =================
_busy = False


def start_circle_ask(bridge=None, hide=(), on_finish=None):
    """开始一次圈选。hide：截图前临时藏起来的 Echo 窗口（桌宠 / 主窗口），圈完恢复。"""
    global _busy
    if _busy:
        return
    _busy = True
    hidden = [w for w in hide if w is not None and w.isVisible()]
    for w in hidden:
        w.hide()
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def restore():
        global _busy
        _busy = False
        for w in hidden:
            w.show()
        if on_finish:
            on_finish()

    def done(crop, rect):
        restore()
        panel = AskPanel(crop, rect, bridge)
        _alive.append(panel)
        panel.show()
        panel.activateWindow()
        panel.raise_()

    def grab():
        ov = SnipOverlay(screen, done, restore)
        _alive.append(ov)
        ov.show()

    QTimer.singleShot(180 if hidden else 0, grab)   # 等窗口真正消失再截图
