"""Trim only artificial Whisper encoder padding for live fast-mode decoding."""
import contextlib
import logging
import threading
import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger('echo.asr')


class RealtimeWhisperModel(WhisperModel):
    def __init__(self, *args, **kwargs):
        self._echo_live = threading.local()
        super().__init__(*args, **kwargs)

    def encode(self, features):
        if getattr(self._echo_live, 'enabled', False) and not getattr(self._echo_live, 'unsupported', False):
            axes = tuple(range(features.ndim-1))
            real = np.flatnonzero(np.any(features != 0, axis=axes))
            if len(real):
                frames = min(features.shape[-1], max(1000, int(real[-1])+9))
                frames += frames % 2
                if frames < features.shape[-1]:
                    try:
                        return super().encode(features[..., :frames].copy())
                    except (ValueError, RuntimeError) as exc:
                        self._echo_live.unsupported = True
                        log.warning('短窗口编码不可用，恢复完整窗口: %s', exc)
        return super().encode(features)


@contextlib.contextmanager
def realtime_decode(model, enabled=True):
    state = getattr(model, '_echo_live', None)
    if state is None:
        yield
        return
    previous = getattr(state, 'enabled', False)
    state.enabled = enabled
    try:
        yield
    finally:
        state.enabled = previous
