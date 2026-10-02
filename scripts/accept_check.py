"""
Echo 验收总入口：一条命令跑完所有自检。

    python scripts/accept_check.py               # 默认项（不需要 API key、不需要桌面）
    python scripts/accept_check.py --with-tray   # 追加托盘/全局快捷键（需要真实桌面，会模拟按键）
    python scripts/accept_check.py --with-ai     # 追加真实 DeepSeek 链路（会消耗 token）
    python scripts/accept_check.py --full        # 全部

退出码：全部通过为 0。任何一项失败都会打印该步的末尾输出。
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def suite(with_tray, with_ai):
    steps = [
        ("课程隔离（重开课程不串课）", ["session_check.py"], "不需要网络"),
        ("离线 UI 冒烟（页面切换 / 主按钮）", ["smoke_ui.py"], "offscreen"),
        ("主题回归（深色 + 浅色）", ["theme_check.py"], "off-screen 逐页取色"),
        ("后端链路（离线 mock 数据）", ["smoke_backend.py", "--mock"], "不调用 AI"),
    ]
    if with_ai:
        steps.append(("后端链路（真实 DeepSeek）", ["smoke_backend.py"], "会消耗 token"))
    if with_tray:
        steps.append(("托盘与全局快捷键", ["tray_check.py"], "需要真实桌面，会模拟按键"))
    return steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-tray", action="store_true", help="追加托盘/快捷键检查")
    ap.add_argument("--with-ai", action="store_true", help="追加真实 DeepSeek 链路")
    ap.add_argument("--full", action="store_true", help="全部检查")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每一步的完整输出")
    args = ap.parse_args()

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    steps = suite(args.with_tray or args.full, args.with_ai or args.full)
    print(f"Echo 验收 — {len(steps)} 项\n" + "=" * 64, flush=True)

    rows, failed = [], []
    for i, (title, argv, note) in enumerate(steps, 1):
        path = SCRIPTS / argv[0]
        if not path.exists():
            rows.append((title, "跳过", 0.0, "脚本不存在"))
            print(f"[{i}/{len(steps)}] {title} — 跳过（缺 {argv[0]}）", flush=True)
            continue
        print(f"[{i}/{len(steps)}] {title} … ({note})", end="", flush=True)
        t0 = time.time()
        proc = subprocess.run([sys.executable, str(path)] + argv[1:], cwd=str(ROOT), env=env,
                              text=True, encoding="utf-8", errors="replace", capture_output=True)
        dt = time.time() - t0
        ok = proc.returncode == 0
        rows.append((title, "通过" if ok else "失败", dt, ""))
        print(f"\r[{i}/{len(steps)}] {title:<34} {'通过' if ok else '失败'}  {dt:5.1f}s", flush=True)
        if args.verbose or not ok:
            out = (proc.stdout or "") + (proc.stderr or "")
            tail = "\n".join(out.strip().splitlines()[-12:])
            print("    " + tail.replace("\n", "\n    "), flush=True)
        if not ok:
            failed.append(title)

    print("=" * 64)
    passed = sum(1 for r in rows if r[1] == "通过")
    print(f"结果：{passed}/{len(rows)} 通过，用时 {sum(r[2] for r in rows):.1f}s")
    if failed:
        print("失败项：\n  - " + "\n  - ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
