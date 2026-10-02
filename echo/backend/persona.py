"""
Echo - 学生画像（根据复习表现生成，不是 AI 猜的）

从错题本的客观数据里算：容易卡在哪一类反馈上（经常「还是没懂」还是一遍就「清楚」）、
整体状态是在进步还是吃力。算出来的 tone_hint 会喂给「讲给 Echo 听」的提示词，
让 AI 说话的方式跟着这个学生调整——容易没听懂的学生，解释要更慢更具体；
吸收快的学生，不用啰嗦复述。

存在 profile.json 的 persona 字段里，跟资料一起落盘、一起受 .gitignore 保护。
资料页有「重置」按钮，清空这个字段；下次用到时会用最新数据重新算一份。
"""
from echo.backend import profile, store

STYLE_NEEDS_EXAMPLES = "needs_examples"
STYLE_CONCISE = "concise"
STYLE_STEADY = "steady"

TREND_IMPROVING = "improving"
TREND_STRUGGLING = "struggling"
TREND_STEADY = "steady"

_STYLE_LABEL = {
    STYLE_NEEDS_EXAMPLES: "容易没听懂，适合多举例子",
    STYLE_CONCISE: "吸收得快，说重点就行",
    STYLE_STEADY: "按正常节奏讲解",
}
_TREND_LABEL = {
    TREND_IMPROVING: "最近在进步",
    TREND_STRUGGLING: "最近比较吃力",
    TREND_STEADY: "状态平稳",
}


def compute() -> dict:
    """从错题本的客观数据里算一份画像。没有复习历史时给中性的默认值。

    只看 review_count > 0（真的被问过、判过的）——刚记下来还没确认过的
    错题不该拉低画像的准头。
    """
    graded = [it for it in store.load() if it.get("review_count")]
    n = len(graded)
    if n == 0:
        return {"style": STYLE_STEADY, "trend": TREND_STEADY,
                "again_rate": 0.0, "clear_rate": 0.0, "sample": 0}

    again = sum(1 for it in graded if it.get("last_result") == store.AGAIN)
    clear = sum(1 for it in graded if it.get("last_result") == store.CLEAR)
    again_rate = again / n
    clear_rate = clear / n
    avg_level = sum(int(it.get("level") or 0) for it in graded) / n

    if again_rate >= 0.4:
        style = STYLE_NEEDS_EXAMPLES
    elif avg_level >= 1.5 and again_rate <= 0.15:
        style = STYLE_CONCISE
    else:
        style = STYLE_STEADY

    if clear_rate >= 0.6:
        trend = TREND_IMPROVING
    elif again_rate >= 0.5:
        trend = TREND_STRUGGLING
    else:
        trend = TREND_STEADY

    return {"style": style, "trend": trend, "again_rate": round(again_rate, 2),
            "clear_rate": round(clear_rate, 2), "sample": n}


def get() -> dict:
    """读画像：profile.json 里存过就直接用，没存过就现算一份（不自动落盘）。"""
    data = profile.load().get("persona")
    return data if isinstance(data, dict) and data else compute()


def save(data: dict = None) -> dict:
    """把画像存进 profile.json。不传 data 就重新算一份当前的存下去。"""
    data = compute() if data is None else data
    profile.save({"persona": data})
    return data


def reset():
    """清掉画像。下次调 get() 会用最新的错题本数据重新算，不是恢复成某个旧值。"""
    profile.save({"persona": {}})


def describe(data: dict = None) -> str:
    """资料页里显示的一句话。"""
    data = get() if data is None else data
    if not data.get("sample"):
        return "还没有复习记录，多做几次「讲给 Echo 听」就会慢慢看出你的画像。"
    return f"{_STYLE_LABEL.get(data.get('style'), '')} · {_TREND_LABEL.get(data.get('trend'), '')}"


def tone_hint(data: dict = None) -> str:
    """喂给 AI 的一句话，让它说话的方式跟着这个学生调整。

    没有足够数据时返回空串——system prompt 不需要为了「还没有画像」专门写一句话，
    调用方（recall.py）判断空串就不把这行塞进 prompt。
    """
    data = get() if data is None else data
    if not data.get("sample"):
        return ""
    bits = []
    if data.get("style") == STYLE_NEEDS_EXAMPLES:
        bits.append("这个学生容易没听懂，解释时要放慢、多举一个具体例子再问他")
    elif data.get("style") == STYLE_CONCISE:
        bits.append("这个学生吸收得快，不用啰嗦复述，说重点就行")
    if data.get("trend") == TREND_STRUGGLING:
        bits.append("最近连续几次都没想起来，语气要耐心，别让他觉得自己很差")
    elif data.get("trend") == TREND_IMPROVING:
        bits.append("最近进步明显，可以在反馈里肯定一下")
    return "；".join(bits)
