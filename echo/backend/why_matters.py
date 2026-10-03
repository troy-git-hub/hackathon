"""
Echo - 「为什么要复习它」

错题卡上有一行说明，回答的不是「这题为什么错」，而是**这个知识点跟学生后面要学的
东西有什么关系** —— 让他觉得这步值得认真补，而不是又一条待办。

一次调用批量生成一整批（用户明确要求「一次性生成」）：每张卡各调一次 API 既慢又贵，
而且模型看不到彼此，写出来容易是同一句套话。

生成结果写进错题本的 why_matters 字段，走 store.set_why()（不是 add()——那个会把
同一道错题的 missing / micro_lesson 一起抹掉，见 store.set_why 的注释）。

拿不到结果时返回空 dict、不抛：没有 AI 说明就不显示这一行，卡片上原有的
「◷ 为什么是今天」还在。不自己编一句「以后会用得上」——那是没有依据的断言。
"""
import logging
import threading

from echo.backend import config, prompts
from echo.backend.llm import LLM

log = logging.getLogger("echo.why_matters")

# 一批最多问几个：一次调用的 token 会随条数线性涨，一条错题两句话其实很省，
# 卡在 12 是给「错题本攒了很久、第一次打开复习页」那种情况兜底 ——
# 超出的留到下一次渲染再问，不在一屏里硬塞。
MAX_PER_CALL = 12


def needs(items) -> list:
    """挑出还没有「为什么要复习它」的条目。已生成的不用再问，省一次调用。"""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        topic = str(it.get("topic") or "").strip()
        if topic and not str(it.get("why_matters") or "").strip():
            out.append(it)
    return out


def _format_items(items) -> str:
    blocks = []
    for i, it in enumerate(items, 1):
        topic = str(it.get("topic") or "").strip()
        miss = str(it.get("missing") or it.get("reason") or "").strip()
        lines = [f"{i}. {topic}"]
        if miss:
            lines.append(f"   他卡在：{miss}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _clean(data, wanted) -> dict:
    """把模型返回的 reasons 收成 {topic: why}，只认输入里真实存在的 topic。

    模型的 topic 可能多一个空格、少一个「的」——所以按去空格后的精确匹配来认，
    对不上就丢掉这一条：宁可少显示一行，也不要把说明挂到别的知识点上。
    """
    rows = data.get("reasons") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    by_topic = {str(t).strip(): t for t in wanted}
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        topic = str(row.get("topic") or "").strip()
        why = str(row.get("why") or "").strip()
        if topic in by_topic and why:
            out[by_topic[topic]] = why
    return out


def plan_batch(items) -> dict:
    """同步批量生成，返回 {topic: 说明}。离线 / 没 key / 调用失败一律返回 {}。"""
    items = [it for it in (items or []) if str(it.get("topic") or "").strip()]
    items = items[:MAX_PER_CALL]
    if not items:
        return {}
    # 离线模式（ECHO_OFFLINE=1）下不许联网，理由同 practice.generate_sync
    if config.OFFLINE or not config.DEEPSEEK_API_KEY:
        return {}
    try:
        system = prompts.system("WHY_MATTERS_SYSTEM")
        user = prompts.WHY_MATTERS_USER.format(items=_format_items(items))
        data = LLM().json(system, user, max_tokens=900, temperature=0.6)
        reasons = _clean(data, [it.get("topic") for it in items])
        if not reasons:
            log.warning("「为什么要复习它」生成结果为空")
        return reasons
    except Exception as e:
        log.warning("「为什么要复习它」生成失败: %s", e)
        return {}


def generate_async(items, on_done=None, on_error=None) -> None:
    """后台线程生成。成功时 on_done({topic: 说明})（可能是空 dict），失败 on_error(str)。"""
    def _run():
        try:
            reasons = plan_batch(items)
            if on_done:
                on_done(reasons)
        except Exception as e:
            log.exception("后台生成「为什么要复习它」失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name="echo-why-matters").start()
