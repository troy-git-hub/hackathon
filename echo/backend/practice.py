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


from echo.backend.assessment import clean_question as _clean_question, clean_questions as _clean_questions, product_help


def fallback_questions(item: dict) -> list:
    """没 key / 调用失败时的兜底练习题：用 item 自己的字段拼出题，保证离线也有东西练。"""
    if product_help(" ".join(str(item.get(k) or "") for k in ("topic", "missing", "step", "micro_lesson"))):
        return []
    if not any(item.get(k) for k in ("missing", "step", "micro_lesson", "now")):
        return []
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
    for question in questions:
        question["_source"] = "local"
        question["type"] = "short_answer"
    return questions


def generate_sync(item: dict, n: int = 3) -> list:
    """同步出题，给自检脚本 / 离线场景用。没有足够课程材料时返回空 list。"""
    item = item or {}
    if product_help(" ".join(str(item.get(k) or "") for k in ("topic", "missing", "step", "micro_lesson"))):
        return []
    # 离线模式（ECHO_OFFLINE=1）下不许联网：只看 API key 会漏掉这个开关，
    # 断网演示时点出题会一直卡到超时才退回兜底
    if config.OFFLINE or not config.llm_configured():
        return fallback_questions(item)
    try:
        system = prompts.system("PRACTICE_SYSTEM", n=n, include_memory=False)
        user = prompts.PRACTICE_USER.format(
            topic=item.get("topic") or "",
            missing=item.get("missing") or "",
            known=item.get("known") or "",
            step=item.get("step") or "",
            now=item.get("now") or "",
            micro_lesson=item.get("micro_lesson") or "",
            n=n,
        )
        from echo.backend.assessment import type_plan
        user += type_plan(n)
        # 练习页有人在等题；网络卡住时尽快交还本地题，避免两次 40 秒超时。
        data = LLM().json(system, user, max_tokens=3000, temperature=0.5,
                          timeout=min(config.LLM_TIMEOUT, 20), attempts=1)
        questions = _clean_questions(data, n)
        if questions:
            for question in questions:
                question["_source"] = "ai"
            return questions
        log.warning("出题结果为空，退回兜底题")
    except Exception as e:
        log.exception("出题失败: %s", e)
    return fallback_questions(item)


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
