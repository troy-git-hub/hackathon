"""Freeze Echo with speech DLLs initialized before Qt during Windows dependency scanning.

PyInstaller normally imports Qt first in its isolated DLL-discovery subprocess.
On this runtime, importing ONNX Runtime after Qt terminates that subprocess. This
keeps PyInstaller's normal analysis intact and uses the same native loading order
as main.py. No installed package is patched and no speech models are loaded.
"""
import sys
from PyInstaller import __main__, isolated
from PyInstaller.building import build_main


def preload_speech_libraries():
    import ctranslate2
    import onnxruntime
    import faster_whisper


original_find = build_main.find_binary_dependencies
OriginalPython = isolated.Python


class SpeechFirstPython(OriginalPython):
    def call(self, function, *args, **kwargs):
        if function.__name__ == "import_library" and not getattr(self, "_echo_native_ready", False):
            super().call(preload_speech_libraries)
            self._echo_native_ready = True
        return super().call(function, *args, **kwargs)


def speech_first_dependencies(*args, **kwargs):
    isolated.Python = SpeechFirstPython
    try:
        return original_find(*args, **kwargs)
    finally:
        isolated.Python = OriginalPython


if sys.platform == "win32":
    build_main.find_binary_dependencies = speech_first_dependencies
__main__.run(sys.argv[1:])
