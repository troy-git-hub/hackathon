"""
Echo - 知识地图

一节课上完，把知识点画成一张图：节点是知识点，连线是「学这个之前得先懂那个」。
不懂的节点点开能看讲解，还能直接看这道题的解析。

数据有两层来源：

  1. 上课时引擎抓到的真实前置关系（Concept.prerequisites），随课程记录一起存下来
     —— 最准，带真正的依赖方向
  2. 没有 graph 的历史课程：退回用 review_chain（掉队点 → 一路追到根源前置概念）
     + 知识点讲课顺序推导，边弱一些但结构完整

两种都能画，所以主页里翻出来的旧课也有知识地图。
"""
import logging
import re

log = logging.getLogger("echo.mindmap")

# 掌握状态：ok 已跟上 / fixed 掉队过但补上了 / review 待回看
STATUS_OK, STATUS_FIXED, STATUS_REVIEW = "ok", "fixed", "review"


def _norm(s: str) -> str:
    """去掉空格标点，用于知识点名字的模糊匹配（「贝叶斯公式」↔「贝叶斯公式的推导」）。"""
    return re.sub(r"[\s，,。.：:、（）()\[\]「」『』!?！？\-—_]+", "", str(s or "")).lower()


def _same(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _skills(lesson: dict) -> list:
    return [s for s in (lesson.get("skills_detail") or []) if s.get("name")]


def _skill_of(lesson: dict, topic: str) -> dict:
    """按名字找出这个知识点在回响里的掌握情况。"""
    for s in _skills(lesson):
        if _same(s.get("name"), topic):
            return s
    return {}


def _mistake_of(mistakes: list, topic: str) -> dict:
    for m in mistakes or []:
        if _same(m.get("topic"), topic):
            return m
    return {}


def _derive_graph(lesson: dict) -> dict:
    """没有 graph 时的推导：复习链当主干，其余知识点按讲课顺序串起来。"""
    nodes = [s["name"] for s in _skills(lesson)]
    edges = []

    chain = [c for c in (lesson.get("review_chain") or []) if c]
    # review_chain 是「掉队点 → … → 最该先复习的根源概念」，反过来才是知识依赖方向
    ordered_chain = list(reversed(chain))
    for a, b in zip(ordered_chain, ordered_chain[1:]):
        edges.append((a, b))
        for t in (a, b):
            if not any(_same(t, n) for n in nodes):
                nodes.append(t)

    # 剩下的知识点按课堂顺序接在前一个后面，保证图是连通的
    prev = ordered_chain[-1] if ordered_chain else None
    for s in _skills(lesson):
        name = s["name"]
        if any(_same(name, t) for t in ordered_chain):
            continue
        if prev and not _same(prev, name):
            edges.append((prev, name))
        prev = name
    return {"nodes": nodes, "edges": edges}


def _levels(nodes: list, edges: list) -> dict:
    """按依赖深度分层：前置概念在第 0 层，依赖它的往上叠。有环也不会死循环。"""
    deps = {n: [] for n in nodes}
    for a, b in edges:
        if a in deps and b in deps and a != b:
            deps[b].append(a)

    level = {}

    def depth(n, seen):
        if n in level:
            return level[n]
        if n in seen:            # 有环，按 0 处理，别再往下钻
            return 0
        seen = seen | {n}
        d = 0
        for p in deps[n]:
            d = max(d, depth(p, seen) + 1)
        level[n] = d
        return d

    for n in nodes:
        depth(n, frozenset())
    return level


def _connect_isolated(nodes: list, edges: list) -> list:
    """把没有任何连线的知识点按顺序接入链里。

    前置关系覆盖率有限：一个知识点可能既没有前置、也没被别人当前置，那就是孤点，
    整张图看着只剩几个散点，像「只画了有关系的几个」。按讲课顺序接上前一个，
    保证图是一节课完整的知识链。
    """
    linked = {t for e in edges for t in e}
    out = list(edges)
    prev = None
    for t in nodes:
        if prev is not None and t not in linked:
            out.append([prev, t])
            linked.add(t)
        prev = t
    return out


def build(lesson: dict, mistakes: list = None) -> dict:
    """把一节课变成可画的图：nodes（含状态/层级）+ edges。

    lesson 传 store.get_lesson(ts) 或 list_lessons() 里的记录；
    mistakes 传 store.load()，用来标出哪些节点是掉过队的。
    """
    lesson = lesson or {}
    raw = lesson.get("graph") if isinstance(lesson.get("graph"), dict) else None
    nodes_src = [str(t) for t in (raw or {}).get("nodes") or [] if str(t).strip()]
    edges_src = [(str(a), str(b)) for a, b in (raw or {}).get("edges") or []]
    if not nodes_src:
        derived = _derive_graph(lesson)
        nodes_src, edges_src = derived["nodes"], derived["edges"]

    # 去重但保序，方便稳定渲染
    nodes_src = list(dict.fromkeys(nodes_src))
    # 边只保留两端都在图里的，并去掉自环和重复
    seen = set()
    edges = []
    for a, b in edges_src:
        if a == b or not _same_in(a, nodes_src) or not _same_in(b, nodes_src):
            continue
        key = (a, b)
        if key in seen:
            continue
        seen.add(key)
        edges.append([a, b])
    edges = _connect_isolated(nodes_src, edges)
    edges = [{"from": a, "to": b} for a, b in edges]

    levels = _levels(nodes_src, [(e["from"], e["to"]) for e in edges])
    nodes = []
    for t in nodes_src:
        sk = _skill_of(lesson, t)
        mk = _mistake_of(mistakes or [], t)
        status = sk.get("status") or (STATUS_REVIEW if mk else STATUS_OK)
        nodes.append({
            "id": t,
            "topic": t,
            "status": status,
            "mastery": float(sk.get("mastery") or 0.0),
            "level": levels.get(t, 0),
            "timecode": mk.get("timecode") or "",
            "has_mistake": bool(mk),
        })
    return {"nodes": nodes, "edges": edges, "levels": levels,
            "has_real_graph": bool(raw and raw.get("nodes"))}


def _same_in(topic: str, nodes: list) -> bool:
    return any(_same(topic, n) for n in nodes)


def from_report(report, title: str = "") -> dict:
    """把刚下课的回响对象转成「课程记录」的形状。

    这样课后不用等存盘就能直接看知识地图，字段和 store.get_lesson(ts) 一致，
    两者都能喂给 build() / MindMapPage.show_lesson()。
    """
    skills = []
    for s in (getattr(report, "skills", None) or []):
        if isinstance(s, dict):
            name, mastery, status = s.get("name", ""), s.get("mastery", 0.0), s.get("status", "ok")
        else:
            name = getattr(s, "name", "")
            mastery, status = getattr(s, "mastery", 0.0), getattr(s, "status", "ok")
        try:
            mastery = float(mastery or 0.0)
        except (TypeError, ValueError):
            mastery = 0.0
        if name:
            skills.append({"name": str(name), "mastery": mastery, "status": str(status)})
    graph = getattr(report, "graph", None) or {}
    return {
        "title": title or getattr(report, "summary", "")[:20] or "一节课",
        "summary": getattr(report, "summary", "") or "",
        "highlights": [str(h) for h in (getattr(report, "highlights", None) or [])],
        "review_chain": [str(c) for c in (getattr(report, "review_chain", None) or [])],
        "skills_detail": skills,
        "graph": {"nodes": [str(n) for n in (graph.get("nodes") or [])],
                  "edges": [[str(a), str(b)] for a, b in (graph.get("edges") or [])]},
    }


def make_item(lesson: dict, topic: str, mistake: dict = None) -> dict:
    """拼出一个「错题形状」的 dict，喂给 practice.py 出题（没有错题也能出题）。"""
    mk = mistake or {}
    lesson = lesson or {}
    highlights = [h for h in (lesson.get("highlights") or []) if _same(topic, h) or topic in str(h)]
    sk = _skill_of(lesson, topic)
    return {
        "topic": topic,
        "missing": mk.get("missing") or f"「{topic}」是怎么来的、什么时候用？",
        "reason": mk.get("reason") or "课后想再确认一下这个知识点",
        "known": mk.get("known") or (highlights[0] if highlights else ""),
        "step": mk.get("step") or "",
        "now": mk.get("now") or "",
        "micro_lesson": mk.get("micro_lesson") or (lesson.get("summary") or ""),
        "status": sk.get("status") or ("review" if mk else "ok"),
    }


def node_detail(lesson: dict, topic: str, mistakes: list = None) -> dict:
    """点开某个知识点要显示的东西：状态、老师怎么讲的、不懂时的讲解。

    同步返回；题目和解析另外走 questions_for()，因为要调 AI。
    """
    lesson = lesson or {}
    sk = _skill_of(lesson, topic)
    mk = _mistake_of(mistakes or [], topic)
    highlights = [str(h) for h in (lesson.get("highlights") or [])
                  if _same(topic, h) or _norm(topic) in _norm(h)]
    # 老师怎么讲的：优先用课程摘要里能对上这个知识点的部分
    taught = "\n".join(highlights) if highlights else (lesson.get("summary") or "")
    return {
        "topic": topic,
        "status": sk.get("status") or (STATUS_REVIEW if mk else STATUS_OK),
        "mastery": float(sk.get("mastery") or 0.0),
        "taught": taught,
        "missing": mk.get("missing") or "",
        "known": mk.get("known") or "",
        "step": mk.get("step") or "",
        "now": mk.get("now") or "",
        "micro_lesson": mk.get("micro_lesson") or "",
        "timecode": mk.get("timecode") or "",
        "has_mistake": bool(mk),
    }


def questions_for(lesson: dict, topic: str, mistakes: list = None, n: int = 2,
                  on_done=None, on_error=None) -> None:
    """后台出这个知识点的题，带解析。出好后 on_done(list[dict])。"""
    import threading

    def _run():
        try:
            from echo.backend import practice
            questions = practice.generate_sync(make_item(lesson, topic, _mistake_of(mistakes or [], topic)), n)
            if on_done:
                on_done(questions)
        except Exception as e:
            log.exception("知识点出题失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name="echo-mindmap-quiz").start()
