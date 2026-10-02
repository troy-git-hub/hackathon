"""
Echo - 课堂引擎（后端核心）

职责：
  transcript 流  →  Concept Timeline（每隔一段时间让 LLM 抽一次知识点）
  学生反馈 ✓ / ? / !  →  !「我掉队了」触发 Break Point Engine
  课程结束  →  「回响」复盘

线程模型：所有 LLM 调用在后台线程执行，结果通过回调抛出。
回调会在后台线程里被调用，UI 层请自行切回主线程（见 qt_bridge.py）。

课程隔离：每次 start() 开一个新 session。所有后台任务都带着发起时的 session 号，
写状态、发回调前都会核对；结束/重开课程后，上一节课迟到的 LLM 结果和转写一律丢弃。
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from echo.backend import config, prompts, quiz, store
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
    summary: str = ""                 # 「这节课讲了什么」，2~4 句连贯的话
    highlights: List[str] = field(default_factory=list)   # 本节课要点，3~5 条
    duration: float = 0.0             # 课程时长（秒）
    line_count: int = 0               # 转写句数
    char_count: int = 0               # 转写总字数
    graph: dict = field(default_factory=dict)   # 知识点前置关系图，给课后「知识地图」用


@dataclass
class _ConceptEntry:
    t: float
    concept: Concept
    is_bp: bool = False
    fixed: bool = False     # 该断点已被学生「补上了」


class EchoEngine:
    def __init__(self,
                 on_transcript: Callable[[str, str], None] = None,
                 on_concept: Callable[[Concept], None] = None,
                 on_breakpoint: Callable[[BreakPoint, List[Concept]], None] = None,
                 on_echo: Callable[[EchoReport], None] = None,
                 on_status: Callable[[str], None] = None,
                 on_error: Callable[[str], None] = None,
                 on_thinking: Callable[[bool, str], None] = None,
                 concept_interval: float = None,
                 use_llm: bool = True,
                 on_event: Callable = None):
        self.on_transcript = on_transcript or (lambda tc, text: None)
        self.on_concept = on_concept or (lambda c: None)
        self.on_breakpoint = on_breakpoint or (lambda bp, cs: None)
        self.on_echo = on_echo or (lambda r: None)
        self.on_status = on_status or (lambda s: None)
        self.on_error = on_error or (lambda e: None)
        self.on_thinking = on_thinking or (lambda active, text: None)
        # 课堂抽问：出一题 / 判分结果
        self.on_checkin = lambda q: None
        self.on_checkin_result = lambda r: None
        # 真实声纹响度（0..1），由音频来源喂入，驱动 UI 的声纹反馈
        self.on_level = lambda level: None
        # 可选：统一事件出口 on_event(session, name, *args)，给 Qt 桥接在主线程再核对一次 session
        self.on_event = on_event
        self.concept_interval = concept_interval or config.CONCEPT_INTERVAL

        self.llm: Optional[LLM] = None
        self._online_llm: Optional[LLM] = None   # 切离线时先存着，恢复在线再放回来
        if use_llm and not config.OFFLINE:
            try:
                self.llm = LLM()
            except Exception as e:  # 无 key / 无 openai 包 → 退化为 mock
                log.warning("LLM 不可用，使用 mock 数据: %s", e)

        self._lock = threading.RLock()
        # 上一节课还没跑完的 LLM 任务会占着线程，多留几个，不拖慢新课
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="echo-llm")
        self.session = 0
        self._stop = threading.Event()
        self._ticker: Optional[threading.Thread] = None
        self.title = ""
        self.reset()

    # ================= 生命周期 =================
    def reset(self):
        """开一个新 session：清空课堂数据，之前发起的后台任务全部作废。"""
        with self._lock:
            self.session += 1
            self.active = False            # 尚未开始上课（拍题/反馈这时不记入课程）
            self._concept_lock = threading.Lock()   # 每节课一把，旧任务卡住也不会挡新课
            self.start_ts = time.time()
            self.lines: List[Line] = []
            self.entries: List[_ConceptEntry] = []
            self.feedbacks: List[Feedback] = []
            self.breakpoints: List[BreakPoint] = []
            self._pending_from = 0          # lines[_pending_from:] 还没抽过 concept
            self._last_extract = time.time()
            # 课堂抽问：学生久不互动就主动问一道，答错进错题本
            self.checkins: List[dict] = []      # 历次抽问（含作答结果）
            self.pending_checkin: Optional[dict] = None   # 当前等着回答的那道题
            self._last_interaction = time.time()    # 学生最近一次动手（反馈/补课/答题）
            self._last_checkin_at = 0.0             # 上一次抽问的墙钟时间

    def start(self):
        self._stop.set()                 # 先停掉上一节课的 ticker
        self.reset()
        self._stop = threading.Event()   # 每节课一个独立的停止信号，旧 ticker 不会被「复活」
        sid = self.session
        self._ticker = threading.Thread(target=self._tick_loop, args=(sid, self._stop),
                                        daemon=True, name=f"echo-ticker-{sid}")
        self._ticker.start()
        self.active = True               # 开始上课：此后拍题/反馈才记入课程
        self._emit(sid, "status", "listening")

    def stop(self):
        self._stop.set()

    def set_title(self, name: str):
        """给这节课命名，开课前调用；超长截断到 40 字。"""
        self.title = (name or "").strip()[:40]

    def clear_title(self):
        """清空课程名，用于「开始新的一节课」时显式重置。"""
        self.title = ""

    # ---------- session 隔离 ----------
    def _live(self, sid) -> bool:
        return sid == self.session

    def _emit(self, sid, name, *args):
        """只把当前这节课的结果交给 UI。"""
        with self._lock:
            if not self._live(sid):
                log.info("丢弃上一节课的 %s 事件", name)
                return
        if self.on_event:
            self.on_event(sid, name, *args)
        else:
            getattr(self, "on_" + name)(*args)

    def emit_status(self, sid, st):
        """给音频来源用：带 session 发状态。"""
        self._emit(sid, "status", st)

    def emit_error(self, sid, msg):
        self._emit(sid, "error", msg)

    def emit_level(self, sid, level):
        """给音频来源用：把当前响度（0..1）发给 UI 做真实声纹反馈。"""
        self._emit(sid, "level", float(level))

    def shutdown(self):
        self.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    @property
    def has_llm(self):
        return self.llm is not None

    def set_offline(self, offline: bool):
        """断网兜底：离线时不再调 LLM，时间轴 / 断点 / 回响全部走规则和 mock。"""
        with self._lock:
            if offline and self.llm:
                self._online_llm, self.llm = self.llm, None
            elif not offline and self._online_llm:
                self.llm, self._online_llm = self._online_llm, None

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
    def add_transcript(self, text: str, t: float = None, session: int = None):
        """session：音频来源开始时拿到的 session 号；不是当前这节课的转写直接丢弃。"""
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            sid = self.session if session is None else session
            if not self._live(sid):
                return
            if t is None:
                t = time.time() - self.start_ts
            line = Line(t, text)
            self.lines.append(line)
        self._emit(sid, "transcript", line.tc, text)

    def _tick_loop(self, sid, stop_event):
        while not stop_event.wait(1.0):
            with self._lock:
                if not self._live(sid):
                    return
                pending = self.lines[self._pending_from:]
                chars = sum(len(l.text) for l in pending)
                due = time.time() - self._last_extract >= self.concept_interval
                checkin = self._checkin_due()
            if pending and (chars >= config.CONCEPT_MIN_CHARS and due or chars >= 400):
                try:
                    self._pool.submit(self._safe, sid, self._extract_concept, False, sid)
                except RuntimeError:      # 程序退出时线程池已关闭
                    return
            if checkin:
                try:
                    self._pool.submit(self._safe, sid, self._ask_checkin, sid)
                except RuntimeError:
                    return

    # ================= Concept Timeline =================
    def _extract_concept(self, force=False, sid=None):
        with self._lock:
            sid = self.session if sid is None else sid
            if not self._live(sid):
                return
            concept_lock = self._concept_lock
        if not concept_lock.acquire(blocking=force):
            return
        try:
            with self._lock:
                if not self._live(sid):
                    return
                pending = self.lines[self._pending_from:]
                if not pending:
                    return
                end_idx = len(self.lines)
                timeline = self._timeline_text()
                prev = self.entries[-1] if self.entries else None
            chunk = "\n".join(f"[{l.tc}] {l.text}" for l in pending)
            preview = (chunk[:30] + "…") if len(chunk) > 30 else chunk
            self._emit(sid, "thinking", True, f"正在理解：{preview}")

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
                if not self._live(sid):   # LLM 返回时已经换了一节课：结果作废
                    return
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
                self._emit(sid, "concept", c)
        finally:
            concept_lock.release()
            self._emit(sid, "thinking", False, "")

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
            self._last_interaction = time.time()   # 学生动手了，说明人在
            sid = self.session
        if kind == "lost":
            self._emit(sid, "status", "analyzing")
            self._pool.submit(self._safe, sid, self._find_breakpoint, sid)

    # ================= Break Point Engine =================
    def _find_breakpoint(self, sid):
        # 同时把还没处理的 transcript 抽成 concept（并行，不阻塞断点分析；
        # 断点 prompt 本身带原始转写，时间轴只用于展示和吸附）
        with self._lock:
            if not self._live(sid):
                return
            has_pending = sum(len(l.text) for l in self.lines[self._pending_from:]) >= 10
        flush = self._pool.submit(self._extract_concept, True, sid) if has_pending else None

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
                            note=str(data.get("note") or ""),
                            known=str(data.get("known") or ""),
                            step=str(data.get("step") or ""),
                            now=str(data.get("now") or ""))
        elif self.llm and window:
            bp = self._heuristic_breakpoint(cur)
        elif not window:
            bp = BreakPoint("", cur, "Echo 还没听到课堂内容",
                            "请确认网课正在播放，且声音没有静音",
                            "Echo 会自动抓取电脑正在播放的声音。开始播放网课后，等老师讲一两分钟再点「我掉队了」。",
                            note="还没有内容", known="网课正在播放",
                            step="确认声音没有静音\n等老师讲一两分钟",
                            now="再点「我掉队了」，Echo 就能帮你找断点")
        elif any("贝叶斯" in line.text for line in window):
            s = SAMPLE_BREAKPOINT
            bp = BreakPoint(s.breakpoint_tc, s.concept, s.missing, s.reason,
                            s.micro_lesson, note="老师快速跳过了推导",
                            known=s.known, step=s.step, now=s.now)
        else:
            bp = self._heuristic_breakpoint(cur)

        if flush:
            # 只短暂等一下：来得及就把最新知识点并进时间轴，来不及也先出断点（concept 稍后照常推送）
            try:
                flush.result(timeout=config.FLUSH_GRACE)
            except Exception as e:
                log.info("flush concept 未及时完成: %s", e)
        with self._lock:
            if not self._live(sid):   # 分析期间已经下课/重开：不往新课里写断点
                return
            shown = self._attach_breakpoint(bp)
            self.breakpoints.append(bp)
        self._emit(sid, "status", "listening")
        self._emit(sid, "breakpoint", bp, shown)

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
                              "Echo 暂时连不上 AI，建议回看最近 1~2 分钟的课程内容。", note="讲得比较快",
                              known="前面讲过的定义", step="回看最近 1~2 分钟的课程内容",
                              now=f"再接上老师现在讲的「{cur}」")
        c = entries[idx].concept
        pre = "、".join(c.prerequisites) or "前面的定义"
        lesson = (f"你可能在「{c.topic}」这里掉队了。\n"
                  f"老师在讲：{c.summary}\n"
                  f"它依赖的前置知识是：{pre}，先确认这些你都清楚。\n"
                  f"Echo 暂时连不上 AI，建议回看 {c.timecode} 附近的内容，再接上老师现在讲的「{cur}」。")
        return BreakPoint(c.timecode, c.topic, f"「{c.topic}」是怎么来的？",
                          f"这里依赖{pre}，讲得比较快", lesson, note="这里讲得比较快",
                          known=pre, step=f"{c.summary}\n回看 {c.timecode} 附近，把这一步和{pre}对上",
                          now=f"再接上老师现在讲的「{cur}」")

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

    def mark_fixed(self):
        """学生点了「✓ 补上了」：把最近一个断点标记为已补上。"""
        with self._lock:
            self._last_interaction = time.time()
            if not self.breakpoints:
                return
            bp = self.breakpoints[-1]
            bp.fixed = True
            for e in reversed(self.entries):
                if e.is_bp and e.concept.timecode == bp.breakpoint_tc:
                    e.fixed = True
                    break

    def mark_self(self):
        """学生点了「我自己看看」：最近一个断点记为自己回看，回响里仍算待复习。"""
        with self._lock:
            self._last_interaction = time.time()
            if self.breakpoints:
                self.breakpoints[-1].self_review = True

    # ================= 课堂抽问（摸鱼探测） =================
    def _checkin_due(self) -> bool:
        """该抽问了吗？只在开课中、有可考的知识点、学生久没动手、且距上次抽问够久时为真。
        调用方需持有 self._lock。"""
        if not config.CHECKIN or not self.active:
            return False
        if self.pending_checkin is not None:      # 上一道还没答，别追着问
            return False
        if not self.entries:                      # 还没听到能出题的内容
            return False
        now = time.time()
        if now - self.start_ts < config.CHECKIN_WARMUP:
            return False
        if now - self._last_checkin_at < config.CHECKIN_INTERVAL:
            return False
        # 学生刚点过反馈 / 补过课，说明人在，不用打扰
        return now - self._last_interaction >= config.CHECKIN_IDLE

    def _ask_checkin(self, sid):
        """后台：拿最近讲过的知识点出一道题，抛 checkin 事件给 UI。"""
        with self._lock:
            if not self._live(sid) or not self.active:
                return
            concept = self.entries[-1].concept
            timeline = self._timeline_text()
            transcript = "\n".join(f"[{l.tc}] {l.text}" for l in self.lines[-12:])
            # 引擎没有 llm 表示「没配 key」或「已切离线」，两种都不该再新建连接
            use_llm = self.llm is not None
        q = quiz.make_checkin_sync(timeline=timeline, transcript=transcript,
                                   current=concept.topic, tc=concept.timecode,
                                   llm=self.llm, use_llm=use_llm)
        with self._lock:
            if not self._live(sid) or not self.active:   # 出题期间下课/重开
                return
            q["id"] = len(self.checkins) + 1
            self.pending_checkin = q
            self._last_checkin_at = time.time()
        self._emit(sid, "checkin", q)

    def answer_checkin(self, choice: int) -> Optional[dict]:
        """学生答了抽问题。返回作答结果（含对错和讲解）；当前没有待答的题则返回 None。
        答错 / 答「有点模糊」的记进错题本，课后「错题复习」会带上它。"""
        with self._lock:
            q = self.pending_checkin
            if q is None:
                return None
            sid = self.session
            self.pending_checkin = None
            self._last_interaction = time.time()
            result = quiz.grade(q, choice)
            options = q.get("options") or []
            record = {
                "id": q.get("id"),
                "topic": q.get("topic") or "",
                "question": q.get("question") or "",
                "choice": choice,
                "choice_text": options[choice] if 0 <= choice < len(options) else "",
                "answer_text": quiz.correct_text(q),
                "result": result,
                "explain": q.get("explain") or "",
                "tc": q.get("tc") or "",
                "time": time.time(),
            }
            self.checkins.append(record)
            mistake = quiz.to_mistake(q, result) if result in (quiz.WRONG, quiz.UNSURE) else None
        if mistake:
            try:
                store.add([mistake])
            except Exception as e:      # 错题本写失败不该影响上课
                log.warning("抽问结果写入错题本失败: %s", e)
        self._emit(sid, "checkin_result", record)
        return record

    def skip_checkin(self):
        """学生把抽问关掉了：算一次互动，不再追问这道题。"""
        with self._lock:
            self.pending_checkin = None
            self._last_interaction = time.time()

    # ================= 回响 =================
    def end_lesson(self):
        """课程结束：异步生成回响页数据。"""
        self.stop()
        self.active = False              # 下课了：拍题/反馈不再记入这节课
        self.pending_checkin = None      # 下课后不该再留着没答完的抽问
        sid = self.session
        self._emit(sid, "status", "summarizing")
        self._pool.submit(self._safe, sid, self._make_echo, sid)

    def _make_echo(self, sid):
        with self._lock:
            if not self._live(sid):
                return
            has_pending = bool(self.lines[self._pending_from:])
        if has_pending:
            try:
                self._extract_concept(True, sid)
            except Exception as e:
                log.warning("flush concept 失败: %s", e)

        report = None
        if self.llm and self.entries:
            try:
                with self._lock:
                    timeline = self._timeline_text()
                    feedback = self._feedback_text()
                    bps = "\n".join(f"- {b.breakpoint_tc} {b.concept}：缺失「{b.missing}」，{b.reason}"
                                    f"（{_bp_outcome(b)}）"
                                    for b in self.breakpoints)
                    duration = time.time() - self.start_ts
                    line_count = len(self.lines)
                    char_count = sum(len(l.text) for l in self.lines)
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
                    st = s.get("status")
                    st = st if st in ("ok", "fixed", "review") else _status_from_mastery(m)
                    skills.append(EchoSkill(str(s.get("name", "")), m, st))
                chain = [str(x) for x in (data.get("review_chain") or []) if x]
                summary = str(data.get("summary") or "")
                highlights = [str(x) for x in (data.get("highlights") or []) if x][:5]
                if skills:
                    report = EchoReport(skills, chain, str(data.get("suggestion") or ""),
                                        summary=summary, highlights=highlights,
                                        duration=duration, line_count=line_count,
                                        char_count=char_count)
            except Exception as e:
                log.warning("回响 LLM 失败，使用规则兜底: %s", e)
        if report is None:
            report = self._heuristic_echo()
        report.graph = self._concept_graph()
        self._emit(sid, "status", "done")
        self._emit(sid, "echo", report)

    def _concept_graph(self) -> dict:
        """把时间轴上的知识点和它们的前置关系整理成一张图，给课后「知识地图」用。

        边只保留两端都在图里的：前置概念如果没在时间轴上出现过，画出来会是个悬空的点。

        前置关系覆盖率有限 —— 一个知识点可能既没有前置、也没被别人当前置，
        那样它就是孤点，整张图看着只有几个散点。这种按讲课顺序接到前一个知识点上，
        保证图是一节课完整的知识链，而不是只连了「有依赖关系」的那几个。
        """
        with self._lock:
            entries = list(self.entries)
        nodes, edges, times = [], [], {}
        for e in entries:
            topic = (e.concept.topic or "").strip()
            if not topic:
                continue
            if not any(_same_topic(topic, n) for n in nodes):
                nodes.append(topic)
                times[topic] = e.concept.timecode
        for e in entries:
            topic = e.concept.topic
            for pre in (e.concept.prerequisites or []):
                hit = next((n for n in nodes if _same_topic(pre, n)), None)
                if hit and not _same_topic(hit, topic):
                    edge = [hit, topic]
                    if edge not in edges:
                        edges.append(edge)

        linked = {t for edge in edges for t in edge}
        prev = None
        for topic in nodes:
            if prev is not None and topic not in linked:
                edges.append([prev, topic])
                linked.add(topic)
            prev = topic
        return {"nodes": nodes, "edges": edges, "times": times}

    def _heuristic_echo(self) -> EchoReport:
        with self._lock:
            entries = list(self.entries)
            bps = list(self.breakpoints)
            fbs = [self._feedback_of(i) for i in range(len(entries))]
            duration = time.time() - self.start_ts
            line_count = len(self.lines)
            char_count = sum(len(l.text) for l in self.lines)
        score = {"ok": 1.0, "warn": 0.55, "lost": 0.6, "bp": 0.15}
        skills = []
        for e, fb in zip(entries, fbs):
            m = min([score[f] for f in fb], default=0.85)
            if e.is_bp and e.fixed:
                m, st = 0.6, "fixed"
            elif e.is_bp or "warn" in fb or "lost" in fb:
                st = "review"
            else:
                st = "ok"
            skills.append(EchoSkill(e.concept.topic, m, st))
        chain = []
        if bps:
            b = bps[0]
            chain = [b.concept]
            for e in entries:
                if e.concept.topic == b.concept:
                    chain += e.concept.prerequisites[:2]
        topics = "、".join(e.concept.topic for e in entries)
        lost_topic = next((e.concept.topic for e, fb in zip(entries, fbs) if "bp" in fb), "")
        if entries:
            summary = f"这节课讲了：{topics}。"
            if lost_topic:
                summary += f"其中「{lost_topic}」你掉队过。"
        else:
            summary = "这节课 Echo 还没抓到足够的知识点，下次记得提前打开哦。"
        highlights = [e.concept.summary for e in entries if e.concept.summary][:5]
        return EchoReport(skills, chain, f"建议复习：{chain[-1]}" if chain else "今天都跟上了！",
                          summary=summary, highlights=highlights,
                          duration=duration, line_count=line_count, char_count=char_count)

    # ================= 工具 =================
    def _timeline_text(self) -> str:
        out = []
        for i, e in enumerate(self.entries):
            c = e.concept
            fb = "、".join(FEEDBACK_LABEL[f] for f in self._feedback_of(i) if f in FEEDBACK_LABEL)
            if e.is_bp:
                fb = (fb + "、" if fb else "") + ("⚠ 掉队断点（已补上）" if e.fixed else "⚠ 掉队断点")
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

    def _safe(self, sid, fn, *a):
        try:
            fn(*a)
        except LLMError as e:
            log.exception("LLM 错误")
            self._emit(sid, "status", "listening")
            self._emit(sid, "error", str(e))
        except Exception as e:
            log.exception("引擎错误")
            self._emit(sid, "status", "listening")
            self._emit(sid, "error", f"{type(e).__name__}: {e}")


def _bp_outcome(b: BreakPoint) -> str:
    if b.fixed:
        return "学生已补上"
    if b.self_review:
        return "学生选择自己看，未用 AI 补"
    return "学生没有补上"


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
    return "ok" if m >= 0.75 else "review"
