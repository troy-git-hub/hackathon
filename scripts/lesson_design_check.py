"""Teaching structure, escaping, compatible HTML route and prompt design contract."""
import copy
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo.backend import paths
folder = tempfile.mkdtemp(prefix="echo-design-")
paths.config_dir = lambda: folder
from echo.backend import blackboard, config, lesson_design
from reading_fixture import BOARD, EXPERIENCE

visual = lesson_design.guided_html(EXPERIENCE, BOARD)
assert visual["layout"] == "guided" and visual["design_version"] == 2
assert 'id=lenses' in visual["html"] and 'id=answers' in visual["html"] and 'id=evidence' in visual["html"]
dirty = copy.deepcopy(EXPERIENCE)
dirty["question"] = '<img src=x onerror="alert(1)">'
dirty["lenses"][0]["body"] = '</script><script>alert(1)</script>'
dirty["lenses"][0]["evidence"] = ["T1", "MADE_UP"]
safe = lesson_design.guided_html(dirty, BOARD)["html"]
assert '<img src=x' not in safe and '</script><script>alert' not in safe and "MADE_UP" not in safe
for field in ("lenses", "comparison", "checkpoint"):
    bad = copy.deepcopy(EXPERIENCE)
    bad[field] = None
    try:
        lesson_design.guided_html(bad, BOARD)
        raise AssertionError("invalid lesson accepted")
    except ValueError:
        pass


class Model:
    def json(self, system, user, **kwargs):
        assert "鲁迅" in system and "原始材料" in system and "--accent-soft" in system
        assert "T1" in user and "T2" in user
        return {"kind": "guided", "experience": EXPERIENCE}


with patch.object(config, "OFFLINE", False), patch.object(blackboard.providers, "configured", return_value=True), patch.object(blackboard, "LLM", return_value=Model()):
    assert blackboard.generate_visual(BOARD)["layout"] == "guided"


class HtmlModel:
    def json(self, *args, **kwargs):
        return {"kind": "html", "title": "参数变化", "html": '<input type="range"><p>比较变化</p>'}


with patch.object(config, "OFFLINE", False), patch.object(blackboard.providers, "configured", return_value=True), patch.object(blackboard, "LLM", return_value=HtmlModel()):
    assert "range" in blackboard.generate_visual(BOARD)["html"]
print("PASS structured reading, evidence, comparison, feedback, escaping, design constraints and existing HTML compatibility")
