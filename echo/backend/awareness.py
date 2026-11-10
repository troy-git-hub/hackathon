"""
Echo - 这节课的共享记忆

圈一下、掉队追问、听课答疑、挂边聊天、掉队补课，说的是同一节课。
以前各记各的：圈完得到的解释，到掉队页再问就跟没发生过一样。

这里只留一份短记，所有入口往里写、所有提示词从这里读。
新开一节课由引擎 reset() 清空，不跨课。
"""
import threading

from echo.backend import config

_lock = threading.Lock()
_items = []          # {"kind", "q", "a"}，旧 → 新
_MAX = 8
_CLIP = 180

_LABELS = {
    "board": ("课堂黑板", "lesson blackboard"),
    "circle": ("圈一下问 AI", "circle-to-ask"),
    "lost": ("掉队里追问", "lost-track follow-up"),
    "qa": ("听课答疑", "lesson Q&A"),
    "dock": ("挂边聊天", "dock chat"),
    "break": ("掉队补课", "catch-up"),
}


def _clip(text: str) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= _CLIP:
        return text
    return text[:_CLIP - 1] + "…"


def note(kind: str, question: str, answer: str):
    """记下一轮交流。问题或回答是空的就不记。"""
    q, a = _clip(question), _clip(answer)
    if not q and not a:
        return
    with _lock:
        _items.append({"kind": kind, "q": q, "a": a})
        del _items[:-_MAX]


def recent(limit: int = 6) -> list:
    with _lock:
        return list(_items[-limit:])


def clear():
    with _lock:
        _items.clear()


def block() -> str:
    """拼进 system prompt 的一段。这节课还没交流过就返回空串。"""
    with _lock:
        items = list(_items)
    if not items:
        return ""
    en = config.UI_LANG == "en"
    if en:
        head = (
            "\n## What already happened in this lesson\n"
            "The student and you already talked. Continue from this — don't act like "
            "it's the first time, and don't repeat an explanation you already gave. "
            "If they ask about the same spot again, build on the earlier answer.\n"
        )
    else:
        head = (
            "\n## 这节课已经发生过的交流\n"
            "下面是这节课里学生跟你说过的话，以及你已经答过的内容。接着这些往下说：\n"
            "不要装成第一次听说，不要把已经讲过的再讲一遍；"
            "如果学生现在问的和之前是同一处，就在上次的答案上往下补。\n"
        )
    lines = [head.rstrip("\n")]
    for it in items:
        zh, en_label = _LABELS.get(it["kind"], (it["kind"], it["kind"]))
        label = en_label if en else zh
        if en:
            lines.append(f"- [{label}] Student: {it['q']} | You said: {it['a']}")
        else:
            lines.append(f"- [{label}] 学生：{it['q']} ｜ 你当时说：{it['a']}")
    return "\n".join(lines) + "\n"
