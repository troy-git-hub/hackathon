"""
Echo - 间隔重复复习自检

    python scripts/review_check.py

覆盖：
  A. 三档反馈的下次复习时间 —— 对照产品给的日期表（10/2 答完 → 10/3 · 10/5 · 10/9 · 10/16）
  B. 连续答「清楚」时间隔阶梯往上走，答崩了清零重来
  C. 到期才出现 —— 没到期的不该出现在今天的任务里
  D. 老数据（1.x 只有 reviewed 布尔值）迁移后不丢、不乱
  E. 首页「今天该回响」卡片的数据
  F. 重新记录同一个知识点时，复习进度不被清零
  G. 接口健壮性
  H. 断点找到的那一刻就落盘（不等下课，重开课程/崩溃不丢）
  I. 「✓ 补上了」/「我自己看看」立刻同步状态
  J. 同一个知识点在新一节课又掉队 → 判定复发
  K. 「为什么要复习它」的依据（due_reason）
  L. 概念为空的断点不落盘
  M. 清缓存：公开的清理接口（clear_mistakes / clear_lessons / clear_all）

退出码：全部通过为 0。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")

from echo.backend import paths   # noqa: E402

_DIR = tempfile.mkdtemp(prefix="echo-review-")
paths.config_dir = lambda: _DIR

from echo.backend import store   # noqa: E402

FAILED = []
DAY = 86400.0


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


def days_later(base, ts):
    return round((ts - base) / DAY, 2)


def fresh(topic="条件概率", **kw):
    """清空错题本，放一条新的进去。

    显式给 time：新错题的「该复习时间」就是它被记下来的那一刻，
    不写死的话会取真实当前时间，和测试里假设的 T0 对不上。
    """
    store._write([])
    item = {"topic": topic, "missing": "为什么分母是 P(B)？", "micro_lesson": "讲解…",
            "reason": "老师跳过了推导", "status": "review", "reviewed": False, "time": T0}
    item.update(kw)
    store.add([item])


# ---------- A ----------
section("A. 三档反馈 → 下次复习时间（对照产品日期表）")
T0 = time.mktime(time.strptime("2026-10-02 09:00", "%Y-%m-%d %H:%M"))

fresh()
rec = store.grade("条件概率", store.AGAIN, now=T0)
check("还是没懂 → 明天（10/3）", days_later(T0, rec["due"]) == 1.0, f"{days_later(T0, rec['due'])} 天后")
check("还是没懂 → level 清零", rec["level"] == 0, str(rec["level"]))

fresh()
rec = store.grade("条件概率", store.FUZZY, now=T0)
check("有点模糊 → 3 天后（10/5）", days_later(T0, rec["due"]) == 3.0, f"{days_later(T0, rec['due'])} 天后")

fresh()
rec = store.grade("条件概率", store.CLEAR, now=T0)
check("记得很清楚 → 7 天后（10/9）", days_later(T0, rec["due"]) == 7.0, f"{days_later(T0, rec['due'])} 天后")
check("记得很清楚 → level 升到 1", rec["level"] == 1, str(rec["level"]))

rec = store.grade("条件概率", store.CLEAR, now=T0)
check("连续两次清楚 → 14 天后（10/16）", days_later(T0, rec["due"]) == 14.0,
      f"{days_later(T0, rec['due'])} 天后")

# ---------- B ----------
section("B. 阶梯：连对越多推越远，答崩了清零")
fresh()
seq = []
for i in range(6):
    r = store.grade("条件概率", store.CLEAR, now=T0)
    seq.append(days_later(T0, r["due"]))
check("阶梯递增到上限", seq == [7, 14, 30, 60, 120, 120], str(seq))
check("level 一路累加", store.load()[0]["level"] == 6, str(store.load()[0]["level"]))

r = store.grade("条件概率", store.AGAIN, now=T0)
check("连对很多次后答崩 → 还是明天再来", days_later(T0, r["due"]) == 1.0, f"{days_later(T0, r['due'])}")
check("答崩后 level 清零（下次从 7 天重新爬）", r["level"] == 0, str(r["level"]))
r = store.grade("条件概率", store.CLEAR, now=T0)
check("清零后再答对 → 回到 7 天", days_later(T0, r["due"]) == 7.0, f"{days_later(T0, r['due'])}")

fresh()
store.grade("条件概率", store.CLEAR, now=T0)
r = store.grade("条件概率", store.FUZZY, now=T0)
check("模糊不清零 level（只是 3 天后再问）", r["level"] == 1 and days_later(T0, r["due"]) == 3.0,
      f"level={r['level']} due={days_later(T0, r['due'])}")

# ---------- C ----------
section("C. 到期才出现")
fresh()
check("新错题立刻就该复习", len(store.due_items(now=T0)) == 1)
store.grade("条件概率", store.CLEAR, now=T0)
check("刚答完「清楚」→ 今天不再出现", store.due_items(now=T0) == [])
check("6 天后仍未到期", store.due_items(now=T0 + 6 * DAY) == [])
check("7 天后重新出现", len(store.due_items(now=T0 + 7 * DAY)) == 1)

fresh()
store.grade("条件概率", store.AGAIN, now=T0)
check("答崩的明天就回来", len(store.due_items(now=T0 + 1 * DAY)) == 1)

section("C2. 排序：最该先看的排前面")
store._write([])
store.add([{"topic": "清楚的", "missing": "a"}, {"topic": "没懂的", "missing": "b"},
           {"topic": "模糊的", "missing": "c"}])
store.grade("清楚的", store.CLEAR, now=T0 - 30 * DAY)
store.grade("模糊的", store.FUZZY, now=T0 - 30 * DAY)
store.grade("没懂的", store.AGAIN, now=T0 - 30 * DAY)
order = [it["topic"] for it in store.due_items(now=T0)]
check("没懂 → 模糊 → 清楚", order == ["没懂的", "模糊的", "清楚的"], str(order))

# ---------- D ----------
section("D. 老数据（1.x）迁移")
store._write([
    {"topic": "老·没复习过", "missing": "x", "reviewed": False, "time": T0 - 10 * DAY},
    {"topic": "老·标过掌握", "missing": "y", "reviewed": True,
     "time": T0 - 30 * DAY, "reviewed_at": T0 - 2 * DAY},
])
due = [it["topic"] for it in store.due_items(now=T0)]
check("没复习过的老错题 → 现在就该看", "老·没复习过" in due, str(due))
check("标过掌握的老错题 → 按掌握那天 +7 天算，还没到期", "老·标过掌握" not in due, str(due))
later = [it["topic"] for it in store.due_items(now=T0 + 6 * DAY)]
check("掌握后满 7 天 → 回来复查一次", "老·标过掌握" in later, str(later))
check("迁移不破坏原字段", all(it.get("missing") for it in store.load()))

# ---------- E ----------
section("E. 首页「今天该回响」卡片")
store._write([])
store.add([{"topic": "贝叶斯公式", "missing": "为什么能反过来算？",
            "review_chain": ["导数", "极限"], "time": T0},
           {"topic": "条件概率", "missing": "分母为什么是 P(B)？", "time": T0}])
s = store.due_summary(now=T0)
check("数出今天要确认几个", s["count"] == 2, str(s["count"]))
check("带出知识点名字", set(s["topics"]) == {"贝叶斯公式", "条件概率"}, str(s["topics"]))
check("给出预计时间", s["minutes"] >= 1, str(s["minutes"]))
check("提示里带上掉队的位置", "极限" in s["hint"] and "导数" in s["hint"], s["hint"])

store.grade("贝叶斯公式", store.CLEAR, now=T0)
store.grade("条件概率", store.CLEAR, now=T0)
s2 = store.due_summary(now=T0)
check("全部答完 → 今天没有待办", s2["count"] == 0 and s2["topics"] == [])
check("没有待办时不编提示", s2["hint"] == "", s2["hint"])

# ---------- F ----------
section("F. 同一个知识点再次被记进来")
store._write([])
store.add([{"topic": "贝叶斯公式", "missing": "原始描述"}])
store.grade("贝叶斯公式", store.CLEAR, now=T0)
store.grade("贝叶斯公式", store.CLEAR, now=T0)
before = store.load()[0]
store.add([{"topic": "贝叶斯公式", "missing": "新一节课的描述"}])
after = store.load()[0]
check("复习进度没被清零", after.get("level") == before["level"] == 2,
      f"{before.get('level')} → {after.get('level')}")
check("下次复习时间没被重置", after.get("due") == before["due"])
check("内容更新成最新的", after.get("missing") == "新一节课的描述", after.get("missing"))

section("F2. 又掉队了 = 其实没掌握，进度该清零")
store._write([])
store.add([{"topic": "贝叶斯公式", "missing": "原始描述"}])
store.grade("贝叶斯公式", store.CLEAR, now=T0)      # 连对两次 → 推到 14 天后
store.grade("贝叶斯公式", store.CLEAR, now=T0)
before = store.load()[0]
check("先攒到 level 2", before["level"] == 2, str(before.get("level")))

store.add([{"topic": "贝叶斯公式", "missing": "新一节课又卡在这"}], relapse=True)
after = store.load()[0]
check("又掉队 → level 清零", after["level"] == 0, str(after.get("level")))
# add() 用的是真实当前时间（不是测试里的 T0），所以这里也按真实时间比
check("又掉队 → 立刻回到今天的复习清单", after.get("due", 0) <= time.time() + 1,
      f"due={after.get('due')}")
check("又掉队 → 不该再显示成已复习", after.get("reviewed") is False)
check("又掉队 → 立刻出现在待复习里",
      "贝叶斯公式" in [i["topic"] for i in store.due_items()])

store._write([])
store.add([{"topic": "甲", "missing": "a"}])
store.grade("甲", store.CLEAR, now=T0)
store.grade("甲", store.CLEAR, now=T0)
store.add([{"topic": "甲", "missing": "只是又记了一次"}])      # 不传 relapse
check("不传 relapse 时进度照旧保留", store.load()[0]["level"] == 2,
      str(store.load()[0].get("level")))

section("G. 接口健壮性")
try:
    store.grade("贝叶斯公式", "whatever")
    check("乱传结果会报错", False, "居然没报错")
except ValueError:
    check("乱传结果会报错", True)
check("给不存在的知识点打分不崩", store.grade("查无此题", store.CLEAR, now=T0) == {})
store._write([])
check("空错题本的卡片不崩", store.due_summary(now=T0)["count"] == 0)
check("空错题本的今日任务是空的", store.due_items(now=T0) == [])

section("H. 断点找到的那一刻就落盘（不等下课）")
from echo.backend.engine import EchoEngine          # noqa: E402
from echo.mock_data import BreakPoint               # noqa: E402

store._write([])
eng = EchoEngine(use_llm=False)
bp1 = BreakPoint("12:00", "链式法则", "为什么要连乘？", "老师跳过了推导", "讲解…")
eng._persist_breakpoint(bp1, check_relapse=True)
check("断点一找到就进错题本，不用等下课",
      any(it["topic"] == "链式法则" for it in store.load()))
check("刚发现的断点不是复发（错题本之前是空的）",
      next(it for it in store.load() if it["topic"] == "链式法则").get("level", 0) == 0)

# 模拟「中途重开课程」：以前的 bug 是 engine.reset() 把内存里的断点全清空、
# 而断点只在内存里、从没写过盘，这节课已经找到的全丢了。现在找到那一刻就已经
# 落盘了，重开只清内存，不影响已经存下的记录。
eng.start()
check("重开课程后，刚才那条断点还在错题本里（不会跟着内存一起清空）",
      any(it["topic"] == "链式法则" for it in store.load()))
eng.shutdown()

section("I. 「✓ 补上了」/「我自己看看」立刻同步状态")
store._write([])
eng = EchoEngine(use_llm=False)
bp2 = BreakPoint("13:00", "泰勒展开", "为什么只取前几项？", "讲得快", "讲解…")
eng._persist_breakpoint(bp2, check_relapse=True)
check("刚存的状态是 review",
      next(it for it in store.load() if it["topic"] == "泰勒展开")["status"] == "review")
with eng._lock:
    eng.breakpoints = [bp2]
eng.mark_fixed()
check("点了「补上了」立刻同步成 fixed（不用等下课）",
      next(it for it in store.load() if it["topic"] == "泰勒展开")["status"] == "fixed")
eng.shutdown()

section("J. 端到端：同一个知识点在新一节课又掉队")
store._write([])
store.add([{"topic": "极限", "missing": "第一次掉队"}])
store.grade("极限", store.CLEAR, now=T0)
store.grade("极限", store.CLEAR, now=T0)
check("先攒到 level 2", store.load()[0]["level"] == 2, str(store.load()[0]["level"]))

eng = EchoEngine(use_llm=False)
bp3 = BreakPoint("12:00", "极限", "为什么是无限逼近？", "老师跳过了推导", "讲解…")
eng._persist_breakpoint(bp3, check_relapse=True)   # _find_breakpoint 里真实发生的调用
after = next(it for it in store.load() if it["topic"] == "极限")
check("复发 → 进度清零", after["level"] == 0, str(after["level"]))
check("复发 → 回到今天的清单", after["due"] <= time.time() + 1, str(after.get("due")))
check("复发 → 描述更新成这次的",
      after.get("missing") == "为什么是无限逼近？", after.get("missing"))

# 后续同步状态（mark_fixed 之类）不该把它当成又一次新的复发重新清零
with eng._lock:
    eng.breakpoints = [bp3]
eng.mark_fixed()
after2 = next(it for it in store.load() if it["topic"] == "极限")
check("状态同步不重新触发复发判断", after2["level"] == 0 and after2["status"] == "fixed",
      str(after2))
eng.shutdown()

section("K. 「为什么要复习它」的依据")
fresh("第一次见")
reason0 = store.due_reason(store.load()[0], now=T0)
check("从没确认过 → 说清楚是第一次", "第一次" in reason0, reason0)

store.grade("第一次见", store.AGAIN, now=T0)
reason1 = store.due_reason(store.load()[0], now=T0 + 1 * DAY)
check("上次没懂 → 依据里说没想起来", "没想起来" in reason1, reason1)

store.grade("第一次见", store.FUZZY, now=T0 + 1 * DAY)
reason2 = store.due_reason(store.load()[0], now=T0 + 4 * DAY)
check("上次模糊 → 依据里说模糊", "模糊" in reason2, reason2)

store.grade("第一次见", store.CLEAR, now=T0 + 4 * DAY)
reason3 = store.due_reason(store.load()[0], now=T0 + 11 * DAY)
check("上次清楚、过了几天 → 依据里带上天数", "7 天" in reason3, reason3)
check("见过不止一次 → 依据里说第几次见到它", "第 4 次" in reason3, reason3)

section("L. 概念为空的断点不落盘")
eng = EchoEngine(use_llm=False)
bp_empty = BreakPoint("01:00", "", "x", "y", "z")
n_before = len(store.load())
eng._persist_breakpoint(bp_empty, check_relapse=True)
check("concept 为空的断点不落盘", len(store.load()) == n_before)
eng.shutdown()


section("M. 清缓存：公开的清理接口（设置页「清除所有缓存」用）")
fresh("待清理甲")
store.add([{"topic": "待清理乙", "missing": "x"}])
n = len(store.load())
check("清错题本返回删掉的条数", store.clear_mistakes() == n, f"返回 {n}")
check("清完错题本是空的", store.load() == [])

eng = EchoEngine(use_llm=False)
ts_c = store.save_lesson("待清理课", [{"name": "甲", "mastery": 0.5, "status": "ok"}], [])
check("清课程归档返回删掉的节数", store.clear_lessons() == 1)
check("清完查不到那节课了", not store.get_lesson(ts_c))

fresh("再来一条")
store.save_lesson("再来一课", [{"name": "乙", "mastery": 0.5, "status": "ok"}], [])
counts = store.clear_all()
check("clear_all 一次清两份", counts == {"mistakes": 1, "lessons": 1}, str(counts))
check("clear_all 之后都是空的", store.load() == [] and store.list_lessons() == [])

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("间隔重复复习自检：全部通过")
