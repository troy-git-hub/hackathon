"""
Echo - 「为什么要复习它」自检

    python scripts/why_check.py

覆盖：
  A. needs() 只挑出还没生成过的（有内容的不再问，省一次调用）
  B. 离线 / 没 key 时返回空 dict，不抛（没有 AI 说明就不显示这一行）
  C. 一次调用批量生成，模型返回的 JSON 收成 {topic: 说明}
  D. 模型认错 topic 时丢掉那一条（宁可不显示，也不挂到别的知识点上）
  E. set_why 只动 why_matters，不碰 missing / micro_lesson / timecode / 复习进度
  F. set_why 不拿空值覆盖已经写好的说明
  G. set_why 幂等：内容没变就不重复写
  H. 一批最多问 MAX_PER_CALL 条

退出码：全部通过为 0。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")

from echo.backend import paths   # noqa: E402

_DIR = tempfile.mkdtemp(prefix="echo-why-")
paths.config_dir = lambda: _DIR

from echo.backend import config, store, why_matters   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def section(t):
    print(f"\n{t}")


def seed():
    store._write([])
    store.add([{"topic": "条件概率定义", "missing": "为什么分母是 P(B)",
                "timecode": "03:12", "micro_lesson": "分母是 B 发生的总可能"}])
    store.grade("条件概率定义", store.FUZZY)          # 制造复习进度，后面验证没被抹掉


class FakeLLM:
    """假模型：把问答走的 JSON 直接还回来，不发网络请求。"""
    calls = 0

    def __init__(self, *a, **kw):
        pass

    def json(self, system, user, **kw):
        FakeLLM.calls += 1
        FakeLLM.last_system = system
        FakeLLM.last_user = user
        return FakeLLM.reply


section("A. needs() 只挑没生成过的")
seed()
check("刚记下的会被挑出来", [it["topic"] for it in why_matters.needs(store.load())] == ["条件概率定义"])
store.set_why({"条件概率定义": "后面所有推导的起点"})
check("已有说明的不再问", why_matters.needs(store.load()) == [])


section("B. 离线 / 没 key 不发请求、不抛")
seed()
config.OFFLINE = True
config.DEEPSEEK_API_KEY = "fake-key"
why_matters.LLM = FakeLLM
FakeLLM.calls = 0
check("离线返回空 dict", why_matters.plan_batch(store.load()) == {})
check("离线一次都没调模型", FakeLLM.calls == 0)

config.OFFLINE = False
config.DEEPSEEK_API_KEY = ""
FakeLLM.calls = 0
check("没 key 也返回空 dict", why_matters.plan_batch(store.load()) == {})
check("没 key 一次都没调模型", FakeLLM.calls == 0)


section("C. 一次调用批量生成")
seed()
config.DEEPSEEK_API_KEY = "fake-key"
FakeLLM.reply = {"reasons": [{"topic": "条件概率定义", "why": "后面所有推导都从这里出发"}]}
FakeLLM.calls = 0
out = why_matters.plan_batch(store.load())
check("收成 {topic: 说明}", out == {"条件概率定义": "后面所有推导都从这里出发"}, str(out))
check("只调了一次模型（批量，不是每条一次）", FakeLLM.calls == 1, f"实际 {FakeLLM.calls} 次")
check("两段错题都写进了同一次提问", "条件概率定义" in FakeLLM.last_user)


section("D. 模型认错 topic 时丢掉那一条")
seed()
FakeLLM.reply = {"reasons": [{"topic": "根本没这个知识点", "why": "x"},
                             {"topic": "条件概率定义", "why": "对的那条"}]}
out = why_matters.plan_batch(store.load())
check("只留输入里真实存在的 topic", out == {"条件概率定义": "对的那条"}, str(out))


section("E. set_why 只动 why_matters，别的一律不碰")
seed()
before = store.load()[0]
store.set_why({"条件概率定义": "后面所有推导的起点"})
after = next(it for it in store.load() if it["topic"] == "条件概率定义")
check("why_matters 写进去了", after.get("why_matters") == "后面所有推导的起点")
for k in ("missing", "timecode", "micro_lesson"):
    check(f"{k} 没被抹掉", after.get(k) == before.get(k),
          f"{before.get(k)!r} → {after.get(k)!r}")
for k in ("level", "due", "last_result", "review_count"):
    check(f"复习进度 {k} 没被动", after.get(k) == before.get(k),
          f"{before.get(k)!r} → {after.get(k)!r}")


section("F. 空值不覆盖已经写好的说明")
store.set_why({"条件概率定义": "后面所有推导的起点"})
n = store.set_why({"条件概率定义": "", "另一个不存在": "x"})
after = next(it for it in store.load() if it["topic"] == "条件概率定义")
check("空串不写、也不返回条数", n == 0, str(n))
check("原来的说明还在", after.get("why_matters") == "后面所有推导的起点")


section("G. 幂等：内容没变不重复写")
check("同样的内容再写一次返回 0", store.set_why({"条件概率定义": "后面所有推导的起点"}) == 0)
check("换个说法才真的写", store.set_why({"条件概率定义": "换个说法"}) == 1)


section("H. 一批最多问 MAX_PER_CALL 条")
store._write([])
store.add([{"topic": f"知识点{i}", "missing": "m"} for i in range(why_matters.MAX_PER_CALL + 7)])
check(f"needs 全都要（{why_matters.MAX_PER_CALL + 7} 条）",
      len(why_matters.needs(store.load())) == why_matters.MAX_PER_CALL + 7)
FakeLLM.reply = {"reasons": []}
FakeLLM.calls = 0
why_matters.plan_batch(store.load())
asked = FakeLLM.last_user.count("他卡在：")
check(f"只问了 {why_matters.MAX_PER_CALL} 条", asked == why_matters.MAX_PER_CALL, f"实际 {asked}")


section("I. 后台生成的回调走通")
seed()
FakeLLM.reply = {"reasons": [{"topic": "条件概率定义", "why": "后台回来的说明"}]}
got = []
why_matters.generate_async(store.load(), on_done=lambda r: got.append(r))
import time as _t                                     # noqa: E402
for _ in range(100):
    if got:
        break
    _t.sleep(0.05)
check("on_done 收到了结果", got and got[0] == {"条件概率定义": "后台回来的说明"}, str(got))

print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("「为什么要复习它」自检：全部通过")
