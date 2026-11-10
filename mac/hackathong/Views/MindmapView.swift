//
//  MindmapView.swift
//  Echo — 知识地图（对应 echo/widgets/mindmap.py）
//
//  单课：按依赖层级从上往下排布知识点，节点按状态上色；可平移 / 缩放 / 拖节点。
//  已学内容：把全部历史课合并成一张大图，按学科分列，顶部横向分类菜单可聚焦某个学科。
//  点节点 → 详情 + 相关知识点 + 两道题；「出题练一练」跳到练习页。
//

import SwiftUI
import AppKit

private let nodeW: CGFloat = 118
private let nodeH: CGFloat = 54
private let levelH: CGFloat = 96
private let gapX: CGFloat = 20
private let pad: CGFloat = 24
private let minScale: CGFloat = 0.45
private let maxScale: CGFloat = 2.4

@Observable
final class MindmapModel {
    /// single = 单课知识地图；learned = 「已学内容」聚合图（按学科分列）
    enum Scope { case single, learned }

    let engine: EchoEngine
    var scope: Scope = .single
    var lesson: LessonRecord?
    var graph: MindmapGraph?
    var positions: [String: CGPoint] = [:]
    var selected: String?
    var detail: MindNodeDetail?
    var questions: [PracticeQuestion] = []
    var loadingQuestions = false
    var offset: CGSize = .zero
    var scale: CGFloat = 1
    var userMoved = false
    var worldSize = CGSize(width: 320, height: 200)
    var viewSize: CGSize = .zero

    // ===== 聚合模式（已学内容）=====
    var subjects: [String] = []
    var focusSubject: Int? = nil              // nil = 全部
    var subjectIndexByTopic: [String: Int] = [:]
    var columnX: [Int: CGFloat] = [:]          // 学科列号 -> 列左边界 x（画列标题用）
    private var learnedMistakes: [ReviewItem] = []
    private var learnedLesson: LessonRecord?

    init(engine: EchoEngine) { self.engine = engine }

    var nodes: [MindNode] { graph?.nodes ?? [] }
    var edges: [MindEdge] { graph?.edges ?? [] }

    /// 两种入口：刚下课从回响报告进（信息最全），或从历史课回顾进
    func show(_ lesson: LessonRecord?, report: EchoReport? = nil) {
        scope = .single
        self.lesson = lesson
        subjects = []
        focusSubject = nil
        subjectIndexByTopic = [:]
        columnX = [:]
        learnedMistakes = []
        learnedLesson = nil
        selected = nil
        detail = nil
        questions = []
        userMoved = false
        let g: MindmapGraph
        if let report {
            g = Mindmap.fromReport(report, title: lesson?.title ?? "")
        } else if let lesson {
            g = Mindmap.build(lesson: lesson, mistakes: ReviewStore.load())
        } else {
            g = MindmapGraph(nodes: [], edges: [])
        }
        graph = g
        layout(g)
    }

    /// 「已学内容」：喂一张合并后的大图 + 学科列表 + 错题记录。
    /// lesson 是可选伪课程（后端 buildAll 若带 skills_detail，详情能看到讲解）。
    func showLearned(graph g: MindmapGraph, subjects: [String], mistakes: [ReviewItem],
                     lesson: LessonRecord? = nil) {
        scope = .learned
        self.lesson = lesson
        learnedLesson = lesson
        learnedMistakes = mistakes
        self.subjects = subjects
        selected = nil
        detail = nil
        questions = []
        loadingQuestions = false
        userMoved = false
        focusSubject = nil
        self.graph = g
        subjectIndexByTopic = [:]
        for n in g.nodes {
            subjectIndexByTopic[n.topic] = subjects.firstIndex(of: n.subject) ?? 0
        }
        layout(g)
    }

    /// 按层级从上往下排（单课）：同层横向均分
    private func layout(_ g: MindmapGraph) {
        if scope == .learned {
            layoutBySubject(g)
        } else {
            layoutByLevel(g)
        }
    }

    private func layoutByLevel(_ g: MindmapGraph) {
        var pos: [String: CGPoint] = [:]
        let byLevel = Dictionary(grouping: g.nodes, by: \.level)
        let widest = byLevel.values.map(\.count).max() ?? 1
        let width = max(320, CGFloat(widest) * (nodeW + gapX) + pad * 2)
        for (level, nodes) in byLevel {
            let step = width / CGFloat(nodes.count)
            for (i, n) in nodes.enumerated() {
                pos[n.id] = CGPoint(x: step * CGFloat(i) + (step - nodeW) / 2, y: pad + CGFloat(level) * levelH)
            }
        }
        positions = pos
        columnX = [:]
        let levels = (byLevel.keys.max() ?? 0) + 1
        worldSize = CGSize(width: width, height: pad * 2 + CGFloat(levels) * levelH)
    }

    /// 分区排布（聚合）：每个学科一列，列内按依赖层级从上往下堆（对应 Python _layout_by_subject）
    private func layoutBySubject(_ g: MindmapGraph) {
        var cols: [Int: [MindNode]] = [:]
        for n in g.nodes {
            let idx = subjectIndexByTopic[n.topic] ?? 0
            cols[idx, default: []].append(n)
        }
        let colW = nodeW + gapX
        let rowH = nodeH + gapX
        var pos: [String: CGPoint] = [:]
        var colX: [Int: CGFloat] = [:]
        var maxRows = 1
        let indices = cols.keys.sorted()
        for (ci, idx) in indices.enumerated() {
            let x = pad + CGFloat(ci) * colW
            colX[idx] = x
            // 列内按层级排序（同层按名字稳定），从上往下堆
            let row = (cols[idx] ?? []).sorted { ($0.level, $0.topic) < ($1.level, $1.topic) }
            for (ri, n) in row.enumerated() {
                pos[n.id] = CGPoint(x: x, y: pad + CGFloat(ri) * rowH)
            }
            maxRows = max(maxRows, row.count)
        }
        positions = pos
        columnX = colX
        let width = max(320, pad * 2 + CGFloat(indices.count) * colW)
        let height = max(320, pad * 2 + CGFloat(maxRows) * rowH)
        worldSize = CGSize(width: width, height: height)
    }

    func fit(in view: CGSize) {
        guard view.width > 0, view.height > 0 else { return }
        let s = min(view.width / worldSize.width, view.height / worldSize.height, 1.0)
        scale = min(max(s, minScale), maxScale)
        offset = CGSize(width: (view.width - worldSize.width * scale) / 2,
                        height: (view.height - worldSize.height * scale) / 2)
    }

    func reset() {
        if let g = graph { layout(g) }
        userMoved = false
        selected = nil
        detail = nil
        questions = []
    }

    /// 某个节点在聚焦模式下是否该淡化（不在选中学科里）。
    func isDimmed(_ topic: String) -> Bool {
        guard scope == .learned, let f = focusSubject else { return false }
        return (subjectIndexByTopic[topic] ?? f) != f
    }

    /// 图上与该节点直接相连的其它知识点（前置 / 后继）。
    var relatedTopics: [String] {
        guard let sel = selected else { return [] }
        var out: [String] = []
        for e in edges {
            if e.from == sel, e.to != sel, !out.contains(e.to) { out.append(e.to) }
            if e.to == sel, e.from != sel, !out.contains(e.from) { out.append(e.from) }
        }
        return out
    }

    /// 把某个节点挪到视口中央（相关知识点跳转用）。
    func centerOn(_ topic: String) {
        guard let p = positions[topic], viewSize.width > 0, viewSize.height > 0 else { return }
        offset = CGSize(width: viewSize.width / 2 - (p.x + nodeW / 2) * scale,
                        height: viewSize.height / 2 - (p.y + nodeH / 2) * scale)
        userMoved = true
    }

    func select(_ topic: String) {
        selected = topic
        detail = nil
        questions = []
        loadingQuestions = true
        let learned = scope == .learned
        let mistakes = learned ? learnedMistakes : ReviewStore.load()
        let d = learned
            ? learnedDetail(topic)
            : Mindmap.nodeDetail(lesson: lesson, topic: topic, mistakes: mistakes)
        detail = d
        let qsLesson: LessonRecord? = learned ? learnedLesson : lesson
        Task {
            let qs = await Mindmap.questions(for: topic, lesson: qsLesson, mistakes: mistakes, n: 2)
            guard selected == topic else { return }
            questions = qs
            loadingQuestions = false
        }
    }

    /// 聚合图的节点详情：状态取合并后的节点，其余解释性文字来自错题记录 / 伪课程。
    private func learnedDetail(_ topic: String) -> MindNodeDetail {
        let node = graph?.nodes.first { $0.topic == topic }
        if let lesson = learnedLesson {
            var d = Mindmap.nodeDetail(lesson: lesson, topic: topic, mistakes: learnedMistakes)
            if let node { d.status = node.status }
            return d
        }
        let mk = learnedMistakes.first { $0.topic == topic }
        return MindNodeDetail(topic: topic,
                              timecode: node?.timecode,
                              taught: "",
                              missing: mk?.missing ?? "",
                              known: mk?.known ?? "",
                              step: mk?.step ?? "",
                              microLesson: mk?.microLesson ?? "",
                              status: node?.status ?? (mk != nil ? "review" : "ok"),
                              reviewFirst: false)
    }
}

// MARK: - 画布

private struct MindCanvas: View {
    var model: MindmapModel
    var onPractice: (String) -> Void
    @State private var dragMode: DragMode = .idle
    @State private var dragOrigin: CGSize = .zero
    @State private var nodeOrigin: CGPoint = .zero
    @State private var hovering = false
    @State private var hoverTopic: String?
    @State private var monitor: Any?
    @State private var frameInWindow: CGRect = .zero

    private enum DragMode: Equatable { case idle, pan, node(String) }

    var body: some View {
        GeometryReader { geo in
            let view = geo.size
            ZStack(alignment: .topLeading) {
                // 空白处拖动 = 平移
                Color.clear
                    .contentShape(.rect)
                    .gesture(DragGesture(minimumDistance: 1)
                        .onChanged { v in
                            if dragMode == .idle {
                                dragMode = .pan
                                dragOrigin = model.offset
                                model.userMoved = true
                            }
                            model.offset = CGSize(width: dragOrigin.width + v.translation.width,
                                                  height: dragOrigin.height + v.translation.height)
                        }
                        .onEnded { _ in dragMode = .idle })

                Canvas { ctx, _ in
                    for e in model.edges {
                        guard let a = model.positions[e.from], let b = model.positions[e.to] else { continue }
                        let active = model.selected == e.from || model.selected == e.to
                        // 聚焦模式下，两端都不在选中学科里的连线淡化
                        let dim = model.isDimmed(e.from) && model.isDimmed(e.to)
                        draw(edge: ctx, from: a, to: b, active: active, dim: dim)
                    }
                    drawSubjectLabels(ctx)
                }
                .frame(width: max(worldSizeW, view.width), height: max(model.worldSize.height, view.height))

                ForEach(model.nodes) { n in
                    nodeView(n)
                        .frame(width: nodeW, height: nodeH)
                        .position(x: (model.positions[n.id]?.x ?? 0) + nodeW / 2,
                                  y: (model.positions[n.id]?.y ?? 0) + nodeH / 2)
                        .gesture(DragGesture(minimumDistance: 4)
                            .onChanged { v in
                                if case .node(let t) = dragMode, t == n.id {
                                    if let o = nodeOrigin as CGPoint? {
                                        model.positions[n.id] = CGPoint(x: o.x + v.translation.width / model.scale,
                                                                        y: o.y + v.translation.height / model.scale)
                                    }
                                } else if dragMode == .idle {
                                    dragMode = .node(n.id)
                                    nodeOrigin = model.positions[n.id] ?? .zero
                                    model.userMoved = true
                                }
                            }
                            .onEnded { _ in dragMode = .idle })
                        .onTapGesture {
                            model.select(n.topic)
                            // 选中后详情面板变高，重新 fit 一次（用户没手动动过时）
                            if !model.userMoved { model.fit(in: view) }
                        }
                }
            }
            .frame(width: view.width, height: view.height, alignment: .topLeading)
            .scaleEffect(model.scale, anchor: .topLeading)
            .offset(model.offset)
            .clipped()
            .contentShape(.rect)
            .onAppear { model.viewSize = view; model.fit(in: view) }
            .onChange(of: view) { _, v in
                model.viewSize = v
                if !model.userMoved { model.fit(in: v) }
            }
            .background(GeometryReader { g in
                Color.clear
                    .onAppear { frameInWindow = g.frame(in: .global) }
                    .onChange(of: g.frame(in: .global)) { _, r in frameInWindow = r }
            })
            .onHover { on in hovering = on; installMonitor() }
            .gesture(MagnificationGesture()
                .onChanged { v in
                    let old = model.scale
                    let new = min(max(old * v, minScale), maxScale)
                    guard new != old else { return }
                    let c = CGPoint(x: view.width / 2, y: view.height / 2)   // 双指缩放以视图中心为锚
                    model.offset = CGSize(width: c.x - (c.x - model.offset.width) / old * new,
                                          height: c.y - (c.y - model.offset.height) / old * new)
                    model.scale = new
                    model.userMoved = true
                })
            .onDisappear { removeMonitor() }
        }
        .frame(minHeight: 300)
    }

    private var worldSizeW: CGFloat { model.worldSize.width }

    // MARK: 节点

    @ViewBuilder private func nodeView(_ n: MindNode) -> some View {
        let style = NodeStyle(status: n.status)
        let isSelected = model.selected == n.topic
        let isHover = hoverTopic == n.topic
        let dim = model.isDimmed(n.topic)
        let reviewFirst = model.graph?.reviewFirst == n.topic
        let bg = dim ? Palette.surface : (isHover && !isSelected ? Palette.surfaceHover : style.bg)
        let line = dim ? Palette.border : style.line
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: Radius.md).fill(bg)
            if isSelected {
                RoundedRectangle(cornerRadius: Radius.md)
                    .strokeBorder(Palette.accent, lineWidth: 2)
            } else if reviewFirst && !dim {
                RoundedRectangle(cornerRadius: Radius.md)
                    .strokeBorder(Palette.primary, style: StrokeStyle(lineWidth: 2, dash: [4, 3]))
            } else {
                RoundedRectangle(cornerRadius: Radius.md)
                    .strokeBorder(line, lineWidth: 1.3)
            }
            VStack(spacing: 1) {
                Text(n.topic)
                    .font(.system(size: 12, weight: n.status == "ok" ? .medium : .semibold))
                    .foregroundStyle(dim ? Palette.textDisabled : Palette.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .frame(width: nodeW - 16)
                if let tc = n.timecode, !tc.isEmpty {
                    Text(tc).font(.system(size: 10)).foregroundStyle(Palette.textSecondary)
                }
            }
            .frame(width: nodeW, height: nodeH - 12)
            .padding(.top, n.timecode?.isEmpty == false ? 2 : 8)

            if n.status != "ok" && !dim {
                Circle().fill(style.line).frame(width: 6.4, height: 6.4).offset(x: 10, y: 11)
            }
            if reviewFirst && !dim {
                Circle().fill(Palette.primary).frame(width: 6.4, height: 6.4)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                    .offset(x: -10, y: 11)
            }
        }
        .contentShape(.rect)
        .onHover { hoverTopic = $0 ? n.topic : (hoverTopic == n.topic ? nil : hoverTopic) }
    }

    // MARK: 连线

    private func draw(edge ctx: GraphicsContext, from a: CGPoint, to b: CGPoint, active: Bool, dim: Bool) {
        let down = b.y >= a.y
        let p1 = CGPoint(x: a.x + nodeW / 2, y: down ? a.y + nodeH : a.y)
        let p2 = CGPoint(x: b.x + nodeW / 2, y: down ? b.y : b.y + nodeH)
        let mid = (p1.y + p2.y) / 2
        var path = Path()
        path.move(to: p1)
        path.addCurve(to: p2, control1: CGPoint(x: p1.x, y: mid), control2: CGPoint(x: p2.x, y: mid))
        let color = dim ? Palette.border : (active ? Palette.accent : Palette.borderStrong)
        ctx.stroke(path, with: .color(color),
                   style: StrokeStyle(lineWidth: dim ? 1 : (active ? 3 : 2), lineCap: .round))
        // 实心三角箭头
        var head = Path()
        let d: CGFloat = down ? 1 : -1
        head.move(to: p2)
        head.addLine(to: CGPoint(x: p2.x - 5.5, y: p2.y - 7.5 * d))
        head.addLine(to: CGPoint(x: p2.x + 5.5, y: p2.y - 7.5 * d))
        head.closeSubpath()
        ctx.fill(head, with: .color(color))
    }

    /// 分区模式：每列顶上标学科名（强调色 11px bold）。
    private func drawSubjectLabels(_ ctx: GraphicsContext) {
        if model.scope == .learned {
            for (idx, x) in model.columnX {
                guard idx < model.subjects.count else { continue }
                let dim = model.focusSubject != nil && model.focusSubject != idx
                ctx.draw(Text(model.subjects[idx])
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(dim ? Palette.textDisabled : Palette.accent),
                         at: CGPoint(x: x, y: pad / 2), anchor: .leading)
            }
        }
    }

    // MARK: 滚轮缩放（以光标为中心）

    private func installMonitor() {
        if !hovering { removeMonitor(); return }
        guard monitor == nil else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { event in
            guard let win = event.window, let content = win.contentView else { return event }
            // NSEvent 是左下原点；SwiftUI 的 .global 是窗口左上原点
            let p = event.locationInWindow
            let pt = CGPoint(x: p.x, y: content.bounds.height - p.y)
            guard frameInWindow.contains(pt) else { return event }
            let factor = pow(1.12, event.scrollingDeltaY / 120 * 3)
            let old = model.scale
            let new = min(max(old * factor, minScale), maxScale)
            guard new != old else { return nil }
            model.offset = CGSize(width: pt.x - (pt.x - model.offset.width) / old * new,
                                  height: (pt.y - frameInWindow.minY) - ((pt.y - frameInWindow.minY) - model.offset.height) / old * new)
            model.scale = new
            model.userMoved = true
            return nil
        }
    }

    private func removeMonitor() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
    }
}

private struct NodeStyle {
    var line: Color
    var bg: Color

    init(status: String) {
        switch status {
        case "review": line = Palette.danger; bg = Palette.dangerBG
        case "fixed": line = Palette.accent; bg = Palette.accentSoft
        default: line = Palette.borderStrong; bg = Palette.surface
        }
    }
}

/// 知识地图的图例 / 重置视图 / 提示行，单课与聚合页共用。
private struct MapTools: View {
    var map: MindmapModel

    var body: some View {
        HStack {
            Text(tr("● 待回看   ● 补上了   ○ 已跟上   ⋯ 建议先看", "● review   ● fixed   ○ ok   ⋯ start here"))
                .font(.system(size: 11)).foregroundStyle(Palette.textSecondary)
            Spacer()
            Button(tr("重置视图", "Reset view")) { map.reset() }
                .buttonStyle(.plain)
                .font(.system(size: 11))
                .foregroundStyle(Palette.textSecondary)
                .padding(.horizontal, 10).padding(.vertical, 3)
                .background(Palette.surface, in: .rect(cornerRadius: Radius.sm))
                .overlay(RoundedRectangle(cornerRadius: Radius.sm).strokeBorder(Palette.border))
                .help(tr("回到自动排布的位置", "Back to the auto layout"))
        }
    }
}

private struct MapHint: View {
    var body: some View {
        Text(tr("拖动空白处平移 · 滚轮缩放 · 点节点看讲解 · 节点也能直接拖走",
                "Drag to pan · scroll to zoom · click a node for the explanation"))
            .font(.system(size: 11)).foregroundStyle(Palette.textDisabled).wrap()
    }
}

// MARK: - 详情面板（单课 / 聚合共用）

private struct MindDetailPanel: View {
    var model: AppModel
    var map: MindmapModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let d = map.detail {
                HStack {
                    Text(d.topic).font(.system(size: 14, weight: .semibold)).foregroundStyle(Palette.textPrimary)
                    Spacer()
                    Text(statusLabel(d.status)).font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(statusColor(d.status))
                }
                Text(taught(d)).font(.system(size: 13)).foregroundStyle(Palette.textPrimary).lineSpacing(3).wrap()
                Text(missText(d)).font(.system(size: 13)).foregroundStyle(Palette.textPrimary).lineSpacing(3).wrap()
                relatedTopics
                if map.loadingQuestions {
                    Text(tr("正在准备这道题…", "Preparing a question…"))
                        .font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
                } else {
                    ForEach(Array(map.questions.enumerated()), id: \.offset) { i, q in
                        questionCard(i, q)
                    }
                }
                HStack {
                    Spacer()
                    Button(tr("出题练一练", "Practice this")) { model.practiceTopic(d.topic) }
                        .buttonStyle(AccentButtonStyle(fontSize: 12, minHeight: 30))
                        .frame(width: 120)
                }
            } else {
                Text(tr("点上面的知识点，这里显示讲解和题目。", "Click a concept above to see the explanation and questions."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            }
        }
        .card()
    }

    /// 相关知识点：图上直接相连的前置 / 后继，点一下选中并聚焦过去。
    @ViewBuilder private var relatedTopics: some View {
        let related = map.relatedTopics
        if !related.isEmpty {
            Text(tr("相关知识点", "Related topics"))
                .font(.system(size: 11, weight: .bold)).foregroundStyle(Palette.accent)
                .padding(.top, 2)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 72), spacing: 6)],
                      alignment: .leading, spacing: 6) {
                ForEach(related, id: \.self) { t in
                    Button {
                        map.select(t)
                        map.centerOn(t)
                    } label: {
                        Text(t)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(Palette.accent)
                            .lineLimit(1)
                            .padding(.horizontal, 9).padding(.vertical, 3)
                            .background(Palette.accentSoft, in: .capsule)
                            .overlay(Capsule().strokeBorder(Palette.accentBorder))
                    }
                    .buttonStyle(.plain)
                    .help(t)
                }
            }
        }
    }

    private func taught(_ d: MindNodeDetail) -> String {
        let body = d.taught.isEmpty ? tr("这节课没有留下这个知识点的讲解记录。", "No explanation recorded for this concept.") : d.taught
        guard let tc = d.timecode, !tc.isEmpty else { return body }
        return tr("老师讲到 \(tc)　\(body)", "Taught at \(tc) · \(body)")
    }

    private func missText(_ d: MindNodeDetail) -> String {
        var lines: [String] = []
        if d.reviewFirst { lines.append(tr("建议先补这个 —— 复习链追到的最根源概念。", "Start here — the root of the review chain.")) }
        if !d.missing.isEmpty { lines.append(tr("你可能卡在：", "Where you got stuck: ") + d.missing) }
        if !d.known.isEmpty { lines.append(tr("先确认你已经知道的：", "What you already know: ") + d.known) }
        if !d.step.isEmpty { lines.append(tr("漏掉的那一步：", "The missing step: ") + d.step) }
        if !d.microLesson.isEmpty { lines.append(d.microLesson) }
        if lines.isEmpty { lines.append(tr("这个知识点没掉队过，可以直接出题确认一下。", "You never fell behind here — try a question to confirm.")) }
        return lines.joined(separator: "\n")
    }

    private func questionCard(_ index: Int, _ q: PracticeQuestion) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(tr("第 \(index + 1) 题", "Q\(index + 1)")).font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Palette.textSecondary)
            Text(q.question).font(.system(size: 13)).foregroundStyle(Palette.textPrimary).wrap()
            ForEach(q.options, id: \.self) { o in
                Text(o).font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
            }
            Text(tr("答案：", "Answer: ") + (q.answer.isEmpty ? tr("见解析", "see explanation") : q.answer))
                .font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.okFG)
            if !q.explain.isEmpty {
                Text(tr("解析：", "Why: ") + q.explain).font(.system(size: 12))
                    .foregroundStyle(Palette.textSecondary).wrap()
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.codeBG, in: .rect(cornerRadius: Radius.md))
    }

    private func statusLabel(_ s: String) -> String {
        switch s {
        case "review": tr("● 待回看", "● review")
        case "fixed": tr("● 已补上", "● fixed")
        default: tr("● 已跟上", "● ok")
        }
    }

    private func statusColor(_ s: String) -> Color {
        switch s {
        case "review": Palette.danger
        case "fixed": Palette.accent
        default: Palette.okFG
        }
    }
}

// MARK: - 单课页面

struct MindmapPage: View {
    var model: AppModel
    var map: MindmapModel

    var body: some View {
        let nodes = map.nodes
        let review = nodes.filter { $0.status == "review" }.count
        let fixed = nodes.filter { $0.status == "fixed" }.count
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("知识地图", "Knowledge map")).font(.system(size: 15, weight: .semibold))
                Text(subtitle(nodes.count, review, fixed)).caption().wrap()
            }
            if nodes.isEmpty {
                Text(tr("这节课还没有知识点记录。上完一节课，这里会长出知识地图。",
                        "No concepts yet. Finish a lesson and the map grows here."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            } else {
                MindCanvas(model: map, onPractice: { topic in
                    map.selected = topic
                    model.practiceTopic(topic)
                })
                .frame(height: 320)
                .background(Palette.windowBG, in: .rect(cornerRadius: Radius.md))
                .overlay(RoundedRectangle(cornerRadius: Radius.md).strokeBorder(Palette.border))

                MapTools(map: map)
                MapHint()
                MindDetailPanel(model: model, map: map)
            }
        }
    }

    private func subtitle(_ total: Int, _ review: Int, _ fixed: Int) -> String {
        if total == 0 { return tr("这节课没有留下知识点记录", "No concepts recorded for this lesson") }
        var s = tr("\(total) 个知识点 · \(review) 个待回看 · \(fixed) 个已补上",
                   "\(total) concepts · \(review) to review · \(fixed) fixed")
        if review == 0 { s += tr(" · 都跟上了", " · all caught up") }
        return s
    }
}

// MARK: - 已学内容（聚合知识地图）

/// 把所有历史课合并成一张按学科分区的大图。
/// 入口由调用方接线：传入后端 `Mindmap.buildAll(lessons:mistakes:)` 的 graph / subjects。
/// `lesson` 可选：带 skills_detail 的伪课程，能让节点详情显示讲解文字。
struct LearnedPage: View {
    var model: AppModel
    var graph: MindmapGraph
    var subjects: [String]
    var mistakes: [ReviewItem]
    var lesson: LessonRecord?

    @State private var map: MindmapModel

    init(model: AppModel, graph: MindmapGraph, subjects: [String], mistakes: [ReviewItem],
         lesson: LessonRecord? = nil) {
        self.model = model
        self.graph = graph
        self.subjects = subjects
        self.mistakes = mistakes
        self.lesson = lesson
        _map = State(initialValue: MindmapModel(engine: model.engine))
    }

    var body: some View {
        let nodes = map.nodes
        let review = nodes.filter { $0.status == "review" }.count
        // 这一页不做纵向滚动；画布高度固定，滚轮事件交给画布缩放。
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("已学内容", "Learned so far")).font(.system(size: 15, weight: .semibold))
                Text(subtitle(nodes.count, review)).caption().wrap()
            }
            if nodes.isEmpty {
                Text(tr("上完一节课，这里会长出你的知识地图。",
                        "Finish a lesson and your map grows here."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            } else {
                categoryMenu
                MindCanvas(model: map, onPractice: { topic in
                    map.selected = topic
                    model.practiceTopic(topic)
                })
                .frame(height: 400)
                .background(Palette.windowBG, in: .rect(cornerRadius: Radius.md))
                .overlay(RoundedRectangle(cornerRadius: Radius.md).strokeBorder(Palette.border))

                MapTools(map: map)
                MapHint()
                MindDetailPanel(model: model, map: map)
            }
        }
        .onAppear { reload() }
        .onChange(of: graph) { _, _ in reload() }
    }

    private func reload() {
        map.showLearned(graph: graph, subjects: subjects, mistakes: mistakes, lesson: lesson)
    }

    private func subtitle(_ total: Int, _ review: Int) -> String {
        if total == 0 { return tr("还没有学过的知识点", "No knowledge points yet") }
        var s = tr("\(total) 个知识点 · \(subjects.count) 个学科",
                   "\(total) knowledge points · \(subjects.count) subjects")
        if review > 0 { s += tr(" · \(review) 个待回看", " · \(review) to review") }
        return s
    }

    /// 标题下、画布上的横向分类菜单：第一个「全部」，之后每个学科一项。
    private var categoryMenu: some View {
        HStack(spacing: 6) {
            chip(tr("全部", "All"), idx: nil)
            ForEach(Array(subjects.enumerated()), id: \.offset) { i, s in
                chip(s, idx: i)
            }
        }
    }

    private func chip(_ title: String, idx: Int?) -> some View {
        let on = map.focusSubject == idx
        return Button {
            map.focusSubject = idx
        } label: {
            Text(title)
                .font(.system(size: 12, weight: on ? .bold : .medium))
                .foregroundStyle(on ? Palette.accent : Palette.textSecondary)
                .lineLimit(1)
                .padding(.horizontal, 12).padding(.vertical, 4)
                .background(on ? Palette.accentSoft : Palette.surface, in: .capsule)
                .overlay(Capsule().strokeBorder(on ? Palette.accent : Palette.border))
        }
        .buttonStyle(.plain)
        .help(title)
    }
}
