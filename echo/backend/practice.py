"""
Echo - 错题练习出题

学生的每个「掉队点」（错题）已经存了 topic / missing / known / step / now / micro_lesson。
这里让 DeepSeek 针对这个错题出几道练习题，让学生真的练一下，而不是只看补课文字。
"""
import logging
import threading

from echo.backend import config, prompts
from echo.backend.llm import LLM

log = logging.getLogger("echo.practice")


def _clean_question(q) -> dict:
    if not isinstance(q, dict):
        return None
    question = str(q.get("question") or "").strip()
    if not question:
        return None
    options = q.get("options")
    options = [str(o).strip() for o in options if str(o).strip()] if isinstance(options, list) else []
    return {
        "question": question,
        "options": options,
        "answer": str(q.get("answer") or "").strip(),
        "explain": str(q.get("explain") or "").strip(),
    }


def _clean_questions(data, n: int) -> list:
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for raw in items:
        q = _clean_question(raw)
        if q:
            out.append(q)
        if len(out) >= n:
            break
    return out


def _fallback(item: dict) -> list:
    """没 key / 调用失败时的兜底练习题：用 item 自己的字段拼出题，保证离线也有东西练。"""
    missing = item.get("missing") or "这个知识点"
    known = item.get("known") or ""
    step = item.get("step") or ""
    now = item.get("now") or ""
    micro = item.get("micro_lesson") or "回顾一下老师刚才讲的内容，把缺的这一步补上。"
    questions = [{
        "question": f"结合已掌握的「{known}」，说说：{missing}" if known else f"说说：{missing}",
        "options": [],
        "answer": step or micro,
        "explain": micro,
    }]
    if now:
        questions.append({
            "question": f"补上这一步之后，再回到老师现在讲的内容：{now}。请简述你的理解。",
            "options": [],
            "answer": now,
            "explain": micro,
        })
    return questions


def generate_sync(item: dict, n: int = 3) -> list:
    """同步出题，给自检脚本 / 离线场景用。永远返回非空 list。"""
    item = item or {}
    if not config.DEEPSEEK_API_KEY:
        return _fallback(item)
    try:
        system = prompts.PRACTICE_SYSTEM.format(n=n)
        user = prompts.PRACTICE_USER.format(
            topic=item.get("topic") or "",
            missing=item.get("missing") or "",
            known=item.get("known") or "",
            step=item.get("step") or "",
            now=item.get("now") or "",
            micro_lesson=item.get("micro_lesson") or "",
            n=n,
        )
        data = LLM().json(system, user, max_tokens=1200, temperature=0.5)
        questions = _clean_questions(data, n)
        if questions:
            return questions
        log.warning("出题结果为空，退回兜底题")
    except Exception as e:
        log.exception("出题失败: %s", e)
    return _fallback(item)


def generate(item: dict, n: int = 3, on_done=None, on_error=None) -> None:
    """后台线程出题。成功时 on_done(questions)，失败时 on_error(str)。"""
    def _run():
        try:
            questions = generate_sync(item, n)
            if on_done:
                on_done(questions)
        except Exception as e:
            log.exception("后台出题失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name="echo-practice").start()
