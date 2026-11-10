"""
Echo 验收总入口：一条命令跑完所有自检。

    python scripts/accept_check.py               # 默认项（不需要 API key、不需要桌面）
    python scripts/accept_check.py --with-tray   # 追加托盘/全局快捷键（需要真实桌面，会模拟按键）
    python scripts/accept_check.py --with-ai     # 追加真实 DeepSeek 链路（会消耗 token）
    python scripts/accept_check.py --with-web    # 追加真实 HTML 浏览器与自动截图时序验收（Windows 需桌面）
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


def suite(with_tray, with_ai, with_web=False):
    steps = [
        ("演示教学设计（阅读角度 / 对照 / 统一风格）", ["lesson_design_check.py"], "不调用真实模型"),
        ("课堂多题型（轮换 / AI 批改 / 长文本换行）", ["checkin_types_check.py"], "不调用真实模型"),
        ("已学内容（课程分支 / 依赖分层 / 聚焦）", ["learned_map_check.py"], "不调用真实模型"),
        ("板书跟随知识点（后台生成 / 图解 / 整课导出）", ["board_follow_check.py"], "不调用真实模型"),
        ("多题型练习（自动判分 / AI 批改 / 解析 / 隔离）", ["assessment_check.py"], "不调用真实模型"),
        ("AI 黑板与知识库（检索 / 来源 / 切课 / 导入）", ["studio_check.py"], "不需要网络"),
        ("课程隔离（重开课程不串课）", ["session_check.py"], "不需要网络"),
        ("课堂抽问（触发 / 判分 / 入错题本）", ["checkin_check.py"], "不需要网络"),
        ("间隔重复复习（三档自评 / 到期调度）", ["review_check.py"], "不需要网络"),
        ("讲给 Echo 听（掌握验证 / 共同根源）", ["recall_check.py"], "不需要网络"),
        ("学生画像（答题表现 → 语气适配）", ["persona_check.py"], "不需要网络"),
        ("语音转文字（麦克风录音 → Whisper）", ["voice_input_check.py"], "不需要真麦克风"),
        ("模型按需下载（就绪判定 / 进度 / 失败兜底）", ["model_fetch_check.py"], "不需要网络"),
        ("「为什么要复习它」（批量生成 / 只动单字段）", ["why_check.py"], "不需要网络"),
        ("反复缺失的前置知识（跨课聚合 / 归一 / 阈值）", ["gaps_check.py"], "不需要网络"),
        ("提示词模板（转义 / 占位符 / 语言指令）", ["prompts_check.py"], "不需要网络"),
        ("离线 UI 冒烟（页面切换 / 主按钮）", ["smoke_ui.py"], "offscreen"),
        ("主题回归（6 套配色）", ["theme_check.py"], "off-screen 逐页取色"),
        ("右键菜单（样式 / 对比度 / 真渲染）", ["menu_check.py"], "offscreen"),
        ("知识地图（建图 / 分层 / 详情 / 出题）", ["mindmap_check.py"], "不需要网络"),
        ("桌宠提醒（课上抽问 / 红点）", ["pet_checkin_check.py"], "offscreen"),
        ("后端链路（离线 mock 数据）", ["smoke_backend.py", "--mock"], "不调用 AI"),
    ]
    if with_ai:
        steps.append(("后端链路（真实 DeepSeek）", ["smoke_backend.py"], "会消耗 token"))
    if with_web:
        steps.append(("HTML 交互与重点捕捉（真实浏览器）", ["blackboard_visual_check.py"], "Windows 需要桌面，不调用模型"))
    if with_tray:
        steps.append(("托盘与全局快捷键", ["tray_check.py"], "需要真实桌面，会模拟按键"))
    return steps


DATA_FILES = ("lessons.json", "review.json")


def _data_fingerprint():
    """用户真实数据的指纹（大小 + 修改时间）。自检跑前跑后各拍一张对一遍。"""
    try:
        from echo.backend import paths
        d = paths.config_dir()
    except Exception:
        return {}
    out = {}
    for name in DATA_FILES:
        try:
            st = os.stat(os.path.join(d, name))
            out[name] = (st.st_size, int(st.st_mtime))
        except OSError:
            out[name] = None
    return out


def _data_diff(before, after):
    return [f"{name}: {before.get(name)} → {after.get(name)}"
            for name in DATA_FILES if before.get(name) != after.get(name)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-tray", action="store_true", help="追加托盘/快捷键检查")
    ap.add_argument("--with-ai", action="store_true", help="追加真实 DeepSeek 链路")
    ap.add_argument("--with-web", action="store_true", help="追加 HTML 交互与重点捕捉（Windows需桌面）")
    ap.add_argument("--full", action="store_true", help="全部检查")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每一步的完整输出")
    args = ap.parse_args()

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    steps = suite(args.with_tray or args.full, args.with_ai or args.full, args.with_web or args.full)
    print(f"Echo 验收 — {len(steps)} 项\n" + "=" * 64, flush=True)

    before = _data_fingerprint()
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

    # 自检不该动用户真实数据。theme_check 曾经每跑一次就往真的 lessons.json 里
    # 存一节假课（它调 window._on_echo 点回响页，那条路会存课程），用户攒了 50 节。
    # 修好那一个之外再加这道网：以后哪个自检脚本又把数据写进真实目录，这里当场报出来。
    dirty = _data_diff(before, _data_fingerprint())
    if dirty:
        print("⚠ 自检动了真实数据（这些脚本应该先把 paths.config_dir 指到临时目录）：")
        for line in dirty:
            print("   " + line)
        failed.append("自检污染了真实数据")

    passed = sum(1 for r in rows if r[1] == "通过")
    print(f"结果：{passed}/{len(rows)} 通过，用时 {sum(r[2] for r in rows):.1f}s")
    if failed:
        print("失败项：\n  - " + "\n  - ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
