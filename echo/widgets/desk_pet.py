"""
Echo - 桌面宠物（经典表情包猫）

assets/emojis 里的表情包猫，跟着课堂状态变表情，
头顶气泡报「老师在讲 X」，找到断点时提醒你点它。

交互：
    单击        打开 / 收起 Echo 面板
    双击        圈一下问 AI
    拖动        挪位置
    鼠标来回蹭  摸摸它（会冒爱心）
    右键        圈一下问 AI / 跟上了 / 有点懵 / 我掉队了 / 设置 / 隐藏桌宠
"""
import math
import os
import random
import time

from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from echo.theme import Colors, font

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "assets", "emojis")
FACES = {
    "idle": "smug.png", "listening": "stare.png", "thinking": "key.png", "alert": "shock.png",
    "ok": "happy.png", "fixed": "happy.png", "warn": "confused.png", "lost": "cry.png",
    "love": "happy.png", "done": "happy.png",
}
IDLE_TIPS = ["听不懂就圈一下，我帮你看 👀", "跟得上吗？跟上了就点我一下", "掉队了别硬撑，右键我",
             "我一直在听，放心听课", "双击我，圈出看不懂的地方"]


def _load_face(path) -> QPixmap:
    """裁到图里最大一块（猫头）的包围盒：去掉切图带进来的水印碎片 / 邻图耳朵和透明边。"""
    pm = QPixmap(path)
    try:
        import io
        import numpy as np
        from PIL import Image
        from collections import deque
        im = Image.open(path).convert("RGBA")
        a = np.array(im)
        mask = a[:, :, 3] > 24
        h, w = mask.shape
        label = np.zeros((h, w), np.int32)
        best, best_n, n = 0, 0, 0
        for y0, x0 in zip(*np.nonzero(mask)):
            if label[y0, x0]:
                continue
            n += 1
            label[y0, x0] = n
            q, cnt = deque([(y0, x0)]), 0
            while q:
                y, x = q.popleft()
                cnt += 1
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not label[yy, xx]:
                        label[yy, xx] = n
                        q.append((yy, xx))
            if cnt > best_n:
                best, best_n = n, cnt
        ys, xs = np.nonzero(label == best)
        a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        buf = io.BytesIO()
        Image.fromarray(a).save(buf, "PNG")
        clean = QPixmap()
        if clean.loadFromData(buf.getvalue()):
            return clean
    except Exception:
        pass
    return pm


class DeskPet(QWidget):
    circle_ask = pyqtSignal()        # 要求开始圈选（由外部接到 start_circle_ask）

    def __init__(self, win=None, tray=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.win, self.tray = win, tray
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Echo · 单击打开面板 · 双击圈一下问 AI · 右键更多")

        self.mood = "idle"
        self._mood_until = 0.0
        self._base_mood = "idle"
        self.status = "listening"
        self.topic = ""
        self.badge = False

        self.bubble = ""
        self._bubble_until = 0.0
        self._hearts = []
        self._jump_t = -10.0
        self._shake_t = -10.0
        self._t0 = time.time()
        self._blink_t = time.time() + random.uniform(2, 5)
        self._blinking = False

        # 尺寸 / 布局：经典表情包猫（比原来再小一点）
        self.CAT, self.W, self.H = 88, 168, 172
        self.faces = {}
        for k, f in FACES.items():
            pm = _load_face(os.path.join(ASSETS, f))
            if not pm.isNull():
                self.faces[k] = pm
        self.setFixedSize(self.W, self.H)

        self._press = None
        self._dragged = False
        self._pet_x = None
        self._pet_dist = 0.0
        self._last_interact = time.time()

        self._click_timer = QTimer(self, singleShot=True, interval=240, timeout=self._single_click)
        self._anim = QTimer(self, interval=33, timeout=self._tick)
        self._anim.start()
        self._idle = QTimer(self, interval=75_000, timeout=self._idle_tip)
        self._idle.start()

        if win is not None and hasattr(win, "echo"):
            e = win.echo
            e.status.connect(self._on_status)
            e.concept.connect(self._on_concept)
            e.breakpoint.connect(self._on_breakpoint)
            e.echo.connect(self._on_echo)
            e.error.connect(lambda m: self.say("出了点小问题，我还在", 3000, "warn"))
        self.say("我是 Echo，陪你听课～", 4000, "ok")

    # ================= 对外 =================
    def say(self, text, ms=4000, mood=None, hold_ms=None):
        self.bubble = text
        self._bubble_until = time.time() + ms / 1000
        if mood:
            self.set_mood(mood, hold_ms if hold_ms is not None else ms)
        self.update()

    def set_mood(self, mood, hold_ms=0):
        if hold_ms:
            self.mood = mood
            self._mood_until = time.time() + hold_ms / 1000
        else:
            self._base_mood = mood
        if mood in ("alert", "fixed", "ok", "love", "done"):
            self._jump_t = time.time()
        if mood in ("lost", "alert"):
            self._shake_t = time.time()
        self.update()

    def place_default(self):
        g = QApplication.primaryScreen().availableGeometry()
        x = g.right() - self.width() - 12
        if self.win is not None and self.win.isVisible():
            x = self.win.x() - self.width() + 30
        self.move(max(g.left(), x), g.bottom() - self.height() - 4)

    # ================= 后端事件 =================
    def _on_status(self, st):
        self.status = st
        base = {"analyzing": "thinking", "summarizing": "thinking", "loading_asr": "thinking",
                "done": "done"}.get(st, "listening")
        self.set_mood(base)
        if st == "analyzing":
            self.say("我回看一下刚才的课…", 15000)
        elif st == "summarizing":
            self.say("在整理这节课的回响…", 15000)
        elif st == "loading_asr":
            self.say("正在加载耳朵（语音识别）…", 8000)

    def _on_concept(self, c):
        cur = self.win.echo.engine.current_concept() if self.win is not None else c
        topic = cur.topic if cur else c.topic
        if topic and topic != self.topic:
            self.topic = topic
            if self.status == "listening":
                self.say(f"老师在讲：{topic}", 5000)

    def _on_breakpoint(self, bp, concepts):
        hidden = self.win is not None and not self.win.isVisible()
        self.badge = hidden
        self.say(("找到啦！点我看补课" if hidden else "找到你掉队的地方了"), 9000, "alert", 4000)

    def _on_echo(self, report):
        self.badge = self.win is not None and not self.win.isVisible()
        self.say("这节课的回响好了，点我看", 9000, "done", 4000)

    def _idle_tip(self):
        if time.time() - self._last_interact < 60 or self.status != "listening" or time.time() < self._bubble_until:
            return
        tips = IDLE_TIPS + ([f"老师在讲：{self.topic}"] if self.topic else [])
        self.say(random.choice(tips), 4500)

    # ================= 动作 =================
    def _toggle_panel(self):
        self.badge = False
        if self.tray is not None:
            self.tray.toggle_window()
        elif self.win is not None:
            self.win.setVisible(not self.win.isVisible())

    def _feedback(self, kind):
        self._last_interact = time.time()
        if kind == "lost":
            if self.tray is not None:
                self.tray.lost()
            elif self.win is not None:
                self.win.show()
                self.win._on_lost()
            self.set_mood("lost", 2500)
            return
        handler = getattr(self.win, "_on_ok" if kind == "ok" else "_on_warn", None)
        if handler:
            handler()
        elif self.win is not None:
            self.win.echo.feedback(kind)
        self.say("收到，继续加油！" if kind == "ok" else "记下了，有点懵就圈出来问我", 2500, kind)

    def _menu(self, pos):
        m = QMenu(self)
        key = getattr(self.tray, "keys", {}).get(3, "") if self.tray is not None else ""
        m.addAction(f"✏️  圈一下问 AI    {key}".rstrip(), self.circle_ask.emit)
        m.addSeparator()
        m.addAction("✓  跟上了", lambda: self._feedback("ok"))
        m.addAction("?  有点懵", lambda: self._feedback("warn"))
        m.addAction("!  我掉队了", lambda: self._feedback("lost"))
        m.addSeparator()
        visible = self.win is not None and self.win.isVisible()
        m.addAction("收起 Echo 面板" if visible else "打开 Echo 面板", self._toggle_panel)
        if self.tray is not None:
            m.addAction("设置…", self.tray.open_settings)
        m.addAction("先藏起来（托盘里能叫回）", self.hide)
        m.exec_(pos)

    # ================= 鼠标 =================
    def _cat_rect(self) -> QRectF:
        x = (self.W - self.CAT) / 2
        return QRectF(x, self.H - self.CAT - 6, self.CAT, self.CAT)

    def mousePressEvent(self, e):
        self._last_interact = time.time()
        if e.button() == Qt.LeftButton:
            self._press = (e.globalPos(), self.pos())
            self._dragged = False
        elif e.button() == Qt.RightButton:
            self._menu(e.globalPos())

    def mouseMoveEvent(self, e):
        if self._press and e.buttons() & Qt.LeftButton:
            d = e.globalPos() - self._press[0]
            if d.manhattanLength() > 5:
                self._dragged = True
            if self._dragged:
                self.move(self._press[1] + d)
            return
        if self._cat_rect().contains(QPointF(e.pos())):
            if self._pet_x is not None:
                self._pet_dist += abs(e.x() - self._pet_x)
            self._pet_x = e.x()
            if self._pet_dist > 260:
                self._pet_dist = 0
                self._hearts.append([e.x(), e.y() - 10, time.time()])
                if self.mood != "love":
                    self.say(random.choice(["呼噜呼噜～", "喵～ 再摸摸", "好舒服，继续听课吧"]), 2000, "love", 2000)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press:
            if not self._dragged:
                self._click_timer.start()
            self._press = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._press = None
            self.circle_ask.emit()

    def _single_click(self):
        self._toggle_panel()

    def enterEvent(self, e):
        self._pet_x, self._pet_dist = None, 0.0

    def leaveEvent(self, e):
        self._pet_x = None

    # ================= 动画 =================
    def _tick(self):
        now = time.time()
        if self.mood != self._base_mood and now > self._mood_until:
            self.mood = self._base_mood
        if now > self._blink_t:
            self._blinking = True
            if now > self._blink_t + 0.12:
                self._blinking = False
                self._blink_t = now + random.uniform(2.5, 6)
        self._hearts = [h for h in self._hearts if now - h[2] < 1.4]
        self.update()

    # ================= 绘制 =================
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        now = time.time()
        t = now - self._t0
        cat = self._cat_rect()

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QRectF(cat.center().x() - 32, cat.bottom() - 2, 64, 8))

        breathe = 1 + 0.02 * math.sin(t * 2.4)
        dy = 0.0
        jt = now - self._jump_t
        if jt < 0.5:
            dy = -14 * math.sin(math.pi * jt / 0.5)
        dx = 0.0
        st = now - self._shake_t
        if st < 0.45:
            dx = 4 * math.sin(st * 60) * (1 - st / 0.45)

        self._draw_classic(p, cat, breathe, dy, dx)

        if self.badge:
            r = QRectF(cat.right() - 16, cat.top() + 6, 20, 20)
            p.setBrush(QColor(Colors.ACCENT))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawEllipse(r)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(font(12, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, "!")

        for x, y, born in self._hearts:
            k = (now - born) / 1.4
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 92, 120, int(255 * (1 - k))))
            self._heart(p, QPointF(x + 8 * math.sin(k * 6), y - 50 * k), 9 + 4 * k)

        if self.bubble and now < self._bubble_until:
            self._draw_bubble(p, self.bubble, cat, min(1.0, (self._bubble_until - now) / 0.3))

    # ---------- classic：表情包猫 ----------
    def _draw_classic(self, p, cat, breathe, dy, dx):
        pm = self.faces.get(self.mood) or self.faces.get("idle")
        if pm is not None:
            w = cat.width()
            h = w * pm.height() / pm.width() * breathe
            target = QRectF(cat.center().x() - w / 2 + dx, cat.bottom() - h + dy, w, h)
            p.drawPixmap(target, pm, QRectF(pm.rect()))
        else:
            p.setBrush(QColor("#F2A93B"))
            p.drawEllipse(cat.adjusted(10, 20 + dy, -10, dy))
        # 思考中：头顶三个点
        now = time.time()
        if self.status in ("analyzing", "summarizing", "loading_asr") and now > self._bubble_until:
            t = now - self._t0
            p.setPen(Qt.NoPen)
            for i in range(3):
                a = 0.35 + 0.65 * max(0.0, math.sin(t * 4 - i * 0.8))
                p.setBrush(QColor(242, 169, 59, int(255 * a)))
                p.drawEllipse(QPointF(cat.center().x() - 14 + i * 14, cat.top() + 2), 4, 4)

    def _heart(self, p, c: QPointF, s):
        path = QPainterPath()
        path.moveTo(c.x(), c.y() + s * 0.35)
        path.cubicTo(c.x() - s, c.y() - s * 0.4, c.x() - s * 0.4, c.y() - s, c.x(), c.y() - s * 0.35)
        path.cubicTo(c.x() + s * 0.4, c.y() - s, c.x() + s, c.y() - s * 0.4, c.x(), c.y() + s * 0.35)
        p.drawPath(path)

    def _draw_bubble(self, p, text, cat: QRectF, alpha):
        f = font(12, QFont.DemiBold)
        fm = QFontMetrics(f)
        maxw = self.W - 16
        br = fm.boundingRect(0, 0, maxw - 24, 200, Qt.TextWordWrap, text)
        w, h = min(maxw, br.width() + 24), min(60, br.height() + 14)
        box = QRectF((self.W - w) / 2, cat.top() - h - 12, w, h)
        p.setOpacity(alpha)
        path = QPainterPath()
        path.addRoundedRect(box, 12, 12)
        tail = QPainterPath()
        cx = cat.center().x()
        tail.moveTo(cx - 7, box.bottom() - 1)
        tail.lineTo(cx, box.bottom() + 8)
        tail.lineTo(cx + 7, box.bottom() - 1)
        path = path.united(tail)
        p.setPen(QPen(QColor(Colors.BUBBLE_BORDER), 1))
        p.setBrush(QColor(Colors.BUBBLE_BG))
        p.drawPath(path)
        p.setPen(QColor(Colors.TEXT_PRIMARY))
        p.setFont(f)
        p.drawText(box.adjusted(12, 7, -12, -7), Qt.AlignCenter | Qt.TextWordWrap, text)
        p.setOpacity(1.0)
