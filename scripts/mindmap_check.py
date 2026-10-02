"""
Echo - 知识地图自检

    python scripts/mindmap_check.py

覆盖：
  A. 有真实前置关系时按 graph 建图（节点 / 边 / 层级）
  B. 没有 graph 的历史课 —— 按复习链 + 讲课顺序推导，图仍然是连通的
  C. 脏数据过滤 —— 悬空的边、自环、重复边都不能进图
  D. 分层 —— 前置概念在第 0 层；有环也不会死循环
  E. 知识点详情 —— 掉过队的带讲解，没掉队的退回课程摘要
  F. 出题 —— make_item 拼出的形状能被 practice.generate_sync 吃下，且带回解析
  G. from_report —— 刚下课的回响对象能直接转成课程记录
  H. 引擎 —— 一节课跑完，report.graph 里是真实的前置关系

退出码：全部通过为 0。
"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from echo.backend import mindmap, paths, store   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


LESSON = {
    "title": "贝叶斯统计",
    "summary": "从条件概率讲到贝叶斯公式，再到后验概率。",
    "highlights": ["条件概率 P(A|B)=P(A交B)/P(B)", "贝叶斯公式 P(A|B)=P(B|A)P(A)/P(B)"],
    "review_chain": ["后验概率", "贝叶斯公式", "条件概率定义"],
    "skills_detail": [
        {"name": "条件概率定义", "mastery": 0.9, "status": "ok"},
        {"name": "贝叶斯公式", "mastery": 0.3, "status": "review"},
        {"name": "后验概率", "mastery": 0.6, "status": "fixed"},
    ],
    "graph": {
        "nodes": ["条件概率定义", "贝叶斯公式", "后验概率"],
        "edges": [["条件概率定义", "贝叶斯公式"], ["贝叶斯公式", "后验概率"]],
    },
}
MISTAKES = [{"topic": "贝叶斯公式", "missing": "为什么 P(A|B) 可以反过来算？",
             "micro_lesson": "贝叶斯公式把 P(B|A) 翻过来…", "known": "P(A|B)=P(A交B)/P(B)",
             "step": "P(A|B)=P(B|A)P(A)/P(B)", "now": "所以能算后验概率",
             "timecode": "18:39", "reason": "老师跳过了推导"}]

# ---------- A ----------
section("A. 有真实前置关系时建图")
g = mindmap.build(LESSON, MISTAKES)
check("节点数正确", len(g["nodes"]) == 3, f"{len(g['nodes'])}")
check("边数正确", len(g["edges"]) == 2, f"{len(g['edges'])}")
check("标记为用了真实图", g["has_real_graph"] is True)
check("状态从 skills 带过来",
      {n["topic"]: n["status"] for n in g["nodes"]}["贝叶斯公式"] == "review")
check("掉过队的节点被标出来",
      next(n for n in g["nodes"] if n["topic"] == "贝叶斯公式")["has_mistake"] is True)

# ---------- D ----------
section("D. 分层")
lv = {n["topic"]: n["level"] for n in g["nodes"]}
check("根源前置在第 0 层", lv["条件概率定义"] == 0, str(lv))
check("依赖它的往上叠", lv["贝叶斯公式"] == 1 and lv["后验概率"] == 2, str(lv))
cyclic = mindmap.build({"skills_detail": [{"name": "A"}, {"name": "B"}],
                        "graph": {"nodes": ["A", "B"], "edges": [["A", "B"], ["B", "A"]]}})
check("有环不死循环", len(cyclic["nodes"]) == 2)

# ---------- C ----------
section("C. 脏数据过滤")
dirty = mindmap.build({"skills_detail": [{"name": "甲"}, {"name": "乙"}],
                       "graph": {"nodes": ["甲", "乙"],
                                 "edges": [["甲", "不存在"], ["甲", "甲"],
                                           ["甲", "乙"], ["甲", "乙"]]}})
check("悬空的边被丢掉", all(e["to"] in ("甲", "乙") and e["from"] in ("甲", "乙")
                            for e in dirty["edges"]))
check("自环被丢掉", not any(e["from"] == e["to"] for e in dirty["edges"]))
check("重复边去重", len(dirty["edges"]) == 1, str(dirty["edges"]))

# ---------- B ----------
section("B. 没有 graph 的历史课")
hist = {k: v for k, v in LESSON.items() if k != "graph"}
gh = mindmap.build(hist, MISTAKES)
check("历史课也能建图", len(gh["nodes"]) >= 3, f"{len(gh['nodes'])}")
check("标记为推导出来的图", gh["has_real_graph"] is False)
check("复习链方向正确（根源在前）",
      any(e["from"] == "条件概率定义" for e in gh["edges"]), str(gh["edges"]))
check("每个非根节点都有父（图连通）",
      len(gh["edges"]) >= len(gh["nodes"]) - 1, f"{len(gh['edges'])} 边 / {len(gh['nodes'])} 点")

# ---------- L. 时间码 + 建议先看 ----------
section("L. 时间码与建议先看")
timed = mindmap.build({
    "review_chain": ["丙", "乙", "甲"],
    "graph": {"nodes": ["甲", "乙", "丙"], "edges": [["甲", "乙"], ["乙", "丙"]],
              "times": {"甲": "00:05", "乙": "02:30", "丙": "04:10"}}}, [])
by_topic = {n["topic"]: n for n in timed["nodes"]}
check("节点带上老师讲到的时间码", by_topic["乙"]["timecode"] == "02:30", str(by_topic["乙"]))
check("复习链的根源被标成「建议先看」", timed["review_first"] == "甲", timed["review_first"])
check("详情能标出「建议先看」",
      mindmap.node_detail({"review_chain": ["丙", "乙", "甲"]}, "甲", [], "甲")["review_first"] is True)
check("其它节点不会被标",
      mindmap.node_detail({"review_chain": ["丙", "乙", "甲"]}, "乙", [], "甲")["review_first"] is False)
check("没有复习链时不乱标",
      mindmap.build({"skills_detail": [{"name": "甲"}]}, [])["review_first"] == "")

# ---------- K. 连通性 ----------
section("K. 图必须连通（不能有孤点）")

def degrees(graph):
    deg = {}
    for e in graph["edges"]:
        deg[e["from"]] = deg.get(e["from"], 0) + 1
        deg[e["to"]] = deg.get(e["to"], 0) + 1
    return deg


sparse = mindmap.build({"skills_detail": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
                        "graph": {"nodes": ["甲", "乙", "丙"],
                                  "edges": [["甲", "乙"]]}}, [])
d = degrees(sparse)
check("存储图里的孤点被接进链里",
      all(d.get(n["topic"], 0) > 0 for n in sparse["nodes"]), str(sparse["edges"]))
check("原本的前置边还在", ["甲", "乙"] in [[e["from"], e["to"]] for e in sparse["edges"]])

from echo.backend.engine import EchoEngine, _ConceptEntry   # noqa: E402
from echo.mock_data import Concept                          # noqa: E402

eng_g = EchoEngine(use_llm=False)
eng_g.start()
with eng_g._lock:
    eng_g.entries = [
        _ConceptEntry(0, Concept("00:01", "甲", [], [], "")),
        _ConceptEntry(10, Concept("00:10", "乙", ["甲"], [], "")),
        _ConceptEntry(20, Concept("00:20", "丙", [], [], "")),      # 孤点
    ]
gg = eng_g._concept_graph()
gd = {t: 0 for t in gg["nodes"]}
for a, b in gg["edges"]:
    gd[a] = gd.get(a, 0) + 1
    gd[b] = gd.get(b, 0) + 1
check("引擎图里所有知识点都进图了", len(gg["nodes"]) == 3, str(gg["nodes"]))
check("引擎图里没有孤点", all(v > 0 for v in gd.values()), str(gg["edges"]))
check("真实前置边保留", ["甲", "乙"] in gg["edges"], str(gg["edges"]))
eng_g.shutdown()

# ---------- E ----------
section("E. 知识点详情")
d = mindmap.node_detail(LESSON, "贝叶斯公式", MISTAKES)
check("带出讲解", "贝叶斯" in d["micro_lesson"])
check("带出缺失的那一步", bool(d["missing"]) and bool(d["step"]))
check("状态为待回看", d["status"] == "review")
d2 = mindmap.node_detail(LESSON, "条件概率定义", MISTAKES)
check("没掉队过的节点也能打开", d2["topic"] == "条件概率定义")
check("没掉队时没有 missing", not d2["missing"])
check("退回课程摘要/要点作为讲解", bool(d2["taught"]))
d3 = mindmap.node_detail(LESSON, "不存在的知识点", MISTAKES)
check("不存在的知识点不崩", d3["topic"] == "不存在的知识点" and d3["status"] == "ok")

# ---------- F ----------
section("F. 出题（离线兜底也要有解析）")
item = mindmap.make_item(LESSON, "贝叶斯公式", MISTAKES[0])
check("拼出的形状带 topic/missing", item["topic"] == "贝叶斯公式" and item["missing"])
from echo.backend import practice   # noqa: E402
qs = practice.generate_sync(item, 2)
check("离线也能出题", bool(qs))
check("题目有解析（explain 非空）", all(q.get("explain") for q in qs))
item_ok = mindmap.make_item(LESSON, "条件概率定义")     # 没错题的节点
qs2 = practice.generate_sync(item_ok, 1)
check("没错题的知识点也能出题", bool(qs2) and bool(qs2[0].get("explain")))

# ---------- G ----------
section("G. from_report")
from echo.backend.engine import EchoReport   # noqa: E402
from echo.mock_data import EchoSkill         # noqa: E402
rep = EchoReport([EchoSkill("条件概率定义", 0.9, "ok"), EchoSkill("贝叶斯公式", 0.3, "review")],
                 ["贝叶斯公式", "条件概率定义"], "多练贝叶斯公式", summary="讲了两件事",
                 highlights=["P(A|B)=P(A交B)/P(B)"],
                 graph={"nodes": ["条件概率定义", "贝叶斯公式"],
                        "edges": [["条件概率定义", "贝叶斯公式"]]})
rec = mindmap.from_report(rep, "今天这节课")
check("转出课程记录形状", rec["skills_detail"][1]["name"] == "贝叶斯公式")
check("graph 带过来了", rec["graph"]["edges"] == [["条件概率定义", "贝叶斯公式"]])
check("转出来的记录能直接建图", len(mindmap.build(rec, [])["edges"]) == 1)

# ---------- H ----------
section("H. 引擎：一节课跑完的真实前置关系")
tmp = tempfile.mkdtemp(prefix="echo-mindmap-")
paths.config_dir = lambda: tmp
from echo.backend.engine import EchoEngine   # noqa: E402

eng = EchoEngine(use_llm=False)
eng.start()
sid = eng.session
for text in ("下面讲条件概率的定义", "贝叶斯公式是这样", "最后看后验概率"):
    eng.add_transcript(text, t=eng.elapsed(), session=sid)
    eng._extract_concept(force=True, sid=sid)
graph = eng._concept_graph()
check("引擎图里有节点", len(graph["nodes"]) >= 1, str(graph["nodes"]))
check("引擎图里有真实的前置边", len(graph["edges"]) >= 1, str(graph["edges"]))
check("边两端都在节点里",
      all(a in graph["nodes"] and b in graph["nodes"] for a, b in graph["edges"]))

got = {}
done = threading.Event()


def on_echo(report):          # 旧式回调是单参数（on_event 那条路才是带 sid 的）
    got["report"] = report
    done.set()


eng.on_echo = on_echo
eng.end_lesson()
done.wait(20)
check("回响对象带上了 graph", bool(getattr(got.get("report"), "graph", None)))
if got.get("report"):
    check("回响里的图能建出知识地图",
          len(mindmap.build(mindmap.from_report(got["report"]), [])["nodes"]) >= 1)

# ---------- I ----------
section("I. 存进课程记录再读回来")
ts = store.save_lesson("测试课", [EchoSkill("甲", 0.5, "review")], ["甲"], graph=graph)
back = store.get_lesson(ts)
check("graph 落盘了", bool(back.get("graph")))
check("读回来边数一致", len(back["graph"]["edges"]) == len(graph["edges"]))
check("读回来的记录能建图", len(mindmap.build(back, [])["nodes"]) >= 1)
ts2 = store.save_lesson("没有图的课", [EchoSkill("乙", 0.9, "ok")], [])
check("不传 graph 也能存（向后兼容）", not store.get_lesson(ts2).get("graph"))
check("没有图的课也能建图", len(mindmap.build(store.get_lesson(ts2), [])["nodes"]) == 1)

eng.shutdown()

# ---------- J. 画布交互 ----------
section("J. 画布交互（拖动 / 缩放 / 点击）")
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt      # noqa: E402
from PyQt5.QtGui import QMouseEvent, QWheelEvent          # noqa: E402
from PyQt5.QtWidgets import QApplication                  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
from echo.widgets import mindmap as mm_view           # noqa: E402
from echo.widgets.mindmap import _Canvas               # noqa: E402

c = _Canvas()
c.resize(400, 300)
clicked = []
c.node_clicked.connect(clicked.append)
c.set_graph(g)
c.grab()                                   # 触发一次绘制，让自动适配生效


def press(x, y):
    c.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPoint(x, y),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def move(x, y):
    c.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPoint(x, y),
                                 Qt.NoButton, Qt.LeftButton, Qt.NoModifier))


def release(x, y):
    c.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPoint(x, y),
                                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def wheel(dy, x=200, y=150):
    c.wheelEvent(QWheelEvent(QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, dy),
                             Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False))


check("新图自动缩放到放得下",
      c._world.width() * c._scale <= c.width() + 1
      and c._world.height() * c._scale <= c.height() + 1)
check("缩放不会超过 1.0（小图不放大）", c._scale <= 1.0)

off = QPointF(c._offset)
press(6, 292)
move(60, 250)
release(60, 250)
check("空白处拖动 = 平移", abs(c._offset.x() - off.x()) > 20)
check("平移不会误触选中", not clicked)

scale0 = c._scale
wheel(120)
check("滚轮向上放大", c._scale > scale0)
for _ in range(60):
    wheel(120)
check("缩放有上限", abs(c._scale - 2.4) < 0.01, f"{c._scale:.2f}")
for _ in range(80):
    wheel(-120)
check("缩放有下限", abs(c._scale - 0.45) < 0.01, f"{c._scale:.2f}")

r = c._rect("贝叶斯公式")
center = c._from_world(r.center())
cx, cy = int(center.x()), int(center.y())
press(cx, cy)
release(cx, cy)
check("点节点会发信号", clicked and clicked[-1] == "贝叶斯公式")
check("点节点会选中", c._selected == "贝叶斯公式")

before = QPointF(c._pos["贝叶斯公式"])
r = c._rect("贝叶斯公式")
center = c._from_world(r.center())
cx, cy = int(center.x()), int(center.y())
press(cx, cy)
move(cx + 40, cy + 20)
release(cx + 40, cy + 20)
moved = c._pos["贝叶斯公式"] - before
# 屏幕上移 40px、当前缩放 s → 世界坐标里应移动 40/s
expect = 40 / c._scale
check(f"拖节点跟手（世界位移 ≈ {expect:.0f}）", abs(moved.x() - expect) < 3,
      f"实际 {moved.x():.0f}")
check("拖动不算点击", len(clicked) == 1)

c.resize(400, 180)                          # 缩小画布
off_before_resize = QPointF(c._offset)
c.resize(400, 180)
check("学生动过视图后，改尺寸不再自动改他的视图",
      abs(c._offset.x() - off_before_resize.x()) < 0.01,
      f"{off_before_resize.x():.0f} -> {c._offset.x():.0f}")

c.reset_view()
check("重置视图还原自动排布",
      abs(c._pos["贝叶斯公式"].y() - (mm_view.PAD + 1 * mm_view.LEVEL_H)) < 0.01,
      f"y={c._pos['贝叶斯公式'].y():.1f}")
check("重置后层级还在", sorted(c._levels.values()) == [0, 1, 2])

blank = _Canvas()
blank.resize(300, 200)
blank.set_graph({"nodes": [], "edges": []})
blank.grab()
check("空图绘制不崩", True)

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("知识地图自检：全部通过")
