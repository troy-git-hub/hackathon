"""
Echo - 知识地图的位置记忆

学生把知识地图里的节点拖到别处之后，下次打开同一节课还是他摆的那个样子，
不用每次重新自动排布。

**存得很省**：记的是「相对自动排布的偏移」，而且只记真的挪动过的节点。
自动排布本身是确定的、随时能重算，把每个节点的绝对坐标都存一遍纯属浪费
—— 一张图六七个节点，学生通常只动了一两个；没动过的节点连键都不出现。
偏移取整到像素，一个节点十几个字节。

这个文件是纯缓存：删掉不丢任何学习记录，只是地图回到默认排布。
（设置里的「清除所有缓存」会一起清掉它。）
"""
import json
import os
import threading

from echo.backend import paths

_LOCK = threading.Lock()
MAX_LESSONS = 60          # 最多记这么多节课，超了丢最早的（按写入先后）


def _path() -> str:
    return os.path.join(paths.config_dir(), "mindmap.json")


def _load() -> dict:
    """读全部记录：{课次键: {知识点: [dx, dy]}}。文件不在或坏了都返回 {}。"""
    with _LOCK:
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


def _write(data: dict):
    path = _path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass                      # 位置记不下来不是致命问题，地图下次回到自动排布而已


def get(key: str) -> dict:
    """取某节课记下的偏移：{知识点: (dx, dy)}。没有记录返回 {}（= 用自动排布）。"""
    if not key:
        return {}
    raw = _load().get(key) or {}
    out = {}
    for topic, d in raw.items():
        try:
            out[str(topic)] = (float(d[0]), float(d[1]))
        except (TypeError, ValueError, IndexError):
            continue              # 手改坏了的条目跳过，不让它把整张图带崩
    return out


def save(key: str, offsets: dict):
    """记下一节课的位置。offsets 传空字典 = 这节课回到自动排布（把记录删掉）。"""
    if not key:
        return
    data = _load()
    # 先摘掉旧的那条再塞回去：这样它在字典里是最新的，
    # 下面按插入顺序裁掉最老的时，刚动过的课不会被误删
    data.pop(key, None)
    if offsets:
        data[key] = {str(t): [int(round(v[0])), int(round(v[1]))]
                     for t, v in offsets.items()
                     if len(v) >= 2 and (int(round(v[0])) or int(round(v[1])))}
    if data and len(data) > MAX_LESSONS:
        for old in list(data)[:-MAX_LESSONS]:
            data.pop(old, None)
    _write(data)


def clear() -> int:
    """清掉所有位置记录，返回删掉的课次数。"""
    data = _load()
    n = len(data)
    if n:
        _write({})
    return n


def stats() -> dict:
    """给设置页显示用：记了几节课、几个节点、文件多大。"""
    data = _load()
    try:
        size = os.path.getsize(_path())
    except OSError:
        size = 0
    return {"lessons": len(data),
            "nodes": sum(len(v or {}) for v in data.values()),
            "bytes": size}
