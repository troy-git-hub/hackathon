"""
Echo - 桌面宠物（表情包猫 + 真实声纹条，可收起成侧边小球）

展开时用 assets/emojis 里的表情包图；拖到屏幕左/右边缘会收起成一颗挂在侧边的小球
（360 加速球式吸附），小球里是矢量 CatAvatar 猫头（会眨眼）。旁边声纹条跟着老师声音
真实起伏；头顶气泡报「老师在讲 X」，找到断点时提醒你点它。

交互：
    单击        打开 / 收起 Echo 面板
    双击        圈一下问 AI
    拖动        挪位置（贴近屏幕边缘松手 → 收起成侧边球）
    鼠标来回蹭  摸摸它（会冒爱心）
    右键        圈一下问 AI / 跟上了 / 有点懵 / 我掉队了 / 设置 / 隐藏桌宠
"""
import math
import os
import random
import time

from PyQt5.QtCore import Qt, QPointF, QRectF, QSettings, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from echo.theme import Colors, font, style_menu
from echo.components.study import CatAvatar
from echo.widgets.dock_chat import DockChat
from echo.i18n import tr

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "assets", "emojis")
FACES = {
    "idle": "smug.png", "listening": "stare.png", "thinking": "key.png", "alert": "shock.png",
    "ok": "happy.png", "fixed": "happy.png", "warn": "confused.png", "lost": "cry.png",
    "love": "happy.png", "done": "happy.png",
}
IDLE_TIPS = [
    tr("听不懂就圈一下，我帮你看 👀", "Stuck? Circle it and I'll take a look 👀"),
    tr("跟得上吗？跟上了就点我一下", "Keeping up? Give me a click if you are"),
    tr("掉队了别硬撑，右键我", "Falling behind? Right-click me"),
    tr("我一直在听，放心听课", "I'm listening — just focus on the lesson"),
    tr("双击我，圈出看不懂的地方", "Double-click me to circle anything you don't get"),
]


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


class _DockBubble(QWidget):
    """磁吸态独立消息气泡，不撑宽窄条的鼠标区域。"""

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(196, 72)
        self.message = ""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(QColor(Colors.BUBBLE_BORDER), 1))
        p.setBrush(QColor(Colors.BUBBLE_BG))
        p.drawRoundedRect(box, 12, 12)
        p.setPen(QColor(Colors.TEXT_PRIMARY))
        p.setFont(font(11, QFont.DemiBold))
        p.drawText(box.adjusted(12, 8, -12, -8), Qt.TextWordWrap | Qt.AlignVCenter,
                   self.message[:60] + ("…" if len(self.message) > 60 else ""))


class DeskPet(QWidget):
    circle_ask = pyqtSignal()        # 要求开始圈选（由外部接到 start_circle_ask）

    # 桌宠心情 → CatAvatar 情绪（矢量猫头，跟主页/标题栏同一套画法，会眨眼）
    _MOOD_EMO = {
        "idle": "idle", "listening": "idle", "thinking": "thinking",
        "alert": "warn", "ok": "ok", "fixed": "ok", "love": "ok",
        "warn": "warn", "lost": "lost", "done": "ok",
    }
    # 收起后挂在屏幕侧边的「加速球」直径
    ORB = 48
    DOCK_H = 112
    FLYOUT_W = 230
    DOCK_MARGIN = 40

    def __init__(self, win=None, tray=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.win, self.tray = win, tray
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("Echo · 单击打开面板 · 双击圈一下问 AI · 拖到屏幕边缘收起",
                           "Echo · click to open panel · double-click to circle-ask AI · drag to screen edge to dock"))

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
        self._phase = 0.0
        self._level = 0.0          # 真实音频响度（0..1）
        self._level_env = 0.0      # 平滑后的响度包络

        # 尺寸 / 布局：表情包猫（左边）+ 真实声纹条（右边）；收起后只剩一个球
        self.CAT, self.W, self.H = 88, 176, 172
        self.GAP, self.VBAR_W = 10, 70
        self.VN = 9
        self._vbar = [0.05] * self.VN
        self.docked = False          # True = 收起成侧边加速球
        self.dock_side = ""          # "left" / "right"
        self._hover_expanded = False # 悬停临时展开：鼠标移开就收回
        self._hover_out_since = None
        self.skin = QSettings("Echo", "Echo").value("desktop_pet_skin", "cartoon")
        if self.skin not in ("cartoon", "line"):
            self.skin = "cartoon"
        self.setFixedSize(self.W, self.H)

        # 展开态用 assets/emojis 下的表情包图；收起态用矢量 CatAvatar（自动眨眼）。
        self.faces = {}
        for k, f in FACES.items():
            pm = _load_face(os.path.join(ASSETS, f))
            if not pm.isNull():
                self.faces[k] = pm
        self.cat = CatAvatar(self.CAT, self)
        self.cat.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._layout_cat()
        self._dock_bubble = _DockBubble()

        # 挂边小球点开的小窗：声纹 + 文字追问
        engine = self.win.echo.engine if (self.win is not None and hasattr(self.win, "echo")) else None
        self.chat = DockChat(engine)

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
            e.error.connect(lambda m: self.say(tr("出了点小问题，我还在", "Small hiccup, but I'm still here"), 3000, "warn"))
            if hasattr(e, "level"):
                e.level.connect(self._on_level)
        self.say(tr("我是 Echo，陪你听课～", "I'm Echo, your study buddy."), 4000, "ok")

    # ================= 对外 =================
    def say(self, text, ms=4000, mood=None, hold_ms=None):
        self.bubble = text
        self._bubble_until = time.time() + ms / 1000
        if mood:
            self.set_mood(mood, hold_ms if hold_ms is not None else ms)
        self._refresh_dock_bubble()
        self.update()

    def _refresh_dock_bubble(self):
        if not hasattr(self, "_dock_bubble"):
            return
        if not self.isVisible() or not self.docked or self._hover_expanded or time.time() >= self._bubble_until:
            self._dock_bubble.hide()
            return
        self._dock_bubble.message = self.bubble
        g = QApplication.primaryScreen().availableGeometry()
        x = self.x() + self.width() + 6 if self.dock_side == "left" else self.x() - self._dock_bubble.width() - 6
        y = max(g.top(), min(self.y() + self.DOCK_H - self._dock_bubble.height(),
                              g.bottom() - self._dock_bubble.height() + 1))
        self._dock_bubble.move(x, y)
        self._dock_bubble.show()
        self._dock_bubble.update()

    def set_mood(self, mood, hold_ms=0):
        self.mood = mood
        if hold_ms:
            self._mood_until = time.time() + hold_ms / 1000
        else:
            self._base_mood = mood
        self._sync_cat_emotion()
        if mood in ("alert", "fixed", "ok", "love", "done"):
            self._jump_t = time.time()
        if mood in ("lost", "alert"):
            self._shake_t = time.time()
        self.update()

    def _sync_cat_emotion(self):
        emo = self._MOOD_EMO.get(self.mood, "idle")
        self.cat.set_emotion(emo)
        if hasattr(self, "chat"):
            self.chat.set_emotion(emo)

    def set_skin(self, skin):
        if skin not in ("cartoon", "line"):
            return
        self.skin = skin
        QSettings("Echo", "Echo").setValue("desktop_pet_skin", skin)
        self._layout_cat()
        self.update()

    def place_default(self):
        g = QApplication.primaryScreen().availableGeometry()
        x = g.right() - self.width() - 12
        if self.win is not None and self.win.isVisible():
            x = self.win.x() - self.width() + 30
        self.move(max(g.left(), x), g.bottom() - self.height() - 4)

    # ================= 侧边收起（360 加速球式吸附） =================
    def _layout_cat(self):
        """桌面态和磁吸态始终使用同一皮肤。"""
        if self.docked and self._hover_expanded:
            s = 54
            self.cat.setFixedSize(s, s)
            self.cat.move(34 if self.dock_side == "left" else self.width() - 88, 26)
        elif self.docked:
            s = 32
            self.cat.setFixedSize(s, s)
            self.cat.move((self.ORB - s) // 2, 76)
        else:
            self.cat.setFixedSize(self.CAT, self.CAT)
            self.cat.move(4, self.H - self.CAT - 6)
        self.cat.setVisible(self.skin == "line")

    def _orb_rect(self) -> QRectF:
        return QRectF(2, 2, self.ORB - 4, self.DOCK_H - 4)

    def _set_docked(self, docked, side=""):
        """切换收起 / 展开；side ∈ {"left", "right"}。"""
        self._hover_expanded = False
        self._hover_out_since = None
        self.docked = docked
        self.dock_side = side if docked else ""
        self.setFixedSize(self.ORB if docked else self.W,
                          self.DOCK_H if docked else self.H)
        self._layout_cat()
        if not docked and hasattr(self, "chat"):
            self.chat.hide()   # 展开回桌宠时，把声纹/聊天小窗一并收掉
        self._refresh_dock_bubble()
        self.update()

    def _set_hover_expanded(self, expanded):
        if not self.docked or self._hover_expanded == expanded:
            return
        g = QApplication.primaryScreen().availableGeometry()
        center_y = self.y() + self.height() // 2
        self._hover_expanded = expanded
        self.setFixedSize(self.FLYOUT_W if expanded else self.ORB, self.DOCK_H)
        x = g.left() if self.dock_side == "left" else g.right() - self.width() + 1
        y = max(g.top(), min(center_y - self.height() // 2, g.bottom() - self.height() + 1))
        self.move(x, y)
        self._layout_cat()
        self._refresh_dock_bubble()
        self.update()

    def _update_dock_hover(self, now):
        """根据真实鼠标位置切换，避免窗口缩放引发的 enter/leave 事件抖动。"""
        if not self.docked or self._press or not self.isVisible():
            self._hover_out_since = None
            return
        inside = self.frameGeometry().contains(QCursor.pos())
        if inside:
            self._hover_out_since = None
            if not self._hover_expanded:
                self._set_hover_expanded(True)
        elif self._hover_expanded:
            if self._hover_out_since is None:
                self._hover_out_since = now
            elif now - self._hover_out_since >= 0.3:
                self._set_hover_expanded(False)

    def _snap_dock(self):
        """贴到屏幕左 / 右边缘，竖直方向不跑出屏。"""
        g = QApplication.primaryScreen().availableGeometry()
        x = g.left() if self.dock_side == "left" else g.right() - self.width() + 1
        y = max(g.top(), min(self.y(), g.bottom() - self.height()))
        self.move(x, y)
        self._refresh_dock_bubble()

    def _maybe_dock(self):
        """拖动松手后：贴近屏幕边缘就收起成侧边球，否则保持展开。"""
        g = QApplication.primaryScreen().availableGeometry()
        if self.x() - g.left() < self.DOCK_MARGIN:
            self._set_docked(True, "left")
        elif g.right() - (self.x() + self.width()) < self.DOCK_MARGIN:
            self._set_docked(True, "right")
        else:
            self._set_docked(False, "")
        if self.docked:
            self._snap_dock()

    # ================= 后端事件 =================
    def _on_status(self, st):
        self.status = st
        base = {"analyzing": "thinking", "summarizing": "thinking", "loading_asr": "thinking",
                "done": "done"}.get(st, "listening")
        self.set_mood(base)
        if st == "analyzing":
            self.say(tr("我回看一下刚才的课…", "Let me look back at that part…"), 15000)
        elif st == "summarizing":
            self.say(tr("在整理这节课的回响…", "Summarizing this lesson…"), 15000)
        elif st == "loading_asr":
            self.say(tr("正在加载耳朵（语音识别）…", "Loading speech recognition…"), 8000)

    def _on_level(self, level):
        self._level = max(0.0, min(1.0, float(level)))
        if hasattr(self, "chat") and self.chat.isVisible():
            self.chat.set_level(self._level)

    def _on_concept(self, c):
        cur = self.win.echo.engine.current_concept() if self.win is not None else c
        topic = cur.topic if cur else c.topic
        if topic and topic != self.topic:
            self.topic = topic
            if self.status == "listening":
                self.say(tr("老师在讲：", "Now teaching: ") + topic, 5000)

    def _on_breakpoint(self, bp, concepts):
        hidden = self.win is not None and not self.win.isVisible()
        self.badge = hidden
        self.say((tr("找到啦！点我看补课", "Found it! Click to see the fix") if hidden
                  else tr("找到你掉队的地方了", "Found where you fell behind")), 9000, "alert", 4000)

    def _on_echo(self, report):
        self.badge = self.win is not None and not self.win.isVisible()
        self.say(tr("这节课的回响好了，点我看", "This lesson's review is ready — click to see"), 9000, "done", 4000)

    def _idle_tip(self):
        if time.time() - self._last_interact < 60 or self.status != "listening" or time.time() < self._bubble_until:
            return
        tips = IDLE_TIPS + ([tr("老师在讲：", "Now teaching: ") + self.topic] if self.topic else [])
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
        self.say(tr("收到，继续加油！", "Got it, keep going!") if kind == "ok"
                 else tr("记下了，有点懵就圈出来问我", "Noted — circle it and ask me if you're confused"), 2500, kind)

    def _menu(self, pos):
        m = style_menu(QMenu(self))
        key = getattr(self.tray, "keys", {}).get(3, "") if self.tray is not None else ""
        m.addAction(f"{tr('✏️  圈一下问 AI', '✏️  Circle to ask AI')}    {key}".rstrip(), self.circle_ask.emit)
        m.addSeparator()
        m.addAction(tr("✓  跟上了", "✓  Keeping up"), lambda: self._feedback("ok"))
        m.addAction(tr("?  有点懵", "?  A bit lost"), lambda: self._feedback("warn"))
        m.addAction(tr("!  我掉队了", "!  I fell behind"), lambda: self._feedback("lost"))
        m.addSeparator()
        visible = self.win is not None and self.win.isVisible()
        m.addAction(tr("收起 Echo 面板", "Hide Echo panel") if visible else tr("打开 Echo 面板", "Open Echo panel"), self._toggle_panel)
        if self.tray is not None:
            m.addAction(tr("设置…", "Settings…"), self.tray.open_settings)
        skins = m.addMenu(tr("桌宠皮肤", "Pet skin"))
        for skin, label in (("cartoon", tr("原版卡通猫", "Cartoon cat")), ("line", tr("线稿猫", "Line-art cat"))):
            action = skins.addAction(label, lambda checked=False, choice=skin: self.set_skin(choice))
            action.setCheckable(True)
            action.setChecked(self.skin == skin)
        m.addAction(tr("先藏起来（托盘里能叫回）", "Hide for now (bring back from tray)"), self.hide)
        m.exec_(pos)

    # ================= 鼠标 =================
    def _cat_rect(self) -> QRectF:
        return QRectF(4, self.H - self.CAT - 6, self.CAT, self.CAT)

    def _voice_rect(self) -> QRectF:
        x = 4 + self.CAT + self.GAP
        return QRectF(x, self.H - self.CAT - 6, self.VBAR_W, self.CAT)

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
                if self.docked and not self._dragged:
                    self._set_docked(False, "")   # 开始拖动：先把收起的小球展开
                    self.move(e.globalPos().x() - self.W // 2,
                              e.globalPos().y() - self.H // 2)
                    self._press = (e.globalPos(), self.pos())
                    self._dragged = True
                    return
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
                    self.say(random.choice([tr("呼噜呼噜～", "Purr…"), tr("喵～ 再摸摸", "Meow~ more pets"),
                                            tr("好舒服，继续听课吧", "That feels nice — back to the lesson")]),
                             2000, "love", 2000)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press:
            if not self._dragged:
                self._click_timer.start()   # 单击：打开 / 收起 Echo 面板
            else:
                self._maybe_dock()          # 拖完松手：贴近屏幕边缘就收起成侧边球
            self._press = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._press = None
            self.circle_ask.emit()

    def _single_click(self):
        # 用户要求：挂边态单击和不磁吸时一样，弹出主窗口（首页），不要弹「声纹+聊天」小窗
        self._toggle_panel()

    def _toggle_chat(self):
        """挂边态单击：弹 / 收「声纹 + 聊天」小窗。"""
        if self.chat.isVisible():
            self.chat.hide()
        else:
            self.chat.show_near(self)

    def enterEvent(self, e):
        self._pet_x, self._pet_dist = None, 0.0

    def leaveEvent(self, e):
        self._pet_x = None

    def hideEvent(self, e):
        if hasattr(self, "_dock_bubble"):
            self._dock_bubble.hide()
        super().hideEvent(e)

    # ================= 动画 =================
    def _tick(self):
        now = time.time()
        self._update_dock_hover(now)
        if self._dock_bubble.isVisible() and now >= self._bubble_until:
            self._dock_bubble.hide()
        if self.mood != self._base_mood and now > self._mood_until:
            self.mood = self._base_mood
            self._sync_cat_emotion()
        self._hearts = [h for h in self._hearts if now - h[2] < 1.4]
        # 真实声纹条：跟随音频响度，说话时快起、停顿时慢落
        if self._level > self._level_env:
            self._level_env += (self._level - self._level_env) * 0.6
        else:
            self._level_env += (self._level - self._level_env) * 0.18
        self._phase += 0.5
        for i in range(self.VN):
            x = i / (self.VN - 1)
            w = 1.0 - abs(x - 0.5) * 2.0          # 中间最高
            v = self._level_env * (0.45 + 0.55 * w) * (0.85 + 0.15 * math.sin(self._phase + x * 5.0))
            self._vbar[i] = max(0.05, min(1.0, v))
        self.update()

    # ================= 绘制 =================
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        now = time.time()
        if self.docked:
            if self._hover_expanded:
                self._draw_hover_dock(p, now)
            else:
                self._draw_orb(p)
        else:
            self._draw_full(p, now)

    def _draw_orb(self, p):
        """收起态：上半段真实音量，下半段当前皮肤的猫头。"""
        r = self._orb_rect()
        p.setPen(QPen(QColor(Colors.BORDER_STRONG), 1))
        p.setBrush(QColor(Colors.SURFACE))
        p.drawRoundedRect(r, 18, 18)
        for i, v in enumerate(self._vbar):
            length = 4 + 26 * v
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Colors.ACCENT))
            p.drawRoundedRect(QRectF(24 - length / 2, 10 + i * 7, length, 3), 1.5, 1.5)
        if self.skin == "cartoon":
            pm = self.faces.get(self.mood) or self.faces.get("idle")
            if pm is not None:
                p.drawPixmap(QRectF(7, 74, 34, 34), pm, QRectF(pm.rect()))
        if self.badge:
            br = QRectF(r.right() - 7, r.top() + 1, 8, 8)
            p.setBrush(QColor(Colors.ACCENT))
            p.setPen(Qt.NoPen)
            p.drawEllipse(br)

    def _draw_hover_dock(self, p, now):
        w = self.width()
        p.setPen(QPen(QColor(Colors.BORDER_STRONG), 1))
        p.setBrush(QColor(Colors.SURFACE))
        p.drawRoundedRect(QRectF(2, 2, w - 4, self.DOCK_H - 4), 16, 16)
        bar_x = 7 if self.dock_side == "left" else w - 27
        for i, v in enumerate(self._vbar):
            length = 4 + 15 * v
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Colors.ACCENT))
            p.drawRoundedRect(QRectF(bar_x + (20 - length) / 2,
                                     10 + i * 11.5, length, 3), 1.5, 1.5)
        if self.skin == "cartoon":
            pm = self.faces.get(self.mood) or self.faces.get("idle")
            if pm is not None:
                cat_x = 38 if self.dock_side == "left" else w - 84
                p.drawPixmap(QRectF(cat_x, 28, 50, 50), pm, QRectF(pm.rect()))
        text_x = 99 if self.dock_side == "left" else 12
        p.setPen(QColor(Colors.TEXT_SECONDARY))
        p.setFont(font(10, QFont.DemiBold))
        p.drawText(QRectF(text_x, 16, 119, 20), Qt.AlignVCenter,
                   tr("ECHO · 课堂动态", "ECHO · Lesson update"))
        p.setPen(QColor(Colors.TEXT_PRIMARY))
        p.setFont(font(11, QFont.DemiBold))
        message = (self.bubble if now < self._bubble_until else
                   (tr("老师在讲：", "Now teaching: ") + self.topic if self.topic else
                    tr("我在听，随时问我", "I'm listening — ask anytime")))
        p.drawText(QRectF(text_x, 39, 119, 61), Qt.TextWordWrap | Qt.AlignVCenter,
                   message[:55] + ("…" if len(message) > 55 else ""))

    def _draw_full(self, p, now):
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

        if self.skin == "cartoon":
            self._draw_classic(p, cat, breathe, dy, dx)
        self._draw_voice(p, self._voice_rect())

        if self.badge:
            r = QRectF(cat.right() - 16, cat.top() + 6, 20, 20)
            p.setBrush(QColor(Colors.ACCENT))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawEllipse(r)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(font(12, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, "!")

        # 思考中：头顶三个点
        if self.status in ("analyzing", "summarizing", "loading_asr") and now > self._bubble_until:
            t = now - self._t0
            p.setPen(Qt.NoPen)
            for i in range(3):
                a = 0.35 + 0.65 * max(0.0, math.sin(t * 4 - i * 0.8))
                p.setBrush(QColor(242, 169, 59, int(255 * a)))
                p.drawEllipse(QPointF(cat.center().x() - 14 + i * 14, cat.top() + 2), 4, 4)

        for x, y, born in self._hearts:
            k = (now - born) / 1.4
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 92, 120, int(255 * (1 - k))))
            self._heart(p, QPointF(x + 8 * math.sin(k * 6), y - 50 * k), 9 + 4 * k)

        if self.bubble and now < self._bubble_until:
            self._draw_bubble(p, self.bubble, cat, min(1.0, (self._bubble_until - now) / 0.3))

    # ---------- classic：表情包猫（展开态用 assets/emojis 图片） ----------
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

    def _draw_voice(self, p: QPainter, area: QRectF):
        """真实声纹条：柱高随真实音频响度起伏，中间高两边低。"""
        n = self.VN
        gap = 2.5
        bw = (area.width() - gap * (n - 1)) / n
        for i in range(n):
            h = area.height() * self._vbar[i]
            x = area.x() + i * (bw + gap)
            center = 1.0 - abs(i / (n - 1) - 0.5) * 2.0
            col = QColor(Colors.ACCENT)
            col.setAlpha(int(90 + 140 * center))
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            r = QRectF(x, area.center().y() - h / 2, bw, max(3.0, h))
            p.drawRoundedRect(r, bw / 2, bw / 2)

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
        cx = self.W / 2
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
