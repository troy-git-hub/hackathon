"""Echo 学习助手 agent：JSON-mode ReAct 闭环（嵌入 Echo 主窗口）。

用户在聊天里说需求 → 模型返回 {"tool": 名, "args": {...}} 或 {"reply": "文本"} →
通过 ctx 服务执行 → 结构化事件（on_event）回界面渲染成预览卡 → 最多 6 轮 → 最终回复。
不用原生 function-calling：走现有 LLM.json（JSON mode + echo_purpose=assistant），
账户计费、自定义 key、mock 全兼容。ctx 由宿主界面提供（窗口跳转、开始课程、
云端 API 等）；工具只做读取和用户明确要求的事情。
"""
import json
import time

from echo.backend.llm import LLM, LLMError
from echo.backend import knowledge, booklets, store, study_plans, docx_export

MAX_STEPS = 6

SYSTEM_PROMPT = """你是 Echo 的学习助手 agent，运行在学生的学习客户端里，可以直接操作 Echo 的功能。
可用工具（一次只调一个，参数用 JSON）：
{"tool": "learning_progress", "args": {}} — 学习概况：课程数、最近主题、错题薄弱点
{"tool": "today_reviews", "args": {}} — 今天该复习哪些知识点
{"tool": "search_knowledge", "args": {"query": "关键词"}} — 在用户的资料库与历史课程里检索
{"tool": "make_quiz", "args": {"topic": "知识点", "count": 5}} — 针对知识点出练习题（含答案解析）
{"tool": "create_plan", "args": {"goal": "目标", "days": 7}} — 生成学习计划书并保存到「学习计划」（不是小本；用户要记笔记才用 make_booklet）
{"tool": "open_view", "args": {"view": "错题复习|练习|课程管理|知识地图|已学内容|一周回响|主页"}} — 帮学生直接打开对应界面
{"tool": "start_lesson", "args": {"title": "课名"}} — 直接开始一节新课（先跟用户确认过再调用）
{"tool": "create_paper", "args": {"subject": "数学", "goal": "期中复习卷"}} — 调用清卷直接生成完整试卷（打开清卷窗口，AI 命题约 1-2 分钟）
{"tool": "open_ai_class", "args": {"topic": "课名"}} — 打开 AI 互动课堂，按主题生成会回应学生的课（板书、提问、随堂测）
{"tool": "add_material", "args": {"title": "标题", "text": "内容"}} — 把这段内容存进用户的资料库（课前资料）
{"tool": "read_material", "args": {"title": "标题"}} — 完整读取用户资料库里某篇文档的原文
{"tool": "lesson_memories", "args": {"count": 5}} — 读取最近几堂课的记忆（每堂课的总结、重点、薄弱点），写计划前先调它
{"tool": "export_docx", "args": {"title": "标题", "text": "正文"}} — 把这段内容写成可下载的 Word（.docx），用于打印或再编辑。学习计划、笔记、讲义都可以。
没有合适工具或信息已足够时，直接回复：
{"reply": "给学生的回复（中文、口语化、鼓励式）"}
规则：
- 用户已经说要做什么（出题/做计划/查进度/开课）时立刻调对应工具，不要先给菜单，不要先推荐天数。没说天数就按 7 天直接 create_plan。
- 涉及用户事实（学了什么/资料内容/薄弱点）先调工具，不编造。
- 工具结果已经画在界面卡片里。reply 不要复述工具返回的清单，只说一句结论和下一步。
- 同一轮里已经调过的工具不要再调。
- 学生说「1」「1,2开始」「第二项」时，按你上一轮给的编号直接执行。
- create_plan 写入学习计划；只有用户明确说「记到小本/做笔记」才调 make_booklet。
- 一次只输出一个 JSON 对象。
- 学生说得含糊、而且你还没给过选项时，才在 reply 里问一个具体追问。"""

# 工具结果 → 预览卡类型（界面据此渲染不同卡片）
TOOL_KINDS = {
    "learning_progress": "progress",
    "today_reviews": "progress",
    "search_knowledge": "search",
    "make_quiz": "quiz",
    "create_plan": "plan",
    "open_view": "view",
    "start_lesson": "view",
    "open_ai_class": "view",
    "create_paper": "paper",
    "add_material": "material",
    "make_booklet": "booklet",
    "export_docx": "docx",
    "lesson_memories": "memory",
    "read_material": "text",
}

TOOL_LABELS = {
    "learning_progress": "正在查看学习进度",
    "today_reviews": "正在整理今天的复习",
    "search_knowledge": "正在检索资料",
    "make_quiz": "正在出练习题",
    "create_plan": "正在编写学习计划书",
    "open_view": "正在打开界面",
    "start_lesson": "正在开始课程",
    "open_ai_class": "正在打开 AI 互动课堂",
    "create_paper": "正在调用清卷出卷",
    "add_material": "正在保存到资料库",
    "make_booklet": "正在生成复习小册",
    "export_docx": "正在写成 Word",
    "lesson_memories": "正在读取课堂记忆",
}


def _default_progress() -> str:
    lessons = store.list_lessons()
    review = store.load()
    recent = [str(item.get("title", "")) for item in lessons[:5]]
    weak = []
    for item in review[:8]:
        topic = str(item.get("topic", ""))[:24]
        missed = int(item.get("review_count", 0) or 0)
        if topic:
            weak.append(topic + ("（复习 " + str(missed) + " 次）" if missed else ""))
    lines = ["历史课程 " + str(len(lessons)) + " 节；最近：" + ("、".join(recent) or "（无）") + "。"]
    lines.append("错题本：" + ("、".join(weak) if weak else "目前是空的。"))
    return "\n".join(lines)


def _default_search(query: str) -> str:
    blocks = knowledge.retrieve(query, limit=4)
    if not blocks:
        return "资料库里没有找到与「" + query + "」相关的内容。"
    out = []
    for block in blocks:
        if isinstance(block, dict):
            title, text = block.get("title", ""), block.get("text", "")
        else:
            title, text = getattr(block, "title", ""), getattr(block, "text", "")
        out.append("【" + str(title) + "】" + str(text)[:400])
    return "\n".join(out)


def _lesson_memories(count: int = 5) -> str:
    count = max(1, min(10, int(count or 5)))
    lessons = store.list_lessons()[:count]
    if not lessons:
        return "还没有课程记录。"
    out = []
    for i, item in enumerate(lessons, 1):
        title = str(item.get("title", ""))[:40]
        summary = str(item.get("summary", ""))[:220]
        highlights = [str(h)[:60] for h in (item.get("highlights") or [])[:3]]
        weak = [str(s.get("name", ""))[:30] for s in (item.get("skills_detail") or [])
                if isinstance(s, dict) and s.get("status") in ("weakness", "developing")]
        chunk = f"课程{i}「{title}」：{summary}"
        if highlights:
            chunk += " 重点：" + "；".join(highlights)
        if weak:
            chunk += " 薄弱：" + "、".join(weak)
        out.append(chunk[:500])
    return "\n".join(out)


def _default_plan(llm, goal: str, days: int) -> str:
    data = llm.json(
        "你是学习规划师。参考提供的课堂记忆（学生实际学过的内容和薄弱点）来定制计划。"
        "输出 JSON：{\"days\":[{\"day\":1,\"focus\":\"主题\",\"tasks\":[\"任务1\",\"任务2\"]}]}，"
        "共 " + str(days) + " 天，围绕目标循序渐进，每天 2-4 个可执行任务，任务要具体。",
        "学习目标：" + goal + "\n\n课堂记忆（最近学过的课）：\n" + _lesson_memories(3),
        temperature=0.4, max_tokens=1500, purpose="assistant")
    plan_days = data.get("days") or []
    lines = ["学习计划 · " + goal + "（" + str(len(plan_days)) + " 天）", ""]
    for day in plan_days:
        tasks = "；".join(str(t) for t in (day.get("tasks") or []))
        lines.append("第 " + str(day.get("day")) + " 天 · " + str(day.get("focus")) + "：" + tasks)
    text = "\n".join(lines)[:20000]
    try:
        study_plans.save(goal, days, text)
        saved = "（已保存到学习计划）"
    except Exception:
        saved = "（计划未写入学习计划，内容见预览。）"
    return text + "\n" + saved


def _default_quiz(topic: str, count: int) -> str:
    from echo.backend import account
    from echo.backend.assistant_quiz import pack_quiz
    if account.managed_models():
        import uuid
        response = account.request('/v1/echo/test', {'protocol':'echo.test/1','request_id':uuid.uuid4().hex,
            'operation':'quiz','payload':{'topic':topic,'count':max(1,min(5,count))}}, timeout=65,max_bytes=65536)
        if response.get('protocol')!='echo.test/1':raise LLMError('练习服务响应不正确。')
        return pack_quiz(topic,response['result'].get('questions',[]))
    lesson = None
    for item in store.list_lessons():
        topics = [str(t.get("topic", "")) for t in (item.get("timeline") or [])]
        if topic in topics:
            lesson = item
            break
    item = {"topic": topic, "missing": "", "subject": (lesson or {}).get("subject", "")}
    from echo.backend import practice
    questions = practice.generate_sync(item, n=count)
    if not questions:
        return "「" + topic + "」的题目生成失败，请稍后再试。"
    return pack_quiz(topic, questions)


def _today_reviews() -> str:
    review = store.load()
    due = [r for r in review if (r.get("due") or 0) <= time.time() + 86400]
    if not due:
        return "今天没有到期的复习内容，错题本状态良好。"
    lines = ["今天该复习 " + str(len(due)) + " 个知识点："]
    for item in due[:8]:
        topic = str(item.get("topic", ""))[:30]
        missing = str(item.get("missing", ""))[:40]
        lines.append("· " + topic + "（" + missing + "）")
    return "\n".join(lines)


def run_tool(name: str, args: dict, ctx=None, llm=None) -> str:
    args = args or {}
    ctx = ctx or {}
    if name == "learning_progress":
        service = ctx.get("progress")
        return service() if service else _default_progress()
    if name == "today_reviews":
        service = ctx.get("today_reviews")
        return service() if service else _today_reviews()
    if name == "lesson_memories":
        service = ctx.get("lesson_memories")
        return service(int(args.get("count", 5) or 5)) if service else _lesson_memories(int(args.get("count", 5) or 5))
    if name == "search_knowledge":
        service = ctx.get("search")
        return (service(str(args.get("query", ""))[:120]) if service
                else _default_search(str(args.get("query", ""))[:120]))
    if name == "create_plan":
        goal = str(args.get("goal", ""))[:120]
        days = max(1, min(60, int(args.get("days", 7) or 7)))
        service = ctx.get("create_plan")
        return service(goal, days) if service else _default_plan(llm, goal, days)
    if name == "make_quiz":
        topic = str(args.get("topic", ""))[:80]
        count = max(1, min(10, int(args.get("count", 5) or 5)))
        service = ctx.get("make_quiz")
        return service(topic, count) if service else _default_quiz(topic, count)
    if name == "add_material":
        title = str(args.get("title", ""))[:80] or "未命名资料"
        text = str(args.get("text", ""))[:5000]
        if not text.strip():
            return "没有可保存的内容。"
        knowledge.add(title, text)
        return "已存进资料库【" + title + "】，之后检索和课堂答疑都能用到。"
    if name == "create_paper":
        maker = ctx.get("create_paper")
        if not maker:
            return "这里打不开清卷（在主窗口里使用我才能出卷）。"
        return str(maker(str(args.get("subject", ""))[:12], str(args.get("goal", ""))[:60]))
    if name == "make_booklet":
        title = str(args.get("title", ""))[:60] or "复习小册"
        topics = [str(t).strip()[:40] for t in (args.get("topics") or []) if str(t).strip()][:12]
        if not topics:
            return "没有给出主题，无法生成小册。"
        booklets.generate(title, "AI 助手", topics, use_ai=bool(ctx.get("engine")))
        return "已生成复习小册【" + title + "】（主题 " + str(len(topics)) + " 个），存进我的小本。"
    if name == "export_docx":
        title = str(args.get("title", ""))[:80] or "Echo 文档"
        text = str(args.get("text", ""))[:20000]
        if not text.strip():
            return "没有可写入 Word 的正文。"
        path = docx_export.save(title, text)
        return "已写成 Word【" + title + "】\n" + str(path)
    if name == "read_material":
        title = str(args.get("title", ""))[:80]
        for doc in knowledge.documents():
            if str(doc.get("title", "")) == title:
                return "【" + title + "】\n" + str(doc.get("text", ""))[:3000]
        return "资料库里没有找到【" + title + "】。可以用 search_knowledge 先检索。"
    if name == "open_view":
        opener = ctx.get("open_view")
        if not opener:
            return "这里没有界面可跳转（在主窗口里使用我就能打开）。"
        return str(opener(str(args.get("view", ""))[:20]))
    if name == "start_lesson":
        starter = ctx.get("start_lesson")
        if not starter:
            return "这里没有开课按钮（在主窗口里使用我才能开课）。"
        return str(starter(str(args.get("title", ""))[:40]))
    if name == "open_ai_class":
        opener = ctx.get("open_ai_class")
        if not opener:
            return "这里打不开互动课堂（在主窗口里使用我才能打开）。"
        topic = str(args.get("topic", "")).strip()[:160]
        if len(topic) < 2:
            return "先告诉我这节课想弄懂什么，至少两个字。"
        return str(opener(topic))
    return "未知工具 " + name + "。"


def run_agent(history: list, on_event=None, ctx=None) -> str:
    """跑一轮 agent 对话。on_event(dict) 收结构化事件：
      {"type":"tool_start","name":...,"label":...}
      {"type":"tool_result","name":...,"kind":...,"result":...}
      {"type":"error","text":...}
    ctx 服务键：progress/today_reviews/search/create_plan/make_quiz/open_view/start_lesson。"""
    ctx = ctx or {}
    messages = list(history[-12:])
    observations = []
    llm = None
    used = set()
    for _step in range(MAX_STEPS):
        system = SYSTEM_PROMPT
        if observations:
            system += ("\n\n已执行的工具结果（界面已经用卡片展示，reply 不要复述原文）：\n"
                       + "\n".join(observations)
                       + "\n已调用过的工具：" + "、".join(sorted(used))
                       + "。这些不要再调。信息够了就直接 {\"reply\": \"...\"}。")
        payload = {"对话历史": messages, "工具说明": system}
        try:
            if llm is None:
                llm = LLM()   # 未配置模型时这里抛 LLMError——必须捕获成 error 事件，
                              # 否则后台线程异常、聊天永远卡在「思考中…」
            from echo.backend import account
            if account.managed_models():
                import uuid
                response = account.request('/v1/me/assistant/step', {
                    'protocol': 'echo.assistant/1', 'request_id': uuid.uuid4().hex,
                    'history': messages[-12:], 'observations': observations[-6:]}, timeout=65, max_bytes=65536)
                if response.get('protocol') != 'echo.assistant/1':
                    raise LLMError('助手协议响应不正确。')
                data = response['result']
            else:
                data = llm.json("你只输出一个 JSON 对象。", json.dumps(payload, ensure_ascii=False),
                                temperature=0.3, max_tokens=1200, purpose="assistant")
        except LLMError as exc:
            if on_event:
                on_event({"type": "error", "text": str(exc)})
            return str(exc)
        if not isinstance(data, dict):
            return "（助手走神了，重试一下？）"
        if data.get("reply"):
            return str(data["reply"])
        name = str(data.get("tool", ""))
        if not name:
            return str(data.get("think") or "（没想好怎么回应，再说一遍？）")
        args = data.get("args") or {}
        if not isinstance(args, dict):
            observations.append("工具参数必须为 JSON 对象，请修正参数后再调用。")
            continue
        if name in used:
            observations.append("[" + name + "] 这一轮已经调用过，结果见上方卡片。请直接回复或换一个还没用过的工具。")
            continue
        used.add(name)
        if on_event:
            on_event({"type": "tool_start", "name": name, "label": TOOL_LABELS.get(name, name)})
        try:
            result = run_tool(name, args, ctx, llm)
        except LLMError as exc:
            result = "工具执行失败：" + str(exc)
        except Exception as exc:
            result = "工具执行失败：" + type(exc).__name__ + " " + str(exc)
        if on_event:
            on_event({"type": "tool_result", "name": name,
                      "kind": TOOL_KINDS.get(name, "text"), "result": result})
        observations.append("[" + name + "] " + result[:1500])
        messages.append({"role": "assistant",
                         "content": "（调用工具 " + name + "，参数 " + json.dumps(args, ensure_ascii=False) + "）"})
        messages.append({"role": "user", "content": "工具结果：\n" + result[:1500] + "\n\n请继续。"})
    return "这个需求比较复杂，我先做到这里——你可以拆成几步再让我继续。"
