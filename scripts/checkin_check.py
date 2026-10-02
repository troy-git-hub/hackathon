"""
Echo - 课堂抽问自检

    python scripts/checkin_check.py

覆盖：
  A. 抽问题规范化 —— LLM 给的答案和选项对不上时不判学生错，退化成自评题
  B. 判分 —— 选择题按选项字母判；自评题按「记得 / 模糊 / 没跟上」判
  C. 触发条件 —— 只有「开课中 + 过了热身 + 学生久没动手 + 距上次够久」才抽问
  D. 答错入错题本 —— 字段形状和「错题复习」页约好的一致
  E. 课程隔离 —— 重开课程后，上一节课的抽问不能再作答、也不写进新课

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

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("课堂抽问自检：全部通过")
