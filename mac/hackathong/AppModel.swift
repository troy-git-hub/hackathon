//
//  AppModel.swift
//  Echo — 前端状态与动作（对应 Python floating_window / tray / desk_pet 里的槽函数）
//
//  页面：
//    home     主页（启动页）：今天该回响 + 课程名 + 开始学习 + 错题复习/AI 出题/课程管理
//    listen   听课卡片：当前知识点 + 实时字幕 + 我掉队了 / 答题 / 考考我（抽问卡浮层）
//    mini     折叠条：猫头像 + 知识点 + 「掉队」
//    brk      断点页：刚才会的 → 掉队的那一步 → 老师讲到这里 + 你缺的这一步 + 追问
//    lesson   补课三段式
//    echo     回响：掌握度条 ✓ ? ! + 复习链
//    review   错题复习：今天该复习 / 过几天再复习 + 三档自评
//    practice AI 出题练习
//    detail   知识点详情：这节课讲了什么 + 掌握度 + 知识地图 / 出题
//    mindmap  知识地图
//    courses  课程管理：搜索 / 批量删除 / 重命名 / 看回顾
//    recall   讲给 Echo 听（对话式复习）
//    profile  资料页：头像 + 学习情况
//    ask      问 Echo（随时问）
//

import SwiftUI
import AppKit
import UniformTypeIdentifiers
import UserNotifications

enum Page {
    case home, listen, mini, brk, lesson, echo, review, practice
    case detail, mindmap, courses, recall, profile, ask, learned, weekly

    /// 各页内容区宽度（不含内边距）
    var width: CGFloat {
        switch self {
        case .listen: 340
        case .mini: 300
        case .brk, .echo, .review, .detail, .profile: 380
        case .lesson, .practice, .recall, .ask, .weekly: 400
        case .home: 360
        case .courses: 420
        case .mindmap, .learned: 480
        }
    }
}

/// 面板藏起来时到达、等用户点开的结果
enum Pending { case brk, echo }

@Observable
final class AppModel {
    let engine: EchoEngine
    let cat = CatMood()
    let pet = PetModel()
    let mindmap: MindmapModel

    var page: Page = .home
    var source: SourceKind
    var lessonTitleInput = ""
    private(set) var panelVisible = true
    private(set) var pending: Pending?

    // 本节课学生的选择（回响里用来标「已补上 / 自己看了」）
    private(set) var fixedTopics: Set<String> = []
    private(set) var selfLookTopics: Set<String> = []

    // 状态提示
    private(set) var bpFailed = false
    private(set) var echoFailed = false
    private(set) var showError = false
    var acked: FeedbackKind?

    // 断点页追问
    private var ask: AskSession?
    private(set) var askAnswer = ""
    private(set) var askBusy = false
    private(set) var askError: String?

    // 错题本 / 课程历史 / 统计
    private(set) var reviewPending: [ReviewItem] = []
    private(set) var reviewLater: [ReviewItem] = []
    private(set) var lessons: [LessonRecord] = []
    private(set) var stats = StudyStatsVM()
    private(set) var dueHint = ""
    private(set) var dueMinutes = 0

    // AI 出题练习
    private(set) var practiceItem: ReviewItem?
    private(set) var practiceQs: [PracticeQuestion] = []
    private(set) var practiceIndex = 0
    private(set) var practiceLoading = false
    private(set) var practiceSource = ""
    var showAnswer = false
    private var practiceBack: Page = .home

    // 知识点详情
    private(set) var detail: DetailVM?

    // 课程管理
    private(set) var courses: [CourseRowVM] = []

    // 讲给 Echo 听（RECALL）
    private(set) var recallMessages: [ChatMessage] = []
    private(set) var recallSubtitle = ""
    private(set) var recallLoading = false
    private(set) var recallLoadingText = ""
    private(set) var recallInputEnabled = false
    private(set) var recallShowGrades = false
    private(set) var recallGrade = ""
    private var recallItems: [ReviewItem] = []
    private var recallQuestions: [(prompt: String, label: String)] = []
    private var recallAnswers: [RecallAnswer] = []
    private var recallCurrent = ""

    // 问 Echo（ASK）
    private var qa: AskSession?
    private(set) var askMessages: [ChatMessage] = []
    private(set) var askLoading = false
    private(set) var askInputEnabled = true

    // 资料
    private(set) var profile = ProfileVM(displayName: tr("同学", "there"), sub: "", hasCustomAvatar: false)
    private(set) var avatarImage: NSImage?
    private(set) var needsProfileSetup = false

    // 课堂抽问
    var checkinPreparing = false
    /// 当前展示在听课页上的那道题。引擎答完就清空 pendingCheckin，
    /// 这里留一份，学生才能看到判分和讲解（关掉卡片才清）。
    private(set) var checkinQuestion: CheckinData?
    private var checkinCorrectIndex: Int?

    // 顶栏 toast（「个人信息已更新」这类，5 秒自动消失）
    private(set) var toast: String?
    private var toastTask: Task<Void, Never>?

    // 已学内容（聚合知识地图）/ 一周学习回响
    private(set) var learnedGraph: MindmapGraph?
    private(set) var learnedLesson: LessonRecord?
    private(set) var weeklySkills: [WeeklySkill] = []

    // 窗口层的回调（AppDelegate 注入）
    var onShowPanel: () -> Void = {}
    var onHidePanel: () -> Void = {}
    var onCircleAsk: () -> Void = {}
    var onOpenSettings: () -> Void = {}
    var onQuit: () -> Void = {}
    var onDragPanel: () -> Void = {}
    var onDragPanelEnd: () -> Void = {}

    /// 抓系统声音需要「屏幕与系统录音」权限；被拒时引擎停在 loadingASR 并报错
    var needsScreenPermission: Bool {
        guard engine.status == .loadingASR, source == .system, let err = engine.lastError else { return false }
        return ["TCC", "录", "捕捉"].contains { err.contains($0) }
    }

    func openScreenPrivacySettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
    }

    init(engine: EchoEngine, source: SourceKind) {
        self.engine = engine
        self.mindmap = MindmapModel(engine: engine)
        self.source = source
        refreshStore()
        loadProfile()
        observeEngine()
    }

    // MARK: - 窗口 / 导航

    func setPanelVisible(_ v: Bool) {
        panelVisible = v
        if v { pending = nil }
    }

    /// 打开面板：今天有该回响的、而且**没在上课** → 直接落到主页（顶部就是「今天该回响」）。
    /// 上课时绝不跳页 —— 那等于把学生从课堂里拽出去，这节课的回响和错题都还没存。
    func showPanel() {
        let wasHidden = !panelVisible
        onShowPanel()
        if wasHidden, stats.due > 0, !engine.active, page == .listen || page == .mini {
            showHome()
        }
    }
    func hidePanel() { onHidePanel() }
    func togglePanel() { panelVisible ? hidePanel() : showPanel() }

    /// 点猫头像：回到听课界面（回响页上点就留在回响）
    func openFromAvatar() {
        go(page == .echo ? .echo : .listen)
    }

    func go(_ p: Page) {
        withAnimation(.snappy(duration: 0.25)) { page = p }
    }

    /// ← 按钮：按来源页回退（照 Python 的 _back 规则）
    func back() {
        switch page {
        case .practice: go(practiceBack)
        case .recall, .review, .detail, .mindmap, .courses, .learned, .weekly: showHome()
        case .profile, .ask: go(.listen)
        default: go(.listen)
        }
    }

    /// ← 按钮当前该显示什么
    var backTitle: String {
        switch page {
        case .practice: practiceBack == .detail ? tr("← 详情", "← Details")
            : practiceBack == .mindmap ? tr("← 知识地图", "← Knowledge map") : tr("← 主页", "← Home")
        case .recall: tr("← 错题复习", "← Review")
        case .profile, .ask: tr("← 回到课堂", "← Back to class")
        case .learned: tr("← 已学内容", "← Learned so far")
        case .weekly: tr("← 一周回响", "← Weekly review")
        default: tr("← 主页", "← Home")
        }
    }

    func showHome() {
        refreshStore()
        go(.home)
    }

    func showReview() {
        refreshStore()
        kickWhyMatters()
        go(.review)
    }

    /// 已学内容：把所有历史课合并成一张按学科分区的大图
    func showLearned() {
        let catalog = Mindmap.buildAll(lessons: ReviewStore.listLessons(limit: nil), mistakes: ReviewStore.load())
        learnedGraph = catalog.graph
        learnedLesson = catalog.lesson
        go(.learned)
    }

    /// 一周学习回响：最近 7 天学过的知识点
    func showWeekly() {
        weeklySkills = ReviewStore.weeklySkills(days: 7)
        go(.weekly)
    }

    /// 顶栏 toast，5 秒自动消失（「个人信息已更新」这类）
    func showToast(_ s: String) {
        toast = s
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled else { return }
            self?.toast = nil
        }
    }

    func showProfile() {
        loadProfile()
        go(.profile)
    }

    // MARK: - 课堂

    func feedback(_ kind: FeedbackKind) {
        engine.feedback(kind)
        cat.set(kind == .ok ? .ok : .warn, hold: .milliseconds(kind == .ok ? 2200 : 3000))
        acked = kind
        Task {
            try? await Task.sleep(for: .seconds(1))
            if acked == kind { acked = nil }
        }
    }

    /// 核心：Break Point Engine（异步，结果见 engine.breakpoint）
    func lost() {
        showPanel()
        cat.set(.lost)
        bpFailed = false
        resetAsk()
        engine.feedback(.lost)
        go(.brk)
    }

    func goLesson() {
        go(.lesson)
        cat.set(.thinking)
    }

    func markFixed() {
        if let bp = engine.breakpoint { fixedTopics.insert(bp.concept) }
        engine.markFixed()
        cat.set(.fixed, hold: .milliseconds(2500))
        go(.listen)
    }

    /// 学生自己处理：不调 LLM，收起断点页；断点还没出来就只是取消
    func selfLook() {
        if let bp = engine.breakpoint {
            selfLookTopics.insert(bp.concept)
            engine.markSelf()
        }
        cat.set(.ok, hold: .milliseconds(1500))
        go(.listen)
    }

    func endLesson() {
        showPanel()
        echoFailed = false
        engine.endLesson()
        go(.echo)
    }

    /// 开始今天的学习：把课程名交给引擎，然后开课
    func startToday() {
        let name = lessonTitleInput.trimmingCharacters(in: .whitespaces)
        if name.isEmpty { engine.clearTitle() } else { engine.setTitle(name) }
        lessonTitleInput = ""
        restart()
    }

    func restart() {
        showPanel()
        fixedTopics.removeAll()
        selfLookTopics.removeAll()
        showError = false
        resetAsk()
        cat.set(.idle)
        checkinQuestion = nil
        checkinCorrectIndex = nil
        checkinPreparing = false
        engine.start(source: source)
        go(.listen)
    }

    func setSource(_ s: SourceKind) {
        source = s
        UserDefaults.standard.set(s.rawValue, forKey: "ECHO_SOURCE")
        restart()
    }

    func toggleOffline() {
        engine.setOffline(!engine.offline)
    }

    // MARK: - 课堂抽问

    var checkinData: CheckinData? { checkinQuestion }

    /// 刚答完这道题的判分（只在还展示着这道题时给）
    var checkinFeedback: CheckinFeedback? {
        guard let q = checkinQuestion, let r = engine.checkins.last, r.question == q.question else { return nil }
        return CheckinFeedback(result: r.result, answer: r.answer, explain: r.explain,
                               chosen: r.chosen, correctIndex: checkinAnswerIndex)
    }

    /// 正确选项下标（答完 pendingCheckin 就没了，从记下来的题里找）
    private var checkinAnswerIndex: Int? { checkinCorrectIndex }

    /// 「考考我」：主动要一道题
    func askCheckinNow() {
        guard engine.askCheckinNow() else {
            showStatus(tr("先开始上课，Echo 才知道该考你什么", "Start the lesson first — then Echo knows what to quiz you on"))
            return
        }
        checkinPreparing = true
    }

    func answerCheckin(_ choice: Int) {
        checkinPreparing = false
        engine.answerCheckin(choice)      // 题留着，卡片显示判分
    }

    /// 关掉抽问卡（未作答就是跳过）
    func skipCheckin() {
        checkinPreparing = false
        checkinQuestion = nil
        checkinCorrectIndex = nil
        engine.skipCheckin()
    }

    private var statusNote = ""
    private func showStatus(_ s: String) {
        statusNote = s
        pet.say(s, ms: 4000, mood: .warn)
    }

    // MARK: - 断点追问

    func askBreakpoint(_ q: String) {
        let q = q.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !askBusy else { return }
        if ask == nil {
            var extra = ""
            if let bp = engine.breakpoint {
                extra = tr("刚才定位到的知识断点：\(bp.concept)\n缺失的这一步：\(bp.missing)\n为什么容易掉队：\(bp.reason)",
                           "Knowledge gap just located: \(bp.concept)\nMissing step: \(bp.missing)\nWhy it's easy to fall behind: \(bp.reason)")
            }
            ask = AskSession(engine: engine, extraContext: extra)
        }
        guard let ask else { return }
        askAnswer = ""
        askError = nil
        askBusy = true
        Task {
            do {
                for try await d in ask.ask(q) { askAnswer += d }
            } catch {
                askError = error.localizedDescription
            }
            askBusy = false
        }
    }

    var askShown: Bool { askBusy || !askAnswer.isEmpty || askError != nil }

    private func resetAsk() {
        ask?.cancel()
        ask = nil
        askAnswer = ""
        askError = nil
        askBusy = false
    }

    // MARK: - 问 Echo（ASK 页）

    func openAsk() {
        if qa == nil {
            qa = AskSession(engine: engine)
            askMessages = [ChatMessage(kind: .echo,
                                       text: tr("想问什么就问，我带着这节课听到的内容回答你。这节课上完回来，我们还能接着聊。",
                                                "Ask me anything — I'll answer using what I've heard in this lesson. Come back after class and we can pick this up again."))]
        }
        go(.ask)
    }

    func askSend(_ text: String) {
        guard let qa else { return }
        askMessages.append(ChatMessage(kind: .me, text: text, label: tr("你", "You")))
        askLoading = true
        askInputEnabled = false
        let idx = askMessages.count
        askMessages.append(ChatMessage(kind: .echo, text: "", label: "Echo"))
        Task {
            do {
                for try await d in qa.ask(text) {
                    if askMessages.indices.contains(idx) { askMessages[idx].text += d }
                }
            } catch {
                let msg = tr("现在连不上 AI（可能没网或没配 key），等会儿再问我吧。",
                             "Can't reach the AI right now (offline or no key) — try me again later.")
                if askMessages.indices.contains(idx) {
                    askMessages[idx] = ChatMessage(kind: .note, text: msg, tone: "warn")
                }
            }
            askLoading = false
            askInputEnabled = true
        }
    }

    // MARK: - 回响

    /// 回响行：后端状态 + 前端记下的「补上了 / 自己看了」
    func echoRows(_ report: EchoReport) -> [(name: String, mastery: Double, mark: SkillMark, note: String)] {
        func hit(_ name: String, _ set: Set<String>) -> Bool {
            set.contains { name.contains($0) || $0.contains(name) }
        }
        return report.skills.map { s in
            var st = s.status
            if st == .review && hit(s.name, fixedTopics) { st = .fixed }
            let note = st == .fixed ? tr("掉队过 · 已补上", "Fell behind · caught up")
                : hit(s.name, selfLookTopics) ? tr("掉队过 · 自己看了", "Fell behind · reviewed it myself") : ""
            return (s.name, s.mastery, SkillMark(status: st, mastery: s.mastery), note)
        }
    }

    /// 回响页 → 知识地图
    func mindmapFromReport() {
        mindmap.show(nil, report: engine.report)
        go(.mindmap)
    }

    // MARK: - 错题本 / 主页 / 复习

    func refreshStore() {
        let all = ReviewStore.load()
        reviewPending = all.filter { !$0.reviewed && $0.isDue }
        reviewLater = all.filter { !$0.reviewed && !$0.isDue }
        lessons = ReviewStore.listLessons(limit: 3)
        let s = ReviewStore.stats()
        let due = ReviewStore.dueSummary()
        stats = StudyStatsVM(lessons: s.lessons, pending: s.pending, mastered: s.mastered, due: due.due)
        dueHint = due.hint
        dueMinutes = due.minutes
        courses = ReviewStore.listLessons(limit: nil).map {
            CourseRowVM(id: $0.time, name: $0.title, date: $0.date, points: $0.total,
                        minutes: $0.minutes, review: $0.review)
        }
    }

    func markReviewed(_ topic: String) {
        ReviewStore.markReviewed(topic: topic)
        refreshStore()
    }

    /// 三档自评（错题复习页）
    func gradeReview(_ topic: String, _ g: Grade) {
        ReviewStore.grade(topic: topic, result: g)
        refreshStore()
        maybeRefreshPersona()
    }

    private func saveLesson(_ report: EchoReport) {
        // 离线/兜底拼出来的回响不是真听懂了这节课：存进去只会攒出一堆一模一样的假课，污染历史和画像
        guard !report.fromMock else { return }
        ReviewStore.add(ReviewStore.fromBreakpoints(engine))
        let title = engine.title.isEmpty
            ? (engine.timeline.first?.topic ?? report.skills.first?.name ?? tr("一节课", "A lesson"))
            : engine.title
        let right = engine.checkins.filter { $0.result == Quiz.right }.count
        let ts = ReviewStore.saveLesson(title: title, report: report, summary: report.summary,
                               points: report.highlights,
                               minutes: Int((report.duration / 60).rounded()),
                               chars: report.charCount, graph: report.graph,
                               breakpoints: LessonBreakpoint.rows(engine.breakpoints),
                               quiz: LessonQuiz(total: engine.checkins.count, correct: right))
        if ts == 0 {
            showToast(tr("这节课的记录没能保存，请检查磁盘空间", "Couldn't save this lesson — check your disk space"))
        }
        refreshStore()
        maybeRefreshPersona()
        kickWhyMatters()
    }

    /// 又上完 N 节课或又判过 M 次复习，谁先到就重算一次学生画像（下课 / 打分后都要试一次）。
    private func maybeRefreshPersona() {
        if Persona.maybeRefresh() != nil {
            showToast(tr("个人信息已更新 —— Echo 对你的了解又细了一点",
                         "Profile updated — Echo knows you a bit better now"))
        }
    }

    /// 进复习页时批量生成「为什么要复习它」，只发一次请求，不要每次打分都重发。
    private func kickWhyMatters() {
        let todo = WhyMatters.needs(ReviewStore.load())
        guard !todo.isEmpty else { return }
        Task {
            let reasons = await WhyMatters.planBatch(todo)
            guard !reasons.isEmpty else { return }
            _ = ReviewStore.setWhy(reasons)
            refreshStore()
        }
    }


    // MARK: - 课程管理

    func showCourses() {
        refreshStore()
        go(.courses)
    }

    func renameLesson(_ ts: Double, _ name: String) {
        _ = ReviewStore.renameLesson(ts: ts, newTitle: name)
        refreshStore()
    }

    func deleteLessons(_ ts: [Double]) {
        _ = ReviewStore.deleteLessons(ts)
        refreshStore()
    }

    // MARK: - 知识点详情

    func showDetail(_ ts: Double) {
        guard let lesson = ReviewStore.getLesson(ts: ts) else { return }
        detail = detailVM(lesson)
        mindmap.show(lesson, report: nil)
        go(.detail)
    }

    private func detailVM(_ lesson: LessonRecord) -> DetailVM {
        let skills = lesson.skills.map {
            DetailSkill(name: $0.name, mastery: $0.mastery, status: $0.status,
                        note: $0.status == .fixed ? tr("掉队过 · 已补上", "Fell behind · caught up") : "")
        }
        // 跟上/待复习的数字优先用 skills_detail 现算，没有才退回归档的 ok/review 字段
        let ok = skills.isEmpty ? lesson.ok : skills.filter { $0.status == .ok || $0.status == .fixed }.count
        let review = skills.isEmpty ? lesson.review : skills.count - ok
        let bps = lesson.breakpoints.map {
            DetailBreakpoint(tc: $0.tc, concept: $0.concept, outcome: outcomeLabel($0.outcome))
        }
        let overview = DetailOverview(lostCount: lesson.breakpoints.count,
                                      quizCount: lesson.quiz.total, quizRight: lesson.quiz.correct,
                                      okCount: ok, totalCount: skills.count)
        return DetailVM(id: lesson.time, title: lesson.title, date: lesson.date, ok: ok,
                        review: review, minutes: lesson.minutes, points: lesson.total,
                        chars: lesson.chars, summary: lesson.summary, highlights: lesson.points,
                        skills: skills, chain: lesson.reviewChain, suggestion: lesson.suggestion,
                        breakpoints: bps, overview: overview)
    }

    private func outcomeLabel(_ raw: String) -> String {
        switch raw {
        case "fixed": tr("已补上", "caught up")
        case "self": tr("自己看了", "reviewed alone")
        default: tr("未补上", "not caught up")
        }
    }

    func detailMindmap() {
        if let d = detail, let lesson = ReviewStore.getLesson(ts: d.id) {
            mindmap.show(lesson, report: nil)
            go(.mindmap)
        }
    }

    /// 详情页「出几道题练练」：按整节课出题
    func detailQuiz() {
        guard let d = detail else { return }
        practiceBack = .detail
        practiceItem = ReviewItem(topic: d.title)
        practiceQs = []
        practiceIndex = 0
        showAnswer = false
        practiceLoading = true
        go(.practice)
        Task {
            let qs = await Quiz.lessonQuiz(lesson: ReviewStore.getLesson(ts: d.id), n: 4)
            practiceQs = qs
            practiceLoading = false
        }
    }

    // MARK: - AI 出题练习

    func startPractice() {
        refreshStore()
        guard let first = reviewPending.first ?? reviewLater.first else { return showHome() }
        practice(first)
    }

    func practice(_ item: ReviewItem) {
        practiceBack = .home
        practice(item, back: .home)
    }

    func practice(_ item: ReviewItem, back: Page) {
        practiceBack = back
        practiceItem = item
        practiceQs = []
        practiceIndex = 0
        showAnswer = false
        practiceLoading = true
        practiceSource = ""
        go(.practice)
        Task {
            let qs = await Practice.generate(item, n: 3)
            guard practiceItem?.id == item.id else { return }
            practiceQs = qs
            practiceLoading = false
            practiceSource = tr("AI 生成", "AI generated")
        }
    }

    /// 出题等待时先用本地兜底题练起来，AI 出好了会自动换上
    func useLocalQuestions() {
        guard let item = practiceItem else { return }
        practiceQs = Practice.fallback(item)
        practiceIndex = 0
        showAnswer = false
        practiceLoading = false
        practiceSource = tr("本地题 · 根据已有错题整理", "Local questions · from your mistakes")
    }

    /// 从知识地图点「出题练一练」
    func practiceTopic(_ topic: String) {
        refreshStore()
        let d = mindmap.detail
        let item = ReviewStore.load().first { $0.topic == topic }
            ?? ReviewItem(topic: topic, missing: d?.missing ?? "", microLesson: d?.microLesson ?? "",
                          known: d?.known ?? "", step: d?.step ?? "")
        practice(item, back: .mindmap)
    }

    /// 主页「反复卡住的地方」卡：针对这个根源概念现造一道题
    func practiceGap(_ concept: String) {
        let item = ReviewStore.load().first { $0.topic == concept }
            ?? ReviewItem(topic: concept,
                          missing: tr("「\(concept)」反复没打牢", "\"\(concept)\" keeps slipping"),
                          reason: tr("这个知识点在好几节课里都卡住过", "This concept has come up stuck across several lessons"))
        practice(item, back: .home)
    }

    func nextQuestion() {
        if practiceIndex + 1 < practiceQs.count {
            practiceIndex += 1
            showAnswer = false
        } else {
            back()
        }
    }

    func practiceMastered() {
        if let t = practiceItem?.topic { ReviewStore.markReviewed(topic: t) }
        back()
    }

    // MARK: - 讲给 Echo 听（RECALL）

    func startRecall() {
        refreshStore()
        recallMessages = []
        recallShowGrades = false
        recallGrade = ""
        recallAnswers = []
        recallInputEnabled = false
        let due = ReviewStore.dueItems()
        go(.recall)
        guard !due.isEmpty else {
            recallSubtitle = tr("今天没有要确认的知识点", "Nothing to confirm today")
            recallMessages = [ChatMessage(kind: .echo, text: tr("今天没有到期的知识点，去上课吧～", "Nothing due today — go enjoy your lesson."))]
            return
        }
        let picked = Recall.pick(due, n: 3)
        recallItems = picked.items
        let root = picked.root
        recallSubtitle = (root.isEmpty || picked.items.count <= 1)
            ? tr("这一轮聊 \(picked.items.count) 个知识点：\(picked.items.map(\.topic).joined(separator: "、"))",
                 "This round: \(picked.items.map(\.topic).joined(separator: ", "))")
            : tr("这一轮聊 \(picked.items.count) 个知识点，它们都卡在「\(root)」上",
                 "\(picked.items.count) points this round — all rooted in \"\(root)\"")
        recallLoading = true
        recallLoadingText = tr("Echo 在想怎么问你…", "Echo is thinking how to ask…")
        Task {
            let plan = await Recall.plan(items: recallItems, root: root)
            recallLoading = false
            recallMessages.append(ChatMessage(kind: .echo, text: plan.opening, label: "Echo"))
            recallQuestions = plan.questions.map { (prompt: $0.question, label: $0.kind.label) }
            askNextRecallQuestion()
        }
    }

    private func askNextRecallQuestion() {
        guard !recallQuestions.isEmpty else { return finishRecall() }
        let q = recallQuestions.removeFirst()
        recallCurrent = q.prompt
        recallMessages.append(ChatMessage(kind: .echo, text: "\(q.label)\n\(q.prompt)", label: "Echo"))
        recallInputEnabled = true
    }

    var recallPlaceholder: String {
        recallCurrent.isEmpty ? tr("用你自己的话讲…", "Say it in your own words…")
            : tr("用你自己的话讲…", "Say it in your own words…")
    }

    func recallSend(_ text: String) {
        recallMessages.append(ChatMessage(kind: .me, text: text, label: tr("你", "You")))
        recallAnswers.append(RecallAnswer(question: recallCurrent, answer: text))
        recallInputEnabled = false
        if recallQuestions.isEmpty { finishRecall() } else { askNextRecallQuestion() }
    }

    private func finishRecall() {
        recallLoading = true
        recallLoadingText = tr("Echo 在想你说的对不对…", "Echo is thinking about your answer…")
        Task {
            let result = await Recall.judge(items: recallItems, answers: recallAnswers)
            recallLoading = false
            if result.offline {
                recallMessages.append(ChatMessage(kind: .note, text: tr("这次连不上 AI，我判断不了。你自己说说看，哪个档次更像你？",
                                                                       "I can't reach the AI to judge this time. Which of these feels right to you?"),
                                                  tone: "warn"))
                recallShowGrades = true
                recallInputEnabled = false
                return
            }
            recallMessages.append(ChatMessage(kind: .echo, text: tr("我听完了，说说我的判断：", "Here's what I made of it:"), label: "Echo"))
            for r in result.results {
                var text = "\(r.topic)　\(r.verdict.label)"
                if !r.feedback.isEmpty { text += "\n" + r.feedback }
                if !r.missing.isEmpty { text += "\n" + tr("还没说到的：\(r.missing)", "Still missing: \(r.missing)") }
                recallMessages.append(ChatMessage(kind: .note, text: text))
            }
            Recall.applyResults(result)
            refreshStore()
            maybeRefreshPersona()
            recallSubtitle = tr("记下了，下次到期我再来问你", "Noted — I'll ask again when it's due")
            recallShowGrades = true
            recallInputEnabled = false
        }
    }

    func recallGrade(_ value: String) {
        recallGrade = value
        guard let first = recallItems.first else { return }
        let g: Grade = value == "clear" ? .clear : value == "fuzzy" ? .fuzzy : .again
        ReviewStore.grade(topic: first.topic, result: g)
        recallMessages.append(ChatMessage(kind: .echo,
                                          text: tr("好，那「\(first.topic)」按你说的记。", "OK — noting \"\(first.topic)\" as you said."),
                                          label: "Echo"))
        refreshStore()
        maybeRefreshPersona()
    }

    // MARK: - 资料

    func loadProfile() {
        let p = ProfileStore.load()
        needsProfileSetup = !ProfileStore.exists()
        profile = ProfileVM(displayName: ProfileStore.displayName(),
                            sub: profileSub(p),
                            hasCustomAvatar: ProfileStore.avatarPath() != nil)
        avatarImage = ProfileStore.avatarData().flatMap { NSImage(data: $0) }
    }

    private func profileSub(_ p: Profile?) -> String {
        guard let p else { return "" }
        var bits: [String] = []
        if let age = p.age, age > 0 { bits.append(tr("\(age) 岁", "age \(age)")) }
        if !p.hobbies.isEmpty { bits.append(p.hobbies) }
        return bits.joined(separator: " · ")
    }

    func saveProfileSetup(_ data: ProfileSetupData) -> String? {
        let p = Profile(name: data.name.trimmingCharacters(in: .whitespaces),
                        nickname: data.nickname.trimmingCharacters(in: .whitespaces),
                        age: data.age > 0 ? data.age : nil,
                        hobbies: data.hobbies.trimmingCharacters(in: .whitespaces),
                        username: data.nickname.trimmingCharacters(in: .whitespaces))
        ProfileStore.save(p)
        if let url = data.avatarURL { _ = ProfileStore.setAvatar(from: url) }
        loadProfile()
        return nil
    }

    func pickAvatar() {
        let panel = NSOpenPanel()
        panel.title = tr("换一张头像", "Change your photo")
        panel.allowedContentTypes = [.png, .jpeg, .webP, .bmp]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if !ProfileStore.setAvatar(from: url) {
            pet.say(tr("这张图读不了，换一张试试（支持 PNG / JPG / WebP / BMP）。",
                       "Can't read that image — try another one (PNG / JPG / WebP / BMP)."), ms: 5000, mood: .warn)
        }
        loadProfile()
    }

    func useDefaultAvatar() {
        ProfileStore.clearAvatar()
        loadProfile()
    }

    // MARK: - 后端事件

    private func observeEngine() {
        // 掉队分析结果
        watch({ $0.engine.breakpoint }) { m, bp in
            guard let bp else { return }
            m.bpFailed = false
            m.pet.foundBreakpoint(panelHidden: !m.panelVisible)
            if !m.panelVisible {
                m.pending = .brk
                m.notify(tr("找到你掉队的地方了", "I found where you fell behind"),
                         tr("\(bp.missing.isEmpty ? bp.concept : bp.missing)\n点这里看 30 秒补课",
                            "\(bp.missing.isEmpty ? bp.concept : bp.missing)\nTap to see a 30-second catch-up"))
            }
        }
        // 回响
        watch({ $0.engine.report }) { m, report in
            guard let report else { return }
            m.saveLesson(report)
            let review = m.echoRows(report).filter { $0.mark != .ok }.count
            m.cat.set(review == 0 ? .ok : .idle)
            m.pet.echoReady(panelHidden: !m.panelVisible)
            m.refreshStore()
            if !m.panelVisible {
                m.pending = .echo
                m.notify(tr("这节课的回响好了", "This lesson's echo is ready"),
                         tr("\(report.skills.count) 个知识点，\(review) 个待回看。点这里查看",
                            "\(report.skills.count) concepts, \(review) to revisit. Tap to view"))
            }
        }
        watch({ $0.engine.status }) { m, st in m.pet.status(st) }
        watch({ $0.engine.current?.topic }) { m, topic in
            if let topic { m.pet.topic(topic, listening: m.engine.status == .listening) }
        }
        watch({ $0.engine.lastError }) { m, err in m.onError(err) }
        // 课堂抽问：折叠时先回到听课页
        watch({ $0.engine.pendingCheckin?.question }) { m, q in
            guard let q, let full = m.engine.pendingCheckin else { return }
            m.checkinQuestion = CheckinData(topic: full.topic, question: full.question, options: full.options)
            m.checkinCorrectIndex = full.answerIndex
            m.checkinPreparing = false
            if m.page == .mini { m.go(.listen) }
            m.pet.say(tr("课堂抽查来了", "Quick check — take a look"), ms: 4000, mood: .alert)
        }
    }

    /// 监听 engine 的某个属性，变化时在主线程回调
    private func watch<T: Equatable & Sendable>(_ get: @escaping (AppModel) -> T,
                                                _ action: @escaping (AppModel, T) -> Void) {
        Task { [weak self] in
            guard let me = self else { return }
            var first = true
            for await v in Observations({ get(me) }) {
                if first { first = false; continue }   // 只关心变化
                action(me, v)
            }
        }
    }

    private func onError(_ err: String?) {
        guard let err, !err.isEmpty else {
            showError = false
            return
        }
        showError = true
        pet.say(tr("出了点小问题，我还在", "A small hiccup — I'm still here"), ms: 3000, mood: .warn)
        if page == .brk && engine.breakpoint == nil { bpFailed = true }
        if page == .echo && engine.report == nil { echoFailed = true }
        Task {
            try? await Task.sleep(for: .seconds(6))
            showError = false
        }
    }

    private func notify(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}
