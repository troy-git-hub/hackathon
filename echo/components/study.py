"""
Echo - 学习工具风格组件
  CatAvatar   矢量线稿猫头（只负责情绪反馈，随主题变色，高分屏清晰）
  BreakPath   断点页三节点：刚才会的 → 掉队的那一步 → 老师讲到这里
  LessonStep  补课页三段式中的一段（左侧轨道 + 标签 + 内容）
  SkillRow    回响页一行：知识点 + 掌握度条 + ✓ ? ! 三态
  ReviewChain 回响页复习链：你的掉队点 ↓ 前置 ↓ 建议复习
"""
import math

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt5.QtGui import QPainter, QPainterPath, QColor, QPen, QBrush, QFont

from echo.theme import Colors, Radius, Spacing, font


# ======================= 猫头像 =======================
class CatAvatar(QWidget):
    """线稿猫头。emotion: idle / ok / warn / lost / thinking / fixed"""

    def __init__(self, size=30, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._emotion = "idle"
        self._blink = False
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._do_blink)
        self._blink_timer.start(4200)
        self._revert = QTimer(self)
        self._revert.setSingleShot(True)
        self._revert.timeout.connect(lambda: self.set_emotion("idle"))

    def set_emotion(self, emotion, hold_ms=0):
        """hold_ms > 0 时，过一会儿自动回到 idle。"""
        self._emotion = emotion
        self._revert.stop()
        if hold_ms:
            self._revert.start(hold_ms)
        self.update()

    def _do_blink(self):
        if self._emotion != "idle":
            return
        self._blink = True
        self.update()
        QTimer.singleShot(140, self._end_blink)

    def _end_blink(self):
        self._blink = False
        self.update()

    def paintEvent(self, e):
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = s / 32.0
        p.scale(k, k)

        emo = self._emotion
        line = QColor(Colors.TEXT_PRIMARY)
        if emo == "lost":
            line = QColor(Colors.ACCENT)
        elif emo in ("ok", "fixed"):
            line = QColor(Colors.OK_FG)
        fill = QColor(Colors.SURFACE)

        # 头 + 两只耳朵（一条闭合路径，线稿风格）
        head = QPainterPath()
        head.moveTo(6.2, 13.0)
        head.lineTo(5.0, 4.2)
        head.lineTo(12.0, 8.6)
        head.quadTo(16.0, 7.6, 20.0, 8.6)
        head.lineTo(27.0, 4.2)
        head.lineTo(25.8, 13.0)
        head.cubicTo(28.6, 19.5, 24.5, 27.6, 16.0, 27.6)
        head.cubicTo(7.5, 27.6, 3.4, 19.5, 6.2, 13.0)
        p.setPen(QPen(line, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(fill)
        p.drawPath(head)

        pen = QPen(line, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        ly, lx, rx = 17.2, 11.4, 20.6

        def dot(x, y, r=1.5):
            p.setBrush(line)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)

        # 眼睛
        if emo in ("ok", "fixed"):                      # ^ ^
            for x in (lx, rx):
                path = QPainterPath()
                path.moveTo(x - 2.0, ly + 0.8)
                path.quadTo(x, ly - 2.2, x + 2.0, ly + 0.8)
                p.drawPath(path)
        elif emo == "lost":                             # 下垂的眼睛
            for x, d in ((lx, 1), (rx, -1)):
                p.drawLine(QPointF(x - 2.0, ly - 1.2 * d), QPointF(x + 2.0, ly + 1.2 * d))
                dot(x, ly + 1.6, 1.2)
        elif emo == "warn":                             # 一只眯一只睁
            p.drawLine(QPointF(lx - 2.0, ly), QPointF(lx + 2.0, ly))
            dot(rx, ly, 1.6)
        elif emo == "thinking":                         # 往上看
            dot(lx + 0.6, ly - 1.0)
            dot(rx + 0.6, ly - 1.0)
        elif self._blink:
            p.drawLine(QPointF(lx - 1.8, ly), QPointF(lx + 1.8, ly))
            p.drawLine(QPointF(rx - 1.8, ly), QPointF(rx + 1.8, ly))
        else:
            dot(lx, ly)
            dot(rx, ly)

        # 鼻子 + 嘴
        p.setPen(QPen(line, 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        mouth = QPainterPath()
        if emo in ("ok", "fixed"):
            mouth.moveTo(13.4, 21.4)
            mouth.quadTo(16.0, 24.6, 18.6, 21.4)
        elif emo == "lost":
            mouth.moveTo(13.8, 23.4)
            mouth.quadTo(16.0, 21.4, 18.2, 23.4)
        else:
            mouth.moveTo(13.6, 21.6)
            mouth.quadTo(14.8, 23.0, 16.0, 21.6)
            mouth.quadTo(17.2, 23.0, 18.4, 21.6)
        p.drawPath(mouth)

        # 情绪小符号
        if emo == "warn":
            p.setPen(QColor(Colors.TEXT_SECONDARY))
            f = QFont()
            f.setPixelSize(9)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(24, -1, 9, 11), Qt.AlignCenter, "?")
        elif emo == "thinking":
            for i in range(3):
                dot(23.5 + i * 2.6, 3.0 - i * 0.2, 0.9)
        p.end()


# ======================= 断点页三节点 =======================
ROLE_STYLE = {
    "known": ("刚才会的", "OK_FG"),
    "break": ("掉队的那一步", "ACCENT"),
    "now":   ("老师讲到这里", "NOW_FG"),
}
RAIL_X = 11
NODE_R = 7
TEXT_LEFT = 30


class _PathNode(QWidget):
    def __init__(self, role, concept, note="", first=False, last=False, parent=None):
        super().__init__(parent)
        self.role, self.first, self.last = role, first, last
        label, color_key = ROLE_STYLE[role]
        self.color = QColor(getattr(Colors, color_key))
        is_bp = role == "break"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(TEXT_LEFT, 6 if not is_bp else 8, 8, 8 if not is_bp else 10)
        lay.setSpacing(2)

        cap = QLabel(f"{label}  ·  {concept.timecode}")
        cap.setStyleSheet(f"color: {self.color.name() if is_bp else Colors.TEXT_SECONDARY};"
                          f"font-size: 11px; font-weight: {700 if is_bp else 500};"
                          "background: transparent;")
        lay.addWidget(cap)

        name = QLabel(concept.topic)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY if role != 'known' else Colors.TEXT_SECONDARY};"
            f"font-size: {16 if is_bp else 14}px; font-weight: {700 if is_bp else 500};"
            "background: transparent;")
        lay.addWidget(name)

        if is_bp and note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 12px; background: transparent;")
            lay.addWidget(n)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        cy = 16 if self.role != "break" else 18

        if self.role == "break":   # 断点行：唯一的强调底色
            p.setPen(QPen(QColor(Colors.ACCENT_BORDER), 1))
            p.setBrush(QColor(Colors.ACCENT_SOFT))
            p.drawRoundedRect(QRectF(TEXT_LEFT - 8, 1, self.width() - TEXT_LEFT + 7, h - 2),
                              Radius.MD, Radius.MD)

        p.setPen(QPen(QColor(Colors.BORDER_STRONG), 2))
        if not self.first:
            p.drawLine(QPointF(RAIL_X, 0), QPointF(RAIL_X, cy - NODE_R - 2))
        if not self.last:
            p.drawLine(QPointF(RAIL_X, cy + NODE_R + 2), QPointF(RAIL_X, h))

        c = self.color
        if self.role == "known":         # 空心对勾
            p.setPen(QPen(c, 1.6))
            p.setBrush(QColor(Colors.WINDOW_BG))
            p.drawEllipse(QPointF(RAIL_X, cy), NODE_R, NODE_R)
            path = QPainterPath()
            path.moveTo(RAIL_X - 3.2, cy + 0.2)
            path.lineTo(RAIL_X - 0.8, cy + 2.6)
            path.lineTo(RAIL_X + 3.4, cy - 2.4)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        elif self.role == "break":       # 实心强调色 + 「!」
            halo = QColor(c)
            halo.setAlphaF(0.22)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(RAIL_X, cy), NODE_R + 4, NODE_R + 4)
            p.setBrush(c)
            p.drawEllipse(QPointF(RAIL_X, cy), NODE_R, NODE_R)
            p.setPen(QColor(Colors.ON_ACCENT))
            p.setFont(font(10, QFont.Black))
            p.drawText(QRectF(RAIL_X - NODE_R, cy - NODE_R, NODE_R * 2, NODE_R * 2),
                       Qt.AlignCenter, "!")
        else:                            # 现在：中性实心点
            p.setPen(QPen(c, 1.6))
            p.setBrush(QColor(Colors.WINDOW_BG))
            p.drawEllipse(QPointF(RAIL_X, cy), NODE_R, NODE_R)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(RAIL_X, cy), 3.2, 3.2)
        p.end()


class BreakPath(QWidget):
    """只展示三个节点：刚才会的 → 掉队的那一步 → 老师讲到这里。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

    def clear(self):
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def set_path(self, concepts, breakpoint_tc, note=""):
        """concepts：后端给的时间轴片段；从中挑出 断点前一个 / 断点 / 最后一个。"""
        self.clear()
        if not concepts:
            return
        idx = next((i for i, c in enumerate(concepts) if c.timecode == breakpoint_tc), None)
        if idx is None:
            idx = max(0, len(concepts) - 2)
        nodes = []
        if idx > 0:
            nodes.append(("known", concepts[idx - 1]))
        nodes.append(("break", concepts[idx]))
        if idx < len(concepts) - 1:
            nodes.append(("now", concepts[-1]))
        for i, (role, c) in enumerate(nodes):
            self._lay.addWidget(_PathNode(role, c, note if role == "break" else "",
                                          first=(i == 0), last=(i == len(nodes) - 1)))


# ======================= 补课三段式 =======================
STEP_STYLE = {
    "known": ("你已经知道", "OK_FG"),
    "step":  ("中间漏了这一步", "ACCENT"),
    "now":   ("所以现在你能听懂", "NOW_FG"),
}


class LessonStep(QWidget):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        label, ck = STEP_STYLE[kind]
        self.color = QColor(getattr(Colors, ck))
        self.last = kind == "now"
        main = kind == "step"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(TEXT_LEFT, 0, 0, 14 if not self.last else 0)
        lay.setSpacing(4)
        cap = QLabel(label)
        cap.setStyleSheet(f"color: {self.color.name() if kind != 'now' else Colors.TEXT_SECONDARY};"
                          f"font-size: 12px; font-weight: 700; background: transparent;")
        lay.addWidget(cap)

        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if main:
            self.body.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; background: {Colors.ACCENT_SOFT};"
                f"border: 1px solid {Colors.ACCENT_BORDER}; border-radius: {Radius.MD}px;"
                f"padding: 10px 12px;")
        else:
            self.body.setStyleSheet(f"color: {Colors.TEXT_PRIMARY if kind == 'now' else Colors.TEXT_SECONDARY};"
                                    f"font-size: 13px; background: transparent;")
        lay.addWidget(self.body)

    def setText(self, html_text):
        self.body.setText(html_text)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = 9
        if not self.last:
            p.setPen(QPen(QColor(Colors.BORDER_STRONG), 2))
            p.drawLine(QPointF(RAIL_X, cy + 7), QPointF(RAIL_X, self.height()))
        num = {"known": "1", "step": "2", "now": "3"}[self.kind]
        if self.kind == "step":
            p.setPen(Qt.NoPen)
            p.setBrush(self.color)
            fg = QColor(Colors.ON_ACCENT)
        else:
            p.setPen(QPen(QColor(Colors.BORDER_STRONG), 1.4))
            p.setBrush(QColor(Colors.WINDOW_BG))
            fg = QColor(Colors.TEXT_SECONDARY)
        p.drawEllipse(QPointF(RAIL_X, cy), 8, 8)
        p.setPen(fg)
        p.setFont(font(10, QFont.Bold))
        p.drawText(QRectF(RAIL_X - 8, cy - 8, 16, 16), Qt.AlignCenter, num)
        p.end()


# ======================= 回响：掌握度条 + 复习链 =======================
def echo_status(raw):
    if raw in ("ok", "fixed"):
        return raw
    return "review"


def echo_mark(status, mastery):
    """回响行的三态图标：✓ 跟上了（含已补上）/ ? 有点懵 / ! 掉队了。"""
    if status in ("ok", "fixed"):
        return "ok"
    return "unsure" if mastery >= 0.5 else "lost"


# mark → (图标字, 颜色键, 实心?, 进度条颜色键)
MARK_STYLE = {
    "ok":     ("✓", "OK_FG", True, "OK_FG"),
    "unsure": ("?", "ACCENT", False, "ACCENT_BORDER"),
    "lost":   ("!", "ACCENT", True, "ACCENT"),
}


class _MasteryBar(QWidget):
    def __init__(self, value, color, parent=None):
        super().__init__(parent)
        self.value = max(0.06, min(1.0, value))   # 再低也露一点头，截图里看得出是条
        self.color = QColor(color)
        self.setFixedHeight(8)
        self.setMinimumWidth(80)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QColor(Colors.BORDER))
        p.drawRoundedRect(r, 4, 4)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, r.width() * self.value, r.height()), 4, 4)
        p.end()


class _MarkIcon(QWidget):
    def __init__(self, mark, parent=None):
        super().__init__(parent)
        self.glyph, ck, self.solid, _ = MARK_STYLE[mark]
        self.color = QColor(getattr(Colors, ck))
        self.setFixedSize(20, 20)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1.5, 1.5, 17, 17)
        if self.solid:
            p.setPen(Qt.NoPen)
            p.setBrush(self.color)
            fg = QColor(Colors.ON_ACCENT)
        else:
            p.setPen(QPen(self.color, 1.6))
            p.setBrush(QColor(Colors.WINDOW_BG))
            fg = self.color
        p.drawEllipse(r)
        if self.glyph == "✓":            # 对勾自己画，小尺寸下比字形清楚
            path = QPainterPath()
            path.moveTo(5.8, 10.4)
            path.lineTo(8.8, 13.3)
            path.lineTo(14.4, 7.2)
            p.setPen(QPen(fg, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        else:
            p.setPen(fg)
            p.setFont(font(11, QFont.Black))
            p.drawText(r, Qt.AlignCenter, self.glyph)
        p.end()


class SkillRow(QWidget):
    """回响页一行：知识点 ━━━━━░░ ✓ / ? / !；note 是名字下的小字（已补上 / 自己看了）。"""

    def __init__(self, name, mastery, mark, note="", parent=None):
        super().__init__(parent)
        _, _, _, bar_ck = MARK_STYLE[mark]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 5, 0, 5)
        lay.setSpacing(Spacing.MD)

        col = QVBoxLayout()
        col.setSpacing(0)
        n = QLabel(name)
        n.setFixedWidth(128)
        n.setWordWrap(True)
        n.setToolTip(name)
        n.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;"
                        f"font-weight: {600 if mark == 'lost' else 400}; background: transparent;")
        col.addWidget(n)
        if note:
            t = QLabel(note)
            t.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 11px; background: transparent;")
            col.addWidget(t)
        lay.addLayout(col)

        lay.addWidget(_MasteryBar(mastery, getattr(Colors, bar_ck)), 1, Qt.AlignVCenter)
        lay.addWidget(_MarkIcon(mark), 0, Qt.AlignVCenter)


class ReviewChain(QFrame):
    """你的掉队点 ↓ 前置 ↓ 建议复习：根源。chain 为「掉队点 → … → 根源」。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReviewChain")
        self.setStyleSheet(
            f"QFrame#ReviewChain {{ background: {Colors.SURFACE}; border: 1px solid {Colors.BORDER};"
            f"border-radius: {Radius.MD}px; }}")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        self._lay.setSpacing(2)

    def _add(self, text, style):
        l = QLabel(text)
        l.setWordWrap(True)
        l.setAlignment(Qt.AlignHCenter)
        l.setStyleSheet(style + "background: transparent; border: none;")
        self._lay.addWidget(l)

    def _arrow(self):
        self._add("↓", f"color: {Colors.TEXT_DISABLED}; font-size: 14px;")

    def set_chain(self, chain, suggestion=""):
        """有内容返回 True；没有掉队点也没有建议则返回 False（调用方隐藏）。"""
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = []
        for c in chain:
            c = str(c).strip()
            if c and (not items or items[-1] != c):
                items.append(c)
        suggestion = (suggestion or "").strip()
        if not items:
            if not suggestion:
                return False
            self._add(suggestion, f"color: {Colors.TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")
            return True

        cap = f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"
        self._add("你的掉队点", f"color: {Colors.ACCENT}; font-size: 11px; font-weight: 700;")
        self._add(items[0], f"color: {Colors.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;")
        for mid in items[1:-1]:
            self._arrow()
            self._add("前置", cap)
            self._add(mid, f"color: {Colors.TEXT_PRIMARY}; font-size: 14px;")
        root = items[-1] if len(items) > 1 else None
        self._arrow()
        if root:
            self._add(f"建议复习：{root}",
                      f"color: {Colors.ACCENT}; font-size: 16px; font-weight: 700;")
            if suggestion and not (suggestion.startswith("建议复习") and root in suggestion):
                self._lay.addSpacing(6)
                self._add(suggestion, f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        else:
            self._add(suggestion or f"建议复习：{items[0]}",
                      f"color: {Colors.ACCENT}; font-size: 16px; font-weight: 700;")
        return True
