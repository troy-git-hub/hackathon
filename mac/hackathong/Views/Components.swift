//
//  Components.swift
//  Echo — 学习工具风格组件
//    CatAvatar   矢量线稿猫头（只负责情绪反馈，随主题变色）
//    PulseDots   三个依次跳动的小圆点
//    BreakPath   断点页三节点：刚才会的 → 掉队的那一步 → 老师讲到这里
//    LessonStep  补课页三段式中的一段（左侧轨道 + 标签 + 内容）
//    SkillRow    回响页一行：知识点 + 掌握度条 + ✓ ? ! 三态
//    ReviewChain 回响页复习链：你的掉队点 ↓ 前置 ↓ 建议复习
//    WaveOrb     声纹球：跟着老师声音真实起伏
//

import SwiftUI

private let railX: CGFloat = 11
private let textLeft: CGFloat = 30

// MARK: - 猫头像

enum CatEmotion {
    case idle, ok, warn, lost, thinking, fixed
}

struct CatAvatar: View {
    var emotion: CatEmotion
    var size: CGFloat = 30
    @State private var blink = false

    var body: some View {
        Canvas { ctx, sz in
            ctx.scaleBy(x: sz.width / 32, y: sz.height / 32)
            draw(&ctx)
        }
        .frame(width: size, height: size)
        .task(id: emotion) {
            // idle 时每 4.2 秒眨一次眼
            while !Task.isCancelled, emotion == .idle {
                try? await Task.sleep(for: .seconds(4.2))
                blink = true
                try? await Task.sleep(for: .milliseconds(140))
                blink = false
            }
        }
    }

    private func draw(_ ctx: inout GraphicsContext) {
        let line: Color = switch emotion {
        case .lost: Palette.accent
        case .ok, .fixed: Palette.okFG
        default: Palette.textPrimary
        }
        let stroke = StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round)

        // 头 + 两只耳朵（一条闭合路径）
        var head = Path()
        head.move(to: CGPoint(x: 6.2, y: 13.0))
        head.addLine(to: CGPoint(x: 5.0, y: 4.2))
        head.addLine(to: CGPoint(x: 12.0, y: 8.6))
        head.addQuadCurve(to: CGPoint(x: 20.0, y: 8.6), control: CGPoint(x: 16.0, y: 7.6))
        head.addLine(to: CGPoint(x: 27.0, y: 4.2))
        head.addLine(to: CGPoint(x: 25.8, y: 13.0))
        head.addCurve(to: CGPoint(x: 16.0, y: 27.6), control1: CGPoint(x: 28.6, y: 19.5), control2: CGPoint(x: 24.5, y: 27.6))
        head.addCurve(to: CGPoint(x: 6.2, y: 13.0), control1: CGPoint(x: 7.5, y: 27.6), control2: CGPoint(x: 3.4, y: 19.5))
        ctx.fill(head, with: .color(Palette.surface))
        ctx.stroke(head, with: .color(line), style: stroke)

        func dot(_ x: CGFloat, _ y: CGFloat, _ r: CGFloat = 1.5) {
            ctx.fill(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)), with: .color(line))
        }
        func seg(_ a: CGPoint, _ b: CGPoint) {
            var p = Path()
            p.move(to: a)
            p.addLine(to: b)
            ctx.stroke(p, with: .color(line), style: stroke)
        }

        // 眼睛
        let ly: CGFloat = 17.2, lx: CGFloat = 11.4, rx: CGFloat = 20.6
        switch emotion {
        case .ok, .fixed:                                   // ^ ^
            for x in [lx, rx] {
                var p = Path()
                p.move(to: CGPoint(x: x - 2, y: ly + 0.8))
                p.addQuadCurve(to: CGPoint(x: x + 2, y: ly + 0.8), control: CGPoint(x: x, y: ly - 2.2))
                ctx.stroke(p, with: .color(line), style: stroke)
            }
        case .lost:                                         // 下垂的眼睛
            for (x, d) in [(lx, 1.0), (rx, -1.0)] {
                seg(CGPoint(x: x - 2, y: ly - 1.2 * d), CGPoint(x: x + 2, y: ly + 1.2 * d))
                dot(x, ly + 1.6, 1.2)
            }
        case .warn:                                         // 一只眯一只睁
            seg(CGPoint(x: lx - 2, y: ly), CGPoint(x: lx + 2, y: ly))
            dot(rx, ly, 1.6)
        case .thinking:                                     // 往上看
            dot(lx + 0.6, ly - 1)
            dot(rx + 0.6, ly - 1)
        case .idle where blink:
            seg(CGPoint(x: lx - 1.8, y: ly), CGPoint(x: lx + 1.8, y: ly))
            seg(CGPoint(x: rx - 1.8, y: ly), CGPoint(x: rx + 1.8, y: ly))
        case .idle:
            dot(lx, ly)
            dot(rx, ly)
        }

        // 嘴
        var mouth = Path()
        switch emotion {
        case .ok, .fixed:
            mouth.move(to: CGPoint(x: 13.4, y: 21.4))
            mouth.addQuadCurve(to: CGPoint(x: 18.6, y: 21.4), control: CGPoint(x: 16, y: 24.6))
        case .lost:
            mouth.move(to: CGPoint(x: 13.8, y: 23.4))
            mouth.addQuadCurve(to: CGPoint(x: 18.2, y: 23.4), control: CGPoint(x: 16, y: 21.4))
        default:
            mouth.move(to: CGPoint(x: 13.6, y: 21.6))
            mouth.addQuadCurve(to: CGPoint(x: 16.0, y: 21.6), control: CGPoint(x: 14.8, y: 23.0))
            mouth.addQuadCurve(to: CGPoint(x: 18.4, y: 21.6), control: CGPoint(x: 17.2, y: 23.0))
        }
        ctx.stroke(mouth, with: .color(line), style: StrokeStyle(lineWidth: 1.3, lineCap: .round, lineJoin: .round))

        // 情绪小符号
        if emotion == .warn {
            ctx.draw(Text("?").font(.system(size: 9, weight: .bold)).foregroundStyle(Palette.textSecondary),
                     at: CGPoint(x: 28.5, y: 4.5))
        } else if emotion == .thinking {
            for i in 0..<3 { dot(23.5 + CGFloat(i) * 2.6, 3.0 - CGFloat(i) * 0.2, 0.9) }
        }
    }
}

/// 猫的情绪：可设一个持续时间，过后自动回到 idle
@Observable
final class CatMood {
    private(set) var emotion: CatEmotion = .idle
    private var revert: Task<Void, Never>?

    func set(_ e: CatEmotion, hold: Duration? = nil) {
        revert?.cancel()
        emotion = e
        guard let hold else { return }
        revert = Task { [weak self] in
            try? await Task.sleep(for: hold)
            guard !Task.isCancelled else { return }
            self?.emotion = .idle
        }
    }
}

// MARK: - 加载圆点

struct PulseDots: View {
    var color: Color = Palette.accent

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.16)) { ctx in
            let phase = Int(ctx.date.timeIntervalSinceReferenceDate / 0.16) % 3
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(color.opacity(i == phase ? 1 : 0.3)).frame(width: 6, height: 6)
                }
            }
            .frame(width: 30, height: 12)
        }
    }
}

/// 加载卡片：跳动圆点 + 一句话
struct LoadingCard: View {
    var text: String
    var color: Color = Palette.accent
    var busy = true

    var body: some View {
        HStack(spacing: Spacing.md) {
            if busy { PulseDots(color: color) }
            Text(text)
                .font(.system(size: 14))
                .foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(Spacing.lg)
        .background(Palette.surface, in: .rect(cornerRadius: Radius.md))
        .overlay(RoundedRectangle(cornerRadius: Radius.md).stroke(Palette.border))
    }
}

// MARK: - 富文本：公式等宽高亮，步骤序号弱化

enum RichText {
    private static let formula = try! NSRegularExpression(
        pattern: #"((?:[A-Za-z]\([^()（）]{1,24}\)|[A-Za-z]\b)(?:[\s·*/+\-=×÷^|∩∪A-Za-z0-9().']|乘|除以)*[A-Za-z0-9)])"#)
    private static let stepPrefix = try! NSRegularExpression(
        pattern: #"^(第[一二三四五六七八九十\d]+步[：:]|\d+[\.、．])"#)

    static func paragraphs(_ text: String) -> [AttributedString] {
        text.split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .map(line)
    }

    private static func line(_ s: String) -> AttributedString {
        let ns = s as NSString
        let full = NSRange(location: 0, length: ns.length)
        var out = AttributedString()
        var cursor = 0

        for m in formula.matches(in: s, range: full) {
            let piece = ns.substring(with: m.range)
            guard piece.contains("(") || piece.contains("=") else { continue }
            out += AttributedString(ns.substring(with: NSRange(location: cursor, length: m.range.location - cursor)))
            // 公式内部不许折行：字符之间插 U+2060（word joiner）
            var f = AttributedString(piece.map(String.init).joined(separator: "\u{2060}"))
            f.font = .system(size: 13, design: .monospaced)
            f.backgroundColor = Palette.codeBG
            out += f
            cursor = m.range.location + m.range.length
        }
        out += AttributedString(ns.substring(from: cursor))

        if let m = stepPrefix.firstMatch(in: s, range: full),
           let r = Range(m.range, in: s), let ar = Range(r, in: out) {
            out[ar].foregroundColor = Palette.textSecondary
        }
        return out
    }
}

struct RichTextView: View {
    var text: String
    var size: CGFloat = 13
    var color: Color = Palette.textPrimary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(RichText.paragraphs(text).enumerated()), id: \.offset) { _, p in
                Text(p)
                    .font(.system(size: size))
                    .foregroundStyle(color)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - 左侧轨道（竖线）

/// 在节点圆心上下画轨道线，留出圆点的位置
private struct Rail: View {
    var cy: CGFloat
    var gap: CGFloat
    var first: Bool
    var last: Bool

    var body: some View {
        GeometryReader { geo in
            Path { p in
                if !first {
                    p.move(to: CGPoint(x: railX, y: 0))
                    p.addLine(to: CGPoint(x: railX, y: max(0, cy - gap)))
                }
                if !last {
                    p.move(to: CGPoint(x: railX, y: cy + gap))
                    p.addLine(to: CGPoint(x: railX, y: geo.size.height))
                }
            }
            .stroke(Palette.borderStrong, lineWidth: 2)
        }
    }
}

// MARK: - 断点页三节点

enum PathRole {
    case known, brk, now

    var label: String {
        switch self {
        case .known: tr("刚才会的", "You knew this")
        case .brk: tr("掉队的那一步", "The step you missed")
        case .now: tr("老师讲到这里", "Teacher is here now")
        }
    }
}

private struct PathNode: View {
    var role: PathRole
    var concept: Concept
    var note: String
    var first: Bool
    var last: Bool

    private var isBP: Bool { role == .brk }
    private var cy: CGFloat { isBP ? 18 : 16 }
    private let nodeR: CGFloat = 7

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(role.label)  ·  \(concept.timecode)")
                .font(.system(size: 11, weight: isBP ? .bold : .medium))
                .foregroundStyle(isBP ? Palette.accent : Palette.textSecondary)
            Text(concept.topic)
                .font(.system(size: isBP ? 16 : 14, weight: isBP ? .bold : .medium))
                .foregroundStyle(role == .known ? Palette.textSecondary : Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if isBP && !note.isEmpty {
                Text(note)
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.accent)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.top, isBP ? 8 : 6)
        .padding(.bottom, isBP ? 10 : 8)
        .padding(.trailing, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, textLeft)
        .background(alignment: .leading) {
            if isBP {   // 断点行：唯一的强调底色
                RoundedRectangle(cornerRadius: Radius.md)
                    .fill(Palette.accentSoft)
                    .overlay(RoundedRectangle(cornerRadius: Radius.md).stroke(Palette.accentBorder))
                    .padding(.leading, textLeft - 8)
                    .padding(.vertical, 1)
            }
        }
        .background(Rail(cy: cy, gap: nodeR + 2, first: first, last: last))
        .overlay(alignment: .topLeading) { marker.position(x: railX, y: cy) }
    }

    @ViewBuilder private var marker: some View {
        switch role {
        case .known:     // 空心对勾
            ZStack {
                Circle().fill(Palette.windowBG)
                Circle().stroke(Palette.okFG, lineWidth: 1.6)
                Path { p in
                    p.move(to: CGPoint(x: 3.8, y: 7.2))
                    p.addLine(to: CGPoint(x: 6.2, y: 9.6))
                    p.addLine(to: CGPoint(x: 10.4, y: 4.6))
                }
                .stroke(Palette.okFG, lineWidth: 1.6)
            }
            .frame(width: nodeR * 2, height: nodeR * 2)
        case .brk:       // 实心强调色 + 「!」
            ZStack {
                Circle().fill(Palette.accent.opacity(0.22)).frame(width: nodeR * 2 + 8, height: nodeR * 2 + 8)
                Circle().fill(Palette.accent).frame(width: nodeR * 2, height: nodeR * 2)
                Text("!").font(.system(size: 10, weight: .black)).foregroundStyle(Palette.onAccent)
            }
        case .now:       // 现在：中性实心点
            ZStack {
                Circle().fill(Palette.windowBG)
                Circle().stroke(Palette.nowFG, lineWidth: 1.6)
                Circle().fill(Palette.nowFG).frame(width: 6.4, height: 6.4)
            }
            .frame(width: nodeR * 2, height: nodeR * 2)
        }
    }
}

struct BreakPath: View {
    /// 后端给的时间轴片段；从中挑出 断点前一个 / 断点 / 最后一个
    var concepts: [Concept]
    var breakpointTC: String
    var note: String

    private var nodes: [(PathRole, Concept)] {
        guard !concepts.isEmpty else { return [] }
        let idx = concepts.firstIndex { $0.timecode == breakpointTC } ?? max(0, concepts.count - 2)
        var out: [(PathRole, Concept)] = []
        if idx > 0 { out.append((.known, concepts[idx - 1])) }
        out.append((.brk, concepts[idx]))
        if idx < concepts.count - 1 { out.append((.now, concepts[concepts.count - 1])) }
        return out
    }

    var body: some View {
        let ns = nodes
        VStack(spacing: 0) {
            ForEach(Array(ns.enumerated()), id: \.offset) { i, n in
                PathNode(role: n.0, concept: n.1, note: n.0 == .brk ? note : "",
                         first: i == 0, last: i == ns.count - 1)
            }
        }
    }
}

// MARK: - 补课三段式

enum LessonKind {
    case known, step, now

    var label: String {
        switch self {
        case .known: tr("你已经知道", "What you already know")
        case .step: tr("中间漏了这一步", "The step you missed")
        case .now: tr("所以现在你能听懂", "So now it makes sense")
        }
    }

    var number: String {
        switch self {
        case .known: "1"
        case .step: "2"
        case .now: "3"
        }
    }
}

struct LessonStep: View {
    var kind: LessonKind
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(kind.label)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(kind == .known ? Palette.okFG : kind == .step ? Palette.accent : Palette.textSecondary)
            if kind == .step {
                RichTextView(text: text, size: 14)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Palette.accentSoft, in: .rect(cornerRadius: Radius.md))
                    .overlay(RoundedRectangle(cornerRadius: Radius.md).stroke(Palette.accentBorder))
            } else {
                RichTextView(text: text, size: 13,
                             color: kind == .now ? Palette.textPrimary : Palette.textSecondary)
            }
        }
        .padding(.leading, textLeft)
        .padding(.bottom, kind == .now ? 0 : 14)
        .background(Rail(cy: 9, gap: 7, first: true, last: kind == .now))
        .overlay(alignment: .topLeading) {
            ZStack {
                if kind == .step {
                    Circle().fill(Palette.accent)
                } else {
                    Circle().fill(Palette.windowBG)
                    Circle().stroke(Palette.borderStrong, lineWidth: 1.4)
                }
                Text(kind.number)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(kind == .step ? Palette.onAccent : Palette.textSecondary)
            }
            .frame(width: 16, height: 16)
            .position(x: railX, y: 9)
        }
    }
}

// MARK: - 回响：掌握度条 + ✓ ? ! 三态

enum SkillMark {
    case ok, unsure, lost

    /// ✓ 跟上了（含已补上）/ ? 有点懵 / ! 掉队了
    init(status: SkillStatus, mastery: Double) {
        if status == .ok || status == .fixed {
            self = .ok
        } else {
            self = mastery >= 0.5 ? .unsure : .lost
        }
    }

    var color: Color { self == .ok ? Palette.okFG : Palette.accent }
    var barColor: Color {
        switch self {
        case .ok: Palette.okFG
        case .unsure: Palette.accentBorder
        case .lost: Palette.accent
        }
    }
}

private struct MarkIcon: View {
    var mark: SkillMark

    var body: some View {
        ZStack {
            if mark == .unsure {
                Circle().strokeBorder(mark.color, lineWidth: 1.6)
                Text("?").font(.system(size: 11, weight: .black)).foregroundStyle(mark.color)
            } else {
                Circle().fill(mark.color)
                if mark == .ok {   // 对勾自己画，小尺寸下比字形清楚
                    Path { p in
                        p.move(to: CGPoint(x: 5.3, y: 9.9))
                        p.addLine(to: CGPoint(x: 8.3, y: 12.8))
                        p.addLine(to: CGPoint(x: 13.9, y: 6.7))
                    }
                    .stroke(Palette.onAccent, style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                } else {
                    Text("!").font(.system(size: 11, weight: .black)).foregroundStyle(Palette.onAccent)
                }
            }
        }
        .frame(width: 19, height: 19)
    }
}

/// 回响页一行：知识点 ━━━━━░░ ✓ / ? / !；note 是名字下的小字（已补上 / 自己看了）
struct SkillRow: View {
    var name: String
    var mastery: Double
    var mark: SkillMark
    var note: String = ""

    var body: some View {
        HStack(spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 0) {
                Text(name)
                    .font(.system(size: 14, weight: mark == .lost ? .semibold : .regular))
                    .foregroundStyle(Palette.textPrimary)
                    .wrap()
                    .help(name)
                if !note.isEmpty {
                    Text(note).font(.system(size: 11)).foregroundStyle(Palette.accent)
                }
            }
            .frame(width: 128, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Palette.border)
                    Capsule().fill(mark.barColor)
                        .frame(width: geo.size.width * max(0.06, min(1, mastery)))   // 再低也露一点头
                }
            }
            .frame(height: 8)
            MarkIcon(mark: mark)
        }
        .padding(.vertical, 5)
    }
}

/// 你的掉队点 ↓ 前置 ↓ 建议复习：根源。chain 为「掉队点 → … → 根源」
struct ReviewChain: View {
    var chain: [String]
    var suggestion: String

    private var items: [String] {
        var out: [String] = []
        for c in chain.map({ $0.trimmingCharacters(in: .whitespaces) }) where !c.isEmpty && out.last != c {
            out.append(c)
        }
        return out
    }

    static func hasContent(chain: [String], suggestion: String) -> Bool {
        chain.contains { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            || !suggestion.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        let items = items
        let sug = suggestion.trimmingCharacters(in: .whitespaces)
        VStack(spacing: 2) {
            if items.isEmpty {
                Text(sug).font(.system(size: 15, weight: .semibold)).foregroundStyle(Palette.textPrimary)
            } else {
                Text(tr("你的掉队点", "Your breakpoint")).font(.system(size: 11, weight: .bold)).foregroundStyle(Palette.accent)
                Text(items[0]).font(.system(size: 17, weight: .bold)).foregroundStyle(Palette.textPrimary)
                ForEach(Array(items.dropFirst().dropLast().enumerated()), id: \.offset) { _, mid in
                    arrow
                    Text(tr("前置", "Prerequisite")).font(.system(size: 11)).foregroundStyle(Palette.textSecondary)
                    Text(mid).font(.system(size: 14)).foregroundStyle(Palette.textPrimary)
                }
                arrow
                if items.count > 1, let root = items.last {
                    Text(tr("建议复习：\(root)", "Review: \(root)")).font(.system(size: 16, weight: .bold)).foregroundStyle(Palette.accent)
                    if !sug.isEmpty && !(sug.hasPrefix(tr("建议复习", "Review:")) && sug.contains(root)) {
                        Text(sug).font(.system(size: 12)).foregroundStyle(Palette.textSecondary).padding(.top, 6)
                    }
                } else {
                    Text(sug.isEmpty ? tr("建议复习：\(items[0])", "Review: \(items[0])") : sug)
                        .font(.system(size: 16, weight: .bold)).foregroundStyle(Palette.accent)
                }
            }
        }
        .multilineTextAlignment(.center)
        .wrap()
        .frame(maxWidth: .infinity)
        .card()
    }

    private var arrow: some View {
        Text("↓").font(.system(size: 14)).foregroundStyle(Palette.textDisabled)
    }
}

// MARK: - 声纹球

/// 不在听：7 个小圆点；在听：6 条垂线跟随真实音频响度起伏（两端最短，中间最长）
struct WaveOrb: View {
    var listening: Bool
    var level: Double
    @State private var env = 0.0

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !listening)) { ctx in
            let phase = ctx.date.timeIntervalSinceReferenceDate * 4.4
            Canvas { g, size in
                let s = min(size.width, size.height)
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let r = s * 0.40
                let orb = CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2)
                g.fill(Path(ellipseIn: orb), with: .radialGradient(
                    Gradient(colors: [Palette.accent.opacity(0.75), Palette.accent, Palette.accent.mix(with: .black, by: 0.3)]),
                    center: CGPoint(x: c.x - r * 0.3, y: c.y - r * 0.3), startRadius: 0, endRadius: r * 1.1))
                g.clip(to: Path(ellipseIn: orb))
                if !listening {
                    let n = 7, dot = max(1.2, r * 0.10), sp = r * 1.6 / CGFloat(n - 1)
                    for i in 0..<n {
                        let t = 1 - abs(Double(i) - 3) / 3 * 0.4
                        let x = c.x - sp * 3 + CGFloat(i) * sp
                        g.fill(Path(ellipseIn: CGRect(x: x - dot, y: c.y - dot, width: dot * 2, height: dot * 2)),
                               with: .color(.white.opacity(0.86 * t)))
                    }
                } else {
                    let n = 6, bw = max(1.5, r * 0.16), sp = r * 1.6 / CGFloat(n - 1)
                    for i in 0..<n {
                        let w = sin((Double(i) + 0.5) * .pi / 6)
                        let v = max(0.05, min(1, env * w * (0.82 + 0.18 * sin(phase + Double(i) * 0.9))))
                        let h = CGFloat(v) * r * 2 * 0.78
                        let x = c.x - sp * 2.5 + CGFloat(i) * sp
                        g.fill(Path(roundedRect: CGRect(x: x - bw / 2, y: c.y - h / 2, width: bw, height: h),
                                    cornerRadius: bw / 2), with: .color(.white.opacity(0.9)))
                    }
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .onChange(of: level) { _, lv in
            // 包络：说话时快起、停顿时慢落
            env += (lv - env) * (lv > env ? 0.6 : 0.18)
        }
        .onChange(of: listening) { _, on in if !on { env = 0 } }
    }
}

// MARK: - 声纹条（只有竖条，没有球）

/// 跟着真实音频响度起伏的竖条：中间高、两端低
struct WaveBars: View {
    var level: Double
    var listening: Bool
    var bars: Int = 14
    @State private var env = 0.0

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !listening)) { ctx in
            let phase = ctx.date.timeIntervalSinceReferenceDate * 4.4
            Canvas { g, size in
                let gap: CGFloat = 3
                let bw = max(1.5, (size.width - gap * CGFloat(bars - 1)) / CGFloat(bars))
                for i in 0..<bars {
                    let x = Double(i) / Double(bars - 1)
                    let center = 1 - abs(x - 0.5) * 2
                    let v = max(0.05, min(1, env * (0.4 + 0.6 * center) * (0.85 + 0.15 * sin(phase + x * 5))))
                    let h = max(3, size.height * v)
                    let r = CGRect(x: CGFloat(i) * (bw + gap), y: size.height / 2 - h / 2, width: bw, height: h)
                    g.fill(Path(roundedRect: r, cornerRadius: bw / 2),
                           with: .color(Palette.accent.opacity(0.35 + 0.55 * center)))
                }
            }
        }
        .onChange(of: level) { _, lv in env += (lv - env) * (lv > env ? 0.6 : 0.18) }
        .onChange(of: listening) { _, on in if !on { env = 0 } }
    }
}

// MARK: - 表情包猫

extension CatEmotion {
    /// 标题栏表情包图片（与桌宠同步）
    var faceName: String {
        switch self {
        case .idle: "face_smug"
        case .ok, .fixed: "face_happy"
        case .warn: "face_confused"
        case .lost: "face_cry"
        case .thinking: "face_key"
        }
    }
}
