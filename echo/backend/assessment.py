"""Shared question schema and grading. Objective answers never need a model."""
import json
import logging
import threading

from echo.backend import config, prompts
from echo.backend.llm import LLM

TYPES = {"single_choice": "单选", "fill_blank": "填空", "short_answer": "简答",
         "true_false": "判断", "matching": "连线配对"}


def type_plan(n):
    kinds = ("single_choice", "fill_blank", "true_false", "matching", "short_answer")
    return "\n本套题按题号依次使用以下题型，不要全部替换为单选：" + ", ".join(kinds[i % len(kinds)] for i in range(n))


def product_help(text):
    """Do not turn Echo onboarding instructions into subject exercises."""
    text = str(text).lower()
    return ("echo" in text or "我掉队了" in text) and any(
        term in text for term in ("键盘输入", "摄像头", "鼠标点击", "播放的声音", "静音状态",
                                   "一两分钟", "怎么使用", "使用说明", "录音权限", "我掉队了"))


def clean_question(raw):
    if not isinstance(raw, dict):
        return None
    q = dict(raw)
    q["question"] = str(q.get("question") or "").strip()
    q["explain"] = str(q.get("explain") or "").strip()
    if not q["question"] or not q["explain"] or product_help(str(raw)):
        return None
    q["type"] = q.get("type") or ("single_choice" if q.get("options") else "short_answer")
    if q["type"] not in TYPES:
        return None
    q["options"] = [str(v) for v in q.get("options", [])] if isinstance(q.get("options"), list) else []
    if q["type"] == "true_false":
        q["options"] = ["正确", "错误"]
        val = str(q.get("answer")).strip().lower()
        if val not in ("true", "false", "正确", "错误", "对", "错", "a", "b"):
            return None
        q["answer"] = "A" if val in ("true", "正确", "对", "a") else "B"
    elif q["type"] == "matching":
        left, right, answer = q.get("left"), q.get("right"), q.get("answer")
        if not (isinstance(left, list) and isinstance(right, list) and
                2 <= len(left) == len(right) <= 6 and isinstance(answer, list) and
                len(answer) == len(left) and all(type(a) is int for a in answer) and
                sorted(answer) == list(range(len(right)))):
            return None
        q["left"], q["right"] = list(map(str, left)), list(map(str, right))
    else:
        q["answer"] = str(q.get("answer") or "").strip()
        if not q["answer"]:
            return None
        if q["type"] == "single_choice":
            letter = q["answer"].upper()
            if not (2 <= len(q["options"]) <= 8 and len(letter) == 1 and
                    "A" <= letter <= chr(64 + len(q["options"]))):
                return None
            q["answer"] = letter
    return q


def clean_questions(data, n):
    items = data.get("questions", []) if isinstance(data, dict) else []
    return [q for raw in items if (q := clean_question(raw))][:n] if isinstance(items, list) else []


def reference(q):
    if q.get("type") == "matching":
        return "；".join(f"{left} → {q['right'][i]}" for left, i in zip(q["left"], q["answer"]))
    if q.get("type") == "true_false":
        return "正确" if q["answer"] == "A" else "错误"
    return str(q.get("answer") or "")


def local_grade(q, answer):
    empty = answer is None or answer == "" or (isinstance(answer, list) and any(i < 0 for i in answer))
    if empty:
        return {"status": "unanswered", "score": 0, "feedback": "未完成作答"}
    if q.get("type", "single_choice" if q.get("options") else "short_answer") in ("fill_blank", "short_answer"):
        return {"status": "pending", "score": None, "feedback": "等待 AI 批改"}
    expected = q.get("answer")
    if q.get("type") == "matching":
        score = sum(a == b for a, b in zip(answer, expected)) / len(expected)
    else:
        score = float(str(answer).upper() == str(expected).upper())
    return {"status": "correct" if score == 1 else "partial" if score else "incorrect",
            "score": score, "feedback": "答对了" if score == 1 else "部分配对正确" if score else "再看一下解析"}


def grade_sync(entries, llm=None):
    """Return only validated model grades; missing/failed results stay pending."""
    if config.OFFLINE or (llm is None and not config.llm_configured()):
        return {}
    try:
        data = (llm or LLM()).json(
            prompts.system("ASSESSMENT_GRADE_SYSTEM", include_memory=False),
            json.dumps(entries, ensure_ascii=False), max_tokens=2200, temperature=0,
            timeout=min(config.LLM_TIMEOUT, 25), attempts=1)
        allowed = {e["id"] for e in entries}
        result = {}
        for item in data.get("grades", []):
            idx, score = item.get("id"), item.get("score")
            feedback = str(item.get("feedback") or "").strip()
            if type(idx) is int and idx in allowed and type(score) in (int, float) and 0 <= score <= 1 and feedback:
                result[idx] = {"status": "correct" if score == 1 else "partial" if score else "incorrect",
                               "score": score, "feedback": feedback}
        return result
    except Exception:
        logging.getLogger("echo.assessment").exception("AI grading unavailable")
        return {}


def grade_async(entries, on_done):
    threading.Thread(target=lambda: on_done(grade_sync(entries)), daemon=True,
                     name="echo-grading").start()
