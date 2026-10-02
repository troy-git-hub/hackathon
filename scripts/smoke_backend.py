"""
Echo 后端冒烟测试（不需要 UI）：
    python scripts/smoke_backend.py            # 用真实 DeepSeek
    python scripts/smoke_backend.py --mock     # 不调 LLM
回放示例课 → 中途点「有点懵」→ 点「我掉队了」→ 结束课程，打印每一步结果。
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from echo.backend.engine import EchoEngine
from echo.mock_data import SAMPLE_LESSON

ap = argparse.ArgumentParser()
ap.add_argument("--mock", action="store_true")
args = ap.parse_args()

done = threading.Event()
bp_done = threading.Event()


def on_bp(bp, shown):
    print("\n========== Break Point ==========")
    for c in shown:
        mark = " ⚠" if c.timecode == bp.breakpoint_tc else ""
        print(f"  {c.timecode} {c.topic} [{c.status}]{mark}")
    print(f"  断点 {bp.breakpoint_tc} · {bp.concept} · {bp.note}")
    print(f"  缺失：{bp.missing}\n  原因：{bp.reason}")
    print(f"  ① 你已经知道：{bp.known}\n  ② 漏的一步：\n{bp.step}\n  ③ 现在能听懂：{bp.now}")
    print(f"  补课：\n{bp.micro_lesson}\n")
    bp_done.set()


def on_echo(r):
    print("\n========== 回响 ==========")
    for s in r.skills:
        print(f"  {s.name:<10} {'█' * int(s.mastery * 10):<10} {s.mastery:.2f} {s.status}")
    print("  复习链：", " → ".join(r.review_chain))
    print("  建议：", r.suggestion)
    done.set()


eng = EchoEngine(
    on_concept=lambda c: print(f"  [concept] {c.timecode} {c.topic} | {c.summary}"),
    on_breakpoint=on_bp, on_echo=on_echo,
    on_status=lambda s: print(f"  (status: {s})"),
    on_error=lambda e: print(f"  !! error: {e}"),
    concept_interval=3, use_llm=not args.mock)
eng.start()
print("LLM:", "DeepSeek" if eng.has_llm else "mock")

t0 = time.time()
for i, (t, text) in enumerate(SAMPLE_LESSON):
    eng.add_transcript(text, t=t)
    print(f"[{t:>5.0f}s] {text}")
    time.sleep(0.4)
    if i == 11:
        eng.feedback("warn")
        print("  >>> 学生点了「? 有点懵」")
    if i == 13:
        eng.feedback("lost")
        print("  >>> 学生点了「! 我掉队了」")
        bp_done.wait(90)
        eng.mark_fixed()
        print("  >>> 学生点了「✓ 补上了」")

eng.end_lesson()
done.wait(90)
print(f"\n总耗时 {time.time() - t0:.1f}s")
eng.shutdown()
