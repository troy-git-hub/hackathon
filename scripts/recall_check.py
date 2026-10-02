"""
Echo - 「讲给 Echo 听」自检

    python scripts/recall_check.py

覆盖：
  A. 挑这一轮聊什么 —— 优先挑共享根源的，认不出共同点就按顺序取
  B. 出题 —— 有 key 时两道（讲一遍 + 迁移），没 key 时兜底也两道且不假装能判
  C. 判断 —— 解析 AI 结果、名字写飘了能兜住、判不出来时不硬判
  D. 落地 —— 判断写进复习调度，手动改的也走同一条路

退出码：全部通过为 0。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")     # 不联网

from echo.backend import paths   # noqa: E402

_DIR = tempfile.mkdtemp(prefix="echo-recall-")
paths.config_dir = lambda: _DIR

from echo.backend import recall, store   # noqa: E402

FAILED = []
DAY = 86400.0


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


class StubLLM:
    """假的 LLM：只把预先准备好的 JSON 交出去，用来验解析逻辑。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def json(self, system, user, **kw):
        self.calls.append((system, user))
        return self.payload


def item(topic, chain=None, missing="", known=""):
    return {"topic": topic, "review_chain": chain or [], "missing": missing, "known": known}


# ---------- A ----------
section("A. 挑这一轮聊什么")
shared = [item("导数", ["导数", "极限"], missing="为什么是 Δy/Δx 的极限？"),
          item("链式法则", ["链式法则", "极限"], missing="复合函数为什么连乘？"),
          item("概率", ["概率", "样本空间"])]
chosen, root = recall.pick(shared, n=3)
check("认出共同根源", root == "极限", root)
check("只挑挂在共同根源上的", sorted(i["topic"] for i in chosen) == ["导数", "链式法则"],
      str([i["topic"] for i in chosen]))

no_shared = [item("甲", ["甲"]), item("乙", ["乙"]), item("丙", ["丙"])]
chosen2, root2 = recall.pick(no_shared, n=2)
check("没有共同根源就不硬凑", root2 == "" and len(chosen2) == 2, f"root={root2!r}")

one = [item("只有一个", ["那个"])]
chosen3, root3 = recall.pick(one, n=3)
check("只有一个知识点时不出错", len(chosen3) == 1 and root3 == "")
check("空列表不出错", recall.pick([], n=3) == ([], ""))

chain5 = [item(f"知识点{i}", [f"知识点{i}", "共同"]) for i in range(5)]
chosen4, root4 = recall.pick(chain5, n=3)
check("超过 n 个时按 n 截断", len(chosen4) == 3 and root4 == "共同",
      f"{len(chosen4)} 个，root={root4!r}")

# ---------- B ----------
section("B. 出题")
_stub_plan = StubLLM({
    "opening": "昨天你在「极限」这里掉过队，先不做题。",
    "questions": [{"topic": "极限", "question": "导数到底表示什么？", "kind": "recall"},
                  {"topic": "极限", "question": "如果换成温度随时间变化呢？", "kind": "transfer"}]})
plan = recall.plan(shared, llm=_stub_plan)
check("有 key 时拿到两道题", len(plan["questions"]) == 2, str(len(plan["questions"])))
check("一题讲一遍、一题迁移",
      [q["kind"] for q in plan["questions"]] == ["recall", "transfer"],
      str([q["kind"] for q in plan["questions"]]))
check("带上开场白", bool(plan["opening"]), plan["opening"])
check("不是离线兜底", plan["offline"] is False)
check("喂给模型的提示里带上了共同根源",
      "极限" in _stub_plan.calls[0][1], _stub_plan.calls[0][1][:80])
check("喂给模型的提示里带上每个错题当时缺的那一步",
      "为什么是 Δy/Δx 的极限" in _stub_plan.calls[0][1], _stub_plan.calls[0][1][:120])

plan_off = recall.plan(shared, llm=None, use_llm=False)
check("没 key 也用兜底出两道", len(plan_off["questions"]) == 2)
check("兜底标记为离线", plan_off["offline"] is True)
check("兜底也有开场白", bool(plan_off["opening"]), plan_off["opening"])
check("空知识点不出题", recall.plan([], use_llm=False)["questions"] == [])

# ---------- C ----------
section("C. 判断")
items = [item("导数"), item("链式法则")]
answers = [{"question": "导数表示什么？", "answer": "曲线的斜率"},
           {"question": "换个场景呢？", "answer": "一直缩小范围"}]
res = recall.judge(items, answers, llm=StubLLM({
    "results": [
        {"topic": "导数", "verdict": "clear", "missing": "", "feedback": "你说到点子上了"},
        {"topic": "链式法则", "verdict": "fuzzy", "missing": "没说清为什么连乘",
         "feedback": "方向对，但漏了链式相乘那层"},
    ],
    "review": "下次从复合函数的结构入手",
}))
check("解析出两条判断", len(res["results"]) == 2, str(len(res["results"])))
check("判断带上缺失点和反馈",
      all(r["feedback"] for r in res["results"]))
check("带上复习建议", bool(res["review"]))
check("不是离线", res["offline"] is False)

bad_name = recall.judge(items, answers, llm=StubLLM({
    "results": [{"topic": "『导数』", "verdict": "clear", "missing": "", "feedback": "好"}],
    "review": "",
}))
check("模型把名字写飘了也能落回真知识点",
      len(bad_name["results"]) == 1 and bad_name["results"][0]["topic"] == "导数",
      str(bad_name["results"]))

bad_verdict = recall.judge(items, answers, llm=StubLLM({
    "results": [{"topic": "导数", "verdict": "excellent", "missing": "", "feedback": "x"}],
    "review": "",
}))
check("不认识的程度词被丢掉，不硬塞", bad_verdict["offline"] is True, str(bad_verdict))

check("没答案时不判", recall.judge(items, [], llm=StubLLM({"results": []}))["offline"] is True)
check("没 key 时不假装判过", recall.judge(items, answers, llm=None, use_llm=False)["offline"] is True)

class Boom:
    def json(self, *a, **k):
        raise RuntimeError("网络挂了")

check("AI 挂了不抛异常，退回离线",
      recall.judge(items, answers, llm=Boom())["offline"] is True)

# ---------- D ----------
section("D. 判断落地到复习调度")
store._write([])
store.add([{"topic": "导数", "missing": "x", "time": time.time() - 10 * DAY},
           {"topic": "链式法则", "missing": "y", "time": time.time() - 10 * DAY}])
now = time.time()
out = recall.apply_results([
    {"topic": "导数", "verdict": "clear"},
    {"topic": "链式法则", "verdict": "unclear"},
], now=now)
d = {it["topic"]: it for it in store.load()}
check("清楚 → level 1、7 天后", d["导数"]["level"] == 1 and
      round((d["导数"]["due"] - now) / DAY) == 7, str(d["导数"]))
check("没理解 → level 0、明天", d["链式法则"]["level"] == 0 and
      round((d["链式法则"]["due"] - now) / DAY) == 1, str(d["链式法则"]))
check("返回值带上下次时间", set(out) == {"导数", "链式法则"}, str(out))

out2 = recall.apply_results([{"topic": "导数", "verdict": "fuzzy"}], now=now)
check("手动改成模糊后调度跟着变", round((out2["导数"] - now) / DAY) == 3,
      str(round((out2["导数"] - now) / DAY)))
check("听不懂的档位被忽略", recall.apply_results([{"topic": "导数", "verdict": "?"}]) == {})

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("「讲给 Echo 听」自检：全部通过")
