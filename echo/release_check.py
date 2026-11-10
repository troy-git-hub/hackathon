"""Packaged-runtime verification, entirely isolated from the user's data and keys."""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def run(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    report = {"frozen": bool(getattr(sys, "frozen", False)), "checks": {}, "errors": []}
    try:
        os.environ["ECHO_OFFLINE"] = "1"
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
        with tempfile.TemporaryDirectory(prefix="echo-release-check-") as folder:
            from echo.backend import paths
            paths.config_dir = lambda: folder
            # Match the real entry point's required native-library loading order.
            import ctranslate2
            import onnxruntime
            import faster_whisper
            import pyaudiowpatch
            import sounddevice
            import opencc
            report["checks"]["speech_runtime"] = bool(ctranslate2 and onnxruntime and faster_whisper and pyaudiowpatch and sounddevice)
            report["checks"]["chinese_conversion"] = opencc.OpenCC("t2s").convert("學習") == "学习"
            from PyQt5.QtCore import Qt, QSettings
            from PyQt5.QtWidgets import QApplication
            QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
            QSettings.setDefaultFormat(QSettings.IniFormat)
            QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
            app = QApplication([])
            from echo.theme import apply_theme
            apply_theme(app)
            from echo.widgets.floating_window import FloatingWindow, HOME, MINI
            window = FloatingWindow()
            window._show_page(HOME)
            window._show_page(MINI)
            window._expand_mini()
            report["checks"]["window_navigation"] = window._page == HOME
            report["checks"]["assets"] = Path(paths.asset("assets", "echo.ico")).is_file()
            from echo.widgets.web_lesson import HtmlLesson
            viewer = HtmlLesson()
            report["checks"]["webengine"] = viewer.view is not None
            if viewer.view:
                viewer.resize(320, 180)
                viewer.show()
                viewer.display({"html": '<button id="proof" onclick="this.textContent=\'正常\'">测试</button><script>document.getElementById("proof").click();if(document.getElementById("proof").textContent!=="正常")throw new Error("interaction failed");</script>'})
                result = []
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    app.processEvents()
                    if not result:
                        viewer.page.runJavaScript("window.echoLessonState", lambda state: result.append(state) if isinstance(state, dict) and (state.get("ready") or state.get("error")) else None)
                    if result:
                        break
                    time.sleep(.03)
                report["checks"]["html_interaction"] = bool(result and result[0].get("ready") and not result[0].get("error"))
                viewer.stop()
                viewer.hide()
            window.echo.shutdown()
            window.hide()
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    report["ok"] = bool(report["checks"]) and all(report["checks"].values()) and not report["errors"]
    output = Path(args.report).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
