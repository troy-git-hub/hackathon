"""
课程隔离回归测试：结束 / 重开课程时，上一节课的后台任务不能串进新课。
用一个故意很慢的假 LLM 制造「任务还在跑，课已经换了」的竞态。

    python scripts/session_check.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ECHO_DEMO_INTERVAL", "30")

from echo.backend.engine import EchoEngine
from echo.backend.sources import DemoSource

SLOW = 1.5


class SlowLLM:
    """按 system prompt 区分请求，统一延迟 SLOW 秒后返回固定 JSON。"""

    def json(self, system, user, **kw):
        time.sleep(SLOW)
        if "切分成知识点片段" in system:
            return {"segments": [{"start": "00:01", "topic": "旧课知识点", "concepts": [],
                                  "prerequisites": [], "summary": "上一节课"}]}
        if "我掉队了" in system:
            return {"breakpoint": "00:01", "concept": "旧课知识点", "missing": "旧课断点",
                    "reason": "", "micro_lesson": "", "note": "", "known": "", "step": "", "now": ""}
        return {"skills": [{"name": "旧课知识点", "mastery": 0.3, "status": "review"}],
                "review_chain": ["旧课知识点"], "suggestion": ""}


events = []
lock = threading.Lock()


def make_engine():
    def rec(name):
        return lambda *a: (lock.acquire(), events.append((name, a)), lock.release())
    eng = EchoEngine(on_transcript=rec("transcript"), on_concept=rec("concept"),
                     on_breakpoint=rec("breakpoint"), on_echo=rec("echo"),
                     on_status=rec("status"), on_error=rec("error"),
                     concept_interval=1, use_llm=False)
    eng.llm = SlowLLM()
    return eng


def feed_old_lesson(eng):
    for i in range(6):
        eng.add_transcript(f"上一节课的第 {i} 句话，老师在讲旧的知识点内容。", t=i * 10 + 1)


def names_after(mark):
    with lock:
        return [n for n, a in events[mark:] if n not in ("status",)]


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""))


# A: 点了「我掉队了」，分析还没回来就重开课程
eng = make_engine()
eng.start()
feed_old_lesson(eng)
eng.feedback("lost")
time.sleep(0.2)
eng.start()
mark = len(events)
time.sleep(SLOW * 3)
check("A 掉队分析中途重开：旧断点不进新课",
      "breakpoint" not in names_after(mark) and not eng.breakpoints and not eng.entries,
      f"events={names_after(mark)} bps={len(eng.breakpoints)} entries={[e.concept.topic for e in eng.entries]}")
eng.shutdown()

# B: 知识点抽取进行中重开课程
eng = make_engine()
eng.start()
feed_old_lesson(eng)
time.sleep(1.3)            # ticker 已提交抽取，LLM 还在跑
eng.start()
mark = len(events)
eng.add_transcript("新课第一句。", t=1)
time.sleep(SLOW * 2.5)
check("B 抽取中途重开：旧知识点不写进新课时间轴",
      not eng.entries and "concept" not in names_after(mark) and eng._pending_from == 0,
      f"entries={[e.concept.topic for e in eng.entries]} pending_from={eng._pending_from} events={names_after(mark)}")
eng.shutdown()

# C: 下课生成回响中途重开
eng = make_engine()
eng.start()
feed_old_lesson(eng)
eng.end_lesson()
time.sleep(0.2)
eng.start()
mark = len(events)
time.sleep(SLOW * 4)
check("C 回响生成中途重开：旧回响不弹到新课", "echo" not in names_after(mark),
      f"events={names_after(mark)}")
eng.shutdown()

# D: 旧音频来源在重开后继续送转写
eng = make_engine()
eng.start()
old_src = DemoSource(eng)
eng.start()
old_src.engine.add_transcript("旧来源迟到的一句话", t=3, session=old_src.session)
check("D 旧来源迟到的转写被丢弃", not eng.lines, f"lines={[l.text for l in eng.lines]}")
eng.shutdown()

# E: 多次重开后只剩一个 ticker
eng = make_engine()
for _ in range(4):
    eng.start()
time.sleep(1.5)
tickers = [t for t in threading.enumerate() if t.name.startswith("echo-ticker") and t.is_alive()]
check("E 重开 4 次后只有 1 个 ticker 在跑", len(tickers) == 1, f"{[t.name for t in tickers]}")
eng.shutdown()

# F: Qt 桥接——重开前已排进 Qt 队列的旧事件不送到 UI
from PyQt5.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
from echo.backend.qt_bridge import EchoBridge
br = EchoBridge(source="demo")
got = []
br.transcript.connect(lambda tc, t: got.append(t))
br.start()
old = br.session
th = threading.Thread(target=lambda: br.engine.on_event(old, "transcript", "00:05", "旧课排队中的字幕"))
th.start(); th.join()      # 事件已进 Qt 队列，但主线程还没处理
br.start()                 # 重开
for _ in range(20):
    app.processEvents()
    time.sleep(0.01)
check("F Qt 队列里的旧事件被丢弃", "旧课排队中的字幕" not in got, f"got={got}")
br.shutdown()

print(f"\n{sum(results)}/{len(results)} 通过")
sys.exit(0 if all(results) else 1)
