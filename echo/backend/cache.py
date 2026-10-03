"""
Echo - 本机数据总管

给设置页用：看看攒了多少东西、以及一键清空。

清的是「攒下来的记录」——课程历史、错题本、知识地图记住的位置。
**不动**个人资料（名字/头像）、.env 里的 API key、界面设置：那些是「你设置的」，
不是攒出来的数据，清缓存不该顺手把它们抹掉。

课程/错题走 store 的公开清理接口，不自己拼路径去删；只有「看占用」时问 store 要一下
文件路径（那两个文件归它管，名字写死在别处早晚会对不上）。
"""
import os

from echo.backend import layout, paths, store


def _file_paths() -> list:
    """算占用用的文件路径。优先问 store 要（它是课程/错题的权威），拿不到用默认名。"""
    out = []
    for fn, name in ((getattr(store, "_lessons_path", None), "lessons.json"),
                     (getattr(store, "_path", None), "review.json")):
        try:
            out.append(fn() if callable(fn) else os.path.join(paths.config_dir(), name))
        except Exception:
            out.append(os.path.join(paths.config_dir(), name))
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
            "bytes": sum(_size(p) for p in _file_paths())}


def is_empty(st: dict = None) -> bool:
    """有没有东西可清。看条数而不是字节数 —— 清空后文件还在（内容是个空数组），
    按字节判断会导致「明明清干净了按钮却还亮着」。"""
    st = stats() if st is None else st
    return not (st.get("lessons") or st.get("mistakes")
                or (st.get("layout") or {}).get("lessons"))


def size_text(n: int) -> str:
    """人看的体积。"""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def clear() -> dict:
    """清空，返回清空前的数量（给界面回显用）。

    课程和错题交给 store 清（删除逻辑留在真正管那两个文件的地方，持它自己那把锁）；
    地图位置是这边自己的，自己清。
    """
    before = stats()
    try:
        store.clear_all()
    except Exception:
        pass
    try:
        layout.clear()
    except Exception:
        pass
    return before
