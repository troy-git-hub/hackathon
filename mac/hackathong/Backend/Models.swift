//
//  Models.swift
//  Echo 后端数据模型（对应 Python echo/mock_data.py + store/mindmap/recall/quiz 的公共类型）
//

import Foundation

nonisolated enum ConceptStatus: String, Codable, Sendable {
    case ok, warn, lost, now
}

nonisolated enum SkillStatus: String, Codable, Sendable {
    case ok        // 已跟上
    case fixed     // 掉队过但已补上
    case review    // 待回看
}

nonisolated enum FeedbackKind: String, Codable, Sendable, CaseIterable {
    case ok, warn, lost
    var label: String {
        switch self {
        case .ok: "✓ 跟上了"
        case .warn: "? 有点懵"
        case .lost: "! 我掉队了"
        }
    }
}

nonisolated enum EchoStatus: String, Sendable {
    case idle, loadingASR, listening, analyzing, summarizing, done
}

nonisolated enum SourceKind: String, Sendable, CaseIterable {
    case system   // ScreenCaptureKit 抓电脑正在播放的声音
    case mic      // 麦克风
    case demo     // 回放示例讲稿
}

/// 间隔重复三档自评（对应 store.py 的 AGAIN / FUZZY / CLEAR）
nonisolated enum Grade: String, Codable, Sendable, CaseIterable {
    case again, fuzzy, clear
    var label: String {
        switch self {
        case .again: "还是没懂"
        case .fuzzy: "有点模糊"
        case .clear: "记得很清楚"
        }
    }
}

nonisolated struct TranscriptLine: Identifiable, Hashable, Sendable {
    let id = UUID()
    var t: Double
    var text: String
    var tc: String { fmtTC(t) }
}

nonisolated struct Concept: Identifiable, Hashable, Sendable {
    var id = UUID()
    var timecode: String          // "18:39"
    var topic: String
    var concepts: [String]
    var prerequisites: [String]
    var summary: String
    var status: ConceptStatus = .ok
}

nonisolated struct BreakPoint: Identifiable, Hashable, Sendable {
    var id = UUID()
    var breakpointTC: String
    var concept: String
    var missing: String
    var reason: String
    var microLesson: String
    var note: String = ""         // 时间轴上的短备注
    var known: String = ""        // 三段式补课 ①你已经知道什么
    var step: String = ""         // ②中间漏的那一步
    var now: String = ""          // ③所以现在能听懂什么
    var fixed: Bool = false       // 学生点了「补上了」
    var selfReview: Bool = false  // 学生点了「我自己看看」，没用 AI 补
    var lostAt: Double = 0        // 点「我掉队了」那一刻的墙钟
    var resolvedAt: Double = 0    // 补上 / 自己看那一刻的墙钟；0 = 还欠着
}

nonisolated struct EchoSkill: Identifiable, Hashable, Sendable {
    var id = UUID()
    var name: String
    var mastery: Double           // 0~1
    var status: SkillStatus
}

/// 课程要点在存档里的形状（Python lessons.json 的 skills_detail）
nonisolated struct SkillDetail: Codable, Hashable, Sendable {
    var name: String
    var mastery: Double
    var status: String
}

/// 知识点前置关系图（engine._concept_graph / store 的 graph）
nonisolated struct ConceptGraph: Codable, Hashable, Sendable {
    var nodes: [String] = []
    var edges: [[String]] = []
    var times: [String: String] = [:]
}

nonisolated struct EchoReport: Hashable, Sendable {
    var skills: [EchoSkill]
    var reviewChain: [String]
    var suggestion: String = ""
    var summary: String = ""        // 这节课讲了什么
    var highlights: [String] = []   // 本节课要点
    var duration: Double = 0        // 课程时长（秒）
    var lineCount: Int = 0          // 转写句数
    var charCount: Int = 0          // 转写总字数
    var graph: ConceptGraph = ConceptGraph()
    /// 这份回响是离线/兜底规则拼的，不是真听懂这节课 —— 这种课不写进历史
    var fromMock: Bool = false
}

// MARK: - 时间码

nonisolated func fmtTC(_ t: Double) -> String {
    let t = max(0, Int(t))
    let h = t / 3600, m = (t % 3600) / 60, s = t % 60
    return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%02d:%02d", m, s)
}

nonisolated func parseTC(_ tc: String?) -> Double? {
    guard let tc = tc?.trimmingCharacters(in: .whitespaces), !tc.isEmpty else { return nil }
    var t = 0
    for part in tc.split(separator: ":", omittingEmptySubsequences: false) {
        guard let p = Int(part) else { return nil }
        t = t * 60 + p
    }
    return Double(t)
}

// MARK: - 示例数据（无 key 时的 mock，也可用于 SwiftUI Preview）

enum MockData {
    static let concepts: [Concept] = [
        Concept(timecode: "18:30", topic: "条件概率", concepts: ["条件概率", "联合概率"], prerequisites: ["概率公理"],
                summary: "老师引入条件概率概念，给出定义 P(A|B)=P(A∩B)/P(B)", status: .ok),
        Concept(timecode: "18:34", topic: "条件概率定义", concepts: ["P(A|B)", "P(A∩B)", "P(B)"], prerequisites: ["条件概率"],
                summary: "老师强调条件概率定义，要求记录", status: .ok),
        Concept(timecode: "18:37", topic: "贝叶斯公式", concepts: ["贝叶斯公式", "先验", "后验"], prerequisites: ["条件概率"],
                summary: "老师直接给出贝叶斯公式，未推导", status: .warn),
        Concept(timecode: "18:42", topic: "后验概率", concepts: ["后验概率", "信念更新"], prerequisites: ["贝叶斯公式"],
                summary: "老师解释后验概率是更新后的信念", status: .now),
    ]

    static let breakpoint = BreakPoint(
        breakpointTC: "18:39",
        concept: "贝叶斯公式",
        missing: "从条件概率定义到贝叶斯公式的变换",
        reason: "老师直接使用公式 P(A|B)=P(B|A)P(A)/P(B)，没有解释如何从条件概率定义推导得到。",
        microLesson: """
        其实贝叶斯公式就是条件概率定义的一个变形。

        第一步：由条件概率定义，P(A|B) = P(A∩B) / P(B)。
        第二步：同样，P(B|A) = P(A∩B) / P(A)，所以 P(A∩B) = P(B|A)·P(A)。
        第三步：把第二步的 P(A∩B) 代回第一步，就得到
                 P(A|B) = P(B|A)·P(A) / P(B)。

        这就是贝叶斯公式。它只是把「A 交 B」用两种方式表示了一下。
        """,
        note: "老师快速跳过了推导",
        known: "条件概率 P(A|B) = P(A∩B) / P(B)",
        step: "同理 P(B|A) = P(A∩B) / P(A)，所以 P(A∩B) = P(B|A)·P(A)\n把它代回 P(A|B) 的分子：P(A|B) = P(B|A)·P(A) / P(B)",
        now: "后验概率就是公式左边的 P(A|B)：看到结果 B 之后，对 A 更新后的信念"
    )

    static let report = EchoReport(
        skills: [
            EchoSkill(name: "极限", mastery: 1.0, status: .ok),
            EchoSkill(name: "导数定义", mastery: 0.85, status: .ok),
            EchoSkill(name: "瞬时变化率", mastery: 0.55, status: .fixed),
            EchoSkill(name: "链式法则", mastery: 0.15, status: .review),
        ],
        reviewChain: ["链式法则", "复合函数", "函数复合"],
        suggestion: "建议复习：函数复合"
    )
}
