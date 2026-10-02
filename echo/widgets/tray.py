"""
Echo - 系统托盘

不改窗口内部代码，从外部挂到 FloatingWindow 上：
  · 托盘图标：线稿猫头，跟随任务栏深浅色；分析中 / 有新结果时右下角带琥珀色小点
  · 单击托盘图标：显示 / 隐藏 Echo
  · 右键菜单：我掉队了、下课生成回响、新的一节课、离线模式、退出
  · 关闭 / 最小化 → 收进托盘继续听课（Qt.Tool 窗口最小化后没有任务栏入口，原来无法找回）
  · 窗口藏起来时，掉队分析和课堂回响完成会弹托盘通知，点通知直接打开
  · 全局快捷键（看全屏网课时也能用），被别的软件占用时自动换下一个候选：
        我掉队了        Ctrl+Alt+L → Ctrl+Alt+K → Ctrl+Alt+J → Ctrl+Shift+F9
        显示 / 隐藏     Ctrl+Alt+E → Ctrl+Alt+H → Ctrl+Shift+F10
        圈一下问 AI     Ctrl+Alt+Q → Ctrl+Alt+W → Ctrl+Shift+F11
  · 桌宠（desk_pet.py）由 main.py 挂到 tray.pet 上，退出时一起关掉
"""
import ctypes
import logging
from ctypes import wintypes

from PyQt5.QtCore import Qt, QObject, QEvent, QAbstractNativeEventFilter, QRectF, QPointF, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QPainterPath, QPen, QColor
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QApplication

from echo.theme import Colors

log = logging.getLogger("echo.tray")

ACCENT = "#F2A93B"
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
MOD_SHIFT = 0x0004
VK_F9, VK_F10, VK_F11 = 0x78, 0x79, 0x7A
# id: 候选列表 [(修饰键, 虚拟键码, 显示名)]，按顺序取第一个没被占用的
HOTKEYS = {
    1: [(MOD_CONTROL | MOD_ALT, ord("L"), "Ctrl+Alt+L"), (MOD_CONTROL | MOD_ALT, ord("K"), "Ctrl+Alt+K"),
        (MOD_CONTROL | MOD_ALT, ord("J"), "Ctrl+Alt+J"), (MOD_CONTROL | MOD_SHIFT, VK_F9, "Ctrl+Shift+F9")],
    2: [(MOD_CONTROL | MOD_ALT, ord("E"), "Ctrl+Alt+E"), (MOD_CONTROL | MOD_ALT, ord("H"), "Ctrl+Alt+H"),
        (MOD_CONTROL | MOD_SHIFT, VK_F10, "Ctrl+Shift+F10")],
    3: [(MOD_CONTROL | MOD_ALT, ord("Q"), "Ctrl+Alt+Q"), (MOD_CONTROL | MOD_ALT, ord("W"), "Ctrl+Alt+W"),
        (MOD_CONTROL | MOD_SHIFT, VK_F11, "Ctrl+Shift+F11")],
}


def _taskbar_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 0
    except Exception:
        return True


def cat_icon(badge=None, size=64) -> QIcon:
    """线稿猫头图标。badge: None / "busy"（空心点）/ "alert"（实心点）"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 32.0, size / 32.0)
    line = QColor("#F2F2F2" if _taskbar_dark() else "#1D1E20")

    head = QPainterPath()
    head.moveTo(6.2, 13.0)
    head.lineTo(5.0, 3.6)
    head.lineTo(12.0, 8.4)
    head.quadTo(16.0, 7.4, 20.0, 8.4)
    head.lineTo(27.0, 3.6)
    head.lineTo(25.8, 13.0)
    head.cubicTo(28.8, 19.8, 24.6, 28.2, 16.0, 28.2)
    head.cubicTo(7.4, 28.2, 3.2, 19.8, 6.2, 13.0)
    p.setPen(QPen(line, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(head)
    p.setPen(Qt.NoPen)
    p.setBrush(line)
    p.drawEllipse(QPointF(11.4, 17.4), 2.0, 2.0)
    p.drawEllipse(QPointF(20.6, 17.4), 2.0, 2.0)

    if badge:
        c = QColor(ACCENT)
        p.setBrush(c if badge == "alert" else Qt.NoBrush)
        p.setPen(QPen(c, 2.2) if badge == "busy" else Qt.NoPen)
        p.drawEllipse(QRectF(21.0, 21.0, 10.0, 10.0))
    p.end()
    return QIcon(pm)


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey):
        super().__init__()
        self.on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.on_hotkey(int(msg.wParam))
                return True, 0
        return False, 0


def _menu_qss() -> str:
    """Win11 风格右键菜单：跟随深浅色、圆角、悬浮高亮。"""
    hover = Colors.ACCENT_SOFT if hasattr(Colors, "ACCENT_SOFT") else Colors.SURFACE_HOVER
    return f"""
    QMenu {{
        background-color: {Colors.SURFACE};
        border: 1px solid {Colors.BORDER_STRONG};
        border-radius: 8px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 7px 30px 7px 14px;
        border-radius: 5px;
        color: {Colors.TEXT_PRIMARY};
        background: transparent;
    }}
    QMenu::item:selected {{
        background-color: {Colors.SURFACE_HOVER};
    }}
    QMenu::item:disabled {{
        color: {Colors.TEXT_DISABLED};
    }}
    QMenu::separator {{
        height: 1px;
        background: {Colors.BORDER};
        margin: 4px 8px;
    }}
    QMenu::indicator {{
        width: 14px; height: 14px; margin-left: 6px;
    }}
    QMenu::indicator:checked {{
        background-color: {Colors.ACCENT};
        border-radius: 3px;
        border: 1px solid {Colors.ACCENT};
    }}
    """


class EchoTray(QObject):
    def __init__(self, app: QApplication, win):
        super().__init__(win)
        self.app, self.win = app, win
        self._quitting = False
        self._told_hidden = False
        self._pending = None          # 窗口隐藏时到达、等用户点开的结果：break / echo
        self._status = "listening"
        self._topic = ""
        self.keys = {1: "", 2: "", 3: ""}     # 实际注册成功的快捷键显示名
        self.pet = None               # 桌宠，main.py 里挂上

        app.setQuitOnLastWindowClosed(False)
        self._hotkeys_ok = self._register_hotkeys()
        self.tray = QSystemTrayIcon(cat_icon(), win)
        self.tray.activated.connect(self._on_activated)
        self.tray.messageClicked.connect(self.show_window)
        self._build_menu()
        self.tray.show()

        # 关闭 / 最小化 → 收进托盘
        win.installEventFilter(self)
        if hasattr(win, "min_btn"):
            try:
                win.min_btn.clicked.disconnect()
            except TypeError:
                pass
            win.min_btn.clicked.connect(self.hide_window)
            win.min_btn.setToolTip(f"收进托盘（{self.keys[2] or '点托盘里的猫'} 唤回）")

        # 跟随后端状态
        echo = win.echo
        echo.status.connect(self._on_status)
        echo.concept.connect(self._on_concept)
        echo.breakpoint.connect(self._on_breakpoint)
        echo.echo.connect(self._on_echo)
        if hasattr(echo, "mode"):
            echo.mode.connect(self._on_mode)
        self._refresh()

    # ---------------- 菜单 ----------------
    def _build_menu(self):
        m = QMenu()
        m.setStyleSheet(_menu_qss())
        # 圆角需要无边框 + 透明底；去掉系统阴影，用 QSS 圆角代替
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        m.setAttribute(Qt.WA_TranslucentBackground, True)
        self.act_toggle = m.addAction("显示 / 隐藏 Echo", self.toggle_window)
        m.addSeparator()
        m.addAction("⌂  主页", self.home)
        self.act_lost = m.addAction(f"我掉队了    {self.keys[1]}".rstrip(), self.lost)
        m.addAction(f"圈一下问 AI    {self.keys[3]}".rstrip(), self.circle_ask)
        self.act_end = m.addAction("下课，生成回响", self.end_lesson)
        m.addAction("错题复习", self.review)
        m.addAction("开始新的一节课", self.restart)
        m.addSeparator()
        self.act_offline = QAction("离线模式（不调 AI）", m, checkable=True)
        self.act_offline.triggered.connect(self.toggle_offline)
        m.addAction(self.act_offline)
        m.addSeparator()
        self.act_pet = m.addAction("显示桌宠", self.toggle_pet)
        m.addAction("设置…", self.open_settings)
        m.addAction("退出 Echo", self.quit)
        m.aboutToShow.connect(self._sync_menu)
        self.menu = m
        self.tray.setContextMenu(m)

    def _sync_menu(self):
        self.act_toggle.setText("隐藏 Echo" if self.win.isVisible() else "显示 Echo")
        echo = self.win.echo
        self.act_offline.setChecked(bool(getattr(echo, "offline", False)))
        self.act_offline.setEnabled(hasattr(echo, "set_offline"))
        self.act_pet.setVisible(self.pet is not None)
        self.act_pet.setText("隐藏桌宠" if self.pet is not None and self.pet.isVisible() else "显示桌宠")

    # ---------------- 窗口显示 ----------------
    def show_window(self):
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()
        self._pending = None
        self._refresh()

    def hide_window(self):
        self.win.hide()
        if not self._told_hidden:
            self._told_hidden = True
            tips = []
            if self.keys[1]:
                tips.append(f"掉队了按 {self.keys[1]}")
            tips.append(f"唤回按 {self.keys[2]} 或点托盘里的猫" if self.keys[2] else "唤回请点托盘里的猫")
            self.tray.showMessage("Echo 还在听课", "已收进托盘。" + "，".join(tips) + "。",
                                  QSystemTrayIcon.Information, 4000)
        self._refresh()

    def toggle_window(self):
        if self.win.isVisible():
            self.hide_window()
        else:
            self.show_window()

    def toggle_pet(self):
        if self.pet is not None:
            self.pet.setVisible(not self.pet.isVisible())

    def open_settings(self):
        from echo.widgets.settings import open_settings_dialog
        open_settings_dialog(self.win)

    def circle_ask(self):
        """圈一下问 AI：截图时把 Echo 自己的窗口先藏起来。"""
        from echo.widgets.snip import start_circle_ask
        start_circle_ask(self.win.echo, hide=[self.win, self.pet])

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window()

    def eventFilter(self, obj, e):
        if obj is self.win and not self._quitting:
            if e.type() == QEvent.Close:          # 点关闭 / Alt+F4：收进托盘，不退出
                e.ignore()
                self.hide_window()
                return True
            if e.type() == QEvent.WindowStateChange and self.win.isMinimized():
                QTimer.singleShot(0, lambda: (self.win.showNormal(), self.hide_window()))
        return False

    # ---------------- 课堂操作 ----------------
    def lost(self):
        self.show_window()
        self.win._on_lost()

    def end_lesson(self):
        self.show_window()
        self.win._go_echo()

    def restart(self):
        self.show_window()
        self.win._restart()

    def review(self):
        self.show_window()
        if hasattr(self.win, "_show_review"):
            self.win._show_review()

    def home(self):
        self.show_window()
        if hasattr(self.win, "_show_home"):
            self.win._show_home()

    def toggle_offline(self, checked):
        echo = self.win.echo
        if hasattr(echo, "set_offline"):
            echo.set_offline(bool(checked))

    def quit(self):
        self._quitting = True
        self._unregister_hotkeys()
        self.tray.hide()
        if self.pet is not None:
            self.pet.close()
        self.win.close()             # 窗口 closeEvent 里会关掉后端线程
        self.app.quit()

    # ---------------- 状态 / 通知 ----------------
    STATUS_TEXT = {"listening": "正在听课", "analyzing": "正在找你掉队的地方", "summarizing": "正在整理这节课",
                   "loading_asr": "正在加载语音识别", "done": "已下课"}

    def _on_status(self, st):
        self._status = st
        self._refresh()

    def _on_concept(self, c):
        cur = self.win.echo.engine.current_concept()
        self._topic = cur.topic if cur else ""
        self._refresh()

    def _on_mode(self, kind, offline):
        self.act_offline.setChecked(bool(offline))
        self._refresh()

    def _on_breakpoint(self, bp, concepts):
        if not self.win.isVisible():
            self._pending = "break"
            self.tray.showMessage("找到你掉队的地方了",
                                  f"{bp.missing or bp.concept}\n点这里看 30 秒补课",
                                  QSystemTrayIcon.Information, 8000)
        self._refresh()

    def _on_echo(self, report):
        if not self.win.isVisible():
            self._pending = "echo"
            review = sum(1 for s in report.skills if s.status not in ("ok", "fixed"))
            self.tray.showMessage("这节课的回响好了",
                                  f"{len(report.skills)} 个知识点，{review} 个待回看。点这里查看",
                                  QSystemTrayIcon.Information, 8000)
        self._refresh()

    def _refresh(self):
        busy = self._status in ("analyzing", "summarizing", "loading_asr")
        self.tray.setIcon(cat_icon("alert" if self._pending else ("busy" if busy else None)))
        parts = ["Echo", self.STATUS_TEXT.get(self._status, "")]
        if self._topic and self._status in ("listening", "analyzing"):
            parts.append(f"老师在讲：{self._topic}")
        if getattr(self.win.echo, "offline", False):
            parts.append("离线")
        self.tray.setToolTip(" · ".join(p for p in parts if p)[:120])

    # ---------------- 全局快捷键 ----------------
    def _register_hotkeys(self) -> bool:
        self._filter = _HotkeyFilter(self._on_hotkey)
        self.app.installNativeEventFilter(self._filter)
        user32 = ctypes.windll.user32
        for hid, cands in HOTKEYS.items():
            for mods, vk, name in cands:
                if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                    self.keys[hid] = name
                    break
                log.info("全局快捷键 %s 被其他程序占用，换下一个", name)
            else:
                log.warning("全局快捷键 %d 的候选都被占用", hid)
        return all(self.keys.values())

    def _unregister_hotkeys(self):
        for hid in HOTKEYS:
            ctypes.windll.user32.UnregisterHotKey(None, hid)

    def _on_hotkey(self, hid):
        if hid == 1:
            self.lost()
        elif hid == 2:
            self.toggle_window()
        elif hid == 3:
            self.circle_ask()
