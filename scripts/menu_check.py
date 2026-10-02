"""
Echo - 右键菜单自检

    python scripts/menu_check.py

背景：全局 QSS 里有 `* {{ color: TEXT_PRIMARY }}`，深色主题下会把菜单文字染成白色；
如果某个右键菜单忘了套自己的样式，背景还是系统浅色，就变成「白字白底」看不见。
桌宠右键菜单踩过一次这个坑，所以这里两件事都卡住：

  A. 源码扫描 —— echo/ 下每个 QMenu( 创建点都必须走 theme.style_menu()
  B. 配色对比度 —— menu_qss() 的前景色/背景色对比度达标（深色、浅色各跑一次）
  C. 真渲染 —— 把菜单画成图，确认既有底色又有文字，不是一片糊

退出码：全部通过为 0。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


# ---------- A. 源码扫描 ----------
def scan_sources():
    section("A. 每个 QMenu 创建点都套了样式")
    hits, bad = 0, []
    for root, _, files in os.walk(os.path.join(ROOT, "echo")):
        for f in files:
            if not f.endswith(".py") or f == "theme.py":
                continue
            path = os.path.join(root, f)
            for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
                if re.search(r"\bQMenu\s*\(", line):
                    hits += 1
                    if "style_menu(" not in line:
                        bad.append(f"{os.path.relpath(path, ROOT)}:{i}")
    check(f"找到 {hits} 个 QMenu 创建点", hits > 0)
    check("全部经由 style_menu()", not bad, "漏掉的：" + "、".join(bad))


# ---------- B/C. 分主题跑（IS_DARK 在 import 时冻结，只能开子进程） ----------
def theme_body(mode):
    from PyQt5.QtWidgets import QApplication, QMenu

    app = QApplication(sys.argv)
    from echo import theme
    from echo.theme import Colors, GLOBAL_QSS, menu_qss, style_menu
    app.setStyleSheet(GLOBAL_QSS)          # 复现真实环境：全局 QSS 会渗进菜单

    section(f"B. 配色对比度（{mode}）")
    qss = menu_qss()
    check("菜单样式里有背景色", "background-color" in qss)
    check("菜单样式里有文字色", "color:" in qss and "QMenu::item" in qss)

    def rel_lum(hexcolor):
        h = hexcolor.lstrip("#")
        parts = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        parts = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    fg, bg = Colors.TEXT_PRIMARY, Colors.SURFACE
    a, b = rel_lum(fg), rel_lum(bg)
    ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
    check(f"文字/底对比度 {ratio:.1f}:1 ≥ 4.5", ratio >= 4.5, f"{fg} on {bg}")

    section(f"C. 真渲染（{mode}）")
    # 菜单真的画出来之后，底色必须就是主题的 SURFACE。
    # 忘了套样式的菜单会画成系统白底（暗色主题下白字白底，就是这个坑）——
    # 裸 QMenu 在这里渲染出 (255,255,255)，套了样式的渲染出 Colors.SURFACE，
    # 两者能区分开，所以这条断言是有效的。
    # 注意：offscreen 平台没有字体库，item 文字不会被画出来，所以只能比底色。
    def render_dominant(menu):
        menu.ensurePolished()
        menu.adjustSize()
        menu.show()                  # 不 show 的话菜单内容根本不会画
        app.processEvents()
        img = menu.grab().toImage()
        cols = {}
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() < 200:
                    continue
                k = (c.red(), c.green(), c.blue())
                cols[k] = cols.get(k, 0) + 1
        return max(cols.items(), key=lambda kv: kv[1])[0] if cols else None

    def build_menu():
        m = style_menu(QMenu())
        m.addAction("圈一下问 AI    Ctrl+Alt+Q")
        m.addSeparator()
        m.addAction("跟上了")
        m.addAction("我掉队了")
        return m

    menu = build_menu()
    pm_dom = render_dominant(menu)
    check("菜单画得出来", pm_dom is not None)
    got = "#%02X%02X%02X" % pm_dom if pm_dom else ""
    check(f"菜单底色是主题 SURFACE（{Colors.SURFACE}）", got == Colors.SURFACE, f"实际 {got}")

    if Colors.SURFACE != "#FFFFFF":
        check("深色主题下菜单不是白底", got != "#FFFFFF", f"实际 {got}")

    # 这条直接复现用户看到的现象：忘了套样式的菜单是白底 + 白字。
    # 只有深色主题下白底才算问题（浅色主题 SURFACE 本来就是白的，区分不出来）。
    if Colors.SURFACE != "#FFFFFF":
        naked = QMenu()
        naked.addAction("跟上了")
        naked_dom = render_dominant(naked)
        check("反例：裸菜单确实会画成白底（证明上面那条能区分）",
              naked_dom is None or "#%02X%02X%02X" % naked_dom != Colors.SURFACE)
    else:
        print("  跳过  反例检查（浅色主题 SURFACE 本身就是白色，白底不是缺陷）")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("dark", "light"):
        theme_body(sys.argv[1])
    else:
        scan_sources()
        for mode in ("dark", "light"):
            env = dict(os.environ, ECHO_THEME=mode, QT_QPA_PLATFORM="offscreen",
                       PYTHONIOENCODING="utf-8")
            proc = subprocess.run([sys.executable, os.path.abspath(__file__), mode],
                                  cwd=ROOT, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            print(proc.stdout, end="")
            if proc.returncode != 0:
                print(proc.stderr[-800:] if proc.stderr else "", end="")
                check(f"{mode} 主题子进程", False)

    print("\n" + "=" * 56)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
        sys.exit(1)
    print("右键菜单自检：全部通过")


if __name__ == "__main__":
    main()
