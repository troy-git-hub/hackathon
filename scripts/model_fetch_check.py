"""
Echo - 语音识别模型按需下载自检

    python scripts/model_fetch_check.py

覆盖：
  A. 四个文件齐了才算就绪；缺一个就不算
  B. 没在下的时候 poll_progress 返回 -1（UI 定时器据此决定要不要占用状态栏）
  C. ensure() 幂等：已经就绪不重复起线程；重复调也只起一个
  D. 下载过程中按钮/状态栏能拿到百分比（扫盘算字节），跨 10% 才往上跳
  E. wait_ready：就绪时立刻返回；没起过下载时返回 False，不无限等
  F. 下载失败不抛、不影响上课（WhisperModel 还有兜底路径）
  G. whisper_model_path 优先用已下载好的用户目录

退出码：全部通过为 0。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")

from echo.backend import config, model_fetch          # noqa: E402

FAILED = []
_TMP = tempfile.mkdtemp(prefix="echo-model-")
config.user_models_dir = lambda: _TMP


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


def make_files(size=1024):
    d = model_fetch.model_dir()
    os.makedirs(d, exist_ok=True)
    for f in model_fetch.FILES:
        with open(os.path.join(d, f), "wb") as fh:
            fh.write(b"x" * size)


def wipe():
    import shutil
    shutil.rmtree(model_fetch.model_dir(), ignore_errors=True)
    model_fetch._done = False
    model_fetch._thread = None
    model_fetch._progress["percent"] = -1


section("A. 齐了才算就绪")
wipe()
check("一个文件都没有 -> 不就绪", not model_fetch.is_ready())
d = model_fetch.model_dir()
os.makedirs(d, exist_ok=True)
for f in model_fetch.FILES[:-1]:
    open(os.path.join(d, f), "wb").close()
check("缺一个 -> 不就绪", not model_fetch.is_ready())
open(os.path.join(d, model_fetch.FILES[-1]), "wb").close()
check("四个都齐 -> 就绪", model_fetch.is_ready())


section("B. 没在下时 poll_progress 返回 -1")
wipe()
check("没起过下载 -> -1", model_fetch.poll_progress() == -1)


section("C. ensure() 幂等")
wipe()
started = []


def fake_snapshot_download(**kw):
    started.append(kw)
    time.sleep(2)                      # 假装在下，让线程活着
    make_files()
    return model_fetch.model_dir()


import huggingface_hub                                 # noqa: E402
_orig_snap = huggingface_hub.snapshot_download
huggingface_hub.snapshot_download = fake_snapshot_download
try:
    model_fetch.ensure()
    model_fetch.ensure()               # 第二、三次调用不该再起一个线程
    model_fetch.ensure()
    time.sleep(0.3)
    check("只起了一个下载线程", len(started) == 1, f"起了 {len(started)} 个")

    section("D. 下载中能拿到百分比")
    # 写一个 .incomplete（huggingface_hub 下载中的临时文件），模拟「下到一半」。
    # 不能直接把四个文件写齐 —— 那样 is_ready() 立刻为真，wait_ready 会短路，
    # 线程还没跑完就被当成下完了（这个坑我第一版自检就踩了）。
    d = model_fetch.model_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "model.bin.incomplete"), "wb") as fh:
        fh.write(b"x" * (model_fetch.TOTAL_BYTES // 4))     # 约 25%
    pct = model_fetch.poll_progress()
    check("下载中有百分比 (0~99)", 0 <= pct < 100, str(pct))
    # 进度是 10% 一档往上跳的（免得状态栏每秒刷），所以 25% 实际报 20~26 都算对
    check("约两成半的时候报 20%~26%", 20 <= pct <= 26, str(pct))

    check("wait_ready 最终等到就绪", model_fetch.wait_ready(timeout=10) is True)
    model_fetch._thread.join(10)       # 等下载线程真的跑完（wait_ready 可能短路）
    check("线程跑完 -> 100", model_fetch.poll_progress() == 100,
          str(model_fetch.poll_progress()))
finally:
    huggingface_hub.snapshot_download = _orig_snap


section("E. wait_ready 不无限等")
wipe()
check("没起过下载 -> False（不是死等）", model_fetch.wait_ready(timeout=0.1) is False)


section("F. 下载失败不抛")
wipe()


def boom(**kw):
    raise OSError("假装断网")


huggingface_hub.snapshot_download = boom
try:
    model_fetch.ensure()               # 不该抛
    model_fetch.wait_ready(timeout=5)  # 等它失败完；也不该抛
    check("下载失败后 is_ready 是 False（交给兜底路径）", not model_fetch.is_ready())
    check("失败后进度回到 -1", model_fetch.poll_progress() == -1, str(model_fetch.poll_progress()))
finally:
    huggingface_hub.snapshot_download = _orig_snap


section("G. whisper_model_path 优先用下好的用户目录")
wipe()
_saved = config.user_models_dir
config.user_models_dir = lambda: _TMP
try:
    make_files()
    p = config.whisper_model_path()
    check("指向用户模型目录", os.path.normcase(p) == os.path.normcase(model_fetch.model_dir()),
          p)
    wipe()
    p2 = config.whisper_model_path()
    check("没有已下载的模型时不再指向它（回退到 HF 模型名或随包目录）",
          os.path.normcase(p2) != os.path.normcase(model_fetch.model_dir()), p2)
finally:
    config.user_models_dir = _saved

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("模型按需下载自检：全部通过")
