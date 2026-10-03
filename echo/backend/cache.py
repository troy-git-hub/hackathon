"""
Echo - 本机数据总管

给设置页用：看看攒了多少东西、以及一键清空。

清的是「攒下来的记录」——课程历史、错题本、知识地图记住的位置。
**不动**个人资料（名字/头像）、.env 里的 API key、界面设置：那些是「你设置的」，
不是攒出来的数据，清缓存不该顺手把它们抹掉。

课程/错题的路径优先问 store 要（它是那两个文件的权威，名字写死在别处早晚会对不上），
拿不到才按默认名在配置目录里找。
"""
import os

from echo.backend import layout, paths, store


def _data_files() -> list:
    """会被越攒越大的那几个文件。"""
    out = []
    for fn in (getattr(store, "_lessons_path", None), getattr(store, "_path", None)):
        try:
            if callable(fn):
                out.append(fn())
        except Exception:
            pass
    out.append(os.path.join(paths.config_dir(), "mindmap.json"))
    return list(dict.fromkeys(out))          # 去重，顺序不变


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def stats() -> dict:
    """当前占用。任何一项读不到都当 0，不让设置页因为一个坏文件打不开。"""
    try:
        lessons = len(store.list_lessons(limit=None))
    except Exception:
        lessons = 0
    try:
        mistakes = len(store.load())
    except Exception:
        mistakes = 0
    try:
        lay = layout.stats()
    except Exception:
        lay = {"lessons": 0, "nodes": 0, "bytes": 0}
    return {"lessons": lessons, "mistakes": mistakes, "layout": lay,
            "bytes": sum(_size(p) for p in _data_files())}


def size_text(n: int) -> str:
    """人看的体积。"""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def clear() -> dict:
    """清空。返回清掉了什么，给界面回显用。

    直接删文件：store 读不到文件就当空（load/_load_lessons 都吞 OSError），
    顺带把占的磁盘还回来。个人资料和设置不在这个名单里。
    """
    before = stats()
    for p in _data_files():
        try:
            os.remove(p)
        except OSError:
            pass
    layout.clear()
    return before
