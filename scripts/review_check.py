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

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("间隔重复复习自检：全部通过")
