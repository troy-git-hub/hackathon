"""
Echo - 「反复缺失的前置知识」自检

    python scripts/gaps_check.py

覆盖：
  A. 三节课的薄弱点指向同一个前置 → 出一条结论，课次数、知识点列对
  B. 只有两节课不出结论（阈值边界）
  C. 「极限」和「极限条件」归成同一条（用户例子里就是这么回事）
  D. 没有 graph 的旧课（只有 review_chain）也能算出来
  E. 全部掌握（status 都是 ok）的课不产生结论
  F. 薄弱点自己就是根源（没有前置）→ 不产生结论
  G. 只看最近 WINDOW 节课
  H. 只取「根源」前置：中间那一层不算，免得通用概念通吃
  I. 课次数多的排前面
  J. 模板句子永远非空；离线时 narrate 返回空串、不抛

退出码：全部通过为 0。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")

from echo.backend import gaps                       # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


def lesson(ts, weak, pre, chain=None):
    """一节课：pre 是前置（掌握）、weak 是没掌握的。chain 传了就造旧课（没有 graph）。"""
    ls = {"time": ts, "title": f"课 {ts}",
          "skills_detail": [{"name": pre, "mastery": 0.9, "status": "ok"},
                            {"name": weak, "mastery": 0.3, "status": "review"}]}
    if chain is None:
        ls["graph"] = {"nodes": [pre, weak], "edges": [[pre, weak]]}
    else:
        ls["review_chain"] = chain
    return ls


section("A. 三节课都指向同一个前置")
three = [lesson(100, "导数定义", "极限"),
         lesson(200, "瞬时变化率", "极限"),
         lesson(300, "洛必达法则", "极限")]
out = gaps.recurring(three)
check("出一条结论", len(out) == 1, str(out))
f = out[0] if out else {}
check("概念名是「极限」", f.get("concept") == "极限", str(f.get("concept")))
check("算作 3 节课", f.get("lessons") == 3, str(f.get("lessons")))
check("三个知识点都列出来了",
      f.get("topics") == ["导数定义", "瞬时变化率", "洛必达法则"], str(f.get("topics")))
check("时间范围对", (f.get("first_seen"), f.get("last_seen")) == (100.0, 300.0), str(f))


section("B. 只有两节课不出结论")
check("两节 -> 空", gaps.recurring(three[:2]) == [], str(gaps.recurring(three[:2])))
check("阈值可调：两节 + threshold=2 -> 出结论",
      len(gaps.recurring(three[:2], threshold=2)) == 1)


section("C. 「极限」和「极限条件」是同一个概念")
mixed = [lesson(100, "导数定义", "极限"),
         lesson(200, "瞬时变化率", "极限"),
         lesson(300, "洛必达法则", "极限条件")]
out = gaps.recurring(mixed)
check("合成一条，不是两条", len(out) == 1, str(out))
check("显示名取更短的那个（概念本身）", out and out[0]["concept"] == "极限",
      str(out[0]["concept"]) if out else "")
check("课次数算满 3", out and out[0]["lessons"] == 3, str(out[0]["lessons"]) if out else "")


section("D. 没有 graph 的旧课也能算")
old = [lesson(100, "导数定义", "极限", chain=["导数定义", "极限"]),
       lesson(200, "瞬时变化率", "极限", chain=["瞬时变化率", "极限"]),
       lesson(300, "洛必达法则", "极限", chain=["洛必达法则", "极限"])]
out = gaps.recurring(old)
check("旧课（只有 review_chain）出结论", len(out) == 1, str(out))
check("认出的还是「极限」", out and out[0]["concept"] == "极限", str(out))

# 旧课没有依赖图，只认它**自己报的根源概念**。连根源都没报的旧课，宁可不说，
# 也不要顺着讲课顺序编出来的边去认前置 —— 那是地图页排版用的，不是真的前置关系。
bare = [{"time": t, "skills_detail": [{"name": "导数定义", "mastery": 0.2, "status": "review"}]}
        for t in (100, 200, 300)]
check("旧课连 review_chain 都没有 -> 空", gaps.recurring(bare) == [], str(gaps.recurring(bare)))


section("E. 全都掌握了就不出结论")
ok = [{"time": 100, "skills_detail": [{"name": "导数定义", "mastery": 1.0, "status": "ok"},
                                      {"name": "极限", "mastery": 1.0, "status": "ok"}],
       "graph": {"nodes": ["极限", "导数定义"], "edges": [["极限", "导数定义"]]}}] * 3
check("全 ok -> 空", gaps.recurring(ok) == [], str(gaps.recurring(ok)))


section("F. 薄弱点自己就是根源时不乱认")
# 薄弱点「极限」没有任何前置 —— 它自己就是地基，没有「更上游的前置」可指
no_pre = [{"time": t, "graph": {"nodes": ["极限"], "edges": []},
           "skills_detail": [{"name": "极限", "mastery": 0.2, "status": "review"}]}
          for t in (100, 200, 300)]
check("没有前置 -> 空", gaps.recurring(no_pre) == [], str(gaps.recurring(no_pre)))


section("G. 只看最近 WINDOW 节课")
many = [lesson(t, f"知识点{t}", "极限") for t in range(1, 21)]     # 20 节，全指向极限
check("窗口默认 10 节", gaps.recurring(many)[0]["lessons"] == gaps.WINDOW,
      str(gaps.recurring(many)[0]["lessons"]))
check("窗口可调", gaps.recurring(many, window=4)[0]["lessons"] == 4)


section("H. 只认「根源」前置，中间层不算")
# 极限 → 导数定义 → 洛必达法则；薄弱点是洛必达法则。
# 直接前置是「导数定义」，但真正不稳的地基是链条最上游的「极限」。
chain3 = [{"time": t,
           "graph": {"nodes": ["极限", "导数定义", "洛必达法则"],
                     "edges": [["极限", "导数定义"], ["导数定义", "洛必达法则"]]},
           "skills_detail": [{"name": "极限", "mastery": 0.9, "status": "ok"},
                             {"name": "导数定义", "mastery": 0.9, "status": "ok"},
                             {"name": "洛必达法则", "mastery": 0.2, "status": "review"}]}
          for t in (100, 200, 300)]
out = gaps.recurring(chain3)
check("追到最上游的「极限」", out and out[0]["concept"] == "极限", str(out))
check("中间层「导数定义」没有被当成根源另出一条", len(out) == 1, str(out))


section("I. 课次数多的排前面")
mixed_rank = []
for t in range(1, 6):                      # 甲：5 节
    mixed_rank.append(lesson(t, f"甲点{t}", "甲根"))
for t in range(100, 103):                  # 乙：3 节
    mixed_rank.append(lesson(t, f"乙点{t}", "乙根"))
out = gaps.recurring(mixed_rank)
check("两条结论，甲在前", [x["concept"] for x in out] == ["甲根", "乙根"],
      str([x["concept"] for x in out]))


section("J. 句子与 AI 叙述")
check("模板句子非空", bool(out and out[0]["sentence"]))
check("句子里带概念名", out and "甲根" in out[0]["sentence"], out[0]["sentence"] if out else "")
check("离线 narrate 返回空串、不抛", gaps.narrate(out) == "")
check("空 findings 的 narrate 也是空串", gaps.narrate([]) == "")
check("topics 有上限（资料页窄）",
      len(gaps.recurring([lesson(t, f"点{t}", "根") for t in range(10)])[0]["topics"])
      <= gaps.MAX_TOPICS)

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("「反复缺失的前置知识」自检：全部通过")
