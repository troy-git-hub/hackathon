//
//  EchoEngine.swift
//  Echo - 课堂引擎（后端核心，对应 Python echo/backend/engine.py + qt_bridge.py）
//
//  transcript 流  →  Concept Timeline（每隔一段时间让 LLM 抽一次知识点）
//  学生反馈 ✓ / ? / !  →  !「我掉队了」触发 Break Point Engine
//  课程结束  →  「回响」复盘
//
//  整个引擎跑在 MainActor 上，SwiftUI 直接观察属性即可；LLM 调用是 async 的，不会阻塞 UI。
//

import Foundation
import Observation

private struct Feedback {
    var t: Double
    var kind: FeedbackKind
    var concept: String
}

private struct ConceptEntry {
    var t: Double
    var concept: Concept
    var isBP = false
    var fixed = false     // 该断点已被学生「补上了」
}

@Observable
final class EchoEngine {
    // ================= 给 UI 观察的状态 =================
    private(set) var status: EchoStatus = .idle
    private(set) var transcripts: [TranscriptLine] = []
    /// 最近一次掉队分析结果（分析中为 nil）
    private(set) var breakpoint: BreakPoint?
    /// 回响页数据，endLesson() 之后生成
    private(set) var report: EchoReport?
    private(set) var lastError: String?
    /// 示例课总时长（秒）；实时课程为 0
    private(set) var totalSeconds: Double = 0
    private(set) var sourceKind: SourceKind = EchoConfig.source

    /// 完整的课堂时间轴，最后一个是「现在」
    var timeline: [Concept] { entries.map(\.concept) }
    var current: Concept? { entries.last?.concept }
    /// 掉队时展开窗口要展示的时间轴片段：断点前 1 个 + 断点 + 后 2 个 + 现在
    var breakpointTimeline: [Concept] {
        breakpointShownIDs.compactMap { id in entries.first { $0.concept.id == id }?.concept }
    }
    var hasLLM: Bool { llm != nil }
    /// AI 正在整理时间轴时非 nil：「正在理解：…」
    private(set) var thinking: String?
    /// 真实声纹响度 0…1（约 20Hz），驱动 UI 的声纹球；没声音时回落到 0
    private(set) var level: Double = 0
    /// 离线：不调 LLM，时间轴 / 断点 / 回响全部走规则和 mock（断网演示用）
    private(set) var offline = EchoConfig.offline
    /// 本节课所有掉队断点（错题本用）
    private(set) var breakpoints: [BreakPoint] = []
    /// 当前课次编号；音频来源开始时记下，迟到的转写据此丢弃
    private(set) var lesson = 0

    // ================= 课程名 / 抽问（课堂抽问=摸鱼探测） =================
    /// 课程名。开课前 setTitle(_:) 设置，超长截断 40 字；跨课保留，clearTitle() 显式清空。
    private(set) var title = ""
    /// 是否在上课中。start() 置 true，endLesson() / reset() 置 false；
    /// 反馈（拍题）只在 active 时记入本节课。
    private(set) var active = false
    /// 当前等着学生回答的抽问题（nil 表示没有）。
    private(set) var pendingCheckin: CheckinQuestion?
    /// 本节课历次抽问的作答记录（含对错），抽问重算 / 回响用。
    private(set) var checkins: [CheckinRecord] = []

    // ================= 可选回调（除了观察属性之外的事件流） =================
    @ObservationIgnored var onTranscript: ((TranscriptLine) -> Void)?
    @ObservationIgnored var onConcept: ((Concept) -> Void)?
    @ObservationIgnored var onBreakpoint: ((BreakPoint, [Concept]) -> Void)?
    @ObservationIgnored var onEcho: ((EchoReport) -> Void)?
    @ObservationIgnored var onError: ((String) -> Void)?
    /// 出一题抽问时回调（UI 也可直接观察 pendingCheckin）
    @ObservationIgnored var onCheckin: ((CheckinQuestion) -> Void)?
    /// 学生答完抽问后回调作答结果
    @ObservationIgnored var onCheckinResult: ((CheckinRecord) -> Void)?

    // ================= 内部状态 =================
    private var entries: [ConceptEntry] = []
    private var breakpointShownIDs: [UUID] = []
    @ObservationIgnored private var feedbacks: [Feedback] = []
    @ObservationIgnored private var pendingFrom = 0          // transcripts[pendingFrom...] 还没抽过 concept
    @ObservationIgnored private var lastExtract = Date()
    @ObservationIgnored private var startTS = Date()
    @ObservationIgnored private var conceptInterval = EchoConfig.conceptInterval
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var extracting: Task<Void, Never>?
    @ObservationIgnored private var extractToken = 0
    @ObservationIgnored private var source: AudioSource?
    @ObservationIgnored private let useLLM: Bool
    private var client: LLM?
    // 抽问状态（对应 Python engine 的 _last_interaction / _last_checkin_at / _checkin_asking）
    @ObservationIgnored private var lastInteraction = Date()   // 学生最近一次动手（反馈/补课/答题）
    @ObservationIgnored private var lastCheckinAt = Date.distantPast  // 上一次抽问的墙钟时间
    @ObservationIgnored private var pendingLostAt: Double = 0   // 最近一次点「我掉队了」的墙钟
    @ObservationIgnored private var checkinAsking = false      // 有一道正在出（防抖，别连着派）
    @ObservationIgnored private var weakCheckinTopics: [String] = []  // 抽问答错/模糊过的知识点（去重，按序）
    /// 离线时不给 LLM，引擎各处统一走这个
    private var llm: LLM? { offline ? nil : client }

    init(useLLM: Bool = true) {
        self.useLLM = useLLM
        makeClient()
    }

    /// 按当前配置（含设置里新存的 key）重建 LLM 客户端
    private func makeClient() {
        client = nil
        guard useLLM else { return }
        do { client = try LLM() } catch {   // 无 key → 退化为 mock
            print("[echo.engine] LLM 不可用，使用 mock 数据: \(error.localizedDescription)")
        }
    }

    /// 只切 LLM 在线/离线，不重开课程。
    func setOffline(_ on: Bool) { offline = on }

    // ================= 生命周期 =================

    /// 开课：重置引擎并开始听。source 默认取配置（ECHO_SOURCE，默认 system）。
    func start(source kind: SourceKind? = nil) {
        stop()
        let kind = kind ?? EchoConfig.source
        makeClient()
        reset()
        active = true                 // 开始上课：此后拍题/反馈才记入本节课
        sourceKind = kind
        conceptInterval = kind == .demo ? EchoConfig.demoLineInterval * 3 : EchoConfig.conceptInterval
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                self?.tick()
            }
        }
        status = .listening
        let src = makeSource(kind)
        totalSeconds = src.totalSeconds
        source = src
        src.start()
    }

    /// 停止听课（不生成回响）。
    func stop() {
        ticker?.cancel()
        ticker = nil
        source?.stop()
        source = nil
        level = 0
    }

    private func reset() {
        lesson += 1
        extracting = nil
        startTS = Date()
        transcripts = []
        entries = []
        feedbacks = []
        breakpoints = []
        breakpoint = nil
        breakpointShownIDs = []
        report = nil
        lastError = nil
        thinking = nil
        level = 0
        pendingFrom = 0
        lastExtract = Date()
        // 抽问：尚未开始上课（拍题/反馈这时不记入课程）；title 不在这里清，跨课保留
        active = false
        pendingCheckin = nil
        checkins = []
        lastInteraction = Date()
        lastCheckinAt = Date.distantPast
        pendingLostAt = 0
        checkinAsking = false
        weakCheckinTopics = []
    }

    // ================= 课程名 =================

    /// 给这节课命名，开课前调用；超长截断到 40 字。
    func setTitle(_ name: String) {
        title = String(name.trimmingCharacters(in: .whitespacesAndNewlines).prefix(40))
    }

    /// 清空课程名，用于「开始新的一节课」时显式重置。
    func clearTitle() { title = "" }

    private func makeSource(_ kind: SourceKind) -> AudioSource {
        switch kind {
        case .demo: DemoSource(engine: self)
        case .mic: LiveSpeechSource(engine: self, capture: .mic)
        case .system: LiveSpeechSource(engine: self, capture: .system)
        }
    }

    /// 从开课到现在的墙钟秒数（实时音频用）。
    func elapsed() -> Double { Date().timeIntervalSince(startTS) }

    /// 当前课堂时间（秒）。transcript 带自定义时间戳时以最新一句为准。
    func now() -> Double {
        let wall = elapsed()
        if let last = transcripts.last {
            return max(last.t, min(wall, last.t + 30))
        }
        return wall
    }

    // 给音频来源用的状态 / 错误入口
    func setStatus(_ s: EchoStatus) { status = s }

    func reportError(_ message: String, lesson: Int? = nil) {
        guard lesson == nil || lesson == self.lesson else { return }
        lastError = message
        onError?(message)
    }

    /// 音频来源喂入当前响度（0…1）
    func setLevel(_ v: Double, lesson: Int) {
        guard lesson == self.lesson, source != nil else { return }
        level = max(0, min(1, v))
    }

    // ================= 输入：transcript =================

    /// lesson：音频来源开始时拿到的课次；不是当前这节课的转写直接丢弃。
    func addTranscript(_ text: String, t: Double? = nil, lesson: Int? = nil) {
        guard lesson == nil || lesson == self.lesson else { return }
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let line = TranscriptLine(t: t ?? elapsed(), text: text)
        transcripts.append(line)
        onTranscript?(line)
    }

    /// 语音识别热词：时间轴上已识别出的知识点
    func hotWords() -> [String] {
        var hot: [String] = []
        for c in entries.suffix(6).map(\.concept) {
            for w in [c.topic] + c.concepts.prefix(3) where !hot.contains(w) { hot.append(w) }
        }
        return hot
    }

    private func tick() {
        checkCheckin()      // 摸鱼探测：即使没有新转写也要判断该不该抽问
        let pending = transcripts[pendingFrom...]
        guard !pending.isEmpty else { return }
        let chars = pending.reduce(0) { $0 + $1.text.count }
        let due = Date().timeIntervalSince(lastExtract) >= conceptInterval
        if (chars >= EchoConfig.conceptMinChars && due) || chars >= 400 {
            Task { await self.safely { try await self.extractConcept(force: false) } }
        }
    }

    // ================= Concept Timeline =================

    /// force=false 时已有抽取在跑就直接返回；force=true 时等它跑完再抽一次。
    private func extractConcept(force: Bool) async throws {
        while let running = extracting {
            guard force else { return }
            await running.value
        }
        // 任务自己在结束前清掉 extracting，否则等待者拿到已完成的 task 会原地空转、饿死主线程
        extractToken += 1
        let token = extractToken
        var failure: Error?
        let task = Task {
            do { try await self.doExtract() } catch { failure = error }
            if self.extractToken == token { self.extracting = nil }
        }
        extracting = task
        await task.value
        if let failure { throw failure }
    }

    private func doExtract() async throws {
        let lesson = lesson
        let endIdx = transcripts.count
        let pending = Array(transcripts[pendingFrom..<endIdx])
        guard !pending.isEmpty else { return }
        let timeline = timelineText()
        let chunk = pending.map { "[\($0.tc)] \($0.text)" }.joined(separator: "\n")
        thinking = "正在理解：" + (chunk.count > 30 ? chunk.prefix(30) + "…" : chunk)
        defer { if lesson == self.lesson { thinking = nil } }

        let data: JSONDict
        if let llm {
            data = try await llm.json(system: Prompts.system(Prompts.conceptSystem),
                                      user: Prompts.conceptUser(timeline: timeline.isEmpty ? "（暂无）" : timeline,
                                                                chunk: chunk),
                                      maxTokens: 700)
        } else {
            data = mockConcept(chunk)
        }
        guard lesson == self.lesson else { return }
        let segs = (data["segments"] as? [Any]) ?? [data]

        pendingFrom = max(pendingFrom, endIdx)
        lastExtract = Date()
        var changed: [UUID] = []
        for case let seg as JSONDict in segs {
            let topic = str(seg["topic"]).isEmpty ? "课堂内容" : str(seg["topic"])
            let prevIdx = entries.indices.last
            if let i = prevIdx, sameTopic(entries[i].concept.topic, topic) {
                var c = entries[i].concept
                if topic.count < c.topic.count { c.topic = topic }   // 「贝叶斯公式引入」→「贝叶斯公式」取更短的正式名
                c.concepts = Array(merge(c.concepts, seg["concepts"]).prefix(6))
                c.prerequisites = Array(merge(c.prerequisites, seg["prerequisites"]).prefix(4))
                let summary = str(seg["summary"])
                if !summary.isEmpty { c.summary = summary }
                entries[i].concept = c
                if !changed.contains(c.id) { changed.append(c.id) }
            } else {
                // 片段起点：取 LLM 给的时间码，吸附到本段真实句子上，且保持单调递增
                let lo = max(pending[0].t, prevIdx.map { entries[$0].t + 1 } ?? 0)
                var t = parseTC(seg["start"] as? String).map { min(max($0, lo), pending.last!.t) } ?? lo
                t = max(pending.last { $0.t <= t }?.t ?? t, lo)
                let c = Concept(timecode: fmtTC(t), topic: topic,
                                concepts: asList(seg["concepts"]),
                                prerequisites: asList(seg["prerequisites"]),
                                summary: str(seg["summary"]), status: .now)
                entries.append(ConceptEntry(t: t, concept: c))
                if let i = prevIdx, entries[i].concept.status == .now {
                    // 新 concept 入列后，上一个的时间区间才闭合，此时再按反馈定状态
                    entries[i].concept.status = statusOf(i)
                }
                changed.append(c.id)
            }
        }
        if let onConcept {
            for id in changed { if let c = entries.first(where: { $0.concept.id == id })?.concept { onConcept(c) } }
        }
    }

    private func mockConcept(_ chunk: String) -> JSONDict {
        for c in MockData.concepts where chunk.contains(String(c.topic.prefix(2))) {
            return ["topic": c.topic, "concepts": c.concepts, "prerequisites": c.prerequisites, "summary": c.summary]
        }
        return ["topic": "课堂内容", "concepts": [String](), "prerequisites": [String](), "summary": String(chunk.prefix(30))]
    }

    // ================= 学生反馈 =================

    /// .lost 会异步触发 Break Point Engine。只有上课中（active）才记入本节课。
    func feedback(_ kind: FeedbackKind) {
        guard active else { return }
        lastInteraction = Date()     // 学生动手了，说明人在
        feedbacks.append(Feedback(t: now(), kind: kind, concept: entries.last?.concept.topic ?? ""))
        if kind == .lost {
            pendingLostAt = Date().timeIntervalSince1970   // 掉队起点（墙钟），断点分析好之后挂上去
            status = .analyzing
            breakpoint = nil
            Task { await self.safely { await self.findBreakpoint() } }
        }
    }

    // ================= Break Point Engine =================

    private func findBreakpoint() async {
        let lesson = lesson
        // 同时把还没处理的 transcript 抽成 concept（并行，不阻塞断点分析；
        // 断点 prompt 本身带原始转写，时间轴只用于展示和吸附）
        var flushDone = true
        if transcripts[pendingFrom...].reduce(0, { $0 + $1.text.count }) >= 10 {
            flushDone = false
            Task {
                do { try await self.extractConcept(force: true) } catch {
                    print("[echo.engine] flush concept 失败: \(error.localizedDescription)")
                }
                flushDone = true
            }
        }

        let now = now()
        var window = transcripts.filter { $0.t >= now - EchoConfig.lostWindow }
        if window.isEmpty { window = Array(transcripts.suffix(30)) }
        let timeline = timelineText()
        let feedback = feedbackText()
        let cur = entries.last?.concept.topic ?? "（未知）"

        var data: JSONDict?
        if let llm, !window.isEmpty {
            do {
                data = try await llm.json(
                    system: Prompts.system(Prompts.breakpointSystem),
                    user: Prompts.breakpointUser(
                        timeline: timeline.isEmpty ? "（暂无）" : timeline,
                        feedback: feedback.isEmpty ? "（无）" : feedback,
                        window: "\(Int(EchoConfig.lostWindow) / 60) 分钟",
                        transcript: window.map { "[\($0.tc)] \($0.text)" }.joined(separator: "\n"),
                        current: cur, now: fmtTC(now)),
                    temperature: 0.4, maxTokens: 800,
                    timeout: EchoConfig.breakpointTimeout, attempts: 1)
            } catch {   // 掉队是核心交互，LLM 挂了也要给出断点，不能让 UI 卡在 analyzing
                print("[echo.engine] 断点 LLM 失败，使用规则兜底: \(error.localizedDescription)")
            }
        }

        var bp: BreakPoint
        if let data {
            bp = BreakPoint(breakpointTC: str(data["breakpoint"]),
                            concept: str(data["concept"]).isEmpty ? cur : str(data["concept"]),
                            missing: str(data["missing"]), reason: str(data["reason"]),
                            microLesson: str(data["micro_lesson"]), note: str(data["note"]),
                            known: str(data["known"]), step: str(data["step"]), now: str(data["now"]))
        } else if llm != nil, !window.isEmpty {
            bp = heuristicBreakpoint(cur)
        } else if window.isEmpty {
            bp = BreakPoint(breakpointTC: "", concept: cur, missing: "Echo 还没听到课堂内容",
                            reason: "请确认网课正在播放，且声音没有静音",
                            microLesson: "Echo 会自动抓取电脑正在播放的声音。开始播放网课后，等老师讲一两分钟再点「我掉队了」。",
                            note: "还没有内容", known: "网课正在播放",
                            step: "确认声音没有静音\n等老师讲一两分钟",
                            now: "再点「我掉队了」，Echo 就能帮你找断点")
        } else if window.contains(where: { $0.text.contains("贝叶斯") }) {
            bp = MockData.breakpoint
            bp.id = UUID()
        } else {
            bp = heuristicBreakpoint(cur)
        }

        // 只短暂等一下：来得及就把最新知识点并进时间轴，来不及也先出断点（concept 稍后照常推送）
        let deadline = Date().addingTimeInterval(EchoConfig.flushGrace)
        while !flushDone && Date() < deadline {
            try? await Task.sleep(for: .milliseconds(100))
        }
        guard lesson == self.lesson else { return }
        bp.lostAt = pendingLostAt > 0 ? pendingLostAt : Date().timeIntervalSince1970
        let shown = attachBreakpoint(&bp)
        breakpoints.append(bp)
        breakpoint = bp
        // 立刻落盘，不等下课：中途重开、崩溃、没点下课就关窗，已经找到的断点（含花了 API 的补课讲解）都不丢
        persistBreakpoint(bp, checkRelapse: true)
        if status == .analyzing { status = .listening }
        onBreakpoint?(bp, shown)
    }

    /// 规则兜底：取最近一个点过「有点懵」的知识点，否则取「现在」的前一个。
    private func heuristicBreakpoint(_ cur: String) -> BreakPoint {
        guard !entries.isEmpty else {
            return BreakPoint(breakpointTC: "", concept: cur, missing: "「\(cur)」是怎么来的？", reason: "这一段讲得比较快",
                              microLesson: "Echo 暂时连不上 AI，建议回看最近 1~2 分钟的课程内容。", note: "讲得比较快",
                              known: "前面讲过的定义", step: "回看最近 1~2 分钟的课程内容",
                              now: "再接上老师现在讲的「\(cur)」")
        }
        let idx = entries.indices.last { feedbackOf($0).contains("warn") } ?? max(0, entries.count - 2)
        let c = entries[idx].concept
        let pre = c.prerequisites.isEmpty ? "前面的定义" : c.prerequisites.joined(separator: "、")
        let lesson = """
        你可能在「\(c.topic)」这里掉队了。
        老师在讲：\(c.summary)
        它依赖的前置知识是：\(pre)，先确认这些你都清楚。
        Echo 暂时连不上 AI，建议回看 \(c.timecode) 附近的内容，再接上老师现在讲的「\(cur)」。
        """
        return BreakPoint(breakpointTC: c.timecode, concept: c.topic, missing: "「\(c.topic)」是怎么来的？",
                          reason: "这里依赖\(pre)，讲得比较快", microLesson: lesson, note: "这里讲得比较快",
                          known: pre, step: "\(c.summary)\n回看 \(c.timecode) 附近，把这一步和\(pre)对上",
                          now: "再接上老师现在讲的「\(cur)」")
    }

    /// 把断点吸附到时间轴上的某个 concept，返回给 UI 展示的那一段时间轴。
    private func attachBreakpoint(_ bp: inout BreakPoint) -> [Concept] {
        if entries.isEmpty {
            let c = Concept(timecode: bp.breakpointTC.isEmpty ? fmtTC(now()) : bp.breakpointTC, topic: bp.concept,
                            concepts: [], prerequisites: [], summary: bp.reason, status: .now)
            entries.append(ConceptEntry(t: parseTC(c.timecode) ?? 0, concept: c))
            bp.breakpointTC = c.timecode
            breakpointShownIDs = [c.id]
            return [c]
        }

        var idx: Int?
        for (i, e) in entries.enumerated() where e.concept.topic == bp.concept { idx = i }   // 先按知识点名称精确匹配
        if idx == nil, !bp.concept.isEmpty {   // 再按名称包含（如「贝叶斯公式的推导」↔「贝叶斯公式」）
            for (i, e) in entries.enumerated()
            where bp.concept.contains(e.concept.topic) || e.concept.topic.contains(bp.concept) { idx = i }
        }
        if idx == nil, let t = parseTC(bp.breakpointTC) {   // 再按时间吸附到所在 concept
            idx = entries.indices.last { entries[$0].t <= t } ?? 0
        }
        let i = idx ?? entries.count - 1

        if entries[i].concept.status != .now { entries[i].concept.status = .warn }
        entries[i].isBP = true
        bp.breakpointTC = entries[i].concept.timecode
        if bp.note.isEmpty { bp.note = String(bp.reason.prefix(12)) }

        var shown = Array(entries[max(0, i - 1)..<min(entries.count, i + 3)].map(\.concept.id))
        if let last = entries.last?.concept.id, !shown.contains(last) { shown.append(last) }
        breakpointShownIDs = shown
        return breakpointTimeline
    }

    /// 学生点了「✓ 补上了，继续听课」：把最近一个断点标记为已补上。
    func markFixed() {
        guard !breakpoints.isEmpty else { return }
        lastInteraction = Date()
        breakpoints[breakpoints.count - 1].fixed = true
        breakpoints[breakpoints.count - 1].resolvedAt = Date().timeIntervalSince1970   // 回响里算掉队时长
        let bp = breakpoints[breakpoints.count - 1]
        breakpoint = bp
        if let i = entries.indices.last(where: { entries[$0].isBP && entries[$0].concept.timecode == bp.breakpointTC }) {
            entries[i].fixed = true
        }
        persistBreakpoint(bp)   // 状态 review → fixed，重存一遍覆盖
    }

    /// 学生点了「我自己看看」：最近一个断点记为自己回看，回响里仍算待复习。
    func markSelf() {
        guard !breakpoints.isEmpty else { return }
        lastInteraction = Date()
        breakpoints[breakpoints.count - 1].selfReview = true
        breakpoints[breakpoints.count - 1].resolvedAt = Date().timeIntervalSince1970
        breakpoint = breakpoints[breakpoints.count - 1]
        persistBreakpoint(breakpoints[breakpoints.count - 1])
    }

    /// 把一个断点立刻写进错题本。markFixed / markSelf 改了状态后也调这个同步。
    ///
    /// checkRelapse=true（只有刚找到这一刻才传）：在它自己还没存进错题本之前，查这个 topic
    /// 是不是已经在里面 —— 在的话说明「上次掉的队没真补上，这次又掉了」。等它存进去之后再查，
    /// 查到的就是它自己，每条都会被误判成复发。
    private func persistBreakpoint(_ bp: BreakPoint, checkRelapse: Bool = false) {
        let topic = bp.concept.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !topic.isEmpty else { return }
        let relapse = checkRelapse
            && ReviewStore.load().contains { $0.topic.trimmingCharacters(in: .whitespacesAndNewlines) == topic }
        ReviewStore.add([ReviewItem(topic: topic, timecode: bp.breakpointTC, missing: bp.missing, reason: bp.reason,
                                    microLesson: bp.microLesson, known: bp.known, step: bp.step, now: bp.now,
                                    status: bp.fixed ? "fixed" : "review")], relapse: relapse)
    }

    /// 给追问 / 圈图问答用的课堂上下文：当前知识点 + 最近 N 秒转写。
    func lessonContext(seconds: Double = 120) -> String {
        if transcripts.isEmpty && entries.isEmpty { return "" }
        let nowT = transcripts.last?.t ?? 0
        let recent = transcripts.filter { $0.t >= nowT - seconds }.suffix(25)
        let tl = entries.suffix(5).map(\.concept.topic).joined(separator: " → ")
        return """
        【课堂上下文】
        老师现在在讲：\(entries.last?.concept.topic ?? "（还没识别出知识点）")
        最近的知识点：\(tl.isEmpty ? "（暂无）" : tl)
        老师最近说的话：
        \(recent.isEmpty ? "（暂无）" : recent.map { "[\($0.tc)] \($0.text)" }.joined(separator: "\n"))
        """
    }

    // ================= 课堂抽问（摸鱼探测） =================
    //
    //  出题 / 判分交给 Quiz.swift：Quiz.checkin(...)（内部已带自评题兜底）、
    //  Quiz.selfCheckin(...)、Quiz.grade(...)、Quiz.correctText(...)。
    //  只有在线（llm != nil）才走 Quiz.checkin；离线 / 没 key 直接自评题。

    /// 该抽问了吗？只在开课中、有可考的知识点、学生久没动手、且距上次抽问够久时为真。
    /// 对应 Python 的 _checkin_due，由 tick() 每秒调用；出题要几秒，用 checkinAsking 防抖。
    private func checkCheckin() {
        guard EchoConfig.checkinEnabled, active else { return }
        guard pendingCheckin == nil else { return }      // 上一道还没答，别追着问
        guard !entries.isEmpty else { return }           // 还没听到能出题的内容
        let now = Date()
        guard now.timeIntervalSince(startTS) >= EchoConfig.checkinWarmup else { return }
        guard now.timeIntervalSince(lastCheckinAt) >= EchoConfig.checkinInterval else { return }
        // 学生刚点过反馈 / 补过课，说明人在，不用打扰
        guard now.timeIntervalSince(lastInteraction) >= EchoConfig.checkinIdle else { return }
        guard !checkinAsking else { return }
        checkinAsking = true
        let sid = lesson
        Task { [weak self] in await self?.performCheckin(sid: sid) }
    }

    /// 学生自己按「考考我」要一道课上小题。已经有一道没答完时不再出，返回 false。
    @discardableResult
    func askCheckinNow() -> Bool {
        guard active, pendingCheckin == nil, !checkinAsking else { return false }
        checkinAsking = true
        let sid = lesson
        Task { [weak self] in await self?.performCheckin(sid: sid) }
        return true
    }

    /// 后台：拿最近讲过的知识点出一道题，设 pendingCheckin 并抛 onCheckin 事件。
    private func performCheckin(sid: Int) async {
        defer { checkinAsking = false }
        guard lesson == sid, active else { return }
        let concept = entries.last?.concept
        let current = concept?.topic ?? ""
        let tc = concept?.timecode ?? ""
        let timeline = timelineText()
        let transcript = transcripts.suffix(12).map { "[\($0.tc)] \($0.text)" }.joined(separator: "\n")
        let focus = checkinFocus()

        // 引擎没有 llm 表示「没配 key」或「已切离线」，两种都不该再新建连接，直接自评题。
        var question: CheckinQuestion
        if llm != nil {
            question = await Quiz.checkin(timeline: timeline, transcript: transcript,
                                          current: current, timecode: tc, focus: focus)
        } else {
            question = Quiz.selfCheckin(topic: current, timecode: tc,
                                        why: entries.isEmpty ? "noconcept" : "")
        }
        guard lesson == sid, active else { return }   // 出题期间下课/重开，丢弃
        question.id = checkins.count + 1
        pendingCheckin = question
        lastCheckinAt = Date()
        onCheckin?(question)
    }

    /// 学生答了抽问题。判分、生成 CheckinRecord，答错 / 答「有点模糊」的写进错题本。
    /// 当前没有待答题时返回 nil。
    @discardableResult
    func answerCheckin(_ choice: Int) -> CheckinRecord? {
        guard let q = pendingCheckin else { return nil }
        pendingCheckin = nil
        lastInteraction = Date()
        let result = Quiz.grade(q, choice: choice)
        let record = CheckinRecord(question: q.question, chosen: choice, result: result,
                                   answer: Quiz.correctText(q), explain: q.explain)
        checkins.append(record)
        if result != Quiz.right {
            markWeak(q.topic, tc: q.timecode)
            if !q.topic.isEmpty, !weakCheckinTopics.contains(q.topic) { weakCheckinTopics.append(q.topic) }
            ReviewStore.add([checkinMistake(q, result: result)])
        }
        onCheckinResult?(record)
        return record
    }

    /// 学生把抽问关掉了：算一次互动，不再追问这道题。
    func skipCheckin() {
        pendingCheckin = nil
        lastInteraction = Date()
    }

    /// 这一节课里「以前就掉过队、这次又掉了」的知识点（按出现顺序，去重）。
    ///
    /// 错题本里本来就有记录，说明上次掉的队并没有真的补上 —— 这是「其实没掌握」的强信号。
    /// 必须在 ReviewStore.add(...) 之前调用：add 会把这一节的断点全写进错题本，
    /// 那之后就分不出哪些是「本来就在里面」的了。
    func relapseTopics() -> [String] {
        let known = Set(ReviewStore.load().map { $0.topic.trimmingCharacters(in: .whitespacesAndNewlines) })
        var out: [String] = []
        for bp in breakpoints {
            let topic = bp.concept.trimmingCharacters(in: .whitespacesAndNewlines)
            if !topic.isEmpty, known.contains(topic), !out.contains(topic) { out.append(topic) }
        }
        return out
    }

    /// 学生此刻的状态，喂给出题 prompt：刚在哪儿掉过队、之前哪道抽问答错过。
    private func checkinFocus() -> String {
        var bits: [String] = []
        if let last = breakpoints.last(where: { !$0.concept.isEmpty }) {
            bits.append("刚在「\(last.concept)」点过掉队" + (last.fixed ? "，已经补上了" : "，还没补上"))
        }
        var weak: [String] = []
        for topic in weakCheckinTopics where !topic.isEmpty {
            if !weak.contains(topic) { weak.append(topic) }
        }
        if !weak.isEmpty { bits.append("之前抽问答错过：" + weak.suffix(3).joined(separator: "、")) }
        return bits.isEmpty ? "" : bits.joined(separator: "；") + "。"
    }

    /// 把答错的抽问题转成错题本记录（字段与 ReviewStore.add 约定一致）。
    /// 抽问答错/模糊的知识点写成错题本里的一条（对应 Python quiz.to_mistake 的字段）。
    private func checkinMistake(_ q: CheckinQuestion, result: String) -> ReviewItem {
        let right = Quiz.correctText(q)
        var lesson = q.explain
        if !right.isEmpty { lesson = "正确答案：\(right)" + (q.explain.isEmpty ? "" : "\n\(q.explain)") }
        if result == Quiz.unsure { lesson = "你自评「有点模糊」。" + lesson }
        if lesson.isEmpty { lesson = "回看这个知识点，确认自己能说清楚。" }
        return ReviewItem(topic: q.topic.isEmpty ? "课堂抽问" : q.topic, timecode: q.timecode,
                          missing: q.question, reason: "课堂抽问没答上来",
                          microLesson: lesson, known: "", step: right, now: "", status: "review")
    }

    /// 把一次「抽问没答上来」记成 warn 反馈，对应知识点在时间轴上标黄。
    /// 这样课后的回响、知识地图、错题本三处对得上。
    private func markWeak(_ topic: String, tc: String) {
        guard !topic.isEmpty else { return }
        let t = parseTC(tc) ?? now()
        feedbacks.append(Feedback(t: t, kind: .warn, concept: topic))
        if let i = entries.firstIndex(where: { sameTopic($0.concept.topic, topic) }) {
            entries[i].concept.status = .warn
        } else if !entries.isEmpty {
            entries[entries.count - 1].concept.status = .warn
        }
    }

    // ================= 回响 =================

    /// 课程结束：停止听课并异步生成回响页数据（写入 report）。
    func endLesson() {
        stop()
        active = false               // 下课了：拍题/反馈不再记入这节课
        pendingCheckin = nil         // 下课后不该再留着没答完的抽问
        // 断点在找到那一刻就已落盘（复发也在那时判过，见 persistBreakpoint），这里不再整批写。
        status = .summarizing
        Task { await self.safely { await self.makeEcho() } }
    }


    private func makeEcho() async {
        let lesson = lesson
        if pendingFrom < transcripts.count {
            do { try await extractConcept(force: true) } catch {
                print("[echo.engine] flush concept 失败: \(error.localizedDescription)")
            }
        }

        let duration = now()
        let lineCount = transcripts.count
        let charCount = transcripts.reduce(0) { $0 + $1.text.count }

        var result: EchoReport?
        if let llm, !entries.isEmpty {
            let bps = breakpoints.map {
                "- \($0.breakpointTC) \($0.concept)：缺失「\($0.missing)」，\($0.reason)（\($0.fixed ? "学生已补上" : $0.selfReview ? "学生选择自己看，未用 AI 补" : "学生没有补上")）"
            }.joined(separator: "\n")
            do {
                let feedback = feedbackText()
                let data = try await llm.json(system: Prompts.system(Prompts.echoSystem),
                                              user: Prompts.echoUser(timeline: timelineText(),
                                                                     feedback: feedback.isEmpty ? "（无）" : feedback,
                                                                     breakpoints: bps.isEmpty ? "（无）" : bps),
                                              maxTokens: 800)
                var skills: [EchoSkill] = []
                for case let s as JSONDict in (data["skills"] as? [Any]) ?? [] {
                    let m = max(0, min(1, double(s["mastery"]) ?? 0.5))
                    let st = SkillStatus(rawValue: str(s["status"])) ?? (m >= 0.75 ? .ok : .review)
                    skills.append(EchoSkill(name: str(s["name"]), mastery: m, status: st))
                }
                let chain = asList(data["review_chain"]).filter { !Mindmap.isPlaceholderTopic($0) }
                let summary = str(data["summary"])
                let highlights = Array(asList(data["highlights"]).prefix(5))
                if !skills.isEmpty {
                    result = EchoReport(skills: skills, reviewChain: chain, suggestion: str(data["suggestion"]),
                                        summary: summary, highlights: highlights,
                                        duration: duration, lineCount: lineCount, charCount: charCount)
                }
            } catch {
                print("[echo.engine] 回响 LLM 失败，使用规则兜底: \(error.localizedDescription)")
            }
        }
        guard lesson == self.lesson else { return }
        var r = result ?? heuristicEcho()
        r.fromMock = result == nil   // 走了兜底：不是真听懂这节课，界面据此不写进历史
        r.graph = conceptGraph()
        report = r
        status = .done
        onEcho?(r)
    }

    private func heuristicEcho() -> EchoReport {
        let score: [String: Double] = ["ok": 1.0, "warn": 0.55, "lost": 0.6, "bp": 0.15]
        var skills: [EchoSkill] = []
        for (i, e) in entries.enumerated() {
            let fb = feedbackOf(i)
            var m = fb.compactMap { score[$0] }.min() ?? 0.85
            let st: SkillStatus
            if e.isBP && e.fixed {
                m = 0.6; st = .fixed
            } else if e.isBP || fb.contains("warn") || fb.contains("lost") {
                st = .review
            } else {
                st = .ok
            }
            skills.append(EchoSkill(name: e.concept.topic, mastery: m, status: st))
        }
        var chain: [String] = []
        if let b = breakpoints.first {
            chain = [b.concept]
            for e in entries where e.concept.topic == b.concept { chain += e.concept.prerequisites.prefix(2) }
        }
        let topics = entries.map(\.concept.topic).joined(separator: "、")
        let lost = entries.indices.first { feedbackOf($0).contains("bp") }.map { entries[$0].concept.topic }
        var summary = entries.isEmpty
            ? "这节课 Echo 还没抓到足够的知识点，下次记得提前打开哦。"
            : "这节课讲了：\(topics)。"
        if let lost, !entries.isEmpty { summary += "其中「\(lost)」你掉队过。" }
        let highlights = Array(entries.map(\.concept.summary).filter { !$0.isEmpty }.prefix(5))
        return EchoReport(skills: skills, reviewChain: chain,
                          suggestion: chain.last.map { "建议复习：\($0)" } ?? "今天都跟上了！",
                          summary: summary, highlights: highlights,
                          duration: now(), lineCount: transcripts.count,
                          charCount: transcripts.reduce(0) { $0 + $1.text.count })
    }

    /// 把时间轴上的知识点和它们的前置关系整理成一张图，给课后「知识地图」用。
    /// 边只保留两端都在图里的；孤立点按讲课顺序接到前一个知识点上，保证图是一节课完整的知识链。
    private func conceptGraph() -> ConceptGraph {
        var nodes: [String] = []
        var times: [String: String] = [:]
        for e in entries {
            let topic = e.concept.topic.trimmingCharacters(in: .whitespaces)
            if topic.isEmpty || Mindmap.isPlaceholderTopic(topic) { continue }
            if !nodes.contains(where: { sameTopic($0, topic) }) {
                nodes.append(topic)
                times[topic] = e.concept.timecode
            }
        }
        var edges: [[String]] = []
        var seen = Set<String>()
        for e in entries {
            let topic = e.concept.topic
            if Mindmap.isPlaceholderTopic(topic) { continue }
            guard let hit = nodes.first(where: { sameTopic($0, topic) }) else { continue }
            for pre in e.concept.prerequisites {
                guard let from = nodes.first(where: { sameTopic($0, pre) }), !sameTopic(from, hit) else { continue }
                let key = from + "\u{0}" + hit
                if seen.contains(key) { continue }
                seen.insert(key)
                edges.append([from, hit])
            }
        }
        // 孤点按讲课顺序接上前一个，保证整张图是连着的
        var linked = Set(edges.flatMap { $0 })
        var prev = ""
        for n in nodes {
            if prev.isEmpty { prev = n; continue }
            if !linked.contains(n) {
                let key = prev + "\u{0}" + n
                if !seen.contains(key) { seen.insert(key); edges.append([prev, n]); linked.insert(n) }
            }
            prev = n
        }
        return ConceptGraph(nodes: nodes, edges: edges, times: times)
    }

    // ================= 工具 =================

    private func timelineText() -> String {
        entries.indices.map { i in
            let e = entries[i], c = e.concept
            var fb = feedbackOf(i).compactMap { FeedbackKind(rawValue: $0)?.label }.joined(separator: "、")
            if e.isBP { fb = (fb.isEmpty ? "" : fb + "、") + (e.fixed ? "⚠ 掉队断点（已补上）" : "⚠ 掉队断点") }
            let pre = c.prerequisites.isEmpty ? "无" : c.prerequisites.joined(separator: "、")
            return "[\(c.timecode)] \(c.topic) —— \(c.summary)（前置：\(pre)）" + (fb.isEmpty ? "" : "  学生反馈：\(fb)")
        }.joined(separator: "\n")
    }

    /// 按时间把学生反馈归属到第 i 个 concept（避免 LLM 抽取延迟导致归属错误）。
    private func feedbackOf(_ i: Int) -> [String] {
        let e = entries[i]
        let end = i + 1 < entries.count ? entries[i + 1].t : .infinity
        var out = feedbacks.filter { e.t <= $0.t && $0.t < end }.map(\.kind.rawValue)
        if e.isBP { out.append("bp") }
        return out
    }

    private func statusOf(_ i: Int) -> ConceptStatus {
        let fb = feedbackOf(i)
        return fb.contains("bp") || fb.contains("warn") ? .warn : .ok
    }

    private func feedbackText() -> String {
        feedbacks.map { f in
            let topic = entries.last { $0.t <= f.t }?.concept.topic ?? "未知"
            return "[\(fmtTC(f.t))] \(f.kind.label)（当时在讲：\(topic)）"
        }.joined(separator: "\n")
    }

    private func safely(_ fn: () async throws -> Void) async {
        do {
            try await fn()
        } catch {
            print("[echo.engine] 错误: \(error)")
            if status == .analyzing { status = .listening }
            reportError(error.localizedDescription)
        }
    }
}

// MARK: - 小工具

private func str(_ v: Any?) -> String {
    switch v {
    case let s as String: s.trimmingCharacters(in: .whitespacesAndNewlines)
    case let n as NSNumber: n.stringValue
    default: ""
    }
}

private func double(_ v: Any?) -> Double? {
    switch v {
    case let n as NSNumber: n.doubleValue
    case let s as String: Double(s)
    default: nil
    }
}

private func asList(_ v: Any?) -> [String] {
    if let s = v as? String { return s.isEmpty ? [] : [s] }
    return ((v as? [Any]) ?? []).map { str($0) }.filter { !$0.isEmpty }
}

/// 同名，或一个是另一个加了「引入/推导/定义」等后缀的近似名。
private func sameTopic(_ a: String, _ b: String) -> Bool {
    if a == b { return true }
    let (short, long) = a.count <= b.count ? (a, b) : (b, a)
    return short.count >= 3 && long.hasPrefix(short) && long.count - short.count <= 3
}

private func merge(_ a: [String], _ b: Any?) -> [String] {
    var out = a
    for x in asList(b) where !out.contains(x) { out.append(x) }
    return out
}
