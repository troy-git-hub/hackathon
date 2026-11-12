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
            from PyQt5.QtCore import Qt, QSettings, QTimer, QEventLoop
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
            from echo.backend.learning_export import export_json
            exported = export_json(Path(folder) / "learning-profile.json")
            report["checks"]["learning_export"] = exported["format"] == "echo.learning-profile" and "lessons" not in exported and exported["schema_version"] == "2.0.0"
            selected = export_json(Path(folder) / "weaknesses.json", sections=["difficulties"])
            from echo.widgets.export_options import ExportOptionsDialog
            choices = ExportOptionsDialog()
            report["checks"]["personal_export_selection"] = selected["selected_sections"] == ["difficulties"] and "learner" not in selected and len(choices.selected_sections()) == 5
            choices.close()
            from echo.widgets.subtitles import SubtitleWindow
            window.echo.engine.active = True
            captions = SubtitleWindow(window.echo.engine, lambda: None)
            captions.update_caption("00:12", "字幕运行检查")
            report["checks"]["local_captions"] = captions.caption.text() == "字幕运行检查"
            captions.close()
            window.echo.engine.active = False
            from echo.widgets.update_center import UpdateController, UpdateCenter
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            key = load_pem_public_key(Path(paths.asset("assets", "update-public-key.pem")).read_bytes())
            updates = UpdateController(window)
            center = UpdateCenter(updates)
            report["checks"]["signed_update_ui"] = isinstance(key, Ed25519PublicKey) and center.primary.isEnabled()
            center.close()
            from echo.backend.fast_asr import RealtimeWhisperModel
            report["checks"]["fast_asr_runtime"] = hasattr(RealtimeWhisperModel, "encode")
            from echo.widgets.log_viewer import LogViewer
            logs = LogViewer()
            report["checks"]["diagnostics_ui"] = bool(logs.content.toPlainText())
            logs.close()
            from echo.widgets.web_lesson import HtmlLesson
            viewer = HtmlLesson()
            report["checks"]["webengine"] = viewer.view is not None
            if viewer.view:
                viewer.resize(320, 180)
                viewer.show()
                loads = []
                viewer.loaded.connect(loads.append)
                viewer.display({"html": '<button id="proof" onclick="this.textContent=\'正常\'">测试</button><script>document.getElementById("proof").click();if(document.getElementById("proof").textContent!=="正常")throw new Error("interaction failed");</script>'})
                result = []
                loop = QEventLoop()
                def received(state):
                    if isinstance(state, dict) and (state.get("ready") or state.get("error")):
                        result.append(state)
                        loop.quit()
                timer = QTimer()
                timer.timeout.connect(lambda: viewer.page.runJavaScript("window.echoLessonState", received))
                timer.start(100)
                QTimer.singleShot(25000, loop.quit)
                loop.exec_()
                timer.stop()
                report["browser_loads"] = loads
                report["browser_state"] = result[-1] if result else None
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
