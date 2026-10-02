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


def _write(items):
    p = _path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        pass


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
