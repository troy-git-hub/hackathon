"""
Echo - 掌握验证：「讲给 Echo 听」

Echo 判断的不是「你有没有答对一道题」，而是「你能不能想起来、说清楚，
并在一个新的地方用出来」。所以这里没有选项按钮，是一段小对话：

  1. 「讲给 Echo 听」—— 学生用自己的话把这个知识点讲一遍（自由回答）
  2. 「换个场景试试」—— 换一个他没见过的场景，看能不能用出来（迁移）

AI 根据这两次回答判断 清楚 / 模糊 / 未理解，指出仍然没说到的关键点，
给一句像同桌那样的反馈，并定下次复习时间。

两个刻意的设计：
  · 学生觉得判得不准可以自己改 —— 一次 AI 判定不该给人贴标签，
    改完仍然按他的选择排下次复习。
  · 一次聊一组知识点，优先挑**共享同一个根源概念**的那几个。Echo 有时间轴和
    前置关系，几个错题都通向同一个根源时，一次问在根源上比挨个问省时间，
    也更容易看出真正卡住的地方 —— 这是刷题软件做不到的。

离线 / 没配 key 时不做假判断：照样给出两道题（用错题自己存的字段拼），
但判断权交回学生，界面上退回三档自选。
"""
import logging
import re

from echo.backend import config, store
from echo.backend.llm import LLM

log = logging.getLogger("echo.recall")

# AI 的判断 → 复习调度的三档
VERDICT_TO_GRADE = {"clear": store.CLEAR, "fuzzy": store.FUZZY, "unclear": store.AGAIN}
VERDICT_LABEL = {"clear": "清楚", "fuzzy": "模糊", "unclear": "没理解"}
# 界面上可以手动改成的档位
MANUAL_CHOICES = (("clear", "清楚"), ("fuzzy", "模糊"), ("unclear", "没理解"))


RECALL_PLAN_SYSTEM = """你是 Echo，一个陪学生听网课的 AI 学习副驾驶。学生来复习他之前掉过队的知识点。

请设计一段「聊天式」的掌握验证 —— 不是考试，是同桌之间互相问。要看的不是他记不记得
标准答案，而是他能不能**用自己的话讲出来**，再**换一个新的场景用一次**。

出 2 个问题：
1. 讲给 Echo 听：让他用自己的话解释这个知识点在说什么。不要问定义式的「XX 是什么」，
   要像「你讲给我听听」。
2. 换个场景试试：给一个他没见过的、生活中的或别的领域的场景，看他能不能用出来。

要求：
- 扣住他当初掉队的那一步（missing），不要泛泛地问
- 口语，像聊天。不要「请简述」「试论述」这种考试腔
- 第二题必须是**迁移** —— 换一个情境，不是换个数字重问一遍
- 给了「共同根源概念」时，两题都围绕这个根源问：他几个知识点都卡在同一个地方，
  先确认根源
- opening 像老朋友接着昨天的话题，1~2 句

只输出 JSON：
{
  "opening": "开场白",
  "questions": [
    {"topic": "考的知识点名", "question": "问题", "kind": "recall"},
    {"topic": "考的知识点名", "question": "问题", "kind": "transfer"}
  ]
}"""

RECALL_PLAN_USER = """他还记得的错题（每个都有当初掉队的那一步）：
{items}

共同根源概念：{root}

这个学生的情况：{persona}

请出这两个问题。"""


RECALL_JUDGE_SYSTEM = """你是 Echo。学生刚才用自己的话讲了知识点，并把其中一个用到了新场景里。
现在判断他到底掌握到什么程度。

判断标准（重点）：
- clear（清楚）：能用自己的话说清楚，而且在新场景里用对了。不要求用词标准，
  用大白话讲对就算
- fuzzy（模糊）：方向对但说不完整、只会背结论说不清为什么、或者迁移题没做出来
- unclear（没理解）：说错了，或只说出表面现象没抓住实质

不要因为用词不严谨就判低 —— 学生在用自己的话重述，这是好事。

对每个知识点给出：
- verdict：clear / fuzzy / unclear
- missing：他这次**仍然**没说到的关键点，一句话；没有就留空字符串
- feedback：对他说的一句话，像同桌那样。要具体（「你把极限说成『一直缩小』，
  方向对，但漏了『无限逼近』这层」），不要空泛的「很棒」「继续加油」
- 另外给一句 review：针对这次暴露的问题，下次该从哪儿入手

只输出 JSON：
{
  "results": [
    {"topic": "...", "verdict": "clear|fuzzy|unclear", "missing": "...", "feedback": "..."}
  ],
  "review": "一句话复习建议"
}"""

RECALL_JUDGE_USER = """这一轮在聊的知识点：
{items}

对话记录：
{dialogue}

这个学生的情况：{persona}

请判断他每个知识点的掌握程度。"""


def _system(name: str, **fmt) -> str:
    """取本模块的 system 提示词；英文界面下追加输出语言指令。

    没走 prompts.system()：那段逻辑是 prompts.py 的，这个模块自带提示词，
    直接复用 ENGLISH_OUTPUT 就够了，省得两个文件互相 import 绕圈。
    """
    from echo.backend import prompts
    text = globals()[name]
    if fmt:
        text = text.format(**fmt)
    if config.UI_LANG == "en":
        text += prompts.ENGLISH_OUTPUT
    return text


def _roots(item: dict) -> list:
    """这个知识点所属的复习链（掉队点 → … → 根源概念）。"""
    return [c for c in (item.get("review_chain") or []) if c]


def pick(items: list, n: int = 3) -> tuple:
    """挑这一轮聊哪几个，外加它们的共同根源概念（没有就是空串）。

    优先挑共享同一个根源的：一次问在根源上比挨个问省时间，也更容易看出
    真正卡住的地方。找不到共同点就按传进来的顺序取前 n 个（调用方已按
    「最该先看的排前面」排过）。
    """
    items = list(items or [])
    if len(items) <= 1:
        return items[:n], ""

    chains = [(it, _roots(it)) for it in items]
    counts = {}
    for _it, chain in chains:
        for c in set(chain):
            counts[c] = counts.get(c, 0) + 1
    shared = [c for c, k in counts.items() if k >= 2]
    if shared:
        # 链尾最靠后的那个最接近根源；并列时取被共享次数最多的
        def rank(c):
            deepest = max((chain.index(c) for _i, chain in chains if c in chain), default=-1)
            return (deepest, counts.get(c, 0))
        root = max(shared, key=rank)
        group = [it for it, chain in chains if root in chain][:n]
        if len(group) >= 2:
            return group, root
    return items[:n], ""


def _fallback_plan(items: list, root: str) -> dict:
    """没 key / 调用失败时的兜底：用错题自己存的字段拼两道题。

    判断权交回学生（界面上退回三档自选），这里不假装能判。
    """
    first = items[0] if items else {}
    topic = root or first.get("topic") or "这个知识点"
    missing = first.get("missing") or f"「{topic}」是怎么来的、什么时候用？"
    known = first.get("known") or ""
    opening = f"昨天你在「{topic}」这里掉过队。先不做题，你讲给我听听。"
    questions = [{
        "topic": topic,
        "question": f"{missing}" + (f"（你已经知道：{known}）" if known else ""),
        "kind": "recall",
    }]
    questions.append({
        "topic": topic,
        # 不要在这里写「换个场景试试：」—— 界面上会加这个标签，写了就重复两遍
        "question": "如果这道题换成一个完全不同的情境（比如换成生活里的例子），"
                    "你会怎么把刚才那套想法用上去？",
        "kind": "transfer",
    })
    return {"opening": opening, "questions": questions, "root": root, "offline": True}


def plan(items: list, root: str = "", llm=None, use_llm: bool = True) -> dict:
    """出这一轮的两道题。永远返回可用结果（最差走兜底）。"""
    items = [it for it in (items or []) if it.get("topic")]
    if not items:
        return {"opening": "", "questions": [], "root": "", "offline": True}
    if not root:
        _chosen, root = pick(items)

    if llm is None and use_llm and not config.OFFLINE and config.DEEPSEEK_API_KEY:
        try:
            llm = LLM()
        except Exception as e:
            log.warning("掌握验证取不到 LLM，改用兜底题: %s", e)
    if llm is None:
        return _fallback_plan(items, root)

    described = "\n".join(
        f"- {it.get('topic')}：{it.get('missing') or '（没说清当时卡在哪）'}"
        f"{'；已掌握的前置：' + it['known'] if it.get('known') else ''}"
        for it in items)
    try:
        data = llm.json(_system("RECALL_PLAN_SYSTEM"),
                        RECALL_PLAN_USER.format(items=described,
                                                root=root or "（没有共同的，各自问）",
                                                persona=_persona_hint()),
                        temperature=0.7, max_tokens=700)
    except Exception as e:
        log.warning("掌握验证出题失败，改用兜底题: %s", e)
        return _fallback_plan(items, root)

    questions = []
    for q in (data.get("questions") or []):
        if not isinstance(q, dict):
            continue
        text = str(q.get("question") or "").strip()
        if not text:
            continue
        # 界面会给每道题加「讲给 Echo 听 / 换个场景试试」的标签。模型要是自己在题干里
        # 也带了这个前缀，就会显示两遍 —— 这里统一剥掉。
        text = re.sub(r"^(讲给\s*Echo\s*听|换个场景试试|讲一遍)\s*[：:]\s*", "", text)
        questions.append({"topic": str(q.get("topic") or root or items[0].get("topic") or "").strip(),
                          "question": text,
                          "kind": str(q.get("kind") or "recall")})
    if not questions:
        return _fallback_plan(items, root)
    return {"opening": str(data.get("opening") or "").strip(), "questions": questions[:2],
            "root": root, "offline": False}


def _dialogue_text(answers: list) -> str:
    lines = []
    for i, a in enumerate(answers or [], 1):
        lines.append(f"老师问：{a.get('question', '')}")
        lines.append(f"学生答：{a.get('answer', '')}")
    return "\n".join(lines)


def _persona_hint() -> str:
    """学生画像的一句话，喂给出题/判断的 prompt，让 AI 的语气跟着这个学生调整。

    没有足够数据（新学生、还没复习过几次）时给个中性占位，不留空——
    提示词里的 {persona} 槽位总要有内容，免得输出「这个学生的情况：」后面是空的。
    """
    try:
        from echo.backend import persona
        hint = persona.tone_hint()
    except Exception as e:
        log.warning("取学生画像失败: %s", e)
        hint = ""
    return hint or "还没有足够的复习记录，按正常节奏讲就好"


def judge(items: list, answers: list, llm=None, use_llm: bool = True) -> dict:
    """根据学生的两次回答判断掌握程度。

    返回 {"results": [{"topic", "verdict", "missing", "feedback"}], "review", "offline"}。
    offline=True 表示没判（没 key / 调用失败），界面应退回让学生自己选。
    """
    items = [it for it in (items or []) if it.get("topic")]
    if not items or not answers:
        return {"results": [], "review": "", "offline": True}

    if llm is None and use_llm and not config.OFFLINE and config.DEEPSEEK_API_KEY:
        try:
            llm = LLM()
        except Exception as e:
            log.warning("掌握验证取不到 LLM: %s", e)
    if llm is None:
        return {"results": [], "review": "", "offline": True}

    described = "\n".join(f"- {it.get('topic')}（当初缺的是：{it.get('missing') or '未知'}）"
                          for it in items)
    try:
        data = llm.json(_system("RECALL_JUDGE_SYSTEM"),
                        RECALL_JUDGE_USER.format(items=described, dialogue=_dialogue_text(answers),
                                                 persona=_persona_hint()),
                        temperature=0.3, max_tokens=900)
    except Exception as e:
        log.warning("掌握验证判断失败: %s", e)
        return {"results": [], "review": "", "offline": True}

    known = {it.get("topic"): it for it in items}
    results = []
    for r in (data.get("results") or []):
        if not isinstance(r, dict):
            continue
        topic = str(r.get("topic") or "").strip()
        verdict = str(r.get("verdict") or "").strip().lower()
        if verdict not in VERDICT_TO_GRADE:
            continue
        # 模型偶尔会把知识点名写飘（加了书名号、缩写了）。对不上就按顺序落到没判过的那个，
        # 否则一条结果会因为名字拼不上而丢掉。
        if topic not in known:
            rest = [t for t in known if t not in {x["topic"] for x in results}]
            if not rest:
                continue
            topic = rest[0]
        results.append({"topic": topic, "verdict": verdict,
                        "missing": str(r.get("missing") or "").strip(),
                        "feedback": str(r.get("feedback") or "").strip()})
    if not results:
        return {"results": [], "review": "", "offline": True}
    return {"results": results, "review": str(data.get("review") or "").strip(), "offline": False}


def apply_results(results: list, now: float = None) -> dict:
    """把判断写进复习调度，返回 {topic: 下次复习时间戳}。

    学生手动改过的判断也走这里 —— 界面上的「判断不准确」改完调这个函数，
    调度只认最终结论，不区分是 AI 判的还是人判的。
    """
    if now is None:
        import time
        now = time.time()
    out = {}
    for r in results or []:
        grade = VERDICT_TO_GRADE.get(r.get("verdict"))
        if not grade:
            continue
        rec = store.grade(r["topic"], grade, now)
        if rec:
            out[r["topic"]] = rec.get("due")
    return out


def _in_thread(fn, on_done, on_error, name):
    import threading

    def _run():
        try:
            result = fn()
            if on_done:
                on_done(result)
        except Exception as e:
            log.exception("掌握验证后台任务失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name=name).start()


def plan_async(items: list, root: str = "", on_done=None, on_error=None) -> None:
    """后台出题。成功时 on_done({opening, questions, root})。"""
    _in_thread(lambda: plan(items, root), on_done, on_error, "echo-recall-plan")


def judge_async(items: list, answers: list, on_done=None, on_error=None) -> None:
    """后台判断。成功时 on_done({results, review, offline})。"""
    _in_thread(lambda: judge(items, answers), on_done, on_error, "echo-recall-judge")
