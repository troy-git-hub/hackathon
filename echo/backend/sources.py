"""
Echo - 课程音频来源（真实采集，无演示数据）
  SystemAudioSource : WASAPI loopback 抓电脑正在播放的声音（腾讯会议 / Zoom / B站 / 录播课）→ Whisper
  MicSource         : 麦克风或任意输入设备 → Whisper
"""
import logging
import os
import queue
import threading
import time

from echo.backend import config
from echo.backend.engine import EchoEngine

log = logging.getLogger("echo.asr")

SR = 16000


# ================= 切句 + 转写 =================
class _Segmenter:
    """按静音切句：说话中遇到 ≥0.5s 静音且已累计 ≥2.5s 就切一段；超过 ASR_CHUNK_SECONDS*2 强制切。"""

    def __init__(self, on_segment):
        import numpy as np
        self.np = np
        self.on_segment = on_segment
        self.buf, self.n, self.silent = [], 0, 0
        self.t0 = 0.0
        self.noise = 0.004   # 自适应噪声底

    def feed(self, audio, t_now):
        np = self.np
        for i in range(0, len(audio), SR // 10):          # 100ms 一帧
            frame = audio[i:i + SR // 10]
            if not len(frame):
                continue
            rms = float(np.sqrt(np.mean(frame ** 2)))
            loud = rms > max(0.006, self.noise * 2.5)
            if not loud:
                self.noise = 0.98 * self.noise + 0.02 * rms
            if not self.buf and not loud:
                continue
            if not self.buf:
                self.t0 = t_now
            self.buf.append(frame)
            self.n += len(frame)
            self.silent = 0 if loud else self.silent + len(frame)
            dur = self.n / SR
            if (self.silent >= 0.5 * SR and dur >= 2.5) or dur >= config.ASR_CHUNK_SECONDS * 2:
                self.flush()
            elif self.silent >= 1.0 * SR and dur < 2.5:     # 零碎噪声，丢掉
                self.buf, self.n, self.silent = [], 0, 0

    def flush(self):
        if self.buf:
            self.on_segment(self.np.concatenate(self.buf), self.t0)
        self.buf, self.n, self.silent = [], 0, 0


_HALLUCINATIONS = ("字幕", "订阅", "点赞", "谢谢观看", "请不吝", "Amara", "优优独播")

try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")

    def _to_simplified(text):
        return _cc.convert(text)
except Exception:
    def _to_simplified(text):
        return text


class _WhisperWorker:
    """后台 faster-whisper 转写，模型全局只加载一次。"""

    _model = None
    _model_lock = threading.Lock()

    def __init__(self, engine: EchoEngine):
        self.engine = engine
        self.session = engine.session
        self.q = queue.Queue()
        self._stop = threading.Event()
        self._prev = ""

    @classmethod
    def load(cls, on_status=None):
        with cls._model_lock:
            if cls._model is None:
                from faster_whisper import WhisperModel
                if on_status:
                    on_status("loading_asr")
                kw = dict(device=config.WHISPER_DEVICE, compute_type=config.WHISPER_COMPUTE,
                          cpu_threads=min(config.WHISPER_THREADS, os.cpu_count() or 1))
                # 先只用本地缓存：模型下过一次就不再联网（现场网络/SSL 抽风时联网会卡很久）
                try:
                    cls._model = WhisperModel(config.WHISPER_MODEL, local_files_only=True, **kw)
                    log.info("Whisper 从本地缓存加载：%s", config.WHISPER_MODEL)
                except Exception as e:
                    log.info("本地没有 Whisper 模型（%s），开始下载…", e)
                    try:
                        cls._model = WhisperModel(config.WHISPER_MODEL, **kw)
                    except Exception as e2:
                        raise RuntimeError(
                            f"Whisper 模型 {config.WHISPER_MODEL} 下载失败（{type(e2).__name__}）。"
                            "请检查网络后重试，或把 ECHO_WHISPER_MODEL 设成已下载好的模型文件夹路径") from e2
        return cls._model

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True, name="echo-asr").start()

    def stop(self):
        self._stop.set()

    def put(self, audio, t):
        self.q.put((audio, t))

    def _run(self):
        try:
            model = self.load(lambda st: self.engine.emit_status(self.session, st))
            self.engine.emit_status(self.session, "listening")
        except Exception as e:
            log.exception("Whisper 加载失败")
            self.engine.emit_error(self.session, f"语音识别加载失败：{e}")
            return
        while not self._stop.is_set():
            try:
                audio, t = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            # 用时间轴上已识别出的知识点当热词，减少同音错字（如「备叶思」→「贝叶斯」）
            hot = []
            for c in self.engine.concepts()[-6:]:
                hot += [c.topic] + c.concepts[:3]
            try:
                segs, _ = model.transcribe(
                    audio, language="zh", beam_size=1, vad_filter=True,
                    condition_on_previous_text=False,
                    hotwords=" ".join(dict.fromkeys(hot)) or None,
                    initial_prompt="以下是普通话的课堂讲解，使用简体中文。" + self._prev[-60:])
                text = _to_simplified("".join(s.text for s in segs).strip())
            except Exception as e:
                log.warning("ASR 失败: %s", e)
                continue
            if self._stop.is_set():      # 已下课/换课：正在转写的这段不再送进去
                break
            if len(text) > 1 and not any(h in text for h in _HALLUCINATIONS):
                self._prev = text
                self.engine.add_transcript(text, t=t, session=self.session)


def _resample(audio, sr):
    import numpy as np
    if sr == SR:
        return audio.astype("float32")
    x = np.linspace(0, len(audio), int(len(audio) * SR / sr), endpoint=False)
    return np.interp(x, np.arange(len(audio)), audio).astype("float32")


class _LiveSource:
    total = 0   # 实时课程没有总时长

    def __init__(self, engine: EchoEngine):
        self.engine = engine
        self.session = engine.session
        self.asr = _WhisperWorker(engine)
        self.seg = _Segmenter(self.asr.put)
        self._stop = threading.Event()

    def start(self):
        self._stop.clear()
        # 在子线程中串行加载 ASR + 启动 capture，避免两个 native 库并发初始化冲突，同时 UI 不阻塞
        threading.Thread(target=self._startup, daemon=True, name="echo-source").start()

    def _startup(self):
        """串行：先加载 Whisper 模型，再启动音频捕获，避免 native 库并发初始化访问违例。"""
        try:
            self.asr.load(lambda st: self.engine.emit_status(self.session, st))
        except Exception as e:
            log.exception("Whisper 加载失败")
            self.engine.emit_error(self.session, f"语音识别加载失败：{e}")
            return
        self.engine.emit_status(self.session, "listening")
        self.asr.start()
        self._guard()

    def stop(self):
        self._stop.set()
        self.asr.stop()

    def _guard(self):
        try:
            self._capture()
            self.seg.flush()
        except Exception as e:
            log.exception("音频采集失败")
            self.engine.emit_error(self.session, f"音频采集失败：{e}")

    def _feed(self, mono, sr):
        mono = _resample(mono, sr)
        # 真实声纹：把这一块音频的响度发给 UI（0..1），驱动声纹球，不再用随机假动画
        try:
            import numpy as np
            rms = float(np.sqrt(np.mean(np.square(mono))))
            self.engine.emit_level(self.session, min(1.0, rms * 6.0))
        except Exception:
            pass
        self.seg.feed(mono, self.engine.elapsed())


class SystemAudioSource(_LiveSource):
    """WASAPI loopback：直接抓电脑正在播放的声音，不经过麦克风，耳机也能用。"""

    def _capture(self):
        import numpy as np
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
            dev = p.get_default_wasapi_loopback()
            sr = int(dev["defaultSampleRate"])
            ch = max(1, int(dev["maxInputChannels"]))
            log.info("系统音频: %s %dHz %dch", dev["name"], sr, ch)
            stream = p.open(format=pyaudio.paFloat32, channels=ch, rate=sr, input=True,
                            input_device_index=dev["index"], frames_per_buffer=sr // 10)
            # 没有声音播放时 loopback 不出数据，read 会阻塞，所以轮询可读帧数；
            # 声音停了也就没有"静音帧"，空闲 0.6s 主动把缓冲里的半句话送去转写
            idle_since = time.time()
            while not self._stop.is_set():
                avail = stream.get_read_available()
                if avail <= 0:
                    if time.time() - idle_since > 0.6:
                        self.seg.flush()
                    time.sleep(0.05)
                    continue
                idle_since = time.time()
                data = stream.read(avail, exception_on_overflow=False)
                self._feed(np.frombuffer(data, dtype=np.float32).reshape(-1, ch).mean(axis=1), sr)
            stream.close()
        finally:
            p.terminate()


class MicSource(_LiveSource):
    """麦克风（或「立体声混音」等任意输入设备）。"""

    def __init__(self, engine: EchoEngine, device=None):
        super().__init__(engine)
        self.device = self._resolve_device(device if device is not None else config.AUDIO_DEVICE)

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

    def _capture(self):
        import sounddevice as sd
        info = sd.query_devices(self.device, "input")
        sr = int(info["default_samplerate"])
        ch = min(2, info["max_input_channels"])
        q = queue.Queue()
        with sd.InputStream(device=self.device, channels=ch, samplerate=sr, dtype="float32",
                            blocksize=sr // 10, callback=lambda d, f, t, s: q.put(d.copy())):
            while not self._stop.is_set():
                try:
                    self._feed(q.get(timeout=0.3).mean(axis=1), sr)
                except queue.Empty:
                    pass


def make_source(engine: EchoEngine, kind=None):
    kind = (kind or config.SOURCE).lower()
    if kind == "mic":
        return MicSource(engine)
    try:
        import pyaudiowpatch  # noqa: F401
        return SystemAudioSource(engine)
    except ImportError:
        log.warning("缺少 pyaudiowpatch，改用麦克风")
        return MicSource(engine)


def preload_asr(on_status=None):
    """后台预加载 Whisper，避免开课后第一句话还要等模型加载。"""
    threading.Thread(target=_WhisperWorker.load, args=(on_status,), daemon=True).start()
