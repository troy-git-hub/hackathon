"""
Echo - 错题本 / 复习记录持久化

每节课结束时，把「我掉队了」定位到的断点（错题）存成 JSON，
重启后还能在「错题复习」主页里回看、标记掌握。跨会话保存上下文。

存储位置：config_dir()/review.json（打包后 %APPDATA%\\Echo，开发时项目根目录）。
"""
import json
import os
import threading
import time

from echo.backend import paths

_LOCK = threading.Lock()


def _path() -> str:
    return os.path.join(paths.config_dir(), "review.json")


def load() -> list:
    """读取所有错题记录（list[dict]）。文件不存在或损坏时返回 []。"""
    with _LOCK:
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []


def _write_json(path, items):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def _write(items):
    _write_json(_path(), items)


def add(items):
    """追加/合并一批错题：同一 topic 覆盖更新内容，但保留「已掌握」标记（不复活老错题）。"""
    if not items:
        return
    cur = load()
    by_topic = {it.get("topic"): it for it in cur}
    for it in items:
        topic = (it.get("topic") or "").strip()
        if not topic:
            continue
        it["topic"] = topic
        it.setdefault("time", time.time())
        prev = by_topic.get(topic)
        if prev:
            it["reviewed"] = prev.get("reviewed", False)
            if prev.get("reviewed_at"):
                it["reviewed_at"] = prev["reviewed_at"]
            it["time"] = prev.get("time", it["time"])
        by_topic[topic] = it
    _write(list(by_topic.values()))


def mark_reviewed(topic: str):
    """把某个错题标记为已复习（掌握）。"""
    cur = load()
    changed = False
    for it in cur:
        if it.get("topic") == topic and not it.get("reviewed"):
            it["reviewed"] = True
            it["reviewed_at"] = time.time()
            changed = True
    if changed:
        _write(cur)


def from_breakpoints(engine) -> list:
    """把引擎里的断点（掉队点）转成错题记录。engine 可为 None。"""
    try:
        bps = list(engine.breakpoints) if engine is not None else []
    except Exception:
        bps = []
    out = []
    for bp in bps:
        topic = (bp.concept or "").strip()
        if not topic:
            continue
        out.append({
            "topic": topic,
            "timecode": bp.breakpoint_tc,
            "missing": bp.missing,
            "reason": bp.reason,
            "micro_lesson": bp.micro_lesson,
            "known": bp.known,
            "step": bp.step,
            "now": bp.now,
            "status": "fixed" if bp.fixed else "review",
            "reviewed": False,
        })
    return out


def _lessons_path() -> str:
    return os.path.join(paths.config_dir(), "lessons.json")


def _load_lessons() -> list:
    """读取所有课程历史（list[dict]）。文件不存在或损坏时返回 []。"""
    with _LOCK:
        try:
            with open(_lessons_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []


def _skill_status(sk) -> str:
    """统一吃 (name, mastery, status) 元组 / dict / 对象三种形式，取出 status。"""
    if isinstance(sk, dict):
        return sk.get("status", "ok")
    if isinstance(sk, (list, tuple)):
        return sk[2] if len(sk) > 2 else "ok"
    return getattr(sk, "status", "ok")


def _skill_fields(sk) -> dict:
    """统一吃 (name, mastery, status) 元组 / dict / 对象三种形式，取出三个字段。"""
    if isinstance(sk, dict):
        name, mastery, status = sk.get("name", ""), sk.get("mastery", 0.0), sk.get("status", "ok")
    elif isinstance(sk, (list, tuple)):
        name = sk[0] if len(sk) > 0 else ""
        mastery = sk[1] if len(sk) > 1 else 0.0
        status = sk[2] if len(sk) > 2 else "ok"
    else:
        name = getattr(sk, "name", "")
        mastery = getattr(sk, "mastery", 0.0)
        status = getattr(sk, "status", "ok")
    try:
        mastery = float(mastery)
    except (TypeError, ValueError):
        mastery = 0.0
    return {"name": str(name), "mastery": mastery, "status": str(status)}


def save_lesson(title: str, skills: list, review_chain: list, suggestion: str = "",
                summary: str = "", highlights: list = None,
                duration: float = 0.0, line_count: int = 0, char_count: int = 0,
                graph: dict = None) -> float:
    """存一节课的回响摘要，返回这条记录的 time 时间戳（给详情页定位用）。
    skills 支持元组 / dict / 对象列表。最多保留最近 50 条。

    graph 是可选的课前置关系（{"nodes": [...], "edges": [[前, 后], ...]}），
    给课后「知识地图」用；不传也能画，mindmap 会按复习链和讲课顺序推导。
    """
    skills = skills or []
    total = len(skills)
    ok = sum(1 for sk in skills if _skill_status(sk) == "ok")
    now = time.time()
    record = {
        "time": now,
        "title": title or "未命名课程",
        "date": time.strftime("%Y-%m-%d", time.localtime(now)),
        "total": total,
        "ok": ok,
        "review": total - ok,
        "review_chain": list(review_chain or []),
        "suggestion": suggestion or "",
        "summary": summary or "",
        "highlights": [str(x) for x in (highlights or [])],
        "duration": duration,
        "line_count": line_count,
        "char_count": char_count,
        "skills_detail": [_skill_fields(sk) for sk in skills],
    }
    if graph and graph.get("nodes"):
        record["graph"] = {"nodes": [str(n) for n in graph.get("nodes") or []],
                           "edges": [[str(a), str(b)] for a, b in (graph.get("edges") or [])]}
    cur = _load_lessons()
    cur.append(record)
    _write_json(_lessons_path(), cur[-50:])
    return now


def get_lesson(ts: float) -> dict:
    """按 time 时间戳取一条课程归档，找不到返回 {}。"""
    for it in _load_lessons():
        if abs(it.get("time", 0) - ts) < 0.001:
            return it
    return {}


def list_lessons(limit: int = 5) -> list:
    """最近的课，新 → 旧。"""
    cur = _load_lessons()
    cur.sort(key=lambda it: it.get("time", 0), reverse=True)
    return cur[:limit]


def stats() -> dict:
    """课程 + 错题复习情况汇总。"""
    lessons = _load_lessons()
    reviews = load()
    pending = sum(1 for it in reviews if not it.get("reviewed"))
    mastered = sum(1 for it in reviews if it.get("reviewed"))
    return {"lessons": len(lessons), "pending": pending, "mastered": mastered}
