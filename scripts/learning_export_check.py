"""Read-only, isolated export and Settings integration regression checks."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    with tempfile.TemporaryDirectory(prefix="echo-export-check-") as folder:
        base = Path(folder)
        from echo.backend import paths
        paths.config_dir = lambda: folder
        from echo.backend import learning_export as exporter

        empty = exporter.build_export()
        assert empty["knowledge_points"] == []
        assert empty["learning_preferences"]["again_rate"] is None
        secret = "NEVER_EXPORT_THIS_SECRET"
        fixtures = {
            "profile.json": {"name": "演示用户", "created": 1700000000, "age": 18, "api_key": secret},
            "lessons.json": [
                {"title": "数学·函数", "time": 1700000100, "duration": 600, "summary": "学习函数定义域",
                 "skills_detail": [{"name": "定义域", "mastery": 0, "status": "review"},
                                   {"name": "函数求值", "mastery": .9, "status": "ok"},
                                   {"name": "关系", "mastery": .5, "status": "warn"}],
                 "quiz": {"total": 4, "correct": 3}, "html": secret},
                {"title": "数学·定义域复习", "time": 1700000200,
                 "skills_detail": [{"name": "定义域", "mastery": .4, "status": "warn"}]},
                {"title": "语文·人物", "time": 1700000300,
                 "skills_detail": [{"name": "关系", "mastery": .8, "status": "ok"}]}
            ],
            "review.json": [
                {"topic": "定义域", "time": 1700000201, "reviewed_at": 1700000400,
                 "reviewed": True, "last_result": "clear", "level": 2, "review_count": 6,
                 "missing": "函数的取值限制", "micro_lesson": secret},
                {"topic": "关系", "time": 1700000400, "reviewed": False, "review_count": 99}
            ],
        }
        for name, data in fixtures.items():
            (base / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (base / ".env").write_text("API_KEY=" + secret, encoding="utf-8")
        before = {p.name: p.read_bytes() for p in base.iterdir()}
        data = exporter.export_json(base / "result.json")
        encoded = (base / "result.json").read_text(encoding="utf-8")
        assert secret not in encoded
        assert {p.name: p.read_bytes() for p in base.iterdir() if p.name in before} == before
        by_topic = {(p["subject"], p["topic"]): p for p in data["knowledge_points"]}
        point = by_topic[("数学", "定义域")]
        assert point["state"] == "strength" and point["observations"][0]["mastery"] == 0
        assert point["latest_mastery"] == .4
        assert by_topic[("数学", "函数求值")]["state"] == "strength"
        assert by_topic[(None, "关系")]["state"] == "weakness"
        assert by_topic[("数学", "关系")]["review"] is None
        assert len(data["recurring_difficulties"]) == 1
        assert data["recurring_difficulties"][0]["affected_lesson_count"] == 2
        assert data["lessons"][0]["quiz"]["accuracy"] == .75
        assert data["lessons"][1]["quiz"]["accuracy"] is None
        second = exporter.build_export()
        assert [p["id"] for p in data["knowledge_points"]] == [p["id"] for p in second["knowledge_points"]]
        ids = {p["id"] for p in data["knowledge_points"]}
        lesson_ids = {p["id"] for p in data["lessons"]}
        assert all(r["knowledge_id"] in ids for r in data["reviews"])
        assert all(set(l["knowledge_ids"]) <= ids for l in data["lessons"])
        assert all(o["lesson_id"] in lesson_ids for p in data["knowledge_points"] for o in p["observations"])
        for filename in ("profile.json", "review.json", "lessons.json", ".env"):
            try:
                exporter.export_json(base / filename)
                raise AssertionError("allowed overwriting live file")
            except ValueError:
                pass
        (base / "review.json").write_text("{broken", encoding="utf-8")
        try:
            exporter.export_json(base / "result.json")
            raise AssertionError("silently discarded corrupt records")
        except ValueError:
            pass
        assert (base / "result.json").read_text(encoding="utf-8") == encoded
        (base / "review.json").write_text(json.dumps(fixtures["review.json"]), encoding="utf-8")
        with patch.object(exporter.os, "replace", side_effect=OSError("disk failure")):
            try:
                exporter.export_json(base / "result.json")
                raise AssertionError("ignored write error")
            except OSError:
                pass
        assert not list(base.glob(".echo-export-*.tmp"))
        assert (base / "result.json").read_text(encoding="utf-8") == encoded

        from PyQt5.QtCore import QSettings
        from PyQt5.QtWidgets import QApplication
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
        app = QApplication.instance() or QApplication([])
        from echo.theme import apply_theme
        apply_theme(app)
        from echo.widgets import settings, dialogs
        dialog = settings.SettingsDialog()
        if "--shot" in sys.argv:
            dialog.show()
            app.processEvents()
            scroll = dialog.findChild(settings.QScrollArea)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            app.processEvents()
            (ROOT / "artifacts").mkdir(exist_ok=True)
            dialog.grab().save(str(ROOT / "artifacts/settings-export.png"))
        with patch.object(settings.QFileDialog, "getSaveFileName", return_value=(str(base / "ui-export"), "")), patch.object(dialogs, "info") as info:
            dialog.btn_export_data.click()
            assert (base / "ui-export.json").is_file() and info.called
        with patch.object(settings.QFileDialog, "getSaveFileName", return_value=("", "")), patch.object(exporter, "export_json") as write:
            dialog.btn_export_data.click()
            write.assert_not_called()
        with patch.object(dialogs, "info") as info:
            dialog.btn_export_help.click()
            assert "schema_version" in info.call_args.args[2]
        with patch.object(settings.QFileDialog, "getSaveFileName", return_value=(str(base / "error.json"), "")), patch.object(exporter, "export_json", side_effect=OSError("unwritable")), patch.object(dialogs, "warn") as warning:
            dialog.btn_export_data.click()
            assert warning.called and not (base / "error.json").exists()
        dialog.close()

        schema = json.loads((ROOT / "docs/learning-profile.schema.json").read_text(encoding="utf-8"))
        assert set(schema["required"]) <= data.keys()
        # Optional development validator; never a runtime dependency.
        try:
            import jsonschema
        except ImportError:
            pass
        else:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(data, schema)
            jsonschema.validate(empty, schema)
        if "--write-example" in sys.argv:
            data["exported_at"] = "2026-11-10T10:00:00.000Z"
            target = ROOT / "docs/examples/learning-profile.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: isolated JSON export, evidence, stable IDs, privacy, atomic failure, Settings actions")


if __name__ == "__main__":
    main()
