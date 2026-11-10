"""Freeze Echo with speech DLLs initialized before Qt during Windows dependency scanning.

PyInstaller normally imports Qt first in its isolated DLL-discovery subprocess.
On this runtime, importing ONNX Runtime after Qt terminates that subprocess. This
keeps PyInstaller's normal analysis intact and uses the same native loading order
as main.py. No installed package is patched and no speech models are loaded.
"""
import sys
from pathlib import Path
import pefile
from PyInstaller import __main__, isolated
from PyInstaller.building import build_main


def preload_speech_libraries():
    import ctranslate2
    import onnxruntime
    import faster_whisper


original_find = build_main.find_binary_dependencies
OriginalPython = isolated.Python
OriginalAnalysisInit = build_main.Analysis.__init__


def file_version(filename):
    try:
        with pefile.PE(filename, fast_load=False) as pe:
            info = pe.VS_FIXEDFILEINFO[0]
            return (info.FileVersionMS >> 16, info.FileVersionMS & 65535,
                    info.FileVersionLS >> 16, info.FileVersionLS & 65535)
    except Exception:
        return (0, 0, 0, 0)


def unify_msvc_runtime(rows):
    """Keep Qt's private runtime copies consistent with the newest bundled v14 DLLs."""
    names = {"msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
    latest = {}
    for destination, source, kind in rows:
        name = Path(source).name.lower()
        if name in names:
            version = file_version(source)
            if name not in latest or version > latest[name][0]:
                latest[name] = (version, source)
    return [(destination, latest[Path(source).name.lower()][1], kind)
            if Path(source).name.lower() in latest else (destination, source, kind)
            for destination, source, kind in rows]


def initialize_analysis(self, *args, **kwargs):
    OriginalAnalysisInit(self, *args, **kwargs)
    # Also runs on cached Analysis objects, so portable and installer builds
    # cannot reintroduce Qt's older MSVCP140.dll when reusing the build cache.
    self.binaries = unify_msvc_runtime(self.binaries)


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
    build_main.Analysis.__init__ = initialize_analysis
__main__.run(sys.argv[1:])
