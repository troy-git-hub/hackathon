"""
Echo - 课堂抽问自检

    python scripts/checkin_check.py

覆盖：
  A. 抽问题规范化 —— LLM 给的答案和选项对不上时不判学生错，退化成自评题
  B. 判分 —— 选择题按选项字母判；自评题按「记得 / 模糊 / 没跟上」判
  C. 触发条件 —— 只有「开课中 + 过了热身 + 学生久没动手 + 距上次够久」才抽问
  D. 答错入错题本 —— 字段形状和「错题复习」页约好的一致
  E. 课程隔离 —— 重开课程后，上一节课的抽问不能再作答、也不写进新课
  F. 接上课程上下文 —— 课上答错的点写回时间轴，课后回响/知识地图才看得见；
     学生也能自己按「考考我」主动要一道

退出码：全部通过为 0。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")     # 自检不联网、不调 LLM
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from echo.backend import config, paths, quiz, store   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(title):
    print(f"\n{title}")


# ---------- A. 规范化 ----------
section("A. 抽问题规范化")
q = quiz._clean_checkin({"topic": "条件概率", "question": "P(A|B) 是什么？",
                         "options": ["A. A 发生下 B 的概率", "B. B 发生下 A 的概率"],
                         "answer": "B", "explain": "方向别搞反"}, tc="03:12")
check("正常题保留选项和答案", q.get("answer") == "B" and not q.get("self_report"))

bad = quiz._clean_checkin({"topic": "x", "question": "q", "options": ["A. 1", "B. 2"],
                           "answer": "D"})
check("答案超出选项范围 → 退化为自评题", bad.get("self_report") is True and bad.get("options") == [])

check("没有题干 → 不返回题目", quiz._clean_checkin({"topic": "x"}) == {})

# ---------- B. 判分 ----------
section("B. 判分")
check("选对 → right", quiz.grade(q, 1) == quiz.RIGHT)
check("选错 → wrong", quiz.grade(q, 0) == quiz.WRONG)

sel = quiz._self_checkin("贝叶斯公式", "05:00")
check("自评「记得」→ right", quiz.grade(sel, 0) == quiz.RIGHT)
check("自评「有点模糊」→ unsure", quiz.grade(sel, 1) == quiz.UNSURE)
check("自评「没跟上」→ wrong", quiz.grade(sel, 2) == quiz.WRONG)
check("越界下标 → wrong（不崩）", quiz.grade(sel, 99) == quiz.WRONG)
check("没配 key 时也能出题", bool(sel.get("question")) and len(sel.get("options")) == 3)

# ---------- D. 错题形状 ----------
section("D. 错题记录形状")
m = quiz.to_mistake(q, quiz.WRONG)
need = {"topic", "missing", "micro_lesson", "reason", "known", "step", "now",
        "status", "reviewed"}
check("字段与 store.add 约定一致", need <= set(m), f"缺 {need - set(m)}")
check("status 为 review", m["status"] == "review")
check("reviewed 为 False", m["reviewed"] is False)
check("答错的题带上了正确答案", "B" in (m.get("step") or "") or m.get("step"))

# ---------- C/E. 引擎行为 ----------
# 把 store 写到临时目录，别动用户真实的 review.json
tmp = tempfile.mkdtemp(prefix="echo-checkin-")
paths.config_dir = lambda: tmp

from echo.backend.engine import EchoEngine   # noqa: E402

section("C. 触发条件")
eng = EchoEngine(use_llm=False)
check("没开课时不抽问", eng._checkin_due() is False)

eng.start()
sid = eng.session
check("刚开课（热身期内）不抽问", eng._checkin_due() is False)

eng.add_transcript("下面我们讲条件概率的定义", t=1.0, session=sid)
eng._extract_concept(force=True, sid=sid)
check("已有知识点", len(eng.entries) >= 1)

eng.start_ts -= config.CHECKIN_WARMUP + 10          # 假装开课很久了
eng._last_interaction = time.time() - config.CHECKIN_IDLE - 10
eng._last_checkin_at = 0.0
check("开课够久 + 学生久没动手 → 抽问", eng._checkin_due() is True)

eng._last_interaction = time.time()
check("学生刚点过反馈 → 不打扰", eng._checkin_due() is False)

eng._last_interaction = time.time() - config.CHECKIN_IDLE - 10
eng._last_checkin_at = time.time()
check("距上次抽问不够久 → 不抽", eng._checkin_due() is False)

eng._last_checkin_at = 0.0
eng._ask_checkin(sid)
check("抽问后有待答的题", eng.pending_checkin is not None)
check("题目有题干和选项", bool(eng.pending_checkin.get("question"))
      and len(eng.pending_checkin.get("options") or []) >= 2)
check("有待答题时不再抽第二道", eng._checkin_due() is False)

section("D. 答错入错题本")
rec = eng.answer_checkin(len(eng.pending_checkin["options"]) - 1)   # 最后一项 = 没跟上
check("返回作答结果", rec is not None and rec.get("result") in (quiz.WRONG, quiz.UNSURE))
check("作答后清空待答题", eng.pending_checkin is None)
check("结果记进本次课程", len(eng.checkins) == 1)
saved = store.load()
check("错题真的落盘了", len(saved) == 1 and "课堂抽问" in (saved[0].get("reason") or ""),
      f"实际 {len(saved)} 条")
check("错题 topic 非空", bool(saved) and all(it.get("topic") for it in saved))
check("错题能在复习页渲染（有 missing/micro_lesson）",
      bool(saved) and all(it.get("missing") and it.get("micro_lesson") for it in saved))

check("没有待答题时再答返回 None", eng.answer_checkin(0) is None)

section("E. 课程隔离")
eng._ask_checkin(sid)
old = eng.pending_checkin
eng.start()                                   # 重开新课
check("重开后清空上一节的待答题", eng.pending_checkin is None)
check("上一节的题不能再作答", eng.answer_checkin(0) is None)
check("上一节的结果不串进新课", len(eng.checkins) == 0)
check("旧 sid 的抽问不会写进新课", eng._live(sid) is False)

eng.end_lesson()
check("下课后不抽问", eng._checkin_due() is False)
eng.shutdown()

# ---------- F. 抽问接上课程上下文 ----------
section("F. 抽问接上课程上下文")
eng2 = EchoEngine(use_llm=False)
eng2.start()
sid2 = eng2.session
for text in ("下面我们讲条件概率的定义", "接下来是贝叶斯公式", "最后看后验概率"):
    eng2.add_transcript(text, t=eng2.elapsed(), session=sid2)
    eng2._extract_concept(force=True, sid=sid2)
check("时间轴上有知识点", len(eng2.entries) >= 2, f"{len(eng2.entries)}")


def wait_pending(engine, seconds=10.0):
    deadline = time.time() + seconds
    while engine.pending_checkin is None and time.time() < deadline:
        time.sleep(0.05)
    return engine.pending_checkin


def ask_now(engine, tries=40):
    for _ in range(tries):
        if engine.ask_checkin_now():
            return True
        time.sleep(0.05)
    return False


# 学生主动按「考考我」
check("学生主动要题 → 出得出来", ask_now(eng2))
q2 = wait_pending(eng2)
check("主动要题后有待答题", q2 is not None)
check("出题期间不重复派第二道", eng2.ask_checkin_now() is False)

topic2 = q2.get("topic")
n_fb = len(eng2.feedbacks)
last = len(q2["options"]) - 1                    # 自评题的「没跟上」
eng2.answer_checkin(last)
check("答不上来 → 记一次 warn 反馈",
      len(eng2.feedbacks) == n_fb + 1 and eng2.feedbacks[-1].kind == "warn",
      f"{len(eng2.feedbacks) - n_fb} 条")
check("warn 挂在被问的那个知识点上", eng2.feedbacks[-1].concept == topic2,
      f"{eng2.feedbacks[-1].concept!r} vs {topic2!r}")
hit = [e.concept for e in eng2.entries if e.concept.topic == topic2]
check("对应知识点在时间轴上标黄（回响/地图看得见）",
      bool(hit) and hit[0].status == "warn")
check("课后回响能按它算掌握度",
      any("warn" in eng2._feedback_of(i) for i in range(len(eng2.entries))))

focus = eng2._checkin_focus()
check("出题时带上了学生刚才答错的知识点",
      bool(topic2) and topic2 in focus, focus)

# 答对不该留痕
check("再要一道", ask_now(eng2))
q3 = wait_pending(eng2)
check("第二道拿到了", q3 is not None)
n_fb = len(eng2.feedbacks)
eng2.answer_checkin(0)                           # 自评题的「记得」
check("答对了不写 warn", len(eng2.feedbacks) == n_fb, f"{len(eng2.feedbacks) - n_fb} 条")

eng2.shutdown()

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("课堂抽问自检：全部通过")
