"""
Echo - 学生画像（根据复习表现生成，不是 AI 猜的）

从错题本的客观数据里算：容易卡在哪一类反馈上（经常「还是没懂」还是一遍就「清楚」）、
整体状态是在进步还是吃力。算出来的 tone_hint 会喂给「讲给 Echo 听」的提示词，
让 AI 说话的方式跟着这个学生调整——容易没听懂的学生，解释要更慢更具体；
吸收快的学生，不用啰嗦复述。

存在 profile.json 的 persona 字段里，跟资料一起落盘、一起受 .gitignore 保护。

**多久重算一次**：画像不是每答一道题就变，那样只会来回抖。攒够了新数据才重算——
又上完 LESSON_STEP 节课，或者又判过 REVIEW_STEP 次复习，谁先到算谁。
上次是在什么进度上算的记在 profile.json 的 persona_baseline_* 里（见 _baseline）。

**两个出口别混**：describe() 是给学生看的一段话，tone_hint() 是喂给模型的祈使句。
两者的读者完全不同，所以是两套独立的字符串——给学生看的可以长、可以有温度，
喂给模型的那份只写「你该怎么说话」。
"""
import time

from echo.backend import profile, store

# 攒够这些新数据就重算一次。定得太小画像会随每道题抖，太大又跟不上学生的变化。
LESSON_STEP = 3        # 又上完几节课
REVIEW_STEP = 8        # 又判过几次复习（按「判过的次数」算，不是「复习过的条目数」）

STYLE_NEEDS_EXAMPLES = "needs_examples"
STYLE_CONCISE = "concise"
STYLE_STEADY = "steady"

TREND_IMPROVING = "improving"
TREND_STRUGGLING = "struggling"
TREND_STEADY = "steady"

def _t(zh: str, en: str) -> str:
    """按界面语言二选一。

    这里用 config.UI_LANG，而不是 echo.i18n 的 tr()：tr() 依赖 QSettings，
    会把 PyQt5 拖进后端的导入链，踩 main.py 里记的 ctranslate2/PyQt5 加载顺序坑。
    prompts.py 读同一个开关，两边一致。

    注意 persona 这一块是**静态界面文案**（阈值算出来之后拼的固定句子），
    不是模型生成的内容 —— 所以该翻译；模型生成的那部分走 prompts.system()
    的 ENGLISH_OUTPUT，是另一套机制。
    """
    from echo.backend import config
    return en if config.UI_LANG == "en" else zh


_STYLE_LABEL = {
    STYLE_NEEDS_EXAMPLES: lambda: _t("容易没听懂，适合多举例子",
                                     "benefits from more examples"),
    STYLE_CONCISE: lambda: _t("吸收得快，说重点就行", "picks things up quickly"),
    STYLE_STEADY: lambda: _t("按正常节奏讲解", "steady pace works well"),
}
_TREND_LABEL = {
    TREND_IMPROVING: lambda: _t("最近在进步", "improving lately"),
    TREND_STRUGGLING: lambda: _t("最近比较吃力", "struggling lately"),
    TREND_STEADY: lambda: _t("状态平稳", "steady"),
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


def _progress() -> dict:
    """现在的进度：上过几节课、判过几次复习。

    「判过几次」不能拿 stats()["mastered"] —— 那是「复习过的条目数」，同一个
    知识点练三遍只算一次，攒不到触发线。得把每条自己的 review_count 加起来。
    """
    try:
        lessons = int(store.stats().get("lessons") or 0)
    except Exception:
        lessons = 0
    try:
        reviews = sum(int(it.get("review_count") or 0) for it in store.load())
    except Exception:
        reviews = 0
    return {"lessons": lessons, "reviews": reviews}


def _baseline() -> dict:
    """上次重算时的进度。没记过、或记坏了，都当全 0。"""
    d = profile.load()
    out = {}
    for key, name in (("lessons", "persona_baseline_lessons"),
                      ("reviews", "persona_baseline_reviews")):
        try:
            out[key] = int(d.get(name) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    return out


def needs_refresh() -> bool:
    """攒够新数据了没。两个维度谁先到算谁。"""
    now, was = _progress(), _baseline()
    return (now["lessons"] - was["lessons"] >= LESSON_STEP
            or now["reviews"] - was["reviews"] >= REVIEW_STEP)


def refresh() -> dict:
    """重算 + 落盘，并记下这次是在什么进度上算的。不管攒没攒够都算。"""
    data = compute()
    now = _progress()
    profile.save({"persona": data,
                  "persona_baseline_lessons": now["lessons"],
                  "persona_baseline_reviews": now["reviews"],
                  "persona_updated_at": time.time()})
    return data


def maybe_refresh():
    """攒够了才重算。重算了返回新画像；没重算返回 None —— 调用方据此决定
    要不要跟学生说一声「我更新了对你了解」。"""
    if not needs_refresh():
        return None
    return refresh()


def updated_at() -> float:
    """上次重算的时间戳（0 = 还没重算过）。"""
    try:
        return float(profile.load().get("persona_updated_at") or 0)
    except (TypeError, ValueError):
        return 0


def save(data: dict = None) -> dict:
    """把画像存进 profile.json。不传 data 就重新算一份当前的存下去。"""
    data = compute() if data is None else data
    profile.save({"persona": data})
    return data


def reset():
    """清掉画像，并把水位线挪到当前进度。

    水位线必须跟着挪：只清画像的话，学生一点重置，下次 maybe_refresh() 就发现
    「攒够了」，立刻重算一遍盖回来 —— 刚点完重置就弹「画像已更新」，很莫名其妙。

    重置后显示的内容（get() 现算）跟重置前是一样的，这是对的：画像本来就是从
    复习记录推出来的，记录没变，推出来的东西自然一样。真要清干净的是学习记录，
    那走「设置 → 清除所有缓存」。
    """
    now = _progress()
    profile.save({"persona": {},
                  "persona_baseline_lessons": now["lessons"],
                  "persona_baseline_reviews": now["reviews"],
                  # 归零而不是写 now()：重置之后本机确实没有「已算好的画像」，
                  # 资料页据此显示「实时计算」而不是骗人的「刚刚更新」
                  "persona_updated_at": 0})


def headline(data: dict = None) -> str:
    """画像的短标签，当资料页那一块的小标题用。长解释在 describe()。"""
    data = get() if data is None else data
    if not data.get("sample"):
        return _t("还没攒够记录", "not enough data yet")
    style = _STYLE_LABEL.get(data.get("style"))
    trend = _TREND_LABEL.get(data.get("trend"))
    return " · ".join(f() for f in (style, trend) if f)


def describe(data: dict = None) -> str:
    """资料页里显示的一段话 —— 给学生看的「我理解到的你」。

    读者跟 tone_hint() 完全不同，所以是两套独立的字符串：这一份要让学生看懂
    「记录没白记、而且跟我后面要学的东西有关」，所以给依据（看了多少条）、
    给结论（我发现了什么）、给接下来（我会怎么配合你）。喂模型那份只写祈使句，
    不写这些解释。
    """
    data = get() if data is None else data
    n = int(data.get("sample") or 0)
    if not n:
        return _t("还没有复习记录。多做几次「讲给 Echo 听」，我就慢慢知道该怎么给你讲了。",
                  "No review record yet. A few rounds of “Talk it through” and I'll start "
                  "to know how to explain things in a way that works for you.")

    again = int(round(float(data.get("again_rate") or 0) * n))
    clear = int(round(float(data.get("clear_rate") or 0) * n))
    style, trend = data.get("style"), data.get("trend")

    parts = [_t(f"从你复习过的 {n} 个知识点里，我看到的你：",
                f"From the {n} knowledge points you've reviewed, here's what I see:")]
    if style == STYLE_NEEDS_EXAMPLES:
        parts.append(_t(
            f"其中 {again} 次是「还是没懂」——不是你不行，是第一次讲的时候那一步被跳过去了。"
            "接下来我会把步子放慢，多举一个具体例子再往下走。",
            f"{again} of them ended in “still don't get it” — not because you can't, "
            "but because a step got skipped the first time. I'll slow down and work "
            "through a concrete example before moving on."))
    elif style == STYLE_CONCISE:
        parts.append(_t(
            "大部分一次就清楚，说明这些内容你接得住。"
            "那我就少铺垫，直接说重点，不浪费时间复述你已经会的。",
            "Most of them clicked right away, so these are within reach. I'll skip the "
            "warm-up and get to the point instead of repeating what you already know."))
    else:
        parts.append(_t("整体接得比较稳，偶尔卡一两次，这是正常范围。",
                        "Overall you keep up steadily, with the occasional stumble — "
                        "that's squarely normal."))
    if trend == TREND_IMPROVING:
        parts.append(_t(f"最近这批里有 {clear} 次一遍就想起来了，在往上走。",
                        f"{clear} of the recent ones you recalled straight away — "
                        "you're trending up."))
    elif trend == TREND_STRUGGLING:
        parts.append(_t(
            "最近连着几次都没想起来——先别急，我们把前面的地基补牢再往下学，"
            "不然越往后越吃力。",
            "A few in a row didn't come back to you — no rush. Let's shore up the "
            "foundations first, or it only gets harder further on."))
    parts.append(_t("这些只记在本机，跟着你的复习记录走，随时可以在下面重置。",
                    "This stays on this computer and follows your review record. "
                    "You can reset it below whenever you like."))
    # 中文句子以「。」收尾，直接接下一句；英文要在句号后留一个空格
    sep = _t("", " ")
    return sep.join(parts)


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
