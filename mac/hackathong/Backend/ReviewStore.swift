//
//  ReviewStore.swift
//  Echo - 错题本 / 课程历史持久化（对应 Python echo/backend/store.py）
//  存在 Application Support/Echo/review.json、lessons.json，字段名与 Python 版一致。
//
//  复习不是一次性的「掌握 / 没掌握」：学生答完一次后按真实感受（还是没懂 /
//  有点模糊 / 记得很清楚）决定下次什么时候再确认一次——见下面的「间隔重复」。
//  答得越稳，下次间隔越长；答崩了明天再来。
//

import Foundation

// ================= 间隔重复 =================
// 学生复习完一个知识点后的三档自评（Grade 本体见 Models.swift）。没有「掌握了」
// 这个终态——一次答对不代表长期记住，只是把下次确认时间推远一点。
extension Grade {
    /// 选这一档后大概几天再来确认一次（UI 提示用；clear 从阶梯第一级起算）。
    var days: Int {
        switch self {
        case .again: AGAIN_DAYS
        case .fuzzy: FUZZY_DAYS
        case .clear: CLEAR_LADDER[0]
        }
    }

    /// 从课堂抽问的自评结果（对应 Python quiz.SELF_GRADE = [right, unsure, wrong]）
    /// 映射到三档复习自评；未知结果返回 nil。
    init?(selfReport result: String) {
        switch result {
        case "right": self = .clear
        case "unsure": self = .fuzzy
        case "wrong": self = .again
        default: return nil
        }
    }
}

private let DAY: Double = 86400.0
private let AGAIN_DAYS = 1          // 答崩了：换种讲法，明天再确认
private let FUZZY_DAYS = 3          // 有印象但不稳：留几天再问
// 连续答「清楚」时的间隔阶梯（天）。连对越多，推得越远，最后进长期记忆检查。
private let CLEAR_LADDER: [Int] = [7, 14, 30, 60, 120]

nonisolated struct ReviewItem: Codable, Identifiable, Hashable, Sendable {
    var topic: String
    var timecode: String = ""
    var missing: String = ""
    var reason: String = ""
    var microLesson: String = ""
    var known: String = ""
    var step: String = ""
    var now: String = ""
    var status: String = "review"      // fixed / review
    var reviewed: Bool = false         // 这一轮是否暂时过了（到期后会被 dueItems 重新捞出）
    var time: Double = Date().timeIntervalSince1970
    var reviewedAt: Double?

    // ===== 间隔重复进度（对应 Python 的 level / due / last_result）=====
    var level: Int = 0                 // 连对档位
    var nextDue: Double = 0            // 下次该复习的时间戳；0 表示还没排过进度
    var lastGrade: String = ""         // 上次自评结果 again / fuzzy / clear
    var reviewCount: Int = 0            // 复习过几次（Python review_count；due_reason 要用）
    var reviewChain: [String] = []     // 复习链（hint 文案要用）
    var whyMatters: String = ""        // 「为什么要复习它」的一句话（Python why_matters，setWhy 写入）

    var id: String { topic }

    /// 现在是否到期该复习（照 Python due_items 的 due <= now 判断，含旧数据推导）。
    var isDue: Bool {
        var it = self
        let now = Date().timeIntervalSince1970
        ReviewStore.schedule(&it, now: now)
        return it.nextDue <= now
    }

    /// 距离下次复习还有几天（UI 的「N 天后再确认一次」用）。
    var daysLeft: Int {
        var it = self
        let now = Date().timeIntervalSince1970
        ReviewStore.schedule(&it, now: now)
        return max(0, Int(ceil((it.nextDue - now) / DAY)))
    }

    enum CodingKeys: String, CodingKey {
        case topic, timecode, missing, reason, known, step, now, status, reviewed, time, level
        case microLesson = "micro_lesson"
        case reviewedAt = "reviewed_at"
        // Python store.py 实际写的是 "due" / "last_result"；这里同时接受新版别名键。
        case nextDue = "due"
        case nextDueAlias = "next_due"
        case lastGrade = "last_result"
        case lastGradeAlias = "last_grade"
        case reviewCount = "review_count"
        case reviewChain = "review_chain"
        case whyMatters = "why_matters"
    }

    init(topic: String, timecode: String = "", missing: String = "", reason: String = "", microLesson: String = "",
         known: String = "", step: String = "", now: String = "", status: String = "review") {
        self.topic = topic; self.timecode = timecode; self.missing = missing; self.reason = reason
        self.microLesson = microLesson; self.known = known; self.step = step; self.now = now; self.status = status
    }

    // 宽松解码：缺字段用默认值（兼容 1.x 只有 reviewed 的老文件）
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func s(_ k: CodingKeys) -> String { (try? c.decode(String.self, forKey: k)) ?? "" }
        topic = s(.topic); timecode = s(.timecode); missing = s(.missing); reason = s(.reason)
        microLesson = s(.microLesson); known = s(.known); step = s(.step); now = s(.now)
        status = (try? c.decode(String.self, forKey: .status)) ?? "review"
        reviewed = (try? c.decode(Bool.self, forKey: .reviewed)) ?? false
        time = (try? c.decode(Double.self, forKey: .time)) ?? 0
        reviewedAt = try? c.decode(Double.self, forKey: .reviewedAt)
        level = (try? c.decode(Int.self, forKey: .level)) ?? 0
        if let v = try? c.decode(Double.self, forKey: .nextDue) {
            nextDue = v
        } else if let v = try? c.decode(Double.self, forKey: .nextDueAlias) {
            nextDue = v
        } else {
            nextDue = 0
        }
        if let v = try? c.decode(String.self, forKey: .lastGrade) {
            lastGrade = v
        } else if let v = try? c.decode(String.self, forKey: .lastGradeAlias) {
            lastGrade = v
        } else {
            lastGrade = ""
        }
        reviewCount = (try? c.decode(Int.self, forKey: .reviewCount)) ?? 0
        reviewChain = (try? c.decode([String].self, forKey: .reviewChain)) ?? []
        whyMatters = (try? c.decode(String.self, forKey: .whyMatters)) ?? ""
    }

    // 同时写 Python 规范键与新版别名键，保证新旧数据双向兼容。
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(topic, forKey: .topic)
        try c.encode(timecode, forKey: .timecode)
        try c.encode(missing, forKey: .missing)
        try c.encode(reason, forKey: .reason)
        try c.encode(microLesson, forKey: .microLesson)
        try c.encode(known, forKey: .known)
        try c.encode(step, forKey: .step)
        try c.encode(now, forKey: .now)
        try c.encode(status, forKey: .status)
        try c.encode(reviewed, forKey: .reviewed)
        try c.encode(time, forKey: .time)
        try c.encodeIfPresent(reviewedAt, forKey: .reviewedAt)
        try c.encode(level, forKey: .level)
        try c.encode(nextDue, forKey: .nextDue)          // "due"（Python 规范键）
        try c.encode(nextDue, forKey: .nextDueAlias)     // "next_due"（新版别名）
        try c.encode(lastGrade, forKey: .lastGrade)      // "last_result"（Python 规范键）
        try c.encode(lastGrade, forKey: .lastGradeAlias) // "last_grade"（新版别名）
        try c.encode(reviewCount, forKey: .reviewCount)
        try c.encode(reviewChain, forKey: .reviewChain)
        try c.encode(whyMatters, forKey: .whyMatters)
    }
}

/// 课程归档里的单个知识点（对应 Python store._skill_fields 的三字段）。
nonisolated struct LessonSkill: Codable, Hashable, Sendable {
    var name: String
    var mastery: Double
    var status: SkillStatus

    init(name: String, mastery: Double, status: SkillStatus) {
        self.name = name; self.mastery = mastery; self.status = status
    }

    enum CodingKeys: String, CodingKey { case name, mastery, status }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        mastery = (try? c.decode(Double.self, forKey: .mastery)) ?? 0
        let raw = (try? c.decode(String.self, forKey: .status)) ?? "ok"
        status = SkillStatus(rawValue: raw) ?? .ok
    }
}

/// 一节课的掉队时间线（对应 Python store.save_lesson 的 breakpoints 行）。
nonisolated struct LessonBreakpoint: Codable, Hashable, Sendable {
    var tc: String = ""            // 掉队时间码
    var concept: String = ""
    var lostAt: Double = 0         // 掉队起点墙钟（引擎没记到就是 0）
    var resolvedAt: Double = 0     // 补上/自己看那一刻的墙钟；0 = 没恢复
    var duration: Double = 0       // 真实耗时（秒）
    var outcome: String = ""       // fixed 补上了 / self 自己看了 / open 还欠着

    enum CodingKeys: String, CodingKey {
        case tc, concept, duration, outcome
        case lostAt = "lost_at"
        case resolvedAt = "resolved_at"
    }

    init(tc: String = "", concept: String = "", lostAt: Double = 0, resolvedAt: Double = 0,
         duration: Double = 0, outcome: String = "") {
        self.tc = tc; self.concept = concept; self.lostAt = lostAt
        self.resolvedAt = resolvedAt; self.duration = duration; self.outcome = outcome
    }

    /// 从引擎的断点转一行。引擎的 BreakPoint 没存 lost_at/resolved_at/duration，
    /// 时间字段留 0；结果按 fixed / selfReview 推成 fixed / self / open。
    init(_ bp: BreakPoint, end: Double = Date().timeIntervalSince1970) {
        // 未补上的断点算到「当下」（下课时刻），与 Python engine._breakpoint_rows 一致
        let duration = bp.lostAt > 0 ? max(0, (bp.resolvedAt > 0 ? bp.resolvedAt : end) - bp.lostAt) : 0
        self.init(tc: bp.breakpointTC, concept: bp.concept, lostAt: bp.lostAt, resolvedAt: bp.resolvedAt,
                  duration: duration, outcome: bp.fixed ? "fixed" : (bp.selfReview ? "self" : "open"))
    }

    /// 把整节课的断点转成回响记录行。
    static func rows(_ bps: [BreakPoint]) -> [LessonBreakpoint] {
        let end = Date().timeIntervalSince1970
        return bps.map { LessonBreakpoint($0, end: end) }
    }
}

/// 课中抽问汇总（对应 Python store.save_lesson 的 quiz = {total, correct}）。
nonisolated struct LessonQuiz: Codable, Hashable, Sendable {
    var total: Int = 0
    var correct: Int = 0

    init(total: Int = 0, correct: Int = 0) { self.total = total; self.correct = correct }

    // 宽松解码：缺字段当 0，兼容没有 quiz 的老记录。
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        correct = (try? c.decode(Int.self, forKey: .correct)) ?? 0
    }
}

/// 最近 N 天学过的知识点（对应 Python store.weekly_skills 的返回项）。
nonisolated struct WeeklySkill: Codable, Hashable, Sendable {
    var name: String
    var mastery: Double
    var status: String             // review / fixed / ok（跨课取最差）
}

nonisolated struct LessonRecord: Codable, Identifiable, Hashable, Sendable {
    var time: Double
    var title: String
    var date: String
    var total: Int
    var ok: Int
    var review: Int
    var reviewChain: [String]
    var suggestion: String

    // ===== 回响摘要（对应 Python 的 summary / highlights / duration / char_count）=====
    var summary: String = ""           // 「这节课讲了什么」
    var points: [String] = []          // 本节课要点（Python high_light 的对外名）
    var minutes: Int = 0               // 时长（分钟，由 Python 的 duration 秒换算）
    var chars: Int = 0                 // 转写总字数（Python char_count）
    var skills: [LessonSkill] = []     // 各知识点掌握度（Python skills_detail）
    var graph: ConceptGraph = ConceptGraph()   // 课上抓到的真前置图（Python 的 graph）
    var breakpoints: [LessonBreakpoint] = []   // 掉队时间线（回放历史课详情用）
    var quiz: LessonQuiz = LessonQuiz()        // 课中抽问汇总

    var id: Double { time }

    enum CodingKeys: String, CodingKey {
        case time, title, date, total, ok, review, suggestion, summary
        case reviewChain = "review_chain"
        // Python 规范键 + 新版别名键，解码时都接受。
        case highlights = "highlights"
        case pointsAlias = "points"
        case duration = "duration"
        case minutesAlias = "minutes"
        case charCount = "char_count"
        case charsAlias = "chars"
        case skillsDetail = "skills_detail"
        case skillsAlias = "skills"
        case graph = "graph"
        case breakpoints = "breakpoints"
        case quiz = "quiz"
    }

    init(time: Double, title: String, date: String, total: Int, ok: Int, review: Int,
         reviewChain: [String], suggestion: String, summary: String = "",
         points: [String] = [], minutes: Int = 0, chars: Int = 0, skills: [LessonSkill] = [],
         graph: ConceptGraph = ConceptGraph(), breakpoints: [LessonBreakpoint] = [],
         quiz: LessonQuiz = LessonQuiz()) {
        self.time = time; self.title = title; self.date = date; self.total = total; self.ok = ok
        self.review = review; self.reviewChain = reviewChain; self.suggestion = suggestion
        self.summary = summary; self.points = points; self.minutes = minutes; self.chars = chars
        self.skills = skills; self.graph = graph; self.breakpoints = breakpoints; self.quiz = quiz
    }

    // 宽松解码：缺字段用默认值（兼容没有 summary/highlights/duration 的老课程归档）
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        time = (try? c.decode(Double.self, forKey: .time)) ?? 0
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        date = (try? c.decode(String.self, forKey: .date)) ?? ""
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        ok = (try? c.decode(Int.self, forKey: .ok)) ?? 0
        review = (try? c.decode(Int.self, forKey: .review)) ?? 0
        reviewChain = (try? c.decode([String].self, forKey: .reviewChain)) ?? []
        suggestion = (try? c.decode(String.self, forKey: .suggestion)) ?? ""
        summary = (try? c.decode(String.self, forKey: .summary)) ?? ""
        if let v = try? c.decode([String].self, forKey: .highlights) {
            points = v
        } else if let v = try? c.decode([String].self, forKey: .pointsAlias) {
            points = v
        } else {
            points = []
        }
        // Python 存的是秒（duration）；新版 Swift 也写 minutes，解码优先按秒换算。
        if let d = try? c.decode(Double.self, forKey: .duration) {
            minutes = Int(d / 60)
        } else if let m = try? c.decode(Int.self, forKey: .minutesAlias) {
            minutes = m
        } else {
            minutes = 0
        }
        if let v = try? c.decode(Int.self, forKey: .charCount) {
            chars = v
        } else if let v = try? c.decode(Int.self, forKey: .charsAlias) {
            chars = v
        } else {
            chars = 0
        }
        if let v = try? c.decode([LessonSkill].self, forKey: .skillsDetail) {
            skills = v
        } else if let v = try? c.decode([LessonSkill].self, forKey: .skillsAlias) {
            skills = v
        } else {
            skills = []
        }
        graph = (try? c.decode(ConceptGraph.self, forKey: .graph)) ?? ConceptGraph()
        breakpoints = (try? c.decode([LessonBreakpoint].self, forKey: .breakpoints)) ?? []
        quiz = (try? c.decode(LessonQuiz.self, forKey: .quiz)) ?? LessonQuiz()
    }

    // 同时写 Python 规范键（duration 秒 / highlights / char_count）与新版别名键。
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(time, forKey: .time)
        try c.encode(title, forKey: .title)
        try c.encode(date, forKey: .date)
        try c.encode(total, forKey: .total)
        try c.encode(ok, forKey: .ok)
        try c.encode(review, forKey: .review)
        try c.encode(reviewChain, forKey: .reviewChain)
        try c.encode(suggestion, forKey: .suggestion)
        try c.encode(summary, forKey: .summary)
        try c.encode(points, forKey: .highlights)
        try c.encode(points, forKey: .pointsAlias)
        try c.encode(Double(minutes) * 60, forKey: .duration)   // Python 的 duration 是秒
        try c.encode(minutes, forKey: .minutesAlias)
        try c.encode(chars, forKey: .charCount)
        try c.encode(chars, forKey: .charsAlias)
        try c.encode(skills, forKey: .skillsDetail)
        try c.encode(skills, forKey: .skillsAlias)
        try c.encode(graph, forKey: .graph)
        try c.encode(breakpoints, forKey: .breakpoints)
        try c.encode(quiz, forKey: .quiz)
    }
}

enum ReviewStore {
    // 可重入锁（对应 Python store._LOCK = RLock）：add()/grade() 整段持锁时内部还要调 load()。
    // 引擎现在找到断点就立刻写盘，并发调用变多，读-改-写必须是一个原子操作。
    nonisolated(unsafe) private static let lock = NSRecursiveLock()

    private static var dir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let d = base.appendingPathComponent("Echo", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }
    private static var reviewURL: URL { dir.appendingPathComponent("review.json") }
    private static var lessonsURL: URL { dir.appendingPathComponent("lessons.json") }

    private static func read<T: Decodable>(_ url: URL) -> [T] {
        lock.lock(); defer { lock.unlock() }
        guard let data = try? Data(contentsOf: url) else { return [] }
        return (try? JSONDecoder().decode([T].self, from: data)) ?? []
    }

    /// 原子写一个 JSON 数组文件，返回写没写成功。
    ///
    /// **失败必须让调用方知道**：磁盘满、目录不可写时静默吞错，意味着「复习打分显示
    /// 成功、重开却回到原样」——用户以为记录了，其实什么都没发生，比崩溃更糟。
    @discardableResult
    private static func write<T: Encodable>(_ items: [T], to url: URL) -> Bool {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        guard let data = try? enc.encode(items) else {
            NSLog("[Echo] 数据写入失败 %@: 编码失败", url.path)
            return false
        }
        do {
            try data.write(to: url, options: .atomic)
            return true
        } catch {
            NSLog("[Echo] 数据写入失败 %@: %@", url.path, String(describing: error))
            return false
        }
    }

    // ================= 间隔重复 =================

    /// 照 Python store._schedule：补齐一条记录的复习进度字段（只改内存，不落盘）。
    ///
    /// 老数据（1.x 只有 reviewed 布尔值）没有 level/due，这里就地推导：
    /// 标过「掌握」的当成已经连对一次，其余的算作现在就该复习。
    /// 用 nextDue > 0 判断「已有进度」，等价于 Python 的 "due" in it。
    fileprivate static func schedule(_ it: inout ReviewItem, now: Double) {
        if it.nextDue > 0 { return }
        if it.reviewed {
            if it.level == 0 { it.level = 1 }
            let base = it.reviewedAt ?? (it.time > 0 ? it.time : now)
            it.nextDue = base + Double(CLEAR_LADDER[0]) * DAY
        } else {
            it.nextDue = it.time > 0 ? it.time : now
        }
    }

    /// 照 Python store.next_due：按这次的表现算 (新的 level, 下次复习时间戳)。
    ///
    /// 还是没懂 → level 清零、明天再来；有点模糊 → level 不动、3 天后；
    /// 记得很清楚 → level +1，按阶梯推远。
    static func nextDue(level: Int, result: Grade, now: Double) -> (level: Int, due: Double) {
        switch result {
        case .again:
            return (0, now + Double(AGAIN_DAYS) * DAY)
        case .fuzzy:
            return (max(0, level), now + Double(FUZZY_DAYS) * DAY)
        case .clear:
            let lv = max(0, level) + 1
            let days = CLEAR_LADDER[min(lv - 1, CLEAR_LADDER.count - 1)]
            return (lv, now + Double(days) * DAY)
        }
    }

    /// 复习排序优先级：没懂过的 > 模糊的 > 清楚的（未知按 again 处理）。
    private static func gradeRank(_ result: String) -> Int {
        switch result {
        case Grade.fuzzy.rawValue: return 1
        case Grade.clear.rawValue: return 2
        default: return 0
        }
    }

    // ================= 错题本 =================

    /// 所有错题记录。文件不存在或损坏时返回 []。
    static func load() -> [ReviewItem] { read(reviewURL) }

    /// 追加/合并一批错题：同一 topic 覆盖更新内容，但保留复习进度（不复活老错题）。
    ///
    /// relapse=true 表示「学生在新一节课上又在同一个知识点掉队了」，是「其实没掌握」
    /// 的强信号：把 level 清零、立刻到期重来，不沿用之前攒下来的长间隔。
    /// 默认 false：其它调用点（抽问答错、拍题）只补内容，不动已有进度。
    ///
    /// 返回写没写成功 —— 磁盘满/目录不可写时返回 false，调用方不该当成已保存。
    @discardableResult
    static func add(_ items: [ReviewItem], relapse: Bool = false) -> Bool {
        guard !items.isEmpty else { return true }   // 没东西可写，视为成功
        lock.lock(); defer { lock.unlock() }        // 读-改-写整段持锁
        var cur = load()
        let now = Date().timeIntervalSince1970
        for var it in items {
            it.topic = it.topic.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !it.topic.isEmpty else { continue }
            if it.time == 0 { it.time = now }               // Python 的 setdefault("time", now)
            if let i = cur.firstIndex(where: { $0.topic == it.topic }) {
                let prev = cur[i]
                it.reviewed = prev.reviewed
                if let ra = prev.reviewedAt { it.reviewedAt = ra }
                if prev.time != 0 { it.time = prev.time }
                // 复习进度跟着走，否则同一个知识点再次被记进来就把阶梯清零了
                it.level = prev.level
                it.nextDue = prev.nextDue
                if !prev.lastGrade.isEmpty { it.lastGrade = prev.lastGrade }
                it.reviewCount = prev.reviewCount
                if !prev.reviewChain.isEmpty { it.reviewChain = prev.reviewChain }
                if !prev.whyMatters.isEmpty { it.whyMatters = prev.whyMatters }
                if relapse {
                    it.level = 0
                    it.nextDue = now                        // 立刻回到今天的复习清单里
                    it.lastGrade = Grade.again.rawValue
                    it.reviewed = false
                }
                cur[i] = it
            } else {
                cur.append(it)
            }
        }
        return write(cur, to: reviewURL)
    }

    /// 照 Python store.grade：记一次复习结果，顺手算出下次该什么时候再问。
    /// 返回更新后的那条记录（没找到返回 nil）。写盘失败也返回 nil ——
    /// 这次打分没存上，别把成功的样子返回给调用方。
    @discardableResult
    static func grade(topic: String, result: Grade, now: Double = Date().timeIntervalSince1970) -> ReviewItem? {
        lock.lock(); defer { lock.unlock() }
        var cur = load()
        var hit: ReviewItem?
        for i in cur.indices where cur[i].topic == topic {
            schedule(&cur[i], now: now)
            let r = nextDue(level: cur[i].level, result: result, now: now)
            cur[i].level = r.level
            cur[i].nextDue = r.due
            cur[i].lastGrade = result.rawValue
            cur[i].reviewedAt = now
            // reviewed 仍然写：主页统计和老的筛选逻辑还在看它；
            // 语义变成「这一轮暂时过了」，到期后 dueItems() 会把它重新捞出来。
            cur[i].reviewed = result != .again
            cur[i].reviewCount += 1
            hit = cur[i]
        }
        if hit != nil, !write(cur, to: reviewURL) {
            hit = nil     // 写盘失败 = 这次打分没存上
        }
        return hit
    }

    /// 把某个错题标记为已复习（掌握）。1.x 的二元接口，等价于自评「记得很清楚」。
    static func markReviewed(topic: String) {
        grade(topic: topic, result: .clear)
    }

    /// 现在该复习的知识点，最该先看的排前面。
    ///
    /// 排序：没懂过的 > 模糊的 > 清楚的；同档里到期越久的越靠前。
    /// （用 lastGrade 是否为空代替 Python 的 review_count 判断「有没有复习过」。）
    static func dueItems(now: Double = Date().timeIntervalSince1970) -> [ReviewItem] {
        var out: [ReviewItem] = []
        for var it in load() {
            schedule(&it, now: now)
            if it.nextDue <= now { out.append(it) }
        }
        out.sort { a, b in
            let ra = a.lastGrade.isEmpty ? -1 : gradeRank(a.lastGrade)
            let rb = b.lastGrade.isEmpty ? -1 : gradeRank(b.lastGrade)
            if ra != rb { return ra < rb }
            return a.nextDue < b.nextDue
        }
        return out
    }

    /// 还没到期、过几天要再确认一次的知识点，按到期时间由近到远。
    static func laterItems(now: Double = Date().timeIntervalSince1970) -> [ReviewItem] {
        var out: [ReviewItem] = []
        for var it in load() {
            schedule(&it, now: now)
            if it.nextDue > now { out.append(it) }
        }
        out.sort { $0.nextDue < $1.nextDue }
        return out
    }

    /// 一句话：为什么这个知识点现在该复习了（对应 Python store.due_reason）。
    ///
    /// 不是 AI 现编的 —— 就是把调度状态翻成人话，让学生知道「这不是随机抽的」。
    /// 复习卡片（今天该复习 / 过几天再复习）都用这个。
    static func dueReason(for item: ReviewItem, now: Double = Date().timeIntervalSince1970) -> String {
        let count = item.reviewCount
        let last = item.lastGrade
        var base: String
        if count == 0 {
            base = "第一次掉队，还没确认过"
        } else if last == Grade.again.rawValue {
            base = "上次还是没想起来，这次再试试"
        } else if last == Grade.fuzzy.rawValue {
            base = "上次印象有点模糊，再看一次"
        } else if last == Grade.clear.rawValue {
            let reviewed = item.reviewedAt ?? now
            let days = max(0, Int(((now - reviewed) / DAY).rounded()))
            base = days <= 0 ? "刚确认过，按计划抽查一下"
                             : "上次说记得清楚，\(days) 天过去了，抽查一下有没有忘"
        } else {
            base = "该复习一下了"
        }
        if count >= 2 {
            base += "（第 \(count + 1) 次见到它）"
        }
        return base
    }

    /// 批量写「为什么要复习它」：{topic: 一句话}，返回实际写到几条（对应 Python store.set_why）。
    ///
    /// 单独开一个函数、不复用 add()：add() 是按 topic **整条替换**的，拿它写一个新字段
    /// 会把 missing / micro_lesson / timecode 一起抹掉。这里只动 whyMatters，其余原样留着。
    /// 空串不写入：调用方拿不到 AI 结果时会传空，这时候宁可留着上一次写好的说明。
    @discardableResult
    static func setWhy(_ topics: [String: String]) -> Int {
        var clean: [String: String] = [:]
        for (t, v) in topics {
            let key = t.trimmingCharacters(in: .whitespacesAndNewlines)
            let val = v.trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty && !val.isEmpty { clean[key] = val }
        }
        if clean.isEmpty { return 0 }
        lock.lock(); defer { lock.unlock() }
        var cur = load()
        var n = 0
        for i in cur.indices {
            let topic = cur[i].topic.trimmingCharacters(in: .whitespacesAndNewlines)
            if let v = clean[topic], cur[i].whyMatters != v {
                cur[i].whyMatters = v
                n += 1
            }
        }
        if n > 0 { _ = write(cur, to: reviewURL) }   // Python 忽略写盘结果，返回值只数条数
        return n
    }

    /// 首页「今天该回响」卡片要的那几个数。
    ///
    /// minutes 是粗估：一个知识点看讲解 + 答一道题，按 1 分钟算，至少 1 分钟。
    /// hint 优先说最近一次掉队发生在哪节课的哪里，让学生想得起来当时的场景。
    static func dueSummary(now: Double = Date().timeIntervalSince1970)
        -> (due: Int, later: Int, total: Int, hint: String, minutes: Int) {
        let due = dueItems(now: now)
        let later = laterItems(now: now)
        var hint = ""
        if let first = due.first {
            let chain = first.reviewChain.filter { !$0.isEmpty }
            if chain.count >= 2 {
                hint = "你在「\(chain[chain.count - 1]) → \(chain[0])」这里掉过队"
            } else if !first.missing.isEmpty {
                hint = first.missing
            } else if !first.reason.isEmpty {
                hint = first.reason
            }
        }
        return (due.count, later.count, due.count + later.count, hint, max(1, due.count))
    }

    /// 把引擎里本节课的断点（掉队点）转成错题记录。engine 可为 None。
    static func fromBreakpoints(_ engine: EchoEngine?) -> [ReviewItem] {
        (engine?.breakpoints ?? []).compactMap { bp in
            let topic = bp.concept.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !topic.isEmpty else { return nil }
            return ReviewItem(topic: topic, timecode: bp.breakpointTC, missing: bp.missing, reason: bp.reason,
                              microLesson: bp.microLesson, known: bp.known, step: bp.step, now: bp.now,
                              status: bp.fixed ? "fixed" : "review")
        }
    }

    // ================= 课程历史 =================

    /// 存一节课的回响摘要，最多保留最近 50 条，返回这条记录的 time 时间戳。
    /// summary / points 从回响报告取；当前 EchoReport 还没有这两个字段，拿不到就空。
    @discardableResult
    /// 存一节课的回响。summary / points / minutes / chars / graph / breakpoints / quiz
    /// 不传就从 report 里取（当前 EchoReport 还没有后两者，场景由调用方传）。
    /// 返回这条记录的 time 时间戳；写盘失败返回 0.0（正常时间戳不会是 0），调用方不该当成已保存。
    static func saveLesson(title: String, report: EchoReport, summary: String? = nil,
                           points: [String]? = nil, minutes: Int? = nil, chars: Int? = nil,
                           graph: ConceptGraph? = nil, breakpoints: [LessonBreakpoint]? = nil,
                           quiz: LessonQuiz? = nil) -> Double {
        let now = Date()
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        let nameFmt = DateFormatter()
        nameFmt.dateFormat = "yyyy年MM月dd日 HH时mm分ss秒"
        let ok = report.skills.filter { $0.status == .ok }.count
        // Python save_lesson 会把每个知识点存成 skills_detail；详情页要用。
        let skillRecords = report.skills.map { LessonSkill(name: $0.name, mastery: $0.mastery, status: $0.status) }
        let record = LessonRecord(time: now.timeIntervalSince1970,
                                  title: title.isEmpty ? nameFmt.string(from: now) : title,
                                  date: fmt.string(from: now), total: report.skills.count, ok: ok,
                                  review: report.skills.count - ok, reviewChain: report.reviewChain,
                                  suggestion: report.suggestion,
                                  summary: summary ?? report.summary,
                                  points: points ?? report.highlights,
                                  minutes: minutes ?? Int((report.duration / 60).rounded()),
                                  chars: chars ?? report.charCount, skills: skillRecords,
                                  graph: graph ?? report.graph,
                                  breakpoints: breakpoints ?? [], quiz: quiz ?? LessonQuiz())
        var cur: [LessonRecord] = read(lessonsURL)
        cur.append(record)
        if !write(Array(cur.suffix(50)), to: lessonsURL) {
            return 0.0      // 写盘失败：返回 0 让调用方知道没存上
        }
        return now.timeIntervalSince1970
    }

    /// 照 Python store.get_lesson：按 time 时间戳取一条课程归档，找不到返回 nil。
    static func getLesson(ts: Double) -> LessonRecord? {
        read(lessonsURL).first { abs($0.time - ts) < 0.001 }
    }

    /// 最近的课，新 → 旧。limit=nil（不传）时返回全部。
    static func listLessons(limit: Int? = nil) -> [LessonRecord] {
        let cur: [LessonRecord] = read(lessonsURL)
        let sorted = cur.sorted { $0.time > $1.time }
        guard let limit else { return sorted }
        return Array(sorted.prefix(limit))
    }

    /// 照 Python store.delete_lessons：按时间戳批量删除课程归档，返回删掉的条数；
    /// 写盘失败返回 -1（调用方要能分辨「删了 0 条」和「删了但没存上」——后者重开后课程会原样回来）。
    @discardableResult
    static func deleteLessons(_ tsList: [Double]) -> Int {
        guard !tsList.isEmpty else { return 0 }
        let cur: [LessonRecord] = read(lessonsURL)
        let kept = cur.filter { it in !tsList.contains { abs(it.time - $0) < 0.001 } }
        let removed = cur.count - kept.count
        if removed > 0 && !write(kept, to: lessonsURL) { return -1 }
        return removed
    }

    /// 照 Python store.rename_lesson：重命名一节历史课。返回是否改到（含写盘成败 —— 没写上就是没改到）。
    @discardableResult
    static func renameLesson(ts: Double, newTitle: String) -> Bool {
        let trimmed = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        var cur: [LessonRecord] = read(lessonsURL)
        var changed = false
        for i in cur.indices where abs(cur[i].time - ts) < 0.001 {
            cur[i].title = trimmed
            changed = true
            break
        }
        if changed { return write(cur, to: lessonsURL) }
        return false
    }

    // ================= 公开清理接口（设置页「清除所有缓存」用）=================

    /// 清空错题本，返回删掉的条数；写盘失败返回 0（没写上 = 没清掉）。
    ///
    /// 删除逻辑留在真正管这个文件的地方，别让调用方自己去拼路径、猜文件名。
    @discardableResult
    static func clearMistakes() -> Int {
        lock.lock(); defer { lock.unlock() }
        let n = load().count
        if n > 0 && !write([ReviewItem](), to: reviewURL) { return 0 }
        return n
    }

    /// 清空课程归档，返回删掉的节数；写盘失败返回 0（同上）。
    @discardableResult
    static func clearLessons() -> Int {
        lock.lock(); defer { lock.unlock() }
        let cur: [LessonRecord] = read(lessonsURL)
        if !cur.isEmpty && !write([LessonRecord](), to: lessonsURL) { return 0 }
        return cur.count
    }

    /// 清空错题本 + 课程归档，返回各删了多少。
    ///
    /// 只清 Echo 自己存的这两份学习数据；凭据、设置、头像这些不算「缓存」，不动。
    static func clearAll() -> (mistakes: Int, lessons: Int) {
        (mistakes: clearMistakes(), lessons: clearLessons())
    }

    // ================= 一周学习回响 =================

    // 状态越差越该被看到：review 待回看 < fixed 掉队过但补上了 < ok 已跟上。
    private static func statusRank(_ s: String) -> Int {
        switch s {
        case SkillStatus.review.rawValue: return 0
        case SkillStatus.fixed.rawValue: return 1
        default: return 2
        }
    }

    /// 最近 N 天学过的知识点，跨课去重合并（对应 Python store.weekly_skills）。
    /// 返回 [{name, mastery, status}]，最近在前。
    ///
    /// 同名知识点（模糊匹配）取最近一次掌握度；状态取最差 —— 这一周在哪节课掉过队，
    /// 比「最近一次看起来还行」更该让学生看到。
    static func weeklySkills(days: Int = 7, now: Double = Date().timeIntervalSince1970) -> [WeeklySkill] {
        let cutoff = now - Double(days) * DAY
        // 归一化名 -> (name, mastery, status, time)
        var byName: [String: (name: String, mastery: Double, status: String, time: Double)] = [:]
        for ls in listLessons() {
            if ls.time < cutoff { continue }
            for sk in ls.skills {
                let name = sk.name.trimmingCharacters(in: .whitespacesAndNewlines)
                if name.isEmpty || Mindmap.isPlaceholderTopic(name) { continue }
                let key = Mindmap.normKey(name)
                let st = sk.status.rawValue
                if var rec = byName[key] {
                    if ls.time > rec.time {                 // 更新为最近一次
                        rec.name = name
                        rec.mastery = sk.mastery
                        rec.time = ls.time
                    }
                    if statusRank(st) < statusRank(rec.status) {   // 保留最差状态
                        rec.status = st
                    }
                    byName[key] = rec
                } else {
                    byName[key] = (name, sk.mastery, st, ls.time)
                }
            }
        }
        return byName.values
            .sorted { $0.time > $1.time }
            .map { WeeklySkill(name: $0.name, mastery: $0.mastery, status: $0.status) }
    }

    /// 课程 + 错题复习情况汇总。
    static func stats(now: Double = Date().timeIntervalSince1970)
        -> (lessons: Int, pending: Int, mastered: Int, due: Int) {
        let lessons: [LessonRecord] = read(lessonsURL)
        let reviews = load()
        let mastered = reviews.filter(\.reviewed).count
        return (lessons.count, reviews.count - mastered, mastered, dueItems(now: now).count)
    }
}
