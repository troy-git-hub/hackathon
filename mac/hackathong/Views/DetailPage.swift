//
//  DetailPage.swift
//  Echo — 知识点详情（对应 floating_window 的 DETAIL 页）
//  一节课的回顾：讲了什么 / 每个知识点的掌握度 / 复习链 / 知识地图 / 出题
//

import SwiftUI

struct DetailSkill: Identifiable, Equatable {
    var id: String { name }
    var name: String
    var mastery: Double
    var status: SkillStatus
    var note: String
}

struct DetailVM: Identifiable, Equatable {
    var id: Double
    var title: String
    var date: String
    var ok: Int
    var review: Int
    var minutes: Int
    var points: Int
    var chars: Int
    var summary: String
    var highlights: [String]
    var skills: [DetailSkill]
    var chain: [String]
    var suggestion: String
    var breakpoints: [DetailBreakpoint] = []
    var overview: DetailOverview?
}

/// 一次掉队（对应 Python 的回响时间线一行）
struct DetailBreakpoint: Identifiable, Equatable {
    var id: String { "\(tc)·\(concept)" }
    var tc: String
    var concept: String
    var outcome: String        // 已补上 / 自己看了 / 未补上（已经按当前语言本地化好的文案）
}

/// 本节课概览（对应 Python 的 `_overview_card`）
struct DetailOverview: Equatable {
    var lostCount = 0
    var quizCount = 0
    var quizRight = 0
    var okCount = 0
    var totalCount = 0
}

struct DetailPage: View {
    var detail: DetailVM
    var onMindmap: () -> Void
    var onQuiz: () -> Void
    var onHome: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(detail.title).pageTitle().wrap()
                Text(tr("\(detail.date)　✓ 跟上了 \(detail.ok) · 待复习 \(detail.review)",
                        "\(detail.date)　✓ Kept up \(detail.ok) · To review \(detail.review)"))
                    .caption().wrap()
                if !statLine.isEmpty {
                    Text(statLine).font(.system(size: 11)).foregroundStyle(Palette.textSecondary).wrap()
                }
            }

            if !detail.summary.isEmpty || !detail.highlights.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text(tr("这节课讲了什么", "What this lesson covered"))
                        .font(.system(size: 12, weight: .bold)).foregroundStyle(Palette.accent)
                    if !detail.summary.isEmpty {
                        Text(detail.summary).font(.system(size: 13)).foregroundStyle(Palette.textPrimary)
                            .lineSpacing(3).wrap()
                    }
                    ForEach(Array(detail.highlights.prefix(5).enumerated()), id: \.offset) { _, h in
                        Text("· " + h).font(.system(size: 12)).foregroundStyle(Palette.textPrimary).wrap()
                    }
                }
                .card()
            }

            if !detail.skills.isEmpty {
                VStack(spacing: 0) {
                    ForEach(detail.skills) { s in
                        SkillRow(name: s.name, mastery: s.mastery,
                                 mark: SkillMark(status: s.status, mastery: s.mastery), note: s.note)
                    }
                }
            }

            if ReviewChain.hasContent(chain: detail.chain, suggestion: detail.suggestion) {
                ReviewChain(chain: detail.chain, suggestion: detail.suggestion)
            }

            overviewCard
            breakpointCard

            HStack(spacing: Spacing.sm) {
                Button(tr("知识地图", "Knowledge map"), action: onMindmap).buttonStyle(QuietButtonStyle(expand: false))
                Button(tr("出几道题练练", "Practice a few questions"), action: onQuiz)
                    .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 32))
                Spacer()
                Button(tr("回到主页", "Back to home"), action: onHome).buttonStyle(LinkButtonStyle())
            }
        }
    }

    /// 本节课概览（对应 Python `_overview_card`）
    @ViewBuilder private var overviewCard: some View {
        if let ov = detail.overview, ov.lostCount > 0 || ov.quizCount > 0 || ov.totalCount > 0 {
            VStack(alignment: .leading, spacing: 5) {
                Text(tr("本节课概览", "Lesson at a glance"))
                    .font(.system(size: 12, weight: .bold)).foregroundStyle(Palette.accent)
                if ov.lostCount > 0 {
                    Text(tr("掉队 \(ov.lostCount) 次", "Fell behind \(ov.lostCount)×"))
                        .font(.system(size: 13)).foregroundStyle(Palette.textPrimary)
                }
                if ov.quizCount > 0 {
                    let pct = Int((Double(ov.quizRight) / Double(ov.quizCount) * 100).rounded())
                    Text(tr("抽问 \(ov.quizCount) 次 · 答对 \(ov.quizRight) 道 · 正确率 \(pct)%",
                            "Quizzed \(ov.quizCount)× · \(ov.quizRight) correct · \(pct)% accuracy"))
                        .font(.system(size: 13)).foregroundStyle(Palette.textPrimary)
                }
                if ov.totalCount > 0 {
                    HStack(spacing: Spacing.sm) {
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Palette.border)
                                Capsule().fill(Palette.okFG)
                                    .frame(width: geo.size.width * max(0.04, Double(ov.okCount) / Double(ov.totalCount)))
                            }
                        }
                        .frame(height: 8)
                        Text(tr("已跟上 \(ov.okCount) / \(ov.totalCount)", "Caught up \(ov.okCount) / \(ov.totalCount)"))
                            .font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
                    }
                }
            }
            .card()
        }
    }

    /// 这节课的掉队：时间线（对应 Python `_breakpoint_card`）
    @ViewBuilder private var breakpointCard: some View {
        if !detail.breakpoints.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                Text(tr("这节课的掉队", "Where you fell behind"))
                    .font(.system(size: 12, weight: .bold)).foregroundStyle(Palette.accent)
                ForEach(detail.breakpoints) { bp in
                    Text(tr("\(bp.tc) 掉队 · 「\(bp.concept)」 · \(bp.outcome)",
                            "Fell behind at \(bp.tc) · \"\(bp.concept)\" · \(bp.outcome)"))
                        .font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
                }
            }
            .card()
        }
    }

    private var statLine: String {
        var bits: [String] = []
        if detail.minutes > 0 { bits.append(tr("听了 \(detail.minutes) 分钟", "\(detail.minutes) min listened")) }
        if detail.points > 0 { bits.append(tr("\(detail.points) 个知识点", "\(detail.points) concepts")) }
        if detail.chars > 0 { bits.append(tr("转写 \(detail.chars) 字", "\(detail.chars) chars transcribed")) }
        return bits.joined(separator: " · ")
    }
}
