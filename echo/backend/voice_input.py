"""
Echo - 语音转文字（按一下说话）

用在「讲给 Echo 听」这类需要打字回答的地方：按下开始录音，再按一下结束，
录到的话转成文字填进输入框——不自动发送，学生看一眼、改两个字再决定发不发。

复用 sources.py 里全局只加载一次的 Whisper 模型，不另外起一份、不跟
正在上课时的实时听写抢资源（那条是持续采集，这里是单次短录音，两者
各自独立的 sounddevice/pyaudio 流，互不影响）。
"""
import logging
import threading

log = logging.getLogger("echo.voice_input")

SR = 16000
MAX_SECONDS = 30          # 封个上限：这是单轮对话用的，不是让人讲整节课


class Recorder:
    """一次性录音 + 转写。

    用法：
        r = Recorder()
        r.start()                      # 按下麦克风按钮
        ...用户说话...
        text = r.stop_and_transcribe() # 松开/再按一下，阻塞到转写完，放后台线程调
    """

    def __init__(self):
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()

    def start(self):
        """打开输入流开始录。失败（没有麦克风权限/设备）直接抛异常，调用方提示学生。"""
        import sounddevice as sd

        self._frames = []

        def _cb(indata, frames, t, status):
            with self._lock:
                self._frames.append(indata[:, 0].copy() if indata.ndim > 1 else indata.copy())

        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                      blocksize=SR // 10, callback=_cb)
        self._stream.start()

    def stop(self):
        """只停流，不转写（取消录音时用）。"""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def stop_and_transcribe(self) -> str:
        """停止录音并转写成文字。没录到内容、太短（基本是误触）、或转写失败都返回空串。

        阻塞调用（模型推理要一两秒），别在主线程调。
        """
        import numpy as np

        self.stop()
        with self._lock:
            frames = list(self._frames)
        if not frames:
            return ""
        audio = np.concatenate(frames)[:SR * MAX_SECONDS]
        if len(audio) < SR * 0.3:
            return ""
        try:
            from echo.backend.sources import _WhisperWorker, _to_simplified
            model = _WhisperWorker.load()
            segs, _ = model.transcribe(audio, language="zh", beam_size=1, vad_filter=True)
            return _to_simplified("".join(s.text for s in segs).strip())
        except Exception as e:
            log.warning("语音转文字失败: %s", e)
            return ""


def transcribe_async(recorder: Recorder, on_done=None, on_error=None) -> None:
    """后台线程停止录音并转写。成功时 on_done(text)（text 可能是空串——没录到内容）。"""
    def _run():
        try:
            text = recorder.stop_and_transcribe()
            if on_done:
                on_done(text)
        except Exception as e:
            log.exception("语音转文字失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name="echo-voice-input").start()
