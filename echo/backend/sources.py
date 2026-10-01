"""
Echo - 课程音频来源
  DemoSource : 回放示例课 transcript（现场演示最稳，不依赖网络 ASR / 声卡）
  MicSource  : 麦克风 / 立体声混音 → faster-whisper 本地实时转写
"""
import logging
import os
import queue
import threading

from echo.backend import config
from echo.backend.engine import EchoEngine, parse_tc

log = logging.getLogger("echo.asr")

DEFAULT_DEMO = os.path.join(os.path.dirname(__file__), "demo_lesson.txt")


def load_script(path=None):
    """读取 `时间码 文本` 格式的讲稿，# 开头为注释。"""
    lines = []
    with open(path or DEFAULT_DEMO, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            tc, _, text = raw.partition(" ")
            t = parse_tc(tc)
            if t is None:
                t, text = (lines[-1][0] + 10 if lines else 0), raw
            lines.append((t, text.strip()))
    return lines


class DemoSource:
    def __init__(self, engine: EchoEngine, path=None, interval=None):
        self.engine = engine
        self.lines = load_script(path or config.DEMO_SCRIPT or None)
        self.interval = interval or config.DEMO_LINE_INTERVAL
        self._stop = threading.Event()
        self.total = self.lines[-1][0] if self.lines else 0

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True, name="echo-demo").start()

    def stop(self):
        self._stop.set()

    def _run(self):
        for t, text in self.lines:
            if self._stop.wait(self.interval):
                return
            self.engine.add_transcript(text, t=t)


class MicSource:
    """sounddevice 采集 16k 单声道，按 ASR_CHUNK_SECONDS 切片交给 faster-whisper。"""

    SR = 16000

    def __init__(self, engine: EchoEngine, device=None):
        self.engine = engine
        self.device = self._resolve_device(device if device is not None else config.AUDIO_DEVICE)
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._model = None
        self.total = 0

    @staticmethod
    def _resolve_device(dev):
        if dev in (None, ""):
            return None
        if str(dev).isdigit():
            return int(dev)
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and str(dev) in d["name"]:
                return i
        log.warning("找不到音频设备 %s，使用默认输入", dev)
        return None

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._capture, daemon=True, name="echo-capture").start()
        threading.Thread(target=self._transcribe, daemon=True, name="echo-asr").start()

    def stop(self):
        self._stop.set()

    def _capture(self):
        import numpy as np
        import sounddevice as sd
        info = sd.query_devices(self.device, "input")
        sr = int(info["default_samplerate"])
        ch = min(2, info["max_input_channels"])
        block = int(sr * config.ASR_CHUNK_SECONDS)
        buf = []

        def cb(indata, frames, t, status):
            buf.append(indata.copy())

        self.engine.on_status("listening")
        with sd.InputStream(device=self.device, channels=ch, samplerate=sr,
                            dtype="float32", callback=cb):
            while not self._stop.wait(0.2):
                n = sum(len(b) for b in buf)
                if n >= block:
                    chunks = buf[:]
                    del buf[:len(chunks)]
                    audio = np.concatenate(chunks)
                    audio = audio.mean(axis=1)
                    if sr != self.SR:  # 线性重采样到 16k
                        x = np.linspace(0, len(audio), int(len(audio) * self.SR / sr), endpoint=False)
                        audio = np.interp(x, np.arange(len(audio)), audio).astype("float32")
                    self._q.put(audio)

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self.engine.on_status("loading_asr")
            self._model = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                                       compute_type=config.WHISPER_COMPUTE)
            self.engine.on_status("listening")
        return self._model

    def _transcribe(self):
        import numpy as np
        try:
            model = self._load()
        except Exception as e:
            log.exception("Whisper 加载失败")
            self.engine.on_error(f"ASR 加载失败：{e}")
            return
        while not self._stop.is_set():
            try:
                audio = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if float(np.sqrt(np.mean(audio ** 2))) < 0.003:  # 静音跳过
                continue
            try:
                segs, _ = model.transcribe(audio, language="zh", beam_size=1, vad_filter=True,
                                           initial_prompt="以下是普通话的课堂讲解。")
                text = "".join(s.text for s in segs).strip()
            except Exception as e:
                log.warning("ASR 失败: %s", e)
                continue
            if text:
                self.engine.add_transcript(text)


def make_source(engine: EchoEngine, kind=None):
    kind = (kind or config.SOURCE).lower()
    if kind == "mic":
        return MicSource(engine)
    return DemoSource(engine)
