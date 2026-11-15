//
//  DeskPet.swift
//  Echo — 桌面宠物（经典表情包猫 + 真实声纹条）
//
//  表情包猫跟着课堂状态变表情，旁边声纹条跟着老师声音真实起伏；
//  头顶气泡报「老师在讲 X」，找到断点时提醒你点它。
//
//  交互：
//    单击        打开 / 收起 Echo 面板
//    双击        圈一下问 AI
//    拖动        挪位置
//    鼠标来回蹭  摸摸它（会冒爱心）
//    右键        圈一下问 AI / 跟上了 / 有点懵 / 我掉队了 / 设置 / 隐藏桌宠
//

import SwiftUI
import AppKit

enum PetMood {
    case idle, listening, thinking, alert, ok, fixed, warn, lost, love, done

    var face: String {
        switch self {
        case .idle: "face_smug"
        case .listening: "face_stare"
        case .thinking: "face_key"
        case .alert: "face_shock"
        case .ok, .fixed, .love, .done: "face_happy"
        case .warn: "face_confused"
        case .lost: "face_cry"
        }
    }
}

private let idleTips = [tr("听不懂就圈一下，我帮你看 👀", "Don't get it? Circle it and I'll take a look 👀"),
                        tr("跟得上吗？跟上了就点我一下", "Keeping up? Tap me if you are"),
                        tr("掉队了别硬撑，右键我", "Fell behind? Don't tough it out — right-click me"),
                        tr("我一直在听，放心听课", "I'm always listening — just focus on class"),
                        tr("双击我，圈出看不懂的地方", "Double-click me to circle what you don't get")]

@Observable
final class PetModel {
    var visible = true
    private(set) var baseMood: PetMood = .idle
    private(set) var tempMood: PetMood?
    private(set) var bubble = ""
    private(set) var badge = false
    private(set) var jumpAt = Date.distantPast
    private(set) var shakeAt = Date.distantPast
    private(set) var hearts: [(x: CGFloat, y: CGFloat, born: Date)] = []
    private(set) var busy = false
    /// 今天该回响的知识点数（角标 + 主动提醒）
    private(set) var dueCount = 0
    private var dueAnnounced = false

    // ===== 侧边收起（360 加速球式吸附）=====
    enum DockSide { case left, right }
    private(set) var docked = false
    private(set) var dockSide: DockSide = .right
    private(set) var hoverExpanded = false
    private var collapseTask: Task<Void, Never>?

    static let deskW: CGFloat = 176     // 桌面态尺寸
    static let deskH: CGFloat = 172
    static let dockW: CGFloat = 48      // 收起后的球宽
    static let dockH: CGFloat = 112     // 收起后的高度（桌面态也用它做基准）
    static let expandedW: CGFloat = 230 // 悬停展开的浮出宽度
    static let dockMargin: CGFloat = 40 // 距屏幕边缘 40pt 内就吸附

    var petSize: CGSize {
        guard docked else { return CGSize(width: Self.deskW, height: Self.deskH) }
        return CGSize(width: hoverExpanded ? Self.expandedW : Self.dockW, height: Self.dockH)
    }

    func dock(_ side: DockSide) {
        docked = true
        dockSide = side
        hoverExpanded = false
        badge = false
    }

    func undock() {
        docked = false
        hoverExpanded = false
        collapseTask?.cancel()
    }

    /// 鼠标进出：进去立刻展开，出来 0.3 秒后收回
    func setHover(_ inside: Bool) {
        guard docked else { return }
        collapseTask?.cancel()
        if inside {
            hoverExpanded = true
        } else {
            collapseTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(0.3))
                guard !Task.isCancelled else { return }
                self?.hoverExpanded = false
            }
        }
    }

    private var bubbleTask: Task<Void, Never>?
    private var moodTask: Task<Void, Never>?
    private var topicName = ""
    private var listening = true
    private var lastInteract = Date()
    private var bubbleUntil = Date.distantPast

    var mood: PetMood { tempMood ?? baseMood }

    init() {
        say(tr("我是 Echo，陪你听课～", "I'm Echo, here to study with you."), ms: 4000, mood: .ok)
        Task { [weak self] in   // 75 秒没动静，冒一句提示
            while true {
                try? await Task.sleep(for: .seconds(75))
                self?.idleTip()
            }
        }
    }

    func say(_ text: String, ms: Int = 4000, mood: PetMood? = nil, holdMs: Int? = nil) {
        bubble = text
        bubbleUntil = Date().addingTimeInterval(Double(ms) / 1000)
        bubbleTask?.cancel()
        bubbleTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(ms))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.3)) { self?.bubble = "" }
        }
        if let mood { setMood(mood, holdMs: holdMs ?? ms) }
    }

    func setMood(_ m: PetMood, holdMs: Int = 0) {
        if holdMs > 0 {
            tempMood = m
            moodTask?.cancel()
            moodTask = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(holdMs))
                guard !Task.isCancelled else { return }
                self?.tempMood = nil
            }
        } else {
            baseMood = m
        }
        if [.alert, .fixed, .ok, .love, .done].contains(m) { jumpAt = Date() }
        if [.lost, .alert].contains(m) { shakeAt = Date() }
    }

    func clearBadge() { badge = false }

    /// 开机问候：带上学生的名字
    func greet() {
        let who = ProfileStore.displayName()
        if who.isEmpty || who == tr("同学", "there") {
            say(tr("我是Echo，伴你学习！", "I'm Echo, here to study with you."), ms: 5000, mood: .ok)
        } else {
            say(tr("我是Echo，伴你学习，你好\(who)！", "I'm Echo, here to study with you. Hi \(who)!"), ms: 5000, mood: .ok)
        }
    }

    /// 今天该回响的数量变化（每 15 秒由外面喂）
    func setDue(_ n: Int, panelVisible: Bool) {
        let was = dueCount
        dueCount = n
        if n > 0 && !dueAnnounced {
            dueAnnounced = true
            say(tr("今天有 \(n) 个知识点要确认，点我", "\(n) concepts to review today — click me"),
                ms: 7000, mood: .alert, holdMs: 3000)
        } else if was > 0 && n == 0 && panelVisible {
            say(tr("今天该回响的都过了一遍，记下了", "That's today's review done — nice work"),
                ms: 6000, mood: .done, holdMs: 3000)
        }
    }

    /// 打开面板时若有到期的，直接落到主页（顶部就是「今天该回响」）
    var hasDue: Bool { dueCount > 0 }

    func touched() { lastInteract = Date() }

    // MARK: 后端事件

    func status(_ st: EchoStatus) {
        listening = st == .listening
        busy = st == .analyzing || st == .summarizing || st == .loadingASR
        switch st {
        case .analyzing:
            setMood(.thinking)
            say(tr("我回看一下刚才的课…", "Let me review the lesson so far…"), ms: 15000)
        case .summarizing:
            setMood(.thinking)
            say(tr("在整理这节课的回响…", "Putting together this lesson's echo…"), ms: 15000)
        case .loadingASR:
            setMood(.thinking)
            say(tr("正在加载耳朵（语音识别）…", "Loading my ears (speech recognition)…"), ms: 8000)
        case .done:
            setMood(.done)
        default:
            setMood(.listening)
        }
    }

    func topic(_ t: String, listening: Bool) {
        guard !t.isEmpty, t != topicName else { return }
        topicName = t
        if listening { say(tr("老师在讲：\(t)", "Now teaching: \(t)"), ms: 5000) }
    }

    func foundBreakpoint(panelHidden: Bool) {
        badge = panelHidden
        say(panelHidden ? tr("找到啦！点我看补课", "Found it! Click me for a quick catch-up") : tr("找到你掉队的地方了", "I found where you fell behind"), ms: 9000, mood: .alert, holdMs: 4000)
    }

    func echoReady(panelHidden: Bool) {
        badge = panelHidden
        say(tr("这节课的回响好了，点我看", "This lesson's echo is ready — click me"), ms: 9000, mood: .done, holdMs: 4000)
    }

    func feedbackSaid(_ kind: FeedbackKind) {
        touched()
        switch kind {
        case .ok: say(tr("收到，继续加油！", "Got it, keep it up!"), ms: 2500, mood: .ok)
        case .warn: say(tr("记下了，有点懵就圈出来问我", "Noted — circle anything confusing and ask me"), ms: 2500, mood: .warn)
        case .lost: setMood(.lost, holdMs: 2500)
        }
    }

    /// 摸摸：冒爱心
    func petted(at p: CGPoint) {
        hearts.append((p.x, p.y - 10, Date()))
        hearts.removeAll { Date().timeIntervalSince($0.born) > 1.4 }
        if mood != .love {
            say([tr("呼噜呼噜～", "Purr purr~"), tr("喵～ 再摸摸", "Meow~ pet me again"), tr("好舒服，继续听课吧", "So cozy — let's keep listening")].randomElement()!, ms: 2000, mood: .love, holdMs: 2000)
        }
    }

    private func idleTip() {
        guard Date().timeIntervalSince(lastInteract) >= 60, listening, Date() >= bubbleUntil else { return }
        say((idleTips + (topicName.isEmpty ? [] : [tr("老师在讲：\(topicName)", "Now teaching: \(topicName)")])).randomElement()!, ms: 4500)
    }
}

// MARK: - 视图

struct DeskPetView: View {
    var model: AppModel
    /// 拖动由窗口层按全局鼠标位置移动（窗口跟着动时，SwiftUI 的 translation 会抖）
    var onDrag: () -> Void
    var onDragEnd: () -> Void

    static let size = CGSize(width: 176, height: 172)
    private let catSize: CGFloat = 88
    private let barCount = 9
    @State private var petX: CGFloat?
    @State private var petDist: CGFloat = 0
    @State private var dragging = false
    @State private var env = 0.0

    private var pet: PetModel { model.pet }

    // 点击 / 拖动挂在外层容器上，收起小球和桌面态共用：
    // 拖动一开始小球就会换成桌面猫，手势要是挂在子视图上会跟着被销毁，就拖不出来了。
    var body: some View {
        ZStack {
            if pet.docked {
                dockedBody
            } else {
                deskBody
            }
        }
        .contentShape(.rect)
        .gesture(TapGesture(count: 2).onEnded {
            pet.touched()
            model.onCircleAsk()
        }.exclusively(before: TapGesture().onEnded {
            pet.touched()
            pet.clearBadge()
            model.togglePanel()
        }))
        .simultaneousGesture(DragGesture(minimumDistance: 5, coordinateSpace: .global)
            .onChanged { _ in
                dragging = true
                onDrag()
            }
            .onEnded { _ in
                dragging = false
                onDragEnd()
            })
    }

    // MARK: 侧边收起（小球 / 悬停展开的浮出条）
    //
    // 收起：上面竖排声纹条 + 下面猫脸 + 右上角待复习角标（48×112）
    // 悬停展开：竖排声纹条（贴外缘）+ 猫脸 + 「ECHO · 今天该回响」+ 正文（230×112）
    @ViewBuilder private var dockedBody: some View {
        let left = pet.dockSide == .left
        let expanded = pet.hoverExpanded
        ZStack(alignment: .topTrailing) {
            RoundedRectangle(cornerRadius: expanded ? 18 : 24, style: .continuous)
                .fill(Palette.windowBG)
                .overlay(RoundedRectangle(cornerRadius: expanded ? 18 : 24, style: .continuous)
                    .strokeBorder(Palette.borderStrong))
            if expanded {
                HStack(spacing: 0) {
                    if left { waveColumn; catFace(58); dockText }
                    else { dockText; catFace(58); waveColumn }
                }
            } else {
                VStack(spacing: 0) {
                    waveColumn.padding(.top, 8)
                    Spacer(minLength: 0)
                    catFace(34).padding(.bottom, 6)
                }
                .frame(maxWidth: .infinity)
            }
            // 角标压在卡片内（窗口正好是卡片大小，往外偏移会被裁掉）
            if pet.dueCount > 0 || pet.badge { badgeView.padding(3) }
        }
        .frame(width: pet.petSize.width, height: pet.petSize.height)
        .contentShape(.rect)
        .onHover { pet.setHover($0) }
        .help(tr("Echo · 单击打开面板 · 双击圈一下问 AI · 拖离边缘展开",
                 "Echo · click to open panel · double-click to circle-ask AI · drag away to expand"))
    }

    /// 竖排声纹条（贴屏幕外缘那一侧）
    private var waveColumn: some View {
        VStack(spacing: 3) {
            ForEach(0..<9, id: \.self) { i in
                let w = 1 - abs(Double(i) - 4) / 4     // 中间最亮，两端淡一点
                Capsule()
                    .fill(Palette.accent.opacity(0.45 + 0.55 * w))
                    .frame(width: 10, height: 4)
            }
        }
        .frame(width: 22)
        .padding(.horizontal, pet.hoverExpanded ? 8 : 0)
    }

    private func catFace(_ size: CGFloat) -> some View {
        Image(pet.mood.face)
            .resizable().interpolation(.high).aspectRatio(contentMode: .fit)
            .frame(width: size, height: size)
            .frame(maxHeight: .infinity, alignment: pet.hoverExpanded ? .top : .bottom)
            .padding(.top, pet.hoverExpanded ? 24 : 0)
    }

    /// 展开时的文案：标题行 + 正文（与 Python 的挂边面板一致）
    private var dockText: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(dockHeader).font(.system(size: 11)).tracking(1)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1).minimumScaleFactor(0.7)
            Text(dockBody).font(.system(size: 16))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
    }

    private var dockHeader: String {
        let topic = model.engine.current?.topic ?? ""
        if pet.dueCount > 0 && topic.isEmpty {
            return tr("ECHO · 今天该回响", "ECHO · REVIEW TODAY")
        }
        return tr("ECHO · 课堂动态", "ECHO · LESSON UPDATE")
    }

    private var dockBody: String {
        if !pet.bubble.isEmpty { return pet.bubble }
        if let t = model.engine.current?.topic, !t.isEmpty { return tr("老师在讲：\(t)", "Now teaching: \(t)") }
        if pet.dueCount > 0 { return tr("\(pet.dueCount) 个知识点要确认，点我", "\(pet.dueCount) concept(s) to confirm — click me") }
        return tr("我在听，随时问我", "I'm listening — ask anytime")
    }

    @ViewBuilder private var badgeView: some View {
        ZStack {
            Circle().fill(Palette.accent).overlay(Circle().stroke(Palette.windowBG, lineWidth: 2))
            Text(pet.dueCount > 0 ? (pet.dueCount >= 10 ? "9+" : "\(pet.dueCount)") : "!")
                .font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
        }
        .frame(width: 24, height: 24)
    }

    // MARK: 桌面态
    private var deskBody: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { ctx in
            let now = ctx.date
            ZStack(alignment: .bottomLeading) {
                cat(now)
                    .frame(width: catSize, height: catSize)
                    .offset(x: 4, y: -6)
                voiceBars(now)
                    .frame(width: 70, height: catSize)
                    .offset(x: 4 + catSize + 10, y: -6)
                hearts(now)
                if !pet.bubble.isEmpty {
                    bubble
                        .frame(width: Self.size.width - 16)
                        .offset(x: 8, y: -(catSize + 18))
                        .transition(.opacity)
                }
            }
            .frame(width: Self.size.width, height: Self.size.height, alignment: .bottomLeading)
        }
        .frame(width: Self.size.width, height: Self.size.height)
        .contentShape(.rect)
        .help(tr("Echo · 单击打开面板 · 双击圈一下问 AI · 右键更多", "Echo · click to open panel · double-click to circle & ask AI · right-click for more"))
        .onContinuousHover { phase in
            guard case .active(let p) = phase, !dragging,
                  CGRect(x: 4, y: Self.size.height - catSize - 6, width: catSize, height: catSize).contains(p)
            else { petX = nil; return }
            if let x = petX { petDist += abs(p.x - x) }
            petX = p.x
            if petDist > 260 {
                petDist = 0
                pet.petted(at: p)
            }
        }
        .contextMenu { menu }
        .onChange(of: model.engine.level) { _, lv in env += (lv - env) * (lv > env ? 0.6 : 0.18) }
    }

    @ViewBuilder private var menu: some View {
        Button(tr("✏️  圈一下问 AI    ⌃⌥Q", "✏️  Circle to ask AI    ⌃⌥Q"), action: model.onCircleAsk)
        Divider()
        Button(tr("✓  跟上了", "✓  Kept up")) { model.feedback(.ok); pet.feedbackSaid(.ok) }
        Button(tr("?  有点懵", "?  A bit lost")) { model.feedback(.warn); pet.feedbackSaid(.warn) }
        Button(tr("!  我掉队了", "!  I'm lost")) { model.lost(); pet.feedbackSaid(.lost) }
        Divider()
        Button(model.panelVisible ? tr("收起 Echo 面板", "Collapse Echo panel") : tr("打开 Echo 面板", "Open Echo panel"), action: model.togglePanel)
        Button(tr("设置…", "Settings…"), action: model.onOpenSettings)
        Button(tr("先藏起来（菜单栏里能叫回）", "Hide for now (call me back from the menu bar)")) { pet.visible = false }
    }

    private func cat(_ now: Date) -> some View {
        let t = now.timeIntervalSinceReferenceDate
        let breathe = 1 + 0.02 * sin(t * 2.4)
        let jt = now.timeIntervalSince(pet.jumpAt)
        let dy = jt < 0.5 ? -14 * sin(.pi * jt / 0.5) : 0
        let st = now.timeIntervalSince(pet.shakeAt)
        let dx = st < 0.45 ? 4 * sin(st * 60) * (1 - st / 0.45) : 0
        return ZStack(alignment: .bottom) {
            Ellipse().fill(.black.opacity(0.18)).frame(width: 64, height: 8).offset(y: 4)
            Image(pet.mood.face)
                .resizable()
                .interpolation(.high)
                .aspectRatio(contentMode: .fit)
                .scaleEffect(x: 1, y: breathe, anchor: .bottom)
                .offset(x: dx, y: dy)
            if pet.busy && pet.bubble.isEmpty {   // 思考中：头顶三个点
                HStack(spacing: 6) {
                    ForEach(0..<3, id: \.self) { i in
                        Circle().fill(Palette.accent.opacity(0.35 + 0.65 * max(0, sin(t * 4 - Double(i) * 0.8))))
                            .frame(width: 8, height: 8)
                    }
                }
                .frame(maxHeight: .infinity, alignment: .top)
            }
            if pet.badge || pet.dueCount > 0 {
                ZStack {
                    Circle().fill(Palette.accent).overlay(Circle().stroke(.white, lineWidth: 2))
                    Text(pet.dueCount > 0 ? (pet.dueCount >= 10 ? "9+" : "\(pet.dueCount)") : "!")
                        .font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                }
                .frame(width: 20, height: 20)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .offset(x: 4, y: 6)
            }
        }
    }

    /// 真实声纹条：柱高随音频响度起伏，中间高两边低
    private func voiceBars(_ now: Date) -> some View {
        let phase = now.timeIntervalSinceReferenceDate * 15
        return Canvas { g, size in
            let gap: CGFloat = 2.5
            let bw = (size.width - gap * CGFloat(barCount - 1)) / CGFloat(barCount)
            for i in 0..<barCount {
                let x = Double(i) / Double(barCount - 1)
                let center = 1 - abs(x - 0.5) * 2
                let v = max(0.05, min(1, env * (0.45 + 0.55 * center) * (0.85 + 0.15 * sin(phase + x * 5))))
                let h = max(3, size.height * v)
                let r = CGRect(x: CGFloat(i) * (bw + gap), y: size.height / 2 - h / 2, width: bw, height: h)
                g.fill(Path(roundedRect: r, cornerRadius: bw / 2), with: .color(Palette.accent.opacity(0.35 + 0.55 * center)))
            }
        }
    }

    private func hearts(_ now: Date) -> some View {
        ForEach(Array(pet.hearts.enumerated()), id: \.offset) { _, h in
            let k = now.timeIntervalSince(h.born) / 1.4
            if k < 1 {
                Image(systemName: "heart.fill")
                    .font(.system(size: 14 + 6 * k))
                    .foregroundStyle(Color(red: 1, green: 0.36, blue: 0.47).opacity(1 - k))
                    .position(x: h.x + 8 * sin(k * 6), y: h.y - 50 * k)
            }
        }
        .frame(width: Self.size.width, height: Self.size.height)
    }

    private var bubble: some View {
        Text(pet.bubble)
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(Palette.textPrimary)
            .multilineTextAlignment(.center)
            .lineLimit(3)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .glassEffect(.regular, in: .rect(cornerRadius: 12))
            .frame(maxWidth: .infinity)
    }
}
