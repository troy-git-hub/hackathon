"""
Echo - 学生画像自检

    python scripts/persona_check.py

覆盖：
  A. 没有复习记录时给中性默认值，tone_hint 为空
  B. 连续答崩 → needs_examples / struggling，tone_hint 带上对应提示
  C. 连续答对 → steady/concise 的判断 + improving
  D. 只看真正被判过的记录（review_count>0），刚记下还没判过的不拉低画像
  E. save() / reset() 落盘到 profile.json，不是存在别处
  F. reset 之后不是恢复成某个旧值，是回到"按最新数据重新算"

退出码：全部通过为 0。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")

from echo.backend import paths   # noqa: E402

_DIR = tempfile.mkdtemp(prefix="echo-persona-")
paths.config_dir = lambda: _DIR

from echo.backend import persona, profile, store   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


def seed(topics_results):
    store._write([])
    for topic, results in topics_results.items():
        store.add([{"topic": topic, "missing": "m"}])
        for r in results:
            store.grade(topic, r)


section("A. 没有复习记录")
store._write([])
d = persona.compute()
check("中性默认值", d == {"style": "steady", "trend": "steady",
                        "again_rate": 0.0, "clear_rate": 0.0, "sample": 0}, str(d))
check("tone_hint 为空（没数据不硬编一句话）", persona.tone_hint() == "")
check("describe 说明还没数据", "还没有" in persona.describe(), persona.describe())

section("B. 连续答崩")
seed({"极限": [store.AGAIN], "导数": [store.AGAIN], "链式法则": [store.AGAIN]})
d = persona.compute()
check("style = needs_examples", d["style"] == persona.STYLE_NEEDS_EXAMPLES, str(d))
check("trend = struggling", d["trend"] == persona.TREND_STRUGGLING, str(d))
hint = persona.tone_hint(d)
check("tone_hint 提到要举例子", "例子" in hint, hint)
check("tone_hint 提到要有耐心", "耐心" in hint, hint)

section("C. 连续答对")
seed({"甲": [store.CLEAR, store.CLEAR], "乙": [store.CLEAR, store.CLEAR],
      "丙": [store.CLEAR, store.CLEAR]})
d = persona.compute()
check("trend = improving", d["trend"] == persona.TREND_IMPROVING, str(d))
check("又快又准 → concise", d["style"] == persona.STYLE_CONCISE, str(d))
hint = persona.tone_hint(d)
check("tone_hint 提到不用啰嗦", "啰嗦" in hint, hint)

section("D. 刚记下还没判过的不拉低画像")
seed({"甲": [store.CLEAR, store.CLEAR], "乙": [store.CLEAR, store.CLEAR]})
store.add([{"topic": "刚记下的", "missing": "还没问过"}])   # 不 grade，review_count=0
d = persona.compute()
check("未判过的错题不计入样本量", d["sample"] == 2, str(d))
check("画像不受影响（还是 improving）", d["trend"] == persona.TREND_IMPROVING, str(d))

section("E. 落盘到 profile.json")
persona.save()
check("写进了 profile.json 的 persona 字段", isinstance(profile.load().get("persona"), dict)
      and profile.load()["persona"].get("sample") == 2)
check("get() 优先用存好的，不是每次重算", persona.get() == profile.load()["persona"])

section("F. reset 之后回到\"按最新数据重新算\"")
seed({"甲": [store.AGAIN]})       # 换成会算出不同结果的数据
persona.reset()
check("reset 清空了存的字段", profile.load().get("persona") == {})
after = persona.get()
check("get() 用的是重置后的最新数据，不是存过的老值",
      after["style"] == persona.STYLE_NEEDS_EXAMPLES, str(after))

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("学生画像自检：全部通过")
