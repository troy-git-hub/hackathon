"""
主题回归检查：深色 / 浅色两套主题下，逐页检查配色、对比度和布局。

ECHO_THEME 在 echo.theme 导入时就固化成 IS_DARK（Colors 与 GLOBAL_QSS 都是导入期常量），
所以两种主题各起一个子进程来测，父进程汇总结果。

    python scripts/theme_check.py             # 两种主题都测
    python scripts/theme_check.py --shots     # 顺便把每页截图存到 %TEMP%\\echo_theme_*.png
    python scripts/theme_check.py --child dark    # 内部使用

退出码：全部通过为 0。
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEMES = ("dark", "light")

# 页面内部允许作为「主色」的底色 token（页面被卡片铺满时主色会是 SURFACE）
BG_TOKENS = ("WINDOW_BG", "SURFACE", "ACCENT_SOFT", "CODE_BG", "SURFACE_PRESSED")
# 老版本 Qt 控件默认填的浅灰底：出现即说明有控件没跟着主题走
QT_DEFAULT_LIGHT = "#f0f0f0"

_HEX = re.compile(r"^#([0-9A-Fa-f]{6})$")
_RGBA = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _rgb(value):
    """'#RRGGBB' 或 'rgba(r, g, b, a)' → (r, g, b)；解析不了返回 None。"""
    if not isinstance(value, str):
        return None
    m = _HEX.match(value.strip())
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = _RGBA.match(value.strip())
    if m:
        return tuple(int(m.group(i)) for i in (1, 2, 3))
    return None


def _luminance(rgb):
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(fg, bg):
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _packed(value):
    """'#RRGGBB' → 0xRRGGBB（QImage.pixelColor().rgb() 去掉 alpha 后的比较对象）。"""
    rgb = _rgb(value)
    return None if rgb is None else (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


# ============================ 子进程：单主题检查 ============================
def run_child(theme, shots):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["ECHO_THEME"] = theme          # 必须在 import echo.theme 之前
    os.environ.setdefault("ECHO_SOURCE", "system")
    sys.path.insert(0, str(ROOT))

    # 当前机器的 PyQt5 Python 包与 Qt DLL 分开安装时，可显式指定本地运行库（同 smoke_ui.py）
    runtime = os.getenv("ECHO_QT_RUNTIME")
    if runtime:
        runtime = Path(runtime).resolve()
        os.add_dll_directory(str(runtime / "bin"))
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(runtime / "plugins" / "platforms")
        import PyQt5
        PyQt5.__path__.append(str(runtime.parent))

    from PyQt5.QtCore import QObject, pyqtSignal
    from PyQt5.QtWidgets import QApplication

    # 这套自检会真的调 window._on_echo(...) 把「回响页」点亮 —— 而那条路会存课程
    # 和错题。不隔离的话，每跑一次自检就往用户**真实**的 lessons.json 里塞一节
    # 贝叶斯课（accept_check 每跑一次就多一节，用户攒了 50 节内容一模一样的假课）。
    # 指到临时目录，别动用户真数据。
    from echo.backend import paths
    paths.config_dir = lambda: tempfile.mkdtemp(prefix="echo-theme-")

    from echo.backend.engine import EchoReport
    from echo.mock_data import SAMPLE_BREAKPOINT, SAMPLE_CONCEPTS, SAMPLE_ECHO_SKILLS
    from echo.theme import Colors, IS_DARK, apply_theme
    from echo.widgets import floating_window as ui

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""),
              flush=True)

    # --- 主题确实按 ECHO_THEME 生效 ---
    want_dark = theme == "dark"
    check(f"[{theme}] ECHO_THEME 已生效", IS_DARK == want_dark,
          f"IS_DARK={IS_DARK}，期望 {want_dark}")

    # --- 所有颜色 token 都是合法颜色（能抓出 '{Colors.XXX}' 这类没被插值的占位符）---
    bad_tokens = []
    for name in dir(Colors):
        if name.startswith("_"):
            continue
        value = getattr(Colors, name)
        if isinstance(value, str) and value and _rgb(value) is None:
            bad_tokens.append(f"{name}={value!r}")
    check(f"[{theme}] 颜色 token 全部合法", not bad_tokens, "、".join(bad_tokens))

    # --- 文字与底色的对比度（WCAG）---
    pairs = [
        ("TEXT_PRIMARY", "WINDOW_BG", 4.5),
        ("TEXT_PRIMARY", "SURFACE", 4.5),
        ("TEXT_SECONDARY", "WINDOW_BG", 3.0),
        ("TEXT_SECONDARY", "SURFACE", 3.0),
        ("ON_ACCENT", "ACCENT", 3.0),
    ]
    weak = []
    for fg_name, bg_name, need in pairs:
        fg, bg = _rgb(getattr(Colors, fg_name)), _rgb(getattr(Colors, bg_name))
        if fg is None or bg is None:
            weak.append(f"{fg_name}/{bg_name} 无法解析")
            continue
        got = _contrast(fg, bg)
        if got < need:
            weak.append(f"{fg_name} on {bg_name} = {got:.2f} < {need}")
    check(f"[{theme}] 文字对比度达标", not weak, "；".join(weak))

    # --- 起窗口（用假后端，不碰音频和 API）---
    class FakeEngine:
        def current_concept(self):
            return SAMPLE_CONCEPTS[-1]

        def concepts(self):
            return SAMPLE_CONCEPTS

    class FakeBridge(QObject):
        transcript = pyqtSignal(str, str)
        concept = pyqtSignal(object)
        breakpoint = pyqtSignal(object, object)
        echo = pyqtSignal(object)
        status = pyqtSignal(str)
        thinking = pyqtSignal(bool, str)
        error = pyqtSignal(str)
        mode = pyqtSignal(str, bool)
        level = pyqtSignal(float)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.engine = FakeEngine()
            self.source_kind = "system"
            self.total_seconds = 0

        def start(self):
            pass

        def shutdown(self):
            pass

        def feedback(self, kind):
            pass

        def mark_fixed(self):
            pass

        def mark_self(self):
            pass

        def end_lesson(self):
            pass

    ui.EchoBridge = FakeBridge
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = ui.FloatingWindow()
    window.resize(600, 700)          # 给足空间，避免把「内容比屏幕高」的情况混进来
    window.show()
    for _ in range(4):
        app.processEvents()

    # --- 逐页：主色必须是主题里的底色 ---
    allowed = {_packed(getattr(Colors, t)) for t in BG_TOKENS}
    allowed = {c for c in allowed if c is not None}
    pages = [(ui.LISTEN, "听课"), (ui.MINI, "折叠"), (ui.BREAK, "断点"),
             (ui.LESSON, "补课"), (ui.ECHO, "回响"), (ui.HOME, "主页"),
             (ui.REVIEW, "错题"), (ui.PRACTICE, "练习"), (ui.DETAIL, "回顾"),
             (ui.MINDMAP, "地图"), (ui.COURSES, "课程")]
    for idx, label in pages:
        window._show_page(idx)
        if idx == ui.BREAK:
            window._on_breakpoint(SAMPLE_BREAKPOINT, SAMPLE_CONCEPTS)
        elif idx == ui.ECHO:
            window._on_echo(EchoReport(SAMPLE_ECHO_SKILLS, ["贝叶斯公式", "条件概率"], "先复习条件概率"))
        for _ in range(6):
            app.processEvents()

        img = window.grab().toImage()
        W, H = img.width(), img.height()
        cnt = Counter()
        for y in range(20, H - 20, 2):
            for x in range(20, W - 20, 2):
                cnt[img.pixelColor(x, y).rgb() & 0xFFFFFF] += 1
        top_rgb, top_n = cnt.most_common(1)[0]
        top_hex = "#%06X" % top_rgb
        total = sum(cnt.values())
        qt_default = cnt.get(_packed(QT_DEFAULT_LIGHT), 0)

        if shots:
            img.save(str(Path(os.environ.get("TEMP", ".")) / f"echo_theme_{theme}_{idx}_{label}.png"))

        ok = top_rgb in allowed
        check(f"[{theme}] {label}页底色是主题色", ok,
              f"主色 {top_hex}（占比 {top_n / total:.0%}）不在 {[('#%06X' % c) for c in sorted(allowed)]}")
        check(f"[{theme}] {label}页没有残留的浅灰底", qt_default / total < 0.02,
              f"{qt_default / total:.1%} 的像素是 Qt 默认浅灰 {QT_DEFAULT_LIGHT}")

    # --- 布局：主按钮完整可见、窗口不超屏 ---
    window._show_page(ui.LISTEN)
    for _ in range(6):
        app.processEvents()
    vis = window.btn_lost.visibleRegion()
    check(f"[{theme}] 「我掉队了」完整可见", (not vis.isEmpty()) and window.btn_lost.height() >= 40,
          f"visibleRegion.empty={vis.isEmpty()} 高度={window.btn_lost.height()}")
    scr = app.primaryScreen().availableGeometry()
    check(f"[{theme}] 窗口不超出屏幕", window.height() <= scr.height() and window.width() <= scr.width(),
          f"窗口 {window.width()}x{window.height()}，屏幕 {scr.width()}x{scr.height()}")

    # --- 首次登录窗：QDialog，不在主窗口的页面栈里，上面的逐页取色覆盖不到它 ---
    from echo.widgets.profile_setup import ProfileSetupDialog
    dlg = ProfileSetupDialog()
    dlg.resize(440, 320)
    dlg.show()
    for _ in range(6):
        app.processEvents()
    dimg = dlg.grab().toImage()
    DW, DH = dimg.width(), dimg.height()
    dcnt = Counter()
    for y in range(8, DH - 8, 2):
        for x in range(8, DW - 8, 2):
            dcnt[dimg.pixelColor(x, y).rgb() & 0xFFFFFF] += 1
    dtop, dn = dcnt.most_common(1)[0]
    dtotal = sum(dcnt.values())
    dqt = dcnt.get(_packed(QT_DEFAULT_LIGHT), 0)
    if shots:
        dimg.save(str(Path(os.environ.get("TEMP", ".")) / f"echo_theme_{theme}_profile.png"))
    check(f"[{theme}] 首次登录窗底色是主题色", dtop in allowed,
          f"主色 {'#%06X' % dtop}（占比 {dn / dtotal:.0%}）不在 "
          f"{[('#%06X' % c) for c in sorted(allowed)]}")
    check(f"[{theme}] 首次登录窗没有残留的浅灰底", dqt / dtotal < 0.02,
          f"{dqt / dtotal:.1%} 的像素是 Qt 默认浅灰 {QT_DEFAULT_LIGHT}")
    dlg.close()

    window.close()
    print(f"RESULT {sum(results)}/{len(results)} {theme}", flush=True)
    return 0 if all(results) else 1


# ============================ 父进程：汇总 ============================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", choices=THEMES)
    ap.add_argument("--shots", action="store_true")
    args = ap.parse_args()

    if args.child:
        return run_child(args.child, args.shots)

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    tally = []
    for theme in THEMES:
        print(f"\n===== {theme} =====", flush=True)
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                               "--child", theme] + (["--shots"] if args.shots else []),
                              cwd=str(ROOT), env=env, text=True, encoding="utf-8",
                              errors="replace", capture_output=True)
        print(proc.stdout, end="", flush=True)
        tail = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if tail:
            got, _, total = tail[-1].split()[1].partition("/")
            tally += [True] * int(got) + [False] * (int(total) - int(got))
        else:
            print(proc.stderr[-2000:], flush=True)
            tally.append(False)

    print(f"\n主题检查：{sum(tally)}/{len(tally)} 通过")
    return 0 if tally and all(tally) else 1


if __name__ == "__main__":
    sys.exit(main())
