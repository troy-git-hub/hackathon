"""真实 DeepSeek 跑一节课 → 存 json → 用知识地图渲染成图片。"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from echo.backend.engine import EchoEngine
from echo.backend import mindmap, store
from echo.mock_data import SAMPLE_LESSON

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_real_lesson.json")

done = threading.Event()
bp_done = threading.Event()
state = {}


def on_bp(bp, shown):
    state["bp"] = bp
    print(f"  断点 {bp.breakpoint_tc} · {bp.concept} · {bp.missing}")
    bp_done.set()


def on_echo(r):
    state["report"] = r
    done.set()


eng = EchoEngine(on_breakpoint=on_bp, on_echo=on_echo,
                 on_concept=lambda c: print(f"  [concept] {c.timecode} {c.topic} | {c.summary}"),
                 on_error=lambda e: print(f"  !! {e}"),
                 concept_interval=3)
eng.start()
print("LLM:", "DeepSeek" if eng.has_llm else "mock")
if not eng.has_llm:
    sys.exit("拿不到 DeepSeek，检查 .env 里的 DEEPSEEK_API_KEY")

for i, (t, text) in enumerate(SAMPLE_LESSON):
    eng.add_transcript(text, t=t)
    time.sleep(0.3)
    if i == 11:
        eng.feedback("warn")
    if i == 13:
        eng.feedback("lost")
        bp_done.wait(90)
        eng.mark_fixed()

eng.end_lesson()
done.wait(90)

r = state.get("report")
if r is None:
    sys.exit("没拿到回响")

lesson = mindmap.from_report(r, title="贝叶斯统计")
mistakes = store.from_breakpoints(eng)
if state.get("bp"):
    mistakes = [{**m, "micro_lesson": state["bp"].micro_lesson} for m in mistakes]

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"lesson": lesson, "mistakes": mistakes}, f, ensure_ascii=False, indent=2)

graph = mindmap.build(lesson, mistakes)
print("\n========== 知识地图 ==========")
print("节点:", len(graph["nodes"]), "边:", len(graph["edges"]),
      "真实前置关系:", graph["has_real_graph"])
for n in sorted(graph["nodes"], key=lambda x: x["level"]):
    print(f"  第{n['level']}层 {n['topic']:<12} {n['status']:<7} 掌握度 {n['mastery']:.2f}"
          + ("  [掉过队]" if n["has_mistake"] else ""))
for e in graph["edges"]:
    print(f"  {e['from']} → {e['to']}")
print("\n复习链:", " → ".join(lesson["review_chain"]))
print("已存:", OUT)
eng.shutdown()
