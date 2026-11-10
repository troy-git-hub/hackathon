//
//  WeeklyPage.swift
//  Echo — 一周学习回响（对应 Python 的 WEEKLY 页）
//  最近 7 天学过的知识点，两列网格；跨课同名合并，状态取最差。
//

import SwiftUI

struct WeeklyPage: View {
    var skills: [WeeklySkill]

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("一周学习回响", "Weekly review")).pageTitle()
                Text(subtitle).caption().wrap()
            }
            if skills.isEmpty {
                Text(tr("最近 7 天还没有学习记录。开始听一节课，这里就会长出来。",
                        "Nothing in the last 7 days. Start a lesson and it'll grow here."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            } else {
                LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading),
                                    GridItem(.flexible(), alignment: .leading)],
                          alignment: .leading, spacing: Spacing.sm) {
                    ForEach(Array(skills.enumerated()), id: \.offset) { _, s in
                        SkillTile(name: s.name, mastery: s.mastery,
                                  mark: SkillMark(status: SkillStatus(rawValue: s.status) ?? .review, mastery: s.mastery))
                    }
                }
            }
        }
    }

    private var subtitle: String {
        skills.isEmpty
            ? tr("最近 7 天还没有学习记录", "No lessons in the last 7 days")
            : tr("最近 7 天学了 \(skills.count) 个知识点", "\(skills.count) concepts in the last 7 days")
    }
}

/// 一格：知识点名 + 短掌握度条 + 三态图标
struct SkillTile: View {
    var name: String
    var mastery: Double
    var mark: SkillMark

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(name)
                .font(.system(size: 12, weight: mark == .lost ? .semibold : .regular))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)
                .wrap()
                .help(name)
            HStack(spacing: 6) {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Palette.border)
                        Capsule().fill(mark.barColor)
                            .frame(width: geo.size.width * max(0.06, min(1, mastery)))   // 再低也露一点
                    }
                }
                .frame(height: 8)
                MarkDot(mark: mark)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surface.opacity(0.55), in: .rect(cornerRadius: Radius.md))
        .overlay(RoundedRectangle(cornerRadius: Radius.md).strokeBorder(Palette.border))
    }
}

/// 三态小图标（✓ 实心绿 / ? 空心琥珀 / ! 实心琥珀）
struct MarkDot: View {
    var mark: SkillMark
    var size: CGFloat = 16

    var body: some View {
        ZStack {
            if mark == .unsure {
                Circle().strokeBorder(mark.color, lineWidth: 1.4)
                Text("?").font(.system(size: size * 0.62, weight: .black)).foregroundStyle(mark.color)
            } else {
                Circle().fill(mark.color)
                if mark == .ok {
                    Path { p in
                        p.move(to: CGPoint(x: size * 0.28, y: size * 0.52))
                        p.addLine(to: CGPoint(x: size * 0.44, y: size * 0.68))
                        p.addLine(to: CGPoint(x: size * 0.73, y: size * 0.35))
                    }
                    .stroke(Palette.onAccent, style: StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round))
                } else {
                    Text("!").font(.system(size: size * 0.62, weight: .black)).foregroundStyle(Palette.onAccent)
                }
            }
        }
        .frame(width: size, height: size)
    }
}
