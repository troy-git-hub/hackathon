"""
Echo 真实链路自检：Windows TTS 朗读示例课 → 扬声器播放 → WASAPI loopback 采集
→ Whisper 实时转写 → DeepSeek 时间轴 → 「我掉队了」→ 断点。

    python scripts/live_check.py            # 会从扬声器出声，约 1~2 分钟
    python scripts/live_check.py --lines 8  # 只读前 8 句
"""
import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.basicConfig(level=logging.INFO, format="  %(name)s %(levelname)s %(message)s")
from echo.backend.engine import EchoEngine
from echo.backend.sources import SystemAudioSource, load_script, _WhisperWorker

ap = argparse.ArgumentParser()
ap.add_argument("--lines", type=int, default=14)
ap.add_argument("--direct", action="store_true", help="不走扬声器，把音频按实时速度直接喂给切句+Whisper")
args = ap.parse_args()

text = "。".join(t for _, t in load_script()[:args.lines])
wav = os.path.join(tempfile.gettempdir(), "echo_live_check.wav")
txt = os.path.join(tempfile.gettempdir(), "echo_live_check.txt")
with open(txt, "w", encoding="utf-8-sig") as f:
    f.write(text)

print("合成语音…")
ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{ $s.SelectVoice('Microsoft Huihui Desktop') }} catch {{}}
$s.Rate = 1
$s.SetOutputToWaveFile('{wav}')
$s.Speak([IO.File]::ReadAllText('{txt}'))
$s.Dispose()
"""
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)

print("加载 Whisper…")
t0 = time.time()
_WhisperWorker.load()
print(f"  {time.time() - t0:.1f}s")

bp_done = threading.Event()
lines = []


def on_bp(bp, shown):
    print("\n===== Break Point =====")
    for c in shown:
        print(f"  {c.timecode} {c.topic}{'  ⚠' if c.timecode == bp.breakpoint_tc else ''}")
    print(f"  缺失：{bp.missing}\n  原因：{bp.reason}\n{bp.micro_lesson}")
    bp_done.set()


eng = EchoEngine(
    on_transcript=lambda tc, t: (lines.append(t), print(f"  [ASR {tc}] {t}", flush=True)),
    on_concept=lambda c: print(f"  [concept] {c.timecode} {c.topic}", flush=True),
    on_breakpoint=on_bp,
    on_error=lambda e: print("  !!", e),
    concept_interval=10)
eng.start()
src = SystemAudioSource(eng)
tp = time.time()
if args.direct:
    import wave
    import numpy as np
    src.asr.start()
    with wave.open(wav) as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype("float32") / 32768
        pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
    print(f"直接喂音频 {len(pcm) / sr:.0f}s（实时速度）…")
    step = sr // 10
    for i in range(0, len(pcm), step):
        src._feed(pcm[i:i + step], sr)
        time.sleep(0.1)
    src.seg.flush()
else:
    src.start()
    time.sleep(1)
    print("播放中（扬声器会出声）…")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"(New-Object Media.SoundPlayer '{wav}').PlaySync()"])
print(f"  音频 {time.time() - tp:.1f}s")
time.sleep(8)
print(f"\n转写 {len(lines)} 句，共 {sum(map(len, lines))} 字")
eng.feedback("lost")
bp_done.wait(90)
src.stop()
eng.shutdown()
