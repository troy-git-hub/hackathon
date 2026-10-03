"""
Echo - 错题本 / 复习记录持久化

每节课结束时，把「我掉队了」定位到的断点（错题）存成 JSON，
重启后还能在「错题复习」主页里回看、标记掌握。跨会话保存上下文。

复习不是一次性的「掌握 / 没掌握」：学生答完一次后，按他的真实感受
（还是没懂 / 有点模糊 / 记得很清楚）决定什么时候再来确认一次 —— 见下面的
「间隔重复」一段。答得越稳，下次间隔越长；答崩了就明天再来。

存储位置：config_dir()/review.json（打包后 %APPDATA%\\Echo，开发时项目根目录）。
"""
import json
import os
import threading
import time

from echo.backend import paths

_LOCK = threading.RLock()     # 可重入：grade()/add() 整段持锁时内部还要调 load()

# ================= 间隔重复 =================
# 学生复习完一个知识点后的三档自评。没有「掌握了」这个终态 ——
# 一次答对不代表长期记住，只是把下次确认时间推远一点。
AGAIN, FUZZY, CLEAR = "again", "fuzzy", "clear"
GRADES = (AGAIN, FUZZY, CLEAR)
GRADE_LABEL = {AGAIN: "还是没懂", FUZZY: "有点模糊", CLEAR: "记得很清楚"}

DAY = 86400.0
AGAIN_DAYS = 1          # 答崩了：换种讲法，明天再确认
FUZZY_DAYS = 3          # 有印象但不稳：留几天再问
# 连续答「清楚」时的间隔阶梯（天）。连对越多，推得越远，最后进长期记忆检查。
CLEAR_LADDER = (7, 14, 30, 60, 120)


def _path() -> str:
    return os.path.join(paths.config_dir(), "review.json")


def _schedule(it: dict, now: float) -> dict:
    """补齐一条记录的复习进度字段。

    老数据（1.x 只有 reviewed 布尔值）没有 level/due，这里就地推导：
    标过「掌握」的当成已经连对一次，其余的算作现在就该复习。
    只改内存里的 dict，调用方决定要不要落盘。
    """
    if "due" in it and "level" in it:
        return it
    if it.get("reviewed"):
        it.setdefault("level", 1)
        base = it.get("reviewed_at") or it.get("time") or now
        it.setdefault("due", base + CLEAR_LADDER[0] * DAY)
    else:
        it.setdefault("level", 0)
        it.setdefault("due", it.get("time") or now)
    return it


def next_due(level: int, result: str, now: float) -> tuple:
    """按这次的表现算 (新的 level, 下次复习时间戳)。

    还是没懂 → level 清零、明天再来；有点模糊 → level 不动、3 天后；
    记得很清楚 → level +1，按阶梯推远。
    """
    if result == AGAIN:
        return 0, now + AGAIN_DAYS * DAY
    if result == FUZZY:
        return max(0, int(level or 0)), now + FUZZY_DAYS * DAY
    level = max(0, int(level or 0)) + 1
    days = CLEAR_LADDER[min(level - 1, len(CLEAR_LADDER) - 1)]
    return level, now + days * DAY


def load() -> list:
    """读取所有错题记录（list[dict]）。文件不存在或损坏时返回 []。"""
    with _LOCK:
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []


def _write_json(path, items):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def _write(items):
    _write_json(_path(), items)


def add(items, relapse: bool = False):
    """追加/合并一批错题：同一 topic 覆盖更新内容，但保留复习进度（不复活老错题）。

    relapse=True 表示「学生在新一节课上又在同一个知识点掉队了」。这是「其实没掌握」
    的强信号，不能沿用之前连对几次攒下来的长间隔 —— 那样一个早就该重新学的知识点
    会被排到一个月后。所以这种情况下把 level 清零、立刻到期重来。

    默认 False：其它调用点（抽问答错、拍题）只是把新内容补进来，不该动已有的进度。

    整段持锁：engine 现在找到断点就立刻调用这个函数（不再等下课批量写），
    并发调用变多了，读-改-写必须是一个原子操作，否则两次几乎同时的 add()
    会读到同一份旧数据，后写的那次把先写的那次覆盖掉。
    """
    if not items:
        return
    with _LOCK:
        cur = load()
        by_topic = {it.get("topic"): it for it in cur}
        now = time.time()
        for it in items:
            topic = (it.get("topic") or "").strip()
            if not topic:
                continue
            it["topic"] = topic
            it.setdefault("time", now)
            prev = by_topic.get(topic)
            if prev:
                it["reviewed"] = prev.get("reviewed", False)
                if prev.get("reviewed_at"):
                    it["reviewed_at"] = prev["reviewed_at"]
                it["time"] = prev.get("time", it["time"])
                # 复习进度跟着走，否则同一个知识点再次被记进来就把阶梯清零了
                for k in ("level", "due", "last_result", "review_count"):
                    if k in prev:
                        it[k] = prev[k]
                if relapse:
                    it["level"] = 0
                    it["due"] = now          # 立刻回到今天的复习清单里
                    it["last_result"] = AGAIN
                    it["reviewed"] = False
            by_topic[topic] = it
        _write(list(by_topic.values()))


def mark_reviewed(topic: str):
    """把某个错题标记为已复习（掌握）。

    1.x 的二元接口，等价于学生自评「记得很清楚」—— 保留是因为旧的调用点
    （练习页的「✓ 这个我会了」）还在用；新代码请直接调 grade()。
    """
    grade(topic, CLEAR)


def grade(topic: str, result: str, now: float = None) -> dict:
    """记一次复习结果，顺手算出下次该什么时候再问。

    result 取 AGAIN / FUZZY / CLEAR。返回更新后的那条记录（没找到返回 {}）。
    """
    if result not in GRADES:
        raise ValueError(f"未知的复习结果：{result!r}")
    now = time.time() if now is None else now
    with _LOCK:
        cur = load()
        hit = {}
        for it in cur:
            if it.get("topic") != topic:
                continue
            _schedule(it, now)
            level, due = next_due(it.get("level", 0), result, now)
            it["level"] = level
            it["due"] = due
            it["last_result"] = result
            it["reviewed_at"] = now
            # reviewed 仍然写：主页统计和老的筛选逻辑还在看它。
            # 语义变成「这一轮暂时过了」，到期后 due_items() 会把它重新捞出来。
            it["reviewed"] = result != AGAIN
            it["review_count"] = int(it.get("review_count") or 0) + 1
            hit = it
        if hit:
            _write(cur)
        return hit


def due_items(now: float = None) -> list:
    """现在该复习的知识点，最该先看的排前面。

    排序：没懂过的 > 模糊的 > 清楚的；同档里到期越久的越靠前。
    """
    now = time.time() if now is None else now
    out = []
    for it in load():
        _schedule(it, now)
        if it.get("due", 0) <= now:
            out.append(it)
    rank = {AGAIN: 0, FUZZY: 1, CLEAR: 2}
    out.sort(key=lambda it: (rank.get(it.get("last_result"), 0) if it.get("review_count")
                             else -1, it.get("due", 0)))
    return out


def later_items(now: float = None) -> list:
    """还没到期、过几天要再确认一次的知识点，按到期时间由近到远。

    复习不是「过一遍就消失」——答完之后它下一次还会回来，这里就是那个「还没到时候」的列表。
    """
    now = time.time() if now is None else now
    out = []
    for it in load():
        _schedule(it, now)
        if it.get("due", 0) > now:
            out.append(it)
    out.sort(key=lambda it: it.get("due", 0))
    return out


def due_reason(item: dict, now: float = None) -> str:
    """一句话：为什么这个知识点现在该复习了。

    不是 AI 现编的 —— 就是把调度状态翻成人话，让学生知道「这不是随机抽的」。
    复习卡片（今天该复习 / 过几天再复习）都用这个。
    """
    now = time.time() if now is None else now
    count = int(item.get("review_count") or 0)
    last = item.get("last_result")
    if count == 0:
        base = "第一次掉队，还没确认过"
    elif last == AGAIN:
        base = "上次还是没想起来，这次再试试"
    elif last == FUZZY:
        base = "上次印象有点模糊，再看一次"
    elif last == CLEAR:
        reviewed_at = item.get("reviewed_at") or now
        days = max(0, round((now - reviewed_at) / DAY))
        base = ("刚确认过，按计划抽查一下" if days <= 0 else
                f"上次说记得清楚，{days} 天过去了，抽查一下有没有忘")
    else:
        base = "该复习一下了"
    if count >= 2:
        base += f"（第 {count + 1} 次见到它）"
    return base


def set_why(topics: dict) -> int:
    """批量写「为什么要复习它」：{topic: 一句话}，返回实际写到几条。

    单独开一个函数、不复用 add()：add() 是按 topic **整条替换**的
    （by_topic[topic] = it），只会把 reviewed/time 和几个调度字段带过去 ——
    拿它写一个新字段，会把 missing / micro_lesson / timecode 一起抹成空。
    这里只动 why_matters 一个键，其余原样留着。

    空串不写入：调用方（why_matters）拿不到 AI 结果时会传空，这时候宁可留着
    上一次写好的说明，也不要拿空值把它盖掉。
    """
    clean = {str(t).strip(): str(v).strip() for t, v in (topics or {}).items()
             if str(t).strip() and str(v).strip()}
    if not clean:
        return 0
    with _LOCK:
        cur = load()
        n = 0
        for it in cur:
            topic = str(it.get("topic") or "").strip()
            if topic in clean and it.get("why_matters") != clean[topic]:
                it["why_matters"] = clean[topic]
                n += 1
        if n:
            _write(cur)
        return n


def due_summary(now: float = None) -> dict:
    """首页「今天该回响」卡片要的那几个数。

    minutes 是粗估：一个知识点看讲解 + 答一道题，按 1 分钟算，至少 1 分钟。
    hint 优先说最近一次掉队发生在哪节课的哪里，让学生想得起来当时的场景。
    """
    now = time.time() if now is None else now
    items = due_items(now)
    topics = [it.get("topic", "") for it in items if it.get("topic")]
    hint = ""
    if items:
        first = items[0]
        chain = [c for c in (first.get("review_chain") or []) if c]
        if len(chain) >= 2:
            hint = f"你在「{chain[-1]} → {chain[0]}」这里掉过队"
        elif first.get("missing"):
            hint = first["missing"]
        elif first.get("reason"):
            hint = first["reason"]
    return {
        "count": len(items),
        "topics": topics,
        "minutes": max(1, len(items)),
        "hint": hint,
        "items": items,
    }


def from_breakpoints(engine) -> list:
    """把引擎里的断点（掉队点）转成错题记录。engine 可为 None。"""
    try:
        bps = list(engine.breakpoints) if engine is not None else []
    except Exception:
        bps = []
    out = []
    for bp in bps:
        topic = (bp.concept or "").strip()
        if not topic:
            continue
        out.append({
            "topic": topic,
            "timecode": bp.breakpoint_tc,
            "missing": bp.missing,
            "reason": bp.reason,
            "micro_lesson": bp.micro_lesson,
            "known": bp.known,
            "step": bp.step,
            "now": bp.now,
            "status": "fixed" if bp.fixed else "review",
            "reviewed": False,
        })
    return out


def _lessons_path() -> str:
    return os.path.join(paths.config_dir(), "lessons.json")


def _load_lessons() -> list:
    """读取所有课程历史（list[dict]）。文件不存在或损坏时返回 []。"""
    with _LOCK:
        try:
            with open(_lessons_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []


def _skill_status(sk) -> str:
    """统一吃 (name, mastery, status) 元组 / dict / 对象三种形式，取出 status。"""
    if isinstance(sk, dict):
        return sk.get("status", "ok")
    if isinstance(sk, (list, tuple)):
        return sk[2] if len(sk) > 2 else "ok"
    return getattr(sk, "status", "ok")


def _skill_fields(sk) -> dict:
    """统一吃 (name, mastery, status) 元组 / dict / 对象三种形式，取出三个字段。"""
    if isinstance(sk, dict):
        name, mastery, status = sk.get("name", ""), sk.get("mastery", 0.0), sk.get("status", "ok")
    elif isinstance(sk, (list, tuple)):
        name = sk[0] if len(sk) > 0 else ""
        mastery = sk[1] if len(sk) > 1 else 0.0
        status = sk[2] if len(sk) > 2 else "ok"
    else:
        name = getattr(sk, "name", "")
        mastery = getattr(sk, "mastery", 0.0)
        status = getattr(sk, "status", "ok")
    try:
        mastery = float(mastery)
    except (TypeError, ValueError):
        mastery = 0.0
    return {"name": str(name), "mastery": mastery, "status": str(status)}


def save_lesson(title: str, skills: list, review_chain: list, suggestion: str = "",
                summary: str = "", highlights: list = None,
                duration: float = 0.0, line_count: int = 0, char_count: int = 0,
                graph: dict = None, breakpoints: list = None, quiz: dict = None) -> float:
    """存一节课的回响摘要，返回这条记录的 time 时间戳（给详情页定位用）。
    skills 支持元组 / dict / 对象列表。最多保留最近 50 条。

    graph 是可选的课前置关系（{"nodes": [...], "edges": [[前, 后], ...]}），
    给课后「知识地图」用；不传也能画，mindmap 会按复习链和讲课顺序推导。

    breakpoints 是这节课的掉队时间线（[{tc,concept,lost_at,resolved_at,duration,outcome}]），
    quiz 是课中抽问汇总（{total, correct}），都给历史课程详情页回放用。
    """
    skills = skills or []
    total = len(skills)
    ok = sum(1 for sk in skills if _skill_status(sk) == "ok")
    now = time.time()
    record = {
        "time": now,
        "title": title or time.strftime("%Y年%m月%d日 %H时%M分%S秒", time.localtime(now)),
        "date": time.strftime("%Y-%m-%d", time.localtime(now)),
        "total": total,
        "ok": ok,
        "review": total - ok,
        "review_chain": list(review_chain or []),
        "suggestion": suggestion or "",
        "summary": summary or "",
        "highlights": [str(x) for x in (highlights or [])],
        "duration": duration,
        "line_count": line_count,
        "char_count": char_count,
        "skills_detail": [_skill_fields(sk) for sk in skills],
        "breakpoints": list(breakpoints or []),
        "quiz": {"total": int((quiz or {}).get("total", 0)),
                 "correct": int((quiz or {}).get("correct", 0))},
    }
    if graph and graph.get("nodes"):
        record["graph"] = {"nodes": [str(n) for n in graph.get("nodes") or []],
                           "edges": [[str(a), str(b)] for a, b in (graph.get("edges") or [])]}
        times = graph.get("times") or {}
        if times:
            # 每个知识点老师讲到的时间点，地图上标出来方便回看录像
            record["graph"]["times"] = {str(k): str(v) for k, v in times.items()}
    cur = _load_lessons()
    cur.append(record)
    _write_json(_lessons_path(), cur[-50:])
    return now


def get_lesson(ts: float) -> dict:
    """按 time 时间戳取一条课程归档，找不到返回 {}。"""
    for it in _load_lessons():
        if abs(it.get("time", 0) - ts) < 0.001:
            return it
    return {}


def list_lessons(limit: int = None) -> list:
    """最近的课，新 → 旧。limit=None 时返回全部。"""
    cur = _load_lessons()
    cur.sort(key=lambda it: it.get("time", 0), reverse=True)
    return cur if limit is None else cur[:limit]


def weekly_skills(days: int = 7) -> list:
    """最近 N 天学过的知识点，跨课去重合并。返回 [{name, mastery, status}]（最近在前）。

    同名知识点（模糊匹配）取最近一次掌握度；状态取最差（review < fixed < ok）——
    这一周在哪节课掉过队，比「最近一次看起来还行」更该让学生看到。
    """
    from echo.backend import mindmap   # 函数内 import，避免 store ↔ mindmap 顶层耦合
    now = time.time()
    cutoff = now - days * DAY
    rank = {"review": 0, "fixed": 1, "ok": 2}   # 越小越该复习
    by_name = {}      # 归一化名 -> {"name","mastery","status","time"}
    for ls in list_lessons():
        t = ls.get("time") or 0
        if t < cutoff:
            continue
        for sk in ls.get("skills_detail") or []:
            name = (sk.get("name") or "").strip()
            if not name or mindmap.is_placeholder_topic(name):
                continue
            key = mindmap._norm(name)
            st = sk.get("status") or "ok"
            rec = by_name.get(key)
            if rec is None:
                by_name[key] = {"name": name, "mastery": sk.get("mastery", 0.0),
                                "status": st, "time": t}
                continue
            if t > rec["time"]:                       # 更新为最近一次
                rec["name"] = name
                rec["mastery"] = sk.get("mastery", 0.0)
                rec["time"] = t
            if rank.get(st, 2) < rank.get(rec["status"], 2):   # 保留最差状态
                rec["status"] = st
    out = sorted(by_name.values(), key=lambda r: -r["time"])
    return [{"name": r["name"], "mastery": r["mastery"], "status": r["status"]} for r in out]


def _same_time(a, b) -> bool:
    """两条记录是否同一节课（time 是 float，留一点浮点误差）。"""
    try:
        return abs(float(a) - float(b)) < 0.001
    except (TypeError, ValueError):
        return False


def delete_lessons(ts_list) -> int:
    """按时间戳批量删除课程归档，返回删掉的条数。"""
    if not ts_list:
        return 0
    cur = _load_lessons()
    kept = [it for it in cur if not any(_same_time(it.get("time", 0), t) for t in ts_list)]
    removed = len(cur) - len(kept)
    if removed:
        _write_json(_lessons_path(), kept)
    return removed


def rename_lesson(ts, new_title: str) -> bool:
    """重命名一节历史课。返回是否改到。"""
    new_title = (new_title or "").strip()
    if not new_title:
        return False
    cur = _load_lessons()
    changed = False
    for it in cur:
        if _same_time(it.get("time", 0), ts):
            it["title"] = new_title
            changed = True
            break
    if changed:
        _write_json(_lessons_path(), cur)
    return changed


def clear_mistakes() -> int:
    """清空错题本，返回删掉的条数。

    「设置 → 清除所有缓存」要走这条路来清错题：文件本身可以删，但删除逻辑得留在
    真正管这个文件的地方，别让调用方自己去拼路径、猜文件名。
    """
    with _LOCK:
        n = len(load())
        if n:
            _write([])
        return n


def clear_lessons() -> int:
    """清空课程归档，返回删掉的节数。"""
    with _LOCK:
        n = len(_load_lessons())
        if n:
            _write_json(_lessons_path(), [])
        return n


def clear_all() -> dict:
    """清空错题本 + 课程归档，返回各删了多少（{"mistakes": n, "lessons": m}）。

    只清 Echo 自己存的这两份学习数据；凭据、设置、头像这些不算「缓存」，不动。
    """
    return {"mistakes": clear_mistakes(), "lessons": clear_lessons()}


def stats() -> dict:
    """课程 + 错题复习情况汇总。"""
    lessons = _load_lessons()
    reviews = load()
    pending = sum(1 for it in reviews if not it.get("reviewed"))
    mastered = sum(1 for it in reviews if it.get("reviewed"))
    return {"lessons": len(lessons), "pending": pending, "mastered": mastered,
            "due": len(due_items())}
