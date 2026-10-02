"""
Echo - 出题

两种题：

  · 课中抽问（check-in）
    老师正在讲，学生可能在走神。Echo 拿「刚讲过的知识点」出一道 10 秒能答完的小题，
    看他还跟不跟得上。答错的记进错题本，课后复习时再见。
    没配 key / 连不上 AI 时退化成自评题（记得 / 有点模糊 / 没跟上），一样能发现问题。

  · 课后练习（lesson quiz）
    一节课结束，按这节课的要点出几道题趁热巩固。

错题记录的形状和 store.add() 约好的一致，能直接被「错题复习」页渲染。
"""
import logging
import threading

from echo.backend import config, prompts
from echo.backend.llm import LLM

log = logging.getLogger("echo.quiz")

RIGHT = "right"      # 答对 / 自评「记得」
WRONG = "wrong"      # 答错 / 自评「没跟上」
UNSURE = "unsure"    # 自评「有点模糊」—— 也算需要复习，但比完全不会轻

# 离线自评题的选项：选第一项算跟上，其余都记进错题本
SELF_OPTIONS = ["A. 记得，能说个大概", "B. 有点模糊", "C. 完全没跟上"]
SELF_GRADE = [RIGHT, UNSURE, WRONG]


def _clean_checkin(data, tc: str = "") -> dict:
    """把 LLM 返回的单道抽问题规范化；不适合出题时返回 {}。"""
    if not isinstance(data, dict):
        return {}
    question = str(data.get("question") or "").strip()
    if not question:
        return {}
    raw_options = data.get("options")
    options = [str(o).strip() for o in raw_options if str(o).strip()] \
        if isinstance(raw_options, list) else []
    answer = str(data.get("answer") or "").strip().upper()[:1]
    if options and answer not in [chr(ord("A") + i) for i in range(len(options))]:
        # LLM 给的答案对不上选项，宁可当自评题也不要判错学生
        log.warning("抽问题答案 %r 与选项不匹配，退化为自评题", answer)
        options, answer = [], ""
    return {
        "topic": str(data.get("topic") or "").strip(),
        "question": question,
        "options": options,
        "answer": answer,
        "explain": str(data.get("explain") or "").strip(),
        "tc": tc,
        "self_report": not options,
    }


def _self_checkin(topic: str, tc: str, why: str = "") -> dict:
    """自评兜底题：不判断对错，让学生自己说跟没跟上。"""
    topic = topic or "刚才讲的内容"
    question = f"老师刚讲了「{topic}」，你现在还记得它是怎么回事吗？"
    if why == "noconcept":
        question = "刚才这段课你跟上节奏了吗？"
    return {
        "topic": topic,
        "question": question,
        "options": list(SELF_OPTIONS),
        "answer": "",
        "explain": "",
        "tc": tc,
        "self_report": True,
    }


def make_checkin_sync(timeline: str, transcript: str, current: str,
                      tc: str = "", focus: str = "", llm=None, use_llm: bool = True) -> dict:
    """同步生成一道抽问题。永远返回非空 dict（最差也有自评题兜底）。

    use_llm=False 表示调用方明确要求不走 AI（离线模式），此时不再自己造 LLM。
    focus 是学生此刻的状态（刚掉队过的地方、之前抽问答错的知识点），
    出题时带上它，题目才接得上学生正在补的内容。
    """
    if llm is None and use_llm and not config.OFFLINE and config.DEEPSEEK_API_KEY:
        try:
            llm = LLM()
        except Exception as e:
            log.warning("抽问取不到 LLM，改用自评题: %s", e)
    if llm is not None:
        try:
            data = llm.json(
                prompts.CHECKIN_SYSTEM,
                prompts.CHECKIN_USER.format(
                    timeline=timeline or "（暂无）",
                    transcript=transcript or "（暂无）",
                    current=current or "（还没识别到知识点）",
                    focus=focus or "（没什么特别的，正常听课）",
                ),
                temperature=0.6, max_tokens=500,
                timeout=config.CHECKIN_TIMEOUT, attempts=1)
            q = _clean_checkin(data, tc)
            if q:
                return q
            # LLM 说「这段还不适合出题」→ 不硬出选择题，退成自评题
            log.info("LLM 判断当前内容不适合出题，改用自评题")
        except Exception as e:
            log.warning("抽问 LLM 失败，改用自评题: %s", e)
    return _self_checkin(current, tc)


def grade(question: dict, choice: int) -> str:
    """判分：choice 是学生选的选项下标。返回 right / unsure / wrong。"""
    options = question.get("options") or []
    if not (0 <= choice < len(options)):
        return WRONG
    if question.get("self_report"):
        return SELF_GRADE[choice] if choice < len(SELF_GRADE) else WRONG
    picked = options[choice].strip().upper()[:1]
    return RIGHT if picked == (question.get("answer") or "").upper()[:1] else WRONG


def correct_text(question: dict) -> str:
    """正确答案的文字，用于错题本和讲解。"""
    options = question.get("options") or []
    answer = (question.get("answer") or "").upper()[:1]
    if answer and options:
        for o in options:
            if o.strip().upper().startswith(answer):
                return o
    return "；".join(options[:1]) or question.get("explain") or ""


def to_mistake(question: dict, result: str) -> dict:
    """把答错的抽问题转成错题本记录（字段与 store.add() 约定一致）。"""
    topic = question.get("topic") or "课堂抽问"
    explain = question.get("explain") or ""
    right = correct_text(question)
    lesson = explain
    if right:
        lesson = f"正确答案：{right}" + (f"\n{explain}" if explain else "")
    if result == UNSURE:
        lesson = "你自评「有点模糊」。" + lesson
    return {
        "topic": topic,
        "timecode": question.get("tc") or "",
        "missing": question.get("question") or "",
        "reason": "课堂抽问没答上来",
        "micro_lesson": lesson or "回看这个知识点，确认自己能说清楚。",
        "known": "",
        "step": right,
        "now": "",
        "status": "review",
        "reviewed": False,
        "source": "checkin",
    }


def lesson_quiz_sync(lesson: dict, n: int = 4, llm=None) -> list:
    """按一节课的要点出课后练习题。没有 key 时返回 []，由调用方决定要不要换别的入口。"""
    lesson = lesson or {}
    if config.OFFLINE:                    # 离线演示不联网
        return []
    if llm is None and config.DEEPSEEK_API_KEY:
        try:
            llm = LLM()
        except Exception as e:
            log.warning("课后练习取不到 LLM: %s", e)
    if llm is None:
        return []
    skills = lesson.get("skills_detail") or []
    skills_text = "\n".join(
        f"- {s.get('name', '')}（掌握度 {s.get('mastery', 0)}，{s.get('status', '')}）"
        for s in skills if s.get("name")) or "（无）"
    highlights = lesson.get("highlights") or []
    try:
        data = llm.json(
            prompts.LESSON_QUIZ_SYSTEM.format(n=n),
            prompts.LESSON_QUIZ_USER.format(
                summary=lesson.get("summary") or "（无）",
                highlights="\n".join(f"- {h}" for h in highlights) or "（无）",
                skills=skills_text,
                n=n),
            max_tokens=1400, temperature=0.5)
    except Exception as e:
        log.exception("课后练习出题失败: %s", e)
        return []
    return clean_questions(data, n)


def clean_questions(data, n: int) -> list:
    """规范化一批练习题；形状与 practice.py 的输出保持一致。"""
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        if not question:
            continue
        opts = raw.get("options")
        options = [str(o).strip() for o in opts if str(o).strip()] if isinstance(opts, list) else []
        out.append({
            "question": question,
            "options": options,
            "answer": str(raw.get("answer") or "").strip(),
            "explain": str(raw.get("explain") or "").strip(),
        })
        if len(out) >= n:
            break
    return out


def ask(timeline: str, transcript: str, current: str, tc: str = "",
        llm=None, use_llm: bool = True, on_done=None, on_error=None) -> None:
    """后台线程出一道抽问题，成功后 on_done(question)。"""
    def _run():
        try:
            q = make_checkin_sync(timeline, transcript, current, tc, llm, use_llm)
            if on_done:
                on_done(q)
        except Exception as e:
            log.exception("后台抽问失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name="echo-checkin").start()
