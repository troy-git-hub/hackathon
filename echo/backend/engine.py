"""
Echo - 课堂引擎（后端核心）

职责：
  transcript 流  →  Concept Timeline（每隔一段时间让 LLM 抽一次知识点）
  学生反馈 ✓ / ? / !  →  !「我掉队了」触发 Break Point Engine
  课程结束  →  「回响」复盘

线程模型：所有 LLM 调用在后台线程执行，结果通过回调抛出。
回调会在后台线程里被调用，UI 层请自行切回主线程（见 qt_bridge.py）。
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List, Optional

from echo.backend import config, prompts
from echo.backend.llm import LLM, LLMError
from echo.mock_data import (BreakPoint, Concept, EchoSkill, SAMPLE_BREAKPOINT,
                            SAMPLE_CONCEPTS)

log = logging.getLogger("echo.engine")

FEEDBACK_LABEL = {"ok": "✓ 跟上了", "warn": "? 有点懵", "lost": "! 我掉队了"}


def fmt_tc(t: float) -> str:
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_tc(tc: str) -> Optional[float]:
    try:
        parts = [int(p) for p in str(tc).strip().split(":")]
    except ValueError:
        return None
    t = 0
    for p in parts:
        t = t * 60 + p
    return float(t)


@dataclass
class Line:
    t: float
    text: str

    @property
    def tc(self):
        return fmt_tc(self.t)


@dataclass
class Feedback:
    t: float
    kind: str           # ok / warn / lost
    concept: str = ""


@dataclass
class EchoReport:
    skills: List[EchoSkill]
    review_chain: List[str]
    suggestion: str = ""


@dataclass
class _ConceptEntry:
    t: float
    concept: Concept
    is_bp: bool = False


class EchoEngine:
    def __init__(self,
                 on_transcript: Callable[[str, str], None] = None,
                 on_concept: Callable[[Concept], None] = None,
                 on_breakpoint: Callable[[BreakPoint, List[Concept]], None] = None,
                 on_echo: Callable[[EchoReport], None] = None,
                 on_status: Callable[[str], None] = None,
                 on_error: Callable[[str], None] = None,
                 concept_interval: float = None,
                 use_llm: bool = True):
        self.on_transcript = on_transcript or (lambda tc, text: None)
        self.on_concept = on_concept or (lambda c: None)
        self.on_breakpoint = on_breakpoint or (lambda bp, cs: None)
        self.on_echo = on_echo or (lambda r: None)
        self.on_status = on_status or (lambda s: None)
        self.on_error = on_error or (lambda e: None)
        self.concept_interval = concept_interval or config.CONCEPT_INTERVAL

        self.llm: Optional[LLM] = None
        if use_llm:
            try:
                self.llm = LLM()
            except Exception as e:  # 无 key / 无 openai 包 → 退化为 mock
                log.warning("LLM 不可用，使用 mock 数据: %s", e)

        self._lock = threading.RLock()
        self._concept_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="echo-llm")
        self._stop = threading.Event()
        self._ticker: Optional[threading.Thread] = None
        self.reset()

    # ================= 生命周期 =================
    def reset(self):
        with self._lock:
            self.start_ts = time.time()
            self.lines: List[Line] = []
            self.entries: List[_ConceptEntry] = []
            self.feedbacks: List[Feedback] = []
            self.breakpoints: List[BreakPoint] = []
            self._pending_from = 0          # lines[_pending_from:] 还没抽过 concept
            self._last_extract = time.time()

    def start(self):
        self.reset()
        self._stop.clear()
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True, name="echo-ticker")
        self._ticker.start()
        self.on_status("listening")

    def stop(self):
        self._stop.set()

    def shutdown(self):
        self.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    @property
    def has_llm(self):
        return self.llm is not None

    def elapsed(self) -> float:
        """从开课到现在的墙钟秒数（实时音频用）。"""
        return time.time() - self.start_ts

    def now(self) -> float:
        """当前课堂时间（秒）。transcript 带自定义时间戳时以最新一句为准。"""
        with self._lock:
            wall = time.time() - self.start_ts
            if self.lines:
                return max(self.lines[-1].t, min(wall, self.lines[-1].t + 30))
            return wall

    # ================= 输入：transcript =================
    def add_transcript(self, text: str, t: float = None):
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            if t is None:
                t = time.time() - self.start_ts
            line = Line(t, text)
            self.lines.append(line)
        self.on_transcript(line.tc, text)

    def _tick_loop(self):
        while not self._stop.wait(1.0):
            with self._lock:
                pending = self.lines[self._pending_from:]
                chars = sum(len(l.text) for l in pending)
                due = time.time() - self._last_extract >= self.concept_interval
            if pending and (chars >= config.CONCEPT_MIN_CHARS and due or chars >= 400):
                self._pool.submit(self._safe, self._extract_concept)

    # ================= Concept Timeline =================
    def _extract_concept(self, force=False):
        if not self._concept_lock.acquire(blocking=force):
            return
        try:
            with self._lock:
                pending = self.lines[self._pending_from:]
                if not pending:
                    return
                end_idx = len(self.lines)
                timeline = self._timeline_text()
                prev = self.entries[-1] if self.entries else None
            chunk = "\n".join(f"[{l.tc}] {l.text}" for l in pending)

            if self.llm:
                data = self.llm.json(prompts.CONCEPT_SYSTEM,
                                     prompts.CONCEPT_USER.format(timeline=timeline or "（暂无）",
                                                                 chunk=chunk),
                                     max_tokens=700)
            else:
                data = self._mock_concept(chunk)
            segs = data.get("segments") if isinstance(data.get("segments"), list) else [data]

            changed = []
            with self._lock:
                self._pending_from = end_idx
                self._last_extract = time.time()
                for seg in segs:
                    if not isinstance(seg, dict):
                        continue
                    topic = str(seg.get("topic") or "").strip() or "课堂内容"
                    prev = self.entries[-1] if self.entries else None
                    if prev and _same_topic(prev.concept.topic, topic):
                        c = prev.concept
                        if len(topic) < len(c.topic):   # 「贝叶斯公式引入」→「贝叶斯公式」取更短的正式名
                            c.topic = topic
                        c.concepts = _merge(c.concepts, seg.get("concepts"))[:6]
                        c.prerequisites = _merge(c.prerequisites, seg.get("prerequisites"))[:4]
                        c.summary = seg.get("summary") or c.summary
                    else:
                        # 片段起点：取 LLM 给的时间码，吸附到本段真实句子上，且保持单调递增
                        t = parse_tc(seg.get("start"))
                        lo = max(pending[0].t, prev.t + 1 if prev else 0)
                        t = lo if t is None else min(max(t, lo), pending[-1].t)
                        line_t = [l.t for l in pending if l.t <= t]
                        t = max(line_t[-1] if line_t else t, lo)
                        c = Concept(timecode=fmt_tc(t), topic=topic,
                                    concepts=_as_list(seg.get("concepts")),
                                    prerequisites=_as_list(seg.get("prerequisites")),
                                    summary=str(seg.get("summary") or ""), status="now")
                        self.entries.append(_ConceptEntry(t, c))
                        if prev and prev.concept.status == "now":
                            # 新 concept 入列后，上一个的时间区间才闭合，此时再按反馈定状态
                            prev.concept.status = self._status_of(len(self.entries) - 2)
                    if c not in changed:
                        changed.append(c)
            for c in changed:
                self.on_concept(c)
        finally:
            self._concept_lock.release()

    def _mock_concept(self, chunk):
        for c in SAMPLE_CONCEPTS:
            if c.topic[:2] in chunk:
                return {"topic": c.topic, "concepts": c.concepts,
                        "prerequisites": c.prerequisites, "summary": c.summary}
        return {"topic": "课堂内容", "concepts": [], "prerequisites": [], "summary": chunk[:30]}

    def current_concept(self) -> Optional[Concept]:
        with self._lock:
            return self.entries[-1].concept if self.entries else None

    def concepts(self) -> List[Concept]:
        with self._lock:
            return [e.concept for e in self.entries]

    # ================= 学生反馈 =================
    def feedback(self, kind: str):
        """kind: ok / warn / lost。lost 会异步触发 Break Point Engine。"""
        if kind not in FEEDBACK_LABEL:
            raise ValueError(kind)
        with self._lock:
            cur = self.entries[-1] if self.entries else None
            self.feedbacks.append(Feedback(self.now(), kind, cur.concept.topic if cur else ""))
        if kind == "lost":
            self.on_status("analyzing")
            self._pool.submit(self._safe, self._find_breakpoint)

    # ================= Break Point Engine =================
    def _find_breakpoint(self):
        # 同时把还没处理的 transcript 抽成 concept（并行，不阻塞断点分析；
        # 断点 prompt 本身带原始转写，时间轴只用于展示和吸附）
        with self._lock:
            has_pending = sum(len(l.text) for l in self.lines[self._pending_from:]) >= 10
        flush = self._pool.submit(self._extract_concept, True) if has_pending else None

        with self._lock:
            now = self.now()
            window = [l for l in self.lines if l.t >= now - config.LOST_WINDOW] or self.lines[-30:]
            timeline = self._timeline_text()
            feedback = self._feedback_text()
            cur = self.entries[-1].concept.topic if self.entries else "（未知）"

        data = None
        if self.llm and window:
            try:
                data = self.llm.json(
                prompts.BREAKPOINT_SYSTEM,
                prompts.BREAKPOINT_USER.format(
                    timeline=timeline or "（暂无）",
                    feedback=feedback or "（无）",
                    window=f"{config.LOST_WINDOW // 60} 分钟",
                    transcript="\n".join(f"[{l.tc}] {l.text}" for l in window),
                    current=cur, now=fmt_tc(now)),
                temperature=0.4, max_tokens=800,
                timeout=config.BREAKPOINT_TIMEOUT, attempts=1)
            except Exception as e:   # 掉队是核心交互，LLM 挂了也要给出断点，不能让 UI 卡在 analyzing
                log.warning("断点 LLM 失败，使用规则兜底: %s", e)
        if data is not None:
            bp = BreakPoint(breakpoint_tc=str(data.get("breakpoint") or ""),
                            concept=str(data.get("concept") or cur),
                            missing=str(data.get("missing") or ""),
                            reason=str(data.get("reason") or ""),
                            micro_lesson=str(data.get("micro_lesson") or ""),
                            note=str(data.get("note") or ""))
        elif self.llm and window:
            bp = self._heuristic_breakpoint(cur)
        elif self.llm:
            bp = BreakPoint("", cur, "Echo 还没听到课堂内容",
                            "请确认网课正在播放，且声音没有静音",
                            "Echo 会自动抓取电脑正在播放的声音。开始播放网课后，等老师讲一两分钟再点「我掉队了」。",
                            note="还没有内容")
        else:
            s = SAMPLE_BREAKPOINT
            bp = BreakPoint(s.breakpoint_tc, s.concept, s.missing, s.reason,
                            s.micro_lesson, note="老师快速跳过了推导")

        if flush:
            # 只短暂等一下：来得及就把最新知识点并进时间轴，来不及也先出断点（concept 稍后照常推送）
            try:
                flush.result(timeout=config.FLUSH_GRACE)
            except Exception as e:
                log.info("flush concept 未及时完成: %s", e)
        shown = self._attach_breakpoint(bp)
        with self._lock:
            self.breakpoints.append(bp)
        self.on_status("listening")
        self.on_breakpoint(bp, shown)

    def _heuristic_breakpoint(self, cur: str) -> BreakPoint:
        """规则兜底：取最近一个点过「有点懵」的知识点，否则取「现在」的前一个。"""
        with self._lock:
            entries = list(self.entries)
            idx = next((i for i in range(len(entries) - 1, -1, -1)
                        if "warn" in self._feedback_of(i)), None)
        if idx is None:
            idx = max(0, len(entries) - 2)
        if not entries:
            return BreakPoint("", cur, f"「{cur}」是怎么来的？", "这一段讲得比较快",
                              "Echo 暂时连不上 AI，建议回看最近 1~2 分钟的课程内容。", note="讲得比较快")
        c = entries[idx].concept
        pre = "、".join(c.prerequisites) or "前面的定义"
        lesson = (f"你可能在「{c.topic}」这里掉队了。\n"
                  f"老师在讲：{c.summary}\n"
                  f"它依赖的前置知识是：{pre}，先确认这些你都清楚。\n"
                  f"Echo 暂时连不上 AI，建议回看 {c.timecode} 附近的内容，再接上老师现在讲的「{cur}」。")
        return BreakPoint(c.timecode, c.topic, f"「{c.topic}」是怎么来的？",
                          f"这里依赖{pre}，讲得比较快", lesson, note="这里讲得比较快")

    def _attach_breakpoint(self, bp: BreakPoint) -> List[Concept]:
        """把断点吸附到时间轴上的某个 concept，返回给 UI 展示的那一段时间轴。"""
        with self._lock:
            entries = list(self.entries)
            if not entries:
                c = Concept(bp.breakpoint_tc or fmt_tc(self.now()), bp.concept, [], [], bp.reason, "now")
                self.entries.append(_ConceptEntry(parse_tc(c.timecode) or 0, c))
                bp.breakpoint_tc = c.timecode
                return [c]

            idx = None
            for i, e in enumerate(entries):   # 先按知识点名称精确匹配
                if e.concept.topic == bp.concept:
                    idx = i
            if idx is None and bp.concept:    # 再按名称包含（如「贝叶斯公式的推导」↔「贝叶斯公式」）
                for i, e in enumerate(entries):
                    if e.concept.topic in bp.concept or bp.concept in e.concept.topic:
                        idx = i
            t = parse_tc(bp.breakpoint_tc)
            if idx is None and t is not None:  # 再按时间吸附到所在 concept
                idx = 0
                for i, e in enumerate(entries):
                    if e.t <= t:
                        idx = i
            if idx is None:
                idx = len(entries) - 1

            hit = entries[idx]
            if hit.concept.status != "now":
                hit.concept.status = "warn"
            hit.is_bp = True
            bp.breakpoint_tc = hit.concept.timecode
            if not bp.note:
                bp.note = bp.reason[:12]

            # 展示：断点前 1 个 + 断点 + 后 2 个，再接上「现在」
            shown = entries[max(0, idx - 1): idx + 3]
            if entries[-1] not in shown:
                shown.append(entries[-1])
            return [e.concept for e in shown]

    # ================= 回响 =================
    def end_lesson(self):
        """课程结束：异步生成回响页数据。"""
        self.stop()
        self.on_status("summarizing")
        self._pool.submit(self._safe, self._make_echo)

    def _make_echo(self):
        with self._lock:
            has_pending = bool(self.lines[self._pending_from:])
        if has_pending:
            try:
                self._extract_concept(force=True)
            except Exception as e:
                log.warning("flush concept 失败: %s", e)

        report = None
        if self.llm and self.entries:
            try:
                with self._lock:
                    timeline = self._timeline_text()
                    feedback = self._feedback_text()
                    bps = "\n".join(f"- {b.breakpoint_tc} {b.concept}：缺失「{b.missing}」，{b.reason}"
                                    for b in self.breakpoints)
                data = self.llm.json(prompts.ECHO_SYSTEM,
                                     prompts.ECHO_USER.format(timeline=timeline,
                                                              feedback=feedback or "（无）",
                                                              breakpoints=bps or "（无）"),
                                     max_tokens=800)
                skills = []
                for s in data.get("skills") or []:
                    try:
                        m = max(0.0, min(1.0, float(s.get("mastery", 0.5))))
                    except (TypeError, ValueError):
                        m = 0.5
                    st = s.get("status") if s.get("status") in ("ok", "warn", "lost") else _status_from_mastery(m)
                    skills.append(EchoSkill(str(s.get("name", "")), m, st))
                chain = [str(x) for x in (data.get("review_chain") or []) if x]
                if skills:
                    report = EchoReport(skills, chain, str(data.get("suggestion") or ""))
            except Exception as e:
                log.warning("回响 LLM 失败，使用规则兜底: %s", e)
        if report is None:
            report = self._heuristic_echo()
        self.on_status("done")
        self.on_echo(report)

    def _heuristic_echo(self) -> EchoReport:
        with self._lock:
            entries = list(self.entries)
            bps = list(self.breakpoints)
            fbs = [self._feedback_of(i) for i in range(len(entries))]
        score = {"ok": 1.0, "warn": 0.55, "lost": 0.6, "bp": 0.15}
        skills = []
        for e, fb in zip(entries, fbs):
            m = min([score[f] for f in fb], default=0.85)
            skills.append(EchoSkill(e.concept.topic, m, _status_from_mastery(m)))
        chain = []
        if bps:
            b = bps[0]
            chain = [b.concept]
            for e in entries:
                if e.concept.topic == b.concept:
                    chain += e.concept.prerequisites[:2]
        return EchoReport(skills, chain, f"建议复习：{chain[-1]}" if chain else "今天都跟上了！")

    # ================= 工具 =================
    def _timeline_text(self) -> str:
        out = []
        for i, e in enumerate(self.entries):
            c = e.concept
            fb = "、".join(FEEDBACK_LABEL[f] for f in self._feedback_of(i) if f in FEEDBACK_LABEL)
            if e.is_bp:
                fb = (fb + "、" if fb else "") + "⚠ 掉队断点"
            out.append(f"[{c.timecode}] {c.topic} —— {c.summary}"
                       f"（前置：{'、'.join(c.prerequisites) or '无'}）"
                       + (f"  学生反馈：{fb}" if fb else ""))
        return "\n".join(out)

    def _feedback_of(self, i: int) -> List[str]:
        """按时间把学生反馈归属到第 i 个 concept（避免 LLM 抽取延迟导致归属错误）。"""
        e = self.entries[i]
        end = self.entries[i + 1].t if i + 1 < len(self.entries) else float("inf")
        out = [f.kind for f in self.feedbacks if e.t <= f.t < end]
        if e.is_bp:
            out.append("bp")
        return out

    def _status_of(self, i: int) -> str:
        fb = self._feedback_of(i)
        return "warn" if ("bp" in fb or "warn" in fb) else "ok"

    def _feedback_text(self) -> str:
        def topic_at(t):
            name = "未知"
            for e in self.entries:
                if e.t <= t:
                    name = e.concept.topic
            return name
        return "\n".join(f"[{fmt_tc(f.t)}] {FEEDBACK_LABEL[f.kind]}（当时在讲：{topic_at(f.t)}）"
                         for f in self.feedbacks)

    def _safe(self, fn, *a):
        try:
            fn(*a)
        except LLMError as e:
            log.exception("LLM 错误")
            self.on_status("listening")
            self.on_error(str(e))
        except Exception as e:
            log.exception("引擎错误")
            self.on_status("listening")
            self.on_error(f"{type(e).__name__}: {e}")


def _as_list(v) -> List[str]:
    if isinstance(v, str):
        return [v] if v else []
    return [str(x) for x in (v or []) if x]


def _same_topic(a: str, b: str) -> bool:
    """同名，或一个是另一个加了「引入/推导/定义」等后缀的近似名。"""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and long_.startswith(short) and len(long_) - len(short) <= 3


def _merge(a, b) -> List[str]:
    out = list(a or [])
    for x in _as_list(b):
        if x not in out:
            out.append(x)
    return out


def _status_from_mastery(m: float) -> str:
    return "ok" if m >= 0.75 else "warn" if m >= 0.4 else "lost"
