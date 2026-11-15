//
//  RootView.swift
//  Echo — 悬浮主窗口（液态玻璃卡片）。页面说明见 AppModel.swift
//

import SwiftUI

private let waitHint = tr("播放网课后，Echo 会自动开始听", "Echo starts listening on its own once your class plays")

struct RootView: View {
    var model: AppModel
    @State private var contentHeight: CGFloat = 300
    @State private var askInput = ""
    @State private var askMicPlaceholder: String?
    /// 自检截图用：ImageRenderer 画不出 ScrollView 里的内容
    var noScroll = false

    private var engine: EchoEngine { model.engine }
    private var page: Page { model.page }

    var body: some View {
        let maxH = (NSScreen.main?.visibleFrame.height ?? 800) - 120
        VStack(alignment: .leading, spacing: Spacing.md) {
            if page != .mini { header }
            if noScroll {
                pageBody.frame(width: page.width, alignment: .leading)
            } else {
                // 内容比屏幕还高时才滚动
                ScrollView(.vertical) {
                    pageBody
                        .frame(width: page.width, alignment: .leading)
                        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { contentHeight = $0 }
                }
                .scrollIndicators(contentHeight > maxH ? .automatic : .never)
                .scrollBounceBehavior(.basedOnSize)
                .frame(width: page.width, height: min(contentHeight, maxH))
            }
        }
        .padding(.horizontal, page == .mini ? Spacing.md : Spacing.lg + 2)
        .padding(.top, page == .mini ? Spacing.sm : Spacing.md + 2)
        .padding(.bottom, page == .mini ? Spacing.sm : Spacing.lg + 2)
        .glassEffect(.regular, in: .rect(cornerRadius: Radius.window))
        .contentShape(.rect(cornerRadius: Radius.window))
        .gesture(DragGesture(minimumDistance: 3)   // 整张卡片空白处都能拖
            .onChanged { _ in model.onDragPanel() }
            .onEnded { _ in model.onDragPanelEnd() })
        .fixedSize()
        .animation(.snappy(duration: 0.25), value: page)
    }

    @ViewBuilder private var pageBody: some View {
        switch page {
        case .home: HomePage(model: model)
        case .listen: listenPage
        case .mini: miniPage
        case .brk: breakPage
        case .lesson: lessonPage
        case .echo: echoPage
        case .review: ReviewPage(model: model)
        case .practice: PracticePage(model: model)
        case .detail:
            if let d = model.detail {
                DetailPage(detail: d, onMindmap: model.detailMindmap, onQuiz: model.detailQuiz, onHome: model.showHome)
            }
        case .mindmap:
            MindmapPage(model: model, map: model.mindmap)
        case .courses:
            CoursesPage(rows: model.courses, onOpen: model.showDetail,
                        onRename: model.renameLesson, onDelete: model.deleteLessons)
        case .recall:
            RecallPage(subtitle: model.recallSubtitle, messages: model.recallMessages,
                       loading: model.recallLoading, loadingText: model.recallLoadingText,
                       placeholder: model.recallPlaceholder, inputEnabled: model.recallInputEnabled,
                       showGrades: model.recallShowGrades, currentGrade: model.recallGrade,
                       onSend: model.recallSend, onGrade: model.recallGrade)
        case .profile:
            ProfilePage(profile: model.profile, avatar: model.avatarImage, stats: model.stats,
                        onPickAvatar: model.pickAvatar, onUseDefault: model.useDefaultAvatar,
                        onHome: model.showHome)
        case .ask:
            AskPage(messages: model.askMessages, loading: model.askLoading, onSend: model.askSend)
        case .learned:
            if let g = model.learnedGraph {
                LearnedPage(model: model, graph: g, subjects: g.subjects, mistakes: ReviewStore.load(),
                           lesson: model.learnedLesson)
            }
        case .weekly:
            WeeklyPage(skills: model.weeklySkills)
        }
    }

    // MARK: - 顶栏

    private var showsBack: Bool {
        [.brk, .lesson, .review, .practice, .detail, .mindmap, .courses, .recall, .profile, .ask, .learned, .weekly]
            .contains(page)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: Spacing.sm) {
                Button(action: model.openFromAvatar) {
                    CatAvatar(emotion: model.cat.emotion, size: 30)
                }
                .buttonStyle(.plain)
                .help(tr("点击打开听课界面", "Open the lesson panel"))
                Text("Echo").font(.system(size: 15, weight: .bold)).foregroundStyle(Palette.textPrimary)
                Spacer(minLength: 0)
                if showsBack {
                    Button(model.backTitle, action: model.back).buttonStyle(LinkButtonStyle())
                }
                // 上课期间锁死在课堂：只有「下课」能离开，主页按钮和头像都藏起来
                if page == .echo || (page == .listen && !engine.active) {
                    Button(tr("⌂ 主页", "⌂ Home"), action: model.showHome)
                        .buttonStyle(LinkButtonStyle()).help(tr("回到主页", "Back to home"))
                }
                if page == .listen {
                    Button(tr("下课", "End class"), action: model.endLesson)
                        .buttonStyle(LinkButtonStyle())
                        .help(tr("结束这节课，生成回响", "End this lesson and generate the review"))
                }
                // ⌄ = 折叠成迷你条；× = 收进菜单栏（退出在菜单栏里）
                Button { model.go(.mini) } label: { Image(systemName: "chevron.down") }
                    .buttonStyle(IconButtonStyle()).help(tr("折叠", "Collapse"))
                Button(action: model.hidePanel) { Image(systemName: "xmark") }
                    .buttonStyle(IconButtonStyle()).help(tr("收进菜单栏（⌃⌥E 唤回）", "Hide to the menu bar (⌃⌥E to bring back)"))
                // 右上角：学生自己的头像入口（上课时隐藏——离开课堂只能走「下课」）
                if !engine.active {
                    AvatarView(image: model.avatarImage, size: 32, onClick: model.showProfile)
                        .help(tr("我的资料", "My profile"))
                }
            }
            HStack(spacing: 6) { statusView }
            if let toast = model.toast {
                Text(toast)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.onAccent)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(Palette.accent, in: .capsule)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.snappy(duration: 0.2), value: model.toast)
    }

    @ViewBuilder private var statusView: some View {
        let st = engine.status
        if model.showError {
            Circle().fill(Palette.accent).frame(width: 6, height: 6)
            Text(tr("网络或 AI 出错", "Network or AI error")).caption().help(engine.lastError ?? "")
        } else if let thinking = engine.thinking {   // AI 实时思考
            PulseDots(color: Palette.accent)
            Text(thinking).caption().lineLimit(1)
        } else if st.isBusy {
            PulseDots(color: Palette.accent)
            Text(st.label).caption()
        } else {
            Circle().fill(st == .listening ? Palette.okFG : Palette.textDisabled).frame(width: 6, height: 6)
            Text(st.label).caption()
        }
        if engine.offline {
            Text(tr("离线", "Offline"))
                .font(.system(size: 11))
                .foregroundStyle(Palette.textSecondary)
                .padding(.horizontal, 6)
                .overlay(Capsule().stroke(Palette.borderStrong))
                .help(tr("菜单栏 → 离线模式 可切回在线", "Menu bar → Offline mode to go back online"))
        }
        Spacer(minLength: 0)
    }

    // MARK: - listen 听课卡片

    private var listenPage: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: Spacing.sm) {
                WaveOrb(listening: engine.status == .listening, level: engine.level).frame(width: 48, height: 48)
                Text(tr("老师正在讲", "Teacher is speaking")).caption()
                Spacer()
                Text(engine.transcripts.last?.tc ?? "00:00")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(Palette.textSecondary)
            }
            if model.checkinPreparing || model.checkinData != nil {
                CheckinCardView(data: model.checkinData,
                                preparing: model.checkinPreparing,
                                feedback: model.checkinFeedback,
                                onAnswer: model.answerCheckin,
                                onClose: model.skipCheckin)
            }
            Text(engine.current?.topic ?? tr("等待老师开讲…", "Waiting for the teacher to start…"))
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(Palette.textPrimary)
                .wrap()
            if model.needsScreenPermission {
                permissionCard
            } else if !summaryText.isEmpty {
                Text(summaryText).font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            }
            if engine.totalSeconds > 0 {
                ProgressView(value: min(1, (engine.transcripts.last?.t ?? 0) / engine.totalSeconds))
                    .tint(Palette.textSecondary)
                    .controlSize(.mini)
            }
            if let line = engine.transcripts.last {
                // 实时字幕：左侧细线，安静地滚动
                Text(line.text.count <= 56 ? line.text : String(line.text.prefix(54)) + "…")
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.textSecondary)
                    .wrap()
                    .padding(.vertical, 2)
                    .padding(.leading, 10)
                    .overlay(alignment: .leading) { Rectangle().fill(Palette.borderStrong).frame(width: 2) }
            }

            HStack(spacing: Spacing.sm) {
                Button(tr("我掉队了", "I fell behind"), action: model.lost)
                    .buttonStyle(AccentButtonStyle(minHeight: 46))
                    .help(tr("Echo 回看最近几分钟，找到你从哪一步开始没听懂（⌃⌥L）",
                             "Echo rewinds the last few minutes and finds where you lost the thread (⌃⌥L)"))
                Button(tr("答题", "Ask"), action: model.openAsk)
                    .buttonStyle(QuietButtonStyle(minHeight: 46))
                    .frame(width: 92)
                    .help(tr("随时问 Echo，它带着这节课听到的内容回答；课后回来还能接着问",
                             "Ask Echo anything — answered with this lesson's context, and you can pick it up again after class"))
            }
            .padding(.top, Spacing.sm)
            HStack(spacing: Spacing.sm) {
                feedbackButton(.ok, tr("✓  跟上了", "✓  Kept up"))
                feedbackButton(.warn, tr("?  有点懵", "?  A bit lost"))
                Button(tr("考考我", "Quiz me"), action: model.askCheckinNow)
                    .buttonStyle(QuietButtonStyle())
                    .help(tr("让 Echo 就刚才讲的内容出一道题", "Have Echo quiz you on what was just taught"))
            }
            if engine.breakpoint != nil && !model.bpFailed {
                Button(tr("继续查看刚才的补课 ↗", "Back to the catch-up ↗")) { model.go(.lesson) }
                    .buttonStyle(LinkButtonStyle())
            }
        }
    }

    private var summaryText: String {
        if let cur = engine.current { return cur.summary }
        switch engine.status {
        case .loadingASR:
            // 权限被拒时后端停在 loadingASR 并给出 lastError，常驻显示
            if let err = engine.lastError, !err.isEmpty { return err }
            return tr("首次加载约 10 秒，之后会自动开始听", "First load takes about 10 seconds, then Echo starts listening")
        case _ where !engine.transcripts.isEmpty:
            return tr("正在听，马上识别知识点…", "Listening — concepts show up in a moment…")
        default:
            return waitHint
        }
    }

    /// 没有「屏幕与系统录音」权限：引导去系统设置，或者改用麦克风
    private var permissionCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(tr("需要「屏幕与系统录音」权限", "Screen & System Audio Recording permission needed"))
                .font(.system(size: 13, weight: .semibold)).foregroundStyle(Palette.accent)
            Text(tr("Echo 要抓电脑正在播放的网课声音。打开系统设置，把 Echo 的开关打开，然后点「开始新的一节课」。",
                    "Echo captures the audio your Mac is playing. Open System Settings, switch Echo on, then start a new lesson."))
                .caption().wrap()
            HStack(spacing: Spacing.sm) {
                Button(tr("打开系统设置", "Open System Settings"), action: model.openScreenPrivacySettings)
                    .buttonStyle(QuietButtonStyle(expand: false))
                Button(tr("改用麦克风", "Use the microphone")) { model.setSource(.mic) }
                    .buttonStyle(QuietButtonStyle(expand: false))
                Button(tr("重试", "Retry"), action: model.restart).buttonStyle(LinkButtonStyle())
            }
        }
        .card(border: Palette.accentBorder, padding: Spacing.md)
    }

    private func feedbackButton(_ kind: FeedbackKind, _ title: String) -> some View {
        Button(model.acked == kind ? tr("已记录", "Noted") : title) { model.feedback(kind) }
            .buttonStyle(QuietButtonStyle())
            .disabled(model.acked == kind)
    }

    // MARK: - mini 折叠条

    private var miniPage: some View {
        HStack(spacing: Spacing.sm) {
            Button(action: model.openFromAvatar) { CatAvatar(emotion: model.cat.emotion, size: 28) }
                .buttonStyle(.plain).help(tr("点击展开听课界面", "Expand the lesson panel"))
            VStack(alignment: .leading, spacing: 0) {
                Text(tr("老师正在讲", "Teacher is speaking"))
                    .font(.system(size: 11)).foregroundStyle(Palette.textSecondary)
                Text(engine.current?.topic ?? tr("等待老师开讲…", "Waiting for the teacher to start…"))
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            Button(tr("掉队了", "Behind"), action: model.lost)
                .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 30))
                .frame(width: 72)
            Button { model.go(.listen) } label: { Image(systemName: "chevron.up") }
                .buttonStyle(IconButtonStyle()).help(tr("展开", "Expand"))
            WaveOrb(listening: engine.status == .listening, level: engine.level).frame(width: 36, height: 36)
        }
    }

    // MARK: - break 断点页

    private var breakPage: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            if let bp = engine.breakpoint {
                Text(tr("你可能从这里开始掉队", "You may have fallen behind here")).pageTitle()
                BreakPath(concepts: engine.breakpointTimeline, breakpointTC: bp.breakpointTC, note: bp.note)

                // 你缺的这一步：全页最大、最醒目
                VStack(alignment: .leading, spacing: 6) {
                    Text(tr("你缺的这一步", "The step you're missing"))
                        .font(.system(size: 12, weight: .bold)).foregroundStyle(Palette.accent)
                    Text(bp.missing.isEmpty ? bp.concept : bp.missing)
                        .font(.system(size: 19, weight: .bold)).foregroundStyle(Palette.textPrimary).wrap()
                    if !bp.reason.isEmpty { Text(bp.reason).caption().wrap() }
                }
                .card(border: Palette.accentBorder)
                .overlay(alignment: .leading) {
                    UnevenRoundedRectangle(topLeadingRadius: Radius.md, bottomLeadingRadius: Radius.md)
                        .fill(Palette.accent).frame(width: 4)
                }

                askBox
            } else {
                Text(tr("Echo 正在找你掉队的地方", "Echo is looking for where you fell behind")).pageTitle()
                LoadingCard(text: model.bpFailed
                            ? tr("这次没分析出来，回到课堂再点一次「我掉队了」试试",
                                 "Couldn't work it out this time — back to class, then tap \"I fell behind\" again")
                            : tr("正在回看最近几分钟的课…", "Looking back over the last few minutes…"),
                            busy: !model.bpFailed)
            }
            HStack(spacing: Spacing.sm) {
                Button(tr("30 秒补上这一步", "Fix this step in 30s"), action: model.goLesson)
                    .buttonStyle(AccentButtonStyle())
                    .disabled(engine.breakpoint == nil)
                    .layoutPriority(3)
                Button(tr("我自己看看", "I'll look myself"), action: model.selfLook)
                    .buttonStyle(QuietButtonStyle(minHeight: 44))
                    .help(tr("不用 AI 讲，收起来回到课堂", "Skip the AI explanation and head back to class"))
                    .frame(width: 140)
            }
        }
    }

    /// 追问：学生针对自己的困惑继续问，带上课堂上下文问 DeepSeek
    private var askBox: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(tr("还有哪里不懂？直接问我", "Still unclear? Just ask me")).caption()
            HStack(spacing: Spacing.sm) {
                TextField(askMicPlaceholder ?? tr("比如：为什么分母是 P(B)？", "e.g. why is the denominator P(B)?"), text: $askInput)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Palette.surface.opacity(0.7), in: .rect(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.border))
                    .onSubmit(sendAsk)
                MicButton(overridePlaceholder: $askMicPlaceholder) { askInput = $0 }
                Button(tr("问 AI", "Ask"), action: sendAsk)
                    .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 32))
                    .frame(width: 64)
                    .disabled(model.askBusy)
            }
            if model.askShown {
                ScrollViewReader { proxy in
                    ScrollView {
                        Group {
                            if let err = model.askError {
                                Text(err).foregroundStyle(Palette.danger)
                            } else if model.askAnswer.isEmpty {
                                Text(tr("Echo 正在想…", "Echo is thinking…")).foregroundStyle(Palette.textSecondary)
                            } else {
                                Text(plain(model.askAnswer)).foregroundStyle(Palette.textPrimary).textSelection(.enabled)
                            }
                        }
                        .font(.system(size: 13))
                        .lineSpacing(3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                        .id("end")
                    }
                    .frame(height: 150)
                    .background(Palette.codeBG.opacity(0.7), in: .rect(cornerRadius: 8))
                    .onChange(of: model.askAnswer) { proxy.scrollTo("end", anchor: .bottom) }
                }
            }
        }
        .card(padding: Spacing.md)
    }

    private func sendAsk() {
        model.askBreakpoint(askInput)
        askInput = ""
    }

    // MARK: - lesson 补课三段式

    @ViewBuilder private var lessonPage: some View {
        if let bp = engine.breakpoint {
            let parts = lessonParts(bp)
            VStack(alignment: .leading, spacing: Spacing.md) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(tr("补上这一步 · 约 30 秒", "Fix this step · about 30 seconds")).caption()
                    Text(bp.missing.isEmpty ? bp.concept : bp.missing).pageTitle().wrap()
                }
                VStack(alignment: .leading, spacing: 0) {
                    LessonStep(kind: .known, text: parts.known)
                    LessonStep(kind: .step, text: parts.step)
                    LessonStep(kind: .now, text: parts.now)
                }
                Button(tr("✓  补上了，回到课堂", "✓  Got it — back to class"), action: model.markFixed)
                    .buttonStyle(SolidButtonStyle())
                    .padding(.top, Spacing.xs)
            }
        }
    }

    /// 三段式：优先用后端的 known / step / now，缺了就从时间轴和 micro_lesson 拼出来
    private func lessonParts(_ bp: BreakPoint) -> (known: String, step: String, now: String) {
        let cs = engine.breakpointTimeline
        let idx = cs.firstIndex { $0.timecode == bp.breakpointTC }
        let prev = idx.flatMap { $0 > 0 ? cs[$0 - 1] : nil }
        let now = cs.last
        let known = !bp.known.isEmpty ? bp.known
            : prev.map { $0.summary.isEmpty ? $0.topic : "\($0.topic)：\($0.summary)" }
              ?? tr("前面的定义和例子", "the earlier definitions and examples")
        let step = !bp.step.isEmpty ? bp.step : bp.microLesson
        let nowText = !bp.now.isEmpty ? bp.now
            : now.map { tr("老师现在讲的「\($0.topic)」就是用这一步接着往下推的。",
                           "What the teacher is on now (\"\($0.topic)\") builds straight on this step.") }
              ?? tr("回到课堂，继续往下听。", "Back to class — keep listening.")
        return (known, step, nowText)
    }

    // MARK: - echo 回响

    private var echoPage: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("今天的课", "Today's lesson")).pageTitle()
                if let report = engine.report {
                    let rows = model.echoRows(report)
                    let n = { (m: SkillMark) in rows.filter { $0.mark == m }.count }
                    Text(tr("✓ 跟上了 \(n(.ok)) · ? 有点懵 \(n(.unsure)) · ! 掉队了 \(n(.lost))",
                            "✓ Kept up \(n(.ok)) · ? A bit lost \(n(.unsure)) · ! Fell behind \(n(.lost))")).caption()
                }
            }
            if let report = engine.report {
                VStack(spacing: 0) {
                    ForEach(Array(model.echoRows(report).enumerated()), id: \.offset) { _, r in
                        SkillRow(name: r.name, mastery: r.mastery, mark: r.mark, note: r.note)
                    }
                }
                if ReviewChain.hasContent(chain: report.reviewChain, suggestion: report.suggestion) {
                    ReviewChain(chain: report.reviewChain, suggestion: report.suggestion)
                }
                overviewCard
                breakpointCard
            } else {
                LoadingCard(text: model.echoFailed
                            ? tr("回响生成失败，请检查网络后重试", "Couldn't build the review — check your connection and try again")
                            : tr("正在整理这节课…", "Putting this lesson together…"),
                            color: Palette.textSecondary, busy: !model.echoFailed)
            }
            HStack(spacing: Spacing.sm) {
                Button(tr("错题复习", "Review mistakes"), action: model.showReview)
                    .buttonStyle(QuietButtonStyle(expand: false))
                Button(tr("知识地图", "Knowledge map"), action: model.mindmapFromReport)
                    .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 30))
                    .disabled(engine.report == nil)
                    .frame(width: 110)
                Spacer()
                Button(tr("开始新的一节课", "Start a new lesson"), action: model.restart).buttonStyle(LinkButtonStyle())
            }
        }
    }

    /// 本节课概览：掉队次数 / 抽问正确率 / 掌握概览（对应 Python `_overview_card`）
    @ViewBuilder private var overviewCard: some View {
        let bps = engine.breakpoints
        let checkins = engine.checkins
        let rows = engine.report.map(model.echoRows) ?? []
        let ok = rows.filter { $0.mark == .ok }.count
        if !bps.isEmpty || !checkins.isEmpty || !rows.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                Text(tr("本节课概览", "Lesson at a glance"))
                    .font(.system(size: 12, weight: .bold)).foregroundStyle(Palette.accent)
                if !bps.isEmpty {
                    Text(tr("掉队 \(bps.count) 次", "Fell behind \(bps.count)×"))
                        .font(.system(size: 13)).foregroundStyle(Palette.textPrimary)
                }
                if !checkins.isEmpty {
                    let right = checkins.filter { $0.result == Quiz.right }.count
                    let pct = Int((Double(right) / Double(checkins.count) * 100).rounded())
                    Text(tr("抽问 \(checkins.count) 次 · 答对 \(right) 道 · 正确率 \(pct)%",
                            "Quizzed \(checkins.count)× · \(right) correct · \(pct)% accuracy"))
                        .font(.system(size: 13)).foregroundStyle(Palette.textPrimary)
                }
                if !rows.isEmpty {
                    HStack(spacing: Spacing.sm) {
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Palette.border)
                                Capsule().fill(Palette.okFG)
                                    .frame(width: geo.size.width * max(0.04, Double(ok) / Double(rows.count)))
                            }
                        }
                        .frame(height: 8)
                        Text(tr("已跟上 \(ok) / \(rows.count)", "Caught up \(ok) / \(rows.count)"))
                            .font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
                    }
                }
            }
            .card()
        }
    }

    /// 这节课的掉队：时间线（对应 Python `_breakpoint_card`）
    @ViewBuilder private var breakpointCard: some View {
        let bps = engine.breakpoints
        if !bps.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                Text(tr("这节课的掉队", "Where you fell behind"))
                    .font(.system(size: 12, weight: .bold)).foregroundStyle(Palette.accent)
                ForEach(bps) { bp in
                    let outcome = bp.fixed ? tr("已补上", "caught up")
                        : bp.selfReview ? tr("自己看了", "reviewed alone") : tr("未补上", "not caught up")
                    Text(tr("\(bp.breakpointTC) 掉队 · 「\(bp.concept)」 · \(outcome)",
                            "Fell behind at \(bp.breakpointTC) · \"\(bp.concept)\" · \(outcome)"))
                        .font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
                }
            }
            .card()
        }
    }
}

/// 去掉模型偶尔夹带的 Markdown / LaTeX 记号，按纯文本显示
func plain(_ text: String) -> String {
    var s = text.replacingOccurrences(of: #"\*\*(.+?)\*\*"#, with: "$1", options: .regularExpression)
    s = s.replacingOccurrences(of: #"(?m)^#+\s*"#, with: "", options: .regularExpression)
    for t in ["\\(", "\\)", "\\[", "\\]"] { s = s.replacingOccurrences(of: t, with: "") }
    return s
}

extension EchoStatus {
    var label: String {
        switch self {
        case .idle, .listening: tr("正在听课", "Listening")
        case .analyzing: tr("正在分析", "Analyzing")
        case .summarizing: tr("正在整理", "Summarizing")
        case .loadingASR: tr("正在加载语音识别", "Loading speech recognition")
        case .done: tr("已下课", "Class ended")
        }
    }

    var isBusy: Bool { self == .analyzing || self == .summarizing || self == .loadingASR }
}
