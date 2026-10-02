"""
Echo - 语音转文字自检（不需要真麦克风）

    python scripts/voice_input_check.py

只测不依赖硬件的部分：没录到内容 / 录太短 / 转写结果处理 / 异步回调。
真的按麦克风录音这件事本身没法在没有设备的机器上自动测，人工验收时
在听课页点一下麦克风按钮确认能说话、能转文字。

覆盖：
  A. 没录到任何内容 → 返回空串，不抛异常
  B. 录到的内容太短（基本是误触）→ 返回空串
  C. 正常转写：模拟 Whisper 返回的分段拼成一句话
  D. 转写失败（模型抛异常）→ 返回空串，不传播异常
  E. 异步包装：成功/失败都经回调抛出，不卡在后台线程里

退出码：全部通过为 0。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from echo.backend import voice_input  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


def fake_frames(seconds: float):
    """伪造已经录好的音频帧，绕开 start() 对 sounddevice/真麦克风的依赖。"""
    n = int(voice_input.SR * seconds)
    return [np.zeros(n, dtype="float32")]


class StubModel:
    def __init__(self, text="就是曲线的斜率"):
        self.text = text
        self.calls = 0

    def transcribe(self, audio, **kw):
        self.calls += 1
        Seg = type("Seg", (), {})
        s = Seg()
        s.text = self.text
        return [s], None


class BoomModel:
    def transcribe(self, audio, **kw):
        raise RuntimeError("模型挂了")


# ---------- A ----------
section("A. 没录到任何内容")
r = voice_input.Recorder()
check("空录音返回空串", r.stop_and_transcribe() == "")

# ---------- B ----------
section("B. 录太短（误触）")
r = voice_input.Recorder()
r._frames = fake_frames(0.1)
check("0.1 秒的录音当误触，返回空串", r.stop_and_transcribe() == "")

# ---------- C ----------
section("C. 正常转写")
import echo.backend.sources as sources   # noqa: E402

_orig_load = sources._WhisperWorker.load
sources._WhisperWorker.load = classmethod(lambda cls, on_status=None: StubModel())
try:
    r = voice_input.Recorder()
    r._frames = fake_frames(2.0)
    text = r.stop_and_transcribe()
    check("转写结果就是模型给的文字", text == "就是曲线的斜率", text)
finally:
    sources._WhisperWorker.load = _orig_load

# ---------- D ----------
section("D. 转写失败")
sources._WhisperWorker.load = classmethod(lambda cls, on_status=None: BoomModel())
try:
    r = voice_input.Recorder()
    r._frames = fake_frames(2.0)
    text = r.stop_and_transcribe()
    check("模型挂了不抛异常，返回空串", text == "")
finally:
    sources._WhisperWorker.load = _orig_load

# ---------- E ----------
section("E. 异步包装")
sources._WhisperWorker.load = classmethod(lambda cls, on_status=None: StubModel("换个场景也一样"))
try:
    r = voice_input.Recorder()
    r._frames = fake_frames(2.0)
    done = threading.Event()
    got = {}

    def on_done(text):
        got["text"] = text
        done.set()

    voice_input.transcribe_async(r, on_done=on_done, on_error=lambda m: done.set())
    check("异步转写在合理时间内回调", done.wait(5))
    check("异步转写结果正确", got.get("text") == "换个场景也一样", got)

    r2 = voice_input.Recorder()
    r2.stop_and_transcribe = lambda: (_ for _ in ()).throw(RuntimeError("坏了"))
    done2 = threading.Event()
    err = {}
    voice_input.transcribe_async(r2, on_done=lambda t: done2.set(),
                                 on_error=lambda m: (err.setdefault("msg", m), done2.set()))
    check("转写抛异常时走 on_error 而不是卡住", done2.wait(5))
    check("错误信息传出来了", bool(err.get("msg")), err)
finally:
    sources._WhisperWorker.load = _orig_load

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("语音转文字自检：全部通过")
