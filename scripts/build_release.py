"""
Echo 出安装包：PyInstaller + Inno Setup → dist/Echo-Setup-x.y.exe

    python scripts/build_release.py              # 默认在独立目录里打（推荐）
    python scripts/build_release.py --in-place   # 直接在当前工作区打
    python scripts/build_release.py --skip-iscc  # 只出 dist/Echo/，不编安装包

为什么默认不在当前工作区打：
    PyInstaller 打的是「工作区源码」，不是 git HEAD。如果有别人（或另一个会话）
    正在改同一份工作区，半截改动会被打进安装包 —— 之前就出过「打包中途工作树在动、
    产物不可信、只能重打」的事。独立 worktree 检出当前 HEAD，打出来的包和提交严格对应。

打包参数不在这里手抄：从 build.bat 里解析出来执行，build.bat 改了这边自动跟着改。
"""
import argparse
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISCC_CANDIDATES = [
    r"D:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def say(msg):
    print(f"[打包] {msg}", flush=True)


def run(argv, cwd, log_path):
    say(" ".join(str(a) for a in argv[:4]) + " …")
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        p = subprocess.run(argv, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True)
    return p.returncode, Path(log_path)


def pyinstaller_argv(build_dir: Path):
    """从 build.bat 解析出 PyInstaller 命令行 —— 不手抄，避免两边漂移。"""
    bat = (build_dir / "build.bat").read_text(encoding="utf-8", errors="replace")
    keep = []
    for line in bat.splitlines():
        s = line.strip()
        if not s or s.upper().startswith("REM") or s.startswith("@") or s.startswith("echo"):
            continue
        if s.lower().startswith(("setlocal", "endlocal")):
            continue
        keep.append(line)
    text = re.sub(r"\^\s*\n", " ", "\n".join(keep))          # 拼接 ^ 续行
    m = re.search(r"(pyinstaller\b.*?main\.py)", text, re.S)
    if not m:
        raise SystemExit("没从 build.bat 里解析出 pyinstaller 命令")
    return shlex.split(m.group(1).replace("\\", "/"))


def find_iscc(explicit=""):
    if explicit:
        return Path(explicit)
    for c in ISCC_CANDIDATES:
        if Path(c).exists():
            return Path(c)
    return None


def check_setup_tree(build_dir: Path):
    """PyInstaller 需要 models/ 在那里（它不在 git 里）。缺了就补上。"""
    src = ROOT / "models"
    dst = build_dir / "models"
    if dst.exists():
        return
    if not src.exists():
        raise SystemExit(f"找不到模型目录 {src} —— 先按 README 把 faster-whisper-small 放进去")
    say(f"复制模型到构建目录（{src}）…")
    shutil.copytree(src, dst)


def verify_installer(path: Path):
    """结构自检：PE 头 / 节区是否越界 / Inno 数据标记 / 尾部有数据。

    能查出来的最要命的一种坏法：ISCC 被中断，留下半个 PE —— 文件在、能双击，
    但装到一半报「安装文件已损坏」。只看 PE 头是查不出来的。
    """
    size = path.stat().st_size
    with open(path, "rb") as f:
        if f.read(2) != b"MZ":
            return False, "不是合法的 exe（MZ 缺失）"
        f.seek(0x3C)
        pe_off = struct.unpack("<I", f.read(4))[0]
        f.seek(pe_off)
        if f.read(4) != b"PE\0\0":
            return False, "PE 签名不对"
        _, nsec, _, _, _, opt_size, _ = struct.unpack("<HHIIIHH", f.read(20))
        f.seek(pe_off + 24 + opt_size)
        for _ in range(nsec):
            raw = f.read(40)
            name, _, _, rsize, raddr = struct.unpack("<8sIIII", raw[:24])
            if rsize and raddr + rsize > size:
                return False, f"节区 {name!r} 超出文件 —— 被截断的半成品"
        f.seek(0)
        if b"Inno Setup Setup Data" not in f.read():
            return False, "找不到 Inno Setup 数据标记"
        f.seek(size - 65536)
        if not any(f.read(65536)):
            return False, "尾部 64KB 全是零，可疑"
    return True, f"{size:,} 字节"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-place", action="store_true", help="就在当前工作区打，不另建目录")
    ap.add_argument("--worktree", default="", help="构建目录（默认仓库旁边 echo-build）")
    ap.add_argument("--iscc", default="", help="ISCC.exe 路径（默认自动找）")
    ap.add_argument("--skip-iscc", action="store_true", help="只出 dist/Echo/，不编安装包")
    args = ap.parse_args()

    version = ""
    iss = ROOT / "installer" / "setup.iss"
    m = re.search(r'MyAppVersion\s+"([^"]+)"', iss.read_text(encoding="utf-8"))
    if m:
        version = m.group(1)
    say(f"版本号 {version or '(没读到)'}")

    if args.in_place:
        build_dir = ROOT
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            say("!! 当前工作区有未提交改动，这些东西会被打进包里：")
            for line in dirty.splitlines():
                say("   " + line)
    else:
        build_dir = Path(args.worktree) if args.worktree else ROOT.parent / "echo-build"
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                              capture_output=True, text=True).stdout.strip()
        say(f"准备构建目录 {build_dir} @ {head[:8]}")
        if build_dir.exists():
            subprocess.run(["git", "checkout", "--detach", head], cwd=str(build_dir),
                           capture_output=True)
        else:
            r = subprocess.run(["git", "worktree", "add", "--detach", str(build_dir), head],
                               cwd=str(ROOT), capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"建构建目录失败：{r.stderr.strip()}")
    check_setup_tree(build_dir)

    tmp = Path(os.environ.get("CLAUDE_JOB_DIR", "")) / "tmp"
    tmp = tmp if tmp.parent.exists() else Path(os.environ.get("TEMP", "."))
    tmp.mkdir(parents=True, exist_ok=True)

    say("PyInstaller 开跑（几分钟）…")
    rc, log = run(pyinstaller_argv(build_dir), build_dir, tmp / "build_release_pyi.log")
    if rc:
        say(f"PyInstaller 失败，日志尾部（完整：{log}）：")
        for line in log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]:
            say("   " + line)
        raise SystemExit(1)
    say(f"PyInstaller 完成 → {build_dir / 'dist' / 'Echo'}")

    if args.skip_iscc:
        return

    iscc = find_iscc(args.iscc)
    if not iscc or not iscc.exists():
        raise SystemExit("找不到 ISCC.exe，用 --iscc 指定，例如 "
                         r'--iscc "D:\Program Files (x86)\Inno Setup 6\ISCC.exe"')
    say(f"Inno Setup：{iscc.name} 正在压缩（lzma2/ultra64，这次约 3 分钟）…")
    rc, log = run([str(iscc), str(build_dir / "installer" / "setup.iss")],
                  build_dir, tmp / "build_release_iscc.log")
    text = log.read_text(encoding="utf-8", errors="replace")
    if rc or "Successful compile" not in text:
        say("ISCC 没打印 Successful compile —— 产物不可信，别上传。日志尾部：")
        for line in text.strip().splitlines()[-12:]:
            say("   " + line)
        raise SystemExit(1)

    exe = build_dir / "dist" / f"Echo-Setup-{version}.exe"
    ok, detail = verify_installer(exe)
    say(f"结构自检：{'通过' if ok else '不通过'} —— {detail}")
    if not ok:
        raise SystemExit(1)

    target = ROOT / "dist" / exe.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, target)
    say(f"完成 → {target}")
    say("提醒：dist/ 在 .gitignore 里，安装包要另外分发（Gitee 附件单文件上限 100MB，装不下）")


if __name__ == "__main__":
    sys.exit(main())
