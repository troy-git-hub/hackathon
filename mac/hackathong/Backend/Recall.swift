//
//  Recall.swift
//  Echo - 掌握验证：「讲给 Echo 听」（对应 Python echo/backend/recall.py）
//
//  不是考试，是一段小对话：学生用自己的话讲知识点（recall），再换一个没见过的
//  场景用一次（transfer）；AI 判断 清楚 / 模糊 / 没理解，给出仍没说到的关键点和
//  同桌式反馈。离线 / 没 key 时不假装能判：照样给出两道题，判断权交回学生。
//

import Foundation

nonisolated enum RecallKind: String, Codable, Sendable, CaseIterable {
    case recall = "recall"      // 讲给 Echo 听（Python 的值是 "recall"）
    case transfer = "transfer"  // 换个场景试试

    /// 宽松归一：模型可能写成 talk / 讲给 Echo 听 等。
    init(raw: String) {
        switch raw.lowercased() {
        case "transfer", "换个场景试试": self = .transfer
        default: self = .recall
        }
    }

    var label: String { self == .transfer ? "换个场景试试" : "讲给 Echo 听" }
}

nonisolated struct RecallQuestion: Identifiable, Codable, Hashable, Sendable {
    var id = UUID()
    var topic: String
    var question: String
    var kind: RecallKind
}

/// 一轮掌握验证的题目：开场白 + 两道问题（recall / transfer）。
nonisolated struct RecallPlan: Codable, Hashable, Sendable {
    var opening: String
    var questions: [RecallQuestion]
    var root: String           // 共同根源概念，没有就空串
    var offline: Bool          // true 表示没走 AI（兜底 / 离线）
}

nonisolated struct RecallAnswer: Identifiable, Codable, Hashable, Sendable {
    var id = UUID()
    var question: String
    var answer: String
}

nonisolated enum RecallVerdict: String, Codable, Sendable, CaseIterable {
    case clear, fuzzy, unclear

    var label: String { Recall.verdictLabel[self] ?? rawValue }
}

nonisolated struct RecallItemResult: Identifiable, Codable, Hashable, Sendable {
    var topic: String
    var verdict: RecallVerdict
    var missing: String        // 这次仍然没说到的关键点
    var feedback: String       // 对他说的一句话

    var id: String { topic }
}

nonisolated struct RecallResult: Codable, Hashable, Sendable {
    var results: [RecallItemResult]
    var review: String         // 一句话复习建议
    var offline: Bool          // true 表示没判（没 key / 调用失败），界面应退回自选
}

enum Recall {
    /// AI 判断 → 复习调度三档（对应 Python VERDICT_TO_GRADE）。
    static let verdictToGrade: [RecallVerdict: Grade] = [.clear: .clear, .fuzzy: .fuzzy, .unclear: .again]
    /// 界面上的档位标签。
    static let verdictLabel: [RecallVerdict: String] = [.clear: "清楚", .fuzzy: "模糊", .unclear: "没理解"]
    /// 界面上可以手动改成的档位。
    static let manualChoices: [(verdict: RecallVerdict, label: String)] = [
        (.clear, "清楚"), (.fuzzy, "模糊"), (.unclear, "没理解"),
    ]

    // MARK: - 挑知识点

    /// 挑这一轮聊哪几个，外加它们的共同根源概念（没有就是空串）。
    /// 优先挑共享同一个根源的：一次问在根源上比挨个问省时间。
    static func pick(_ items: [ReviewItem], n: Int = 3) -> (items: [ReviewItem], root: String) {
        let items = Array(items)
        if items.count <= 1 { return (Array(items.prefix(n)), "") }

        let chains: [(item: ReviewItem, chain: [String])] = items.map { ($0, roots($0)) }
        var counts: [String: Int] = [:]
        for entry in chains {
            for c in Set(entry.chain) { counts[c, default: 0] += 1 }
        }
        let shared = counts.filter { $0.value >= 2 }.map(\.key)
        if !shared.isEmpty {
            // 链尾最靠后的那个最接近根源；并列时取被共享次数最多的
            func rank(_ c: String) -> (Int, Int) {
                let deepest = chains.compactMap { $0.chain.firstIndex(of: c) }.max() ?? -1
                return (deepest, counts[c] ?? 0)
            }
            let root = shared.max { a, b in
                let ra = rank(a), rb = rank(b)
                return ra.0 != rb.0 ? ra.0 < rb.0 : ra.1 < rb.1
            }!
            let group = chains.filter { $0.chain.contains(root) }.map(\.item)
            if group.count >= 2 { return (Array(group.prefix(n)), root) }
        }
        return (Array(items.prefix(n)), "")
    }

    // MARK: - 出题

    /// 出这一轮的两道题。永远返回可用结果（最差走兜底）。
    static func plan(items: [ReviewItem], root: String = "") async -> RecallPlan {
        let its = items.filter { !$0.topic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        guard !its.isEmpty else { return RecallPlan(opening: "", questions: [], root: "", offline: true) }
        var root = root
        if root.isEmpty { root = pick(its).root }

        let key = EchoConfig.deepseekAPIKey
        guard !EchoConfig.offline && !key.isEmpty else { return fallbackPlan(its, root: root) }

        let described = its.map { it -> String in
            var line = "- \(it.topic)：\(it.missing.isEmpty ? "（没说清当时卡在哪）" : it.missing)"
            if !it.known.isEmpty { line += "；已掌握的前置：\(it.known)" }
            return line
        }.joined(separator: "\n")

        do {
            let llm = try LLM(apiKey: key)
            let data = try await llm.json(
                system: Prompts.system(Prompts.recallPlanSystem),
                user: Prompts.recallPlanUser(items: described,
                                             root: root.isEmpty ? "（没有共同的，各自问）" : root),
                temperature: 0.7, maxTokens: 700)
            var questions: [RecallQuestion] = []
            for case let q as JSONDict in (data["questions"] as? [Any]) ?? [] {
                var text = str(q["question"])
                guard !text.isEmpty else { continue }
                // 界面会给每道题加标签，模型自己带了前缀就剥掉，免得显示两遍
                text = stripPrefix(text)
                let topic = str(q["topic"]).isEmpty ? (root.isEmpty ? its[0].topic : root) : str(q["topic"])
                let kindRaw = str(q["kind"]).isEmpty ? "recall" : str(q["kind"])
                questions.append(RecallQuestion(topic: topic, question: text, kind: RecallKind(raw: kindRaw)))
            }
            if questions.isEmpty { return fallbackPlan(its, root: root) }
            return RecallPlan(opening: str(data["opening"]), questions: Array(questions.prefix(2)),
                              root: root, offline: false)
        } catch {
            print("[echo.recall] 掌握验证出题失败，改用兜底题: \(error.localizedDescription)")
            return fallbackPlan(its, root: root)
        }
    }

    /// 没 key / 调用失败时的兜底：用错题自己存的字段拼两道题，判断权交回学生。
    private static func fallbackPlan(_ items: [ReviewItem], root: String) -> RecallPlan {
        guard let first = items.first else {
            return RecallPlan(opening: "", questions: [], root: root, offline: true)
        }
        let topic = !root.isEmpty ? root : (first.topic.isEmpty ? "这个知识点" : first.topic)
        let missing = first.missing.isEmpty ? "「\(topic)」是怎么来的、什么时候用？" : first.missing
        let known = first.known
        let opening = "昨天你在「\(topic)」这里掉过队。先不做题，你讲给我听听。"
        var questions = [RecallQuestion(
            topic: topic,
            question: missing + (known.isEmpty ? "" : "（你已经知道：\(known)）"),
            kind: .recall)]
        // 界面上会加「换个场景试试」标签，题干里不要再重复
        questions.append(RecallQuestion(
            topic: topic,
            question: "如果这道题换成一个完全不同的情境（比如换成生活里的例子），你会怎么把刚才那套想法用上去？",
            kind: .transfer))
        return RecallPlan(opening: opening, questions: questions, root: root, offline: true)
    }

    // MARK: - 判断

    /// 根据学生的两次回答判断掌握程度。offline=true 表示没判，界面应退回让学生自己选。
    static func judge(items: [ReviewItem], answers: [RecallAnswer]) async -> RecallResult {
        let its = items.filter { !$0.topic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        if its.isEmpty || answers.isEmpty { return RecallResult(results: [], review: "", offline: true) }

        let key = EchoConfig.deepseekAPIKey
        guard !EchoConfig.offline && !key.isEmpty else {
            return RecallResult(results: [], review: "", offline: true)
        }

        let described = its.map { "- \($0.topic)（当初缺的是：\($0.missing.isEmpty ? "未知" : $0.missing)）" }
            .joined(separator: "\n")
        do {
            let llm = try LLM(apiKey: key)
            let data = try await llm.json(
                system: Prompts.system(Prompts.recallJudgeSystem),
                user: Prompts.recallJudgeUser(items: described, dialogue: dialogueText(answers)),
                temperature: 0.3, maxTokens: 900)

            let known = Set(its.map(\.topic))
            var results: [RecallItemResult] = []
            for case let r as JSONDict in (data["results"] as? [Any]) ?? [] {
                var topic = str(r["topic"])
                guard let verdict = RecallVerdict(rawValue: str(r["verdict"]).lowercased()) else { continue }
                // 模型偶尔会把知识点名写飘；对不上就按顺序落到没判过的那个
                if !known.contains(topic) {
                    let judged = Set(results.map(\.topic))
                    guard let rest = its.map(\.topic).first(where: { !judged.contains($0) }) else { continue }
                    topic = rest
                }
                results.append(RecallItemResult(topic: topic, verdict: verdict,
                                                missing: str(r["missing"]), feedback: str(r["feedback"])))
            }
            if results.isEmpty { return RecallResult(results: [], review: "", offline: true) }
            return RecallResult(results: results, review: str(data["review"]), offline: false)
        } catch {
            print("[echo.recall] 掌握验证判断失败: \(error.localizedDescription)")
            return RecallResult(results: [], review: "", offline: true)
        }
    }

    // MARK: - 写进复习调度

    /// 把判断写进复习调度，返回 {topic: 下次复习时间戳}。对应 Python recall.apply_results()。
    /// 手动改过的判断也走这里 —— 调度只认最终结论，不区分 AI 判的还是人判的。
    @discardableResult
    static func applyResults(_ result: RecallResult, now: Double = Date().timeIntervalSince1970) -> [String: Double] {
        var out: [String: Double] = [:]
        for r in result.results {
            guard let grade = verdictToGrade[r.verdict] else { continue }
            if let rec = ReviewStore.grade(topic: r.topic, result: grade, now: now) {
                out[r.topic] = rec.nextDue
            }
        }
        return out
    }

    // MARK: - 工具

    private static func dialogueText(_ answers: [RecallAnswer]) -> String {
        answers.map { "老师问：\($0.question)\n学生答：\($0.answer)" }.joined(separator: "\n")
    }

    /// 这个知识点所属的复习链（掉队点 → … → 根源概念）。对应 Python recall._roots()。
    private static func roots(_ item: ReviewItem) -> [String] {
        item.reviewChain.filter { !$0.isEmpty }
    }

    /// 剥掉模型自己写在题干前面的「讲给 Echo 听 / 换个场景试试 / 讲一遍：」前缀。
    private static func stripPrefix(_ text: String) -> String {
        let pattern = "^(讲给\\s*Echo\\s*听|换个场景试试|讲一遍)\\s*[：:]\\s*"
        guard let re = try? NSRegularExpression(pattern: pattern) else { return text }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        return re.stringByReplacingMatches(in: text, range: range, withTemplate: "")
    }

    private static func str(_ v: Any?) -> String {
        (v as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
