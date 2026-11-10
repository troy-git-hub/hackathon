"""Regression for the learned map's single-column layout and invented sequence edges."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ECHO_OFFLINE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from echo.backend import paths
folder = tempfile.mkdtemp(prefix="echo-learned-")
paths.config_dir = lambda: folder
from PyQt5.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
from PyQt5.QtWidgets import QApplication
from echo.backend import mindmap
from echo.theme import apply_theme
from echo.widgets.mindmap import MindMapPage

topics = ["函数符号f(x)", "对应关系", "函数求值", "换元法求解析式", "自变量取值范围",
          "复合代入求值", "定义域与值域", "配凑法求解析式", "函数三要素"]
lesson = {"title": "数学 · 函数基础", "time": 1,
          "skills_detail": [{"name": t, "mastery": .5, "status": "review" if i % 3 == 0 else "ok"} for i, t in enumerate(topics)]}
unrelated = mindmap.build_all([lesson])
assert len(unrelated["nodes"]) == 9 and unrelated["edges"] == []  # order is not dependency
lesson["graph"] = {"nodes": topics, "edges": [["函数三要素", "对应关系"], ["函数三要素", "定义域与值域"],
    ["函数三要素", "函数符号f(x)"], ["定义域与值域", "自变量取值范围"],
    ["函数符号f(x)", "函数求值"], ["函数求值", "复合代入求值"]]}
graph = mindmap.build_all([lesson])
assert len(graph["edges"]) == 6
assert graph["levels"]["函数求值"] > graph["levels"]["函数符号f(x)"]
app = QApplication([])
apply_theme(app)
page = MindMapPage()
page.resize(720, 760)
page.show_all([lesson])
page.show()
app.processEvents()
c = page.canvas
assert len(set(round(p.x()) for p in c._pos.values())) >= 3, "same-subject topics still stacked into one column"
for a, b in lesson["graph"]["edges"]:
    assert c._pos[a].y() < c._pos[b].y(), "prerequisite levels ignored"
assert c._course_headers and c._course_headers[0][1] == lesson["title"]
assert c._world.width() * c._scale <= c.width() + 1
assert c._world.height() * c._scale <= c.height() + 1
for i, a in enumerate(topics):
    for b in topics[i+1:]:
        assert not c._rect(a).intersects(c._rect(b)), "nodes overlap"
other = {"title": "历史 · 辛亥革命", "time": 2, "skills_detail": [{"name": "武昌起义", "status": "ok"}]}
page.show_all([lesson, other])
app.processEvents()
c.set_focus(1)
assert c._dimmed(topics[0]) and not c._dimmed("武昌起义")
center = c._from_world(c._rect("武昌起义").center())
assert c.rect().contains(center.toPoint())
c.set_focus(None)
page.show_all([lesson])
page.select("函数求值")
app.processEvents()
assert page.canvas._selected == "函数求值"
assert page.canvas._course_headers, "selecting a knowledge point erased the course branches"
page.detail.clear()
page.detail.hide()
app.processEvents()
out = Path(__file__).resolve().parents[1] / "artifacts"
out.mkdir(exist_ok=True)
page.grab().save(str(out / "learned-map-branches.png"))
page.hide()
print("PASS grouped course branches, real prerequisite rows, parallel unrelated nodes, focus zoom, node selection and complete fit")
