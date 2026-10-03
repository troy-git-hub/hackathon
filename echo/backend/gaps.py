"""
Echo - 反复缺失的前置知识

回答的是**跨课**的问题，不是单节课的复盘：

    第一次：导数没听懂      → 缺的是「极限」
    第二次：瞬时速度没听懂  → 又缺「极限」
    第三次：洛必达法则不会用 → 还是卡在「极限条件」
    这时才能说：你最近三次掉队都和「极限」有关。问题可能不在当前章节，
    而是这个前置知识还不稳定。

**为什么从课程归档算、而不是从错题本算**：错题记录里既没有「属于哪节课」，
也没有前置概念。`review_chain`（掉队点 → 根源）只在课程归档 lessons.json 里，
从来没写进 review.json —— 所以 recall.pick() 那套「共同根源」在生产里取不到值。
这里改用每节课归档里的 skills_detail（哪些点没掌握）+ graph（谁是谁的前置），
数据本来就是齐的，不用新增任何存储字段。

**为什么只数「根源」前置**：一节课的图可能是 极限 → 导数定义 → 洛必达法则。
学生卡在洛必达法则时，直接前置是导数定义，但真正不稳的地基是链条最上游那个。
往下追到没有前置的节点（in-degree 0）才算，正好对应回响里说的「源泉概念」。
不这么做的话，一个什么都是它后代的通用概念（比如「函数」）会永远赢。
"""
import logging
import threading

from echo.backend import config, mindmap, prompts, store
from echo.backend.llm import LLM

log = logging.getLogger("echo.gaps")

WINDOW = 10       # 只看最近这么多节课。再往前的和现在的学习状态关系不大
THRESHOLD = 3     # 跨几节**不同的课**才算「反复」。两次可能只是巧合，说了像乱猜
MAX_TOPICS = 4    # finding 里最多列几个知识点：资料页只有 380px 宽，列长了排版会垮


def _t(zh: str, en: str) -> str:
    """中英二选一。

    不用 i18n.tr()：它会 import QSettings，把 PyQt5 拖进后端的导入链，
    正是 main.py 里记着的 ctranslate2/PyQt5 加载顺序坑。跟 persona 一样读 config。
    """
    return en if getattr(config, "UI_LANG", "zh") == "en" else zh


def _roots_of(topic: str, edges: list) -> list:
    """topic 的「根源前置概念」：顺着前置边往上走，走到没有前置的那些点。

    edges 是 [{"from": 前置, "to": 后继}]。返回去重后的名字列表。
    """
    pres = {}                       # 后继 → [前置, ...]
    for e in edges:
        pres.setdefault(e["to"], []).append(e["from"])
    seen, stack, roots = {topic}, list(pres.get(topic, [])), []
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        ups = pres.get(cur) or []
        if ups:
            stack.extend(ups)
        else:
            roots.append(cur)       # 没有前置 → 它自己就是根源
    return roots


def _weak_topics(graph: dict) -> list:
    """这节课里学生没掌握的知识点（status 不是 ok）。"""
    return [n["topic"] for n in graph.get("nodes") or []
            if n.get("topic") and n.get("status") != mindmap.STATUS_OK]


def _sentence(concept: str, n: int) -> str:
    """模板兜底句。**永远非空** —— 资料页那块不能因为没配 key 就空着。"""
    return _t(f"你最近 {n} 节课都和「{concept}」有关。问题可能不在当前章节，"
              f"而是这个前置知识还不稳定。",
              f"Your last {n} lessons kept coming back to \"{concept}\". The problem may not be "
              f"this chapter at all — that prerequisite still isn't solid.")


def recurring(lessons: list = None, window: int = WINDOW,
              threshold: int = THRESHOLD) -> list:
    """找出反复挡在薄弱知识点后面的根源前置概念。

    返回按「跨了几节课」从多到少排序的 finding 列表：
      {"concept", "lessons", "topics", "first_seen", "last_seen", "sentence"}
    `lessons` 是跨了几节不同的课（= 判据的分子），`topics` 是那些没掌握的知识点。
    """
    try:
        rows = store.list_lessons() if lessons is None else list(lessons)
    except Exception as e:
        log.warning("读课程归档失败: %s", e)
        return []

    agg = {}                       # 归一后的 key → 聚合结果
    for ls in rows[:window]:
        try:
            graph = mindmap.build(ls)
        except Exception as e:
            log.warning("建图失败，跳过这节课: %s", e)
            continue
        weak = _weak_topics(graph)
        if not weak:
            continue
        ts = float(ls.get("time") or 0)
        if graph.get("has_real_graph"):
            # 新课：边就是 AI 报的 prerequisites，谁是谁的前置说得清清楚楚
            edges = graph.get("edges") or []
            for w in weak:
                for root in _roots_of(w, edges):
                    if not mindmap.is_placeholder_topic(root):
                        _bump(agg, root, ts, w)
        else:
            # 旧课没有依赖图。只用它**自己报的那个根源概念**（回响里「最该先复习的」），
            # 不顺着讲课顺序推出来的边去认前置 —— 那些边是给地图页排版用的，
            # 拿它断言「你的问题在这」是在说我们并不知道的事。
            root = graph.get("review_first") or ""
            if root and not mindmap.is_placeholder_topic(root):
                for w in weak:
                    _bump(agg, root, ts, w)

    out = []
    for a in agg.values():
        n = len(a["lessons"])
        if n < threshold:
            continue
        out.append({
            "concept": a["name"],
            "lessons": n,
            "topics": a["topics"][:MAX_TOPICS],
            "first_seen": a["first_seen"],
            "last_seen": a["last_seen"],
            "sentence": _sentence(a["name"], n),
        })
    # 课次数多的排前面；并列时最近还在卡着的先出来
    out.sort(key=lambda f: (-f["lessons"], -f["last_seen"]))
    return out


def _bump(agg: dict, root: str, ts: float, weak_topic: str):
    """把「这节课的这个薄弱点源于 root」记一笔。

    归并要按**包含**判同（复用 mindmap._same，也就是知识地图判「这两个名字是不是同一个
    知识点」用的那套）：用户例子里「极限」和「极限条件」是同一个概念但字面不同，按精确
    字符串分组会把那三次拆成两条、永远凑不够 3 次。共用同一套判定也保证这里和地图页
    对「谁是谁的前置」给出同样的答案。

    显示名取更短的那个：「极限」短于「极限条件」，而短的一般才是概念本身，长的多是
    带定语的变体。拿长的当结论会把话说得比实际更窄。
    """
    root = str(root or "").strip()
    if not root:
        return
    a = next((c for c in agg.values() if mindmap._same(c["name"], root)), None)
    if a is None:
        a = agg.setdefault(root, {"name": root, "lessons": set(), "topics": [],
                                  "first_seen": ts, "last_seen": ts})
    elif len(mindmap._norm(root)) < len(mindmap._norm(a["name"])):
        a["name"] = root
    a["lessons"].add(ts)
    if ts:
        a["first_seen"] = min(a["first_seen"] or ts, ts)
        a["last_seen"] = max(a["last_seen"], ts)
    if weak_topic not in a["topics"]:
        a["topics"].append(weak_topic)


def _format_findings(findings: list) -> str:
    lines = []
    for f in findings:
        lines.append(f"- 根源概念：{f['concept']}"
                     f"（最近 {f['lessons']} 节不同的课都指向它）")
        if f.get("topics"):
            lines.append(f"  他这几节课没掌握的知识点：{'、'.join(f['topics'])}")
    return "\n".join(lines)


def narrate(findings: list) -> str:
    """让 AI 把结论讲成一段话。**拿不到就返回空串**，调用方退回模板句子。

    离线 / 没 key 直接返回空：这段是锦上添花，不能因为它把画像整块拖住。
    """
    if not findings:
        return ""
    if config.OFFLINE or not config.DEEPSEEK_API_KEY:
        return ""
    try:
        system = prompts.system("GAPS_SYSTEM")
        user = prompts.GAPS_USER.format(items=_format_findings(findings))
        data = LLM().json(system, user, max_tokens=500, temperature=0.6)
        return str((data or {}).get("narrative") or "").strip()
    except Exception as e:
        log.warning("生成前置知识叙述失败（退回模板句子）: %s", e)
        return ""


def narrate_async(findings: list, on_done=None, on_error=None) -> None:
    """后台生成叙述。成功时 on_done(文本)（可能是空串），失败 on_error(str)。"""
    def _run():
        try:
            text = narrate(findings)
            if on_done:
                on_done(text)
        except Exception as e:
            log.exception("后台生成前置知识叙述失败")
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, daemon=True, name="echo-gaps-narrate").start()
