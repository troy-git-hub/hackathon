"""
托盘自检：关闭到托盘 / 最小化到托盘 / 全局快捷键 / 隐藏时的托盘通知 / 退出。
会真的按下 Ctrl+Alt+E、Ctrl+Alt+L（模拟键盘），运行约 30 秒。

    python scripts/tray_check.py
"""
import ctypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")
os.environ["ECHO_SOURCE"] = "demo"
os.environ.setdefault("ECHO_DEMO_INTERVAL", "1.0")

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
app = QApplication(sys.argv)
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow
from echo.widgets.tray import EchoTray, cat_icon, HOTKEYS, MOD_ALT, MOD_CONTROL, MOD_SHIFT

apply_theme(app)
win = FloatingWindow()
win.show()
tray = EchoTray(app, win)

tmp = os.environ.get("TEMP", ".")
for name, badge in (("normal", None), ("busy", "busy"), ("alert", "alert")):
    cat_icon(badge).pixmap(64, 64).save(os.path.join(tmp, f"echo_tray_{name}.png"))

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""), flush=True)


KEYUP = 0x0002
MOD_VK = ((MOD_CONTROL, 0x11), (MOD_ALT, 0x12), (MOD_SHIFT, 0x10))


def press(hid):
    """按下 hid 实际注册到的那组快捷键。"""
    mods, vk, _ = next(c for c in HOTKEYS[hid] if c[2] == tray.keys[hid])
    k = ctypes.windll.user32.keybd_event
    held = [v for m, v in MOD_VK if mods & m]
    for v in held:
        k(v, 0, 0, 0)
    k(vk, 0, 0, 0); k(vk, 0, KEYUP, 0)
    for v in reversed(held):
        k(v, 0, KEYUP, 0)


steps = []
step = steps.append

step((500, lambda: check("托盘图标已显示", tray.tray.isVisible() and not tray.tray.icon().isNull())))
step((300, lambda: check(f"全局快捷键注册成功 {tray.keys}", tray._hotkeys_ok)))
step((300, lambda: win.close()))
step((500, lambda: check("点关闭 → 收进托盘而不是退出", not win.isVisible() and tray.tray.isVisible())))
step((300, lambda: press(2)))
step((800, lambda: check("快捷键 → 唤回窗口", win.isVisible())))
step((9000, lambda: press(1)))      # 等示例课讲几句再掉队
step((800, lambda: check("快捷键 → 直接进入掉队分析", win.isVisible() and win._page == 2,
                          f"page={win._page}")))
step((200, lambda: win.min_btn.click()))
step((500, lambda: check("最小化按钮 → 收进托盘", not win.isVisible())))
step((12000, lambda: check("隐藏时断点到达 → 托盘提醒（图标带点）", tray._pending == "break",
                            f"pending={tray._pending} status={tray._status}")))
step((300, lambda: tray.show_window()))
step((500, lambda: check("从托盘打开后提醒清除", win.isVisible() and tray._pending is None)))
step((300, lambda: check("托盘提示文字", tray.tray.toolTip().startswith("Echo"), tray.tray.toolTip())))
step((300, lambda: tray.quit()))


def run(i=0):
    if i < len(steps):
        ms, fn = steps[i]
        QTimer.singleShot(ms, lambda: (fn(), run(i + 1)))


run()
QTimer.singleShot(60000, app.quit)   # 保险
t0 = time.time()
app.exec_()
check("「退出 Echo」能真正退出", time.time() - t0 < 59)
print(f"\n{sum(results)}/{len(results)} 通过")
os._exit(0 if all(results) else 1)
