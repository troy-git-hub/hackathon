"""Synthetic audio and streaming fixtures; never reads a real microphone."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['ECHO_OFFLINE'] = '1'


def main():
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='echo-caption-speed-') as folder:
        from echo.backend import paths
        paths.config_dir = lambda: folder
        from echo.backend.sources import _Segmenter, _WhisperWorker, SR
        # Application startup preloads this runtime before classroom decoding.
        # Exclude a cold native-library import from the partial-caption deadline.
        from echo.backend.fast_asr import RealtimeWhisperModel, WhisperModel, realtime_decode
        from echo.backend.engine import EchoEngine
        chunks = []
        with patch.dict(os.environ, ECHO_CAPTION_MODE='fast'):
            segmenter = _Segmenter(lambda audio,t: chunks.append((audio,t)))
        for index in range(60):
            segmenter.feed(np.full(SR//10, .03, dtype=np.float32), (index+1)/10)
        assert chunks and len(chunks[0][0])/SR <= 2.5
        assert chunks[0][1] == 0
        quiet = []
        cut = _Segmenter(lambda audio,t: quiet.append((audio,t)))
        cut.feed(np.full(SR, .03, dtype=np.float32), 1)
        cut.feed(np.zeros(SR//2, dtype=np.float32), 1.5)
        assert quiet and len(quiet[0][0])/SR <= 1.5

        engine = EchoEngine(use_llm=False)
        first, release = threading.Event(), threading.Event()
        captions, final = [], []
        engine.on_caption = lambda tc,text: (captions.append(text), first.set())
        engine.on_transcript = lambda tc,text: final.append(text)
        kwargs = []
        class Model:
            def transcribe(self, audio, **options):
                kwargs.append(options)
                def stream():
                    yield SimpleNamespace(text='先显示字幕')
                    release.wait(2)
                    yield SimpleNamespace(text='再补全句子')
                return stream(), None
        with patch.object(_WhisperWorker, 'load', return_value=Model()):
            worker = _WhisperWorker(engine)
            worker.put(np.full(SR*2, .03, dtype=np.float32), 0)
            worker.start()
            assert first.wait(2)
            assert captions == ['先显示字幕'] and not final
            release.set()
            deadline = time.monotonic()+2
            while not final and time.monotonic()<deadline: time.sleep(.01)
            worker.stop()
        assert final == ['先显示字幕再补全句子'] and len(engine.lines) == 1
        assert kwargs[0]['temperature'] == 0 and kwargs[0]['best_of'] == 1
        from echo.backend.fast_asr import RealtimeWhisperModel, WhisperModel, realtime_decode
        model = object.__new__(RealtimeWhisperModel)
        model._echo_live = threading.local()
        features = np.zeros((80,3000), dtype=np.float32)
        features[:,:240] = 1
        seen = []
        def reject_short(value):
            seen.append(value.shape[-1])
            if value.shape[-1] < 3000: raise RuntimeError('legacy encoder')
            return 'full-encode'
        with patch.object(WhisperModel, 'encode', side_effect=reject_short):
            with realtime_decode(model):
                assert model.encode(features) == 'full-encode'
            assert not model._echo_live.enabled
        assert seen == [1000,3000]  # unsupported encoders recover without dropping audio
        engine.shutdown()
    print('PASS fast slicing <=2.5s, early silence, immediate partial captions, single committed transcript, greedy decoding')


if __name__ == '__main__':
    main()
