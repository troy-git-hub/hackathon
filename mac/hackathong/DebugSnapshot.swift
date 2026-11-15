//
//  DebugSnapshot.swift
//  Echo — 自检（仅 DEBUG）：ECHO_SNAPSHOT=1 启动时，用示例课把整条流程真跑一遍
//  （听课 → 考考我 → 我掉队了 → 补课 → 问 Echo → 下课回响 → 主页 → 知识地图 →
//    课程管理 → 知识点详情 → 资料 → 讲给 Echo 听），每一页渲染成 PNG，写到沙盒
//  tmp/echo-snapshots/，并记录日志。
//

#if DEBUG
import SwiftUI
import AppKit
import Speech
import AVFoundation

enum DebugSnapshot {
    static var enabled: Bool { ProcessInfo.processInfo.environment["ECHO_SNAPSHOT"] == "1" }

    /// 一直把引擎状态写到 tmp/echo-probe.txt（排查真实音频源卡住）
    static func probe(_ engine: EchoEngine) {
        let url = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("echo-probe.txt")
        Task {
            var log = ""
            for i in 0..<120 {
                log += "\(i)s status=\(engine.status) err=\(engine.lastError ?? "-") lines=\(engine.transcripts.count) level=\(String(format: "%.2f", engine.level)) speech=\(SFSpeechRecognizer.authorizationStatus().rawValue) mic=\(AVCaptureDevice.authorizationStatus(for: .audio).rawValue) screen=\(CGPreflightScreenCaptureAccess())\n"
                try? log.write(to: url, atomically: true, encoding: .utf8)
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    static func run(_ model: AppModel) {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("echo-snapshots")
        try? FileManager.default.removeItem(at: dir)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var log = ""
        func note(_ s: String) {
            log += "[\(Date().formatted(date: .omitted, time: .standard))] \(s)\n"
            try? log.write(to: dir.appendingPathComponent("log.txt"), atomically: true, encoding: .utf8)
        }
        func shot(_ name: String) {
            for scheme in [ColorScheme.light, .dark] {
                let view = RootView(model: model, noScroll: true)
                    .background(Palette.windowBG, in: .rect(cornerRadius: Radius.window))
                    .environment(\.colorScheme, scheme)
                let r = ImageRenderer(content: view)
                r.scale = 2
                if let cg = r.cgImage,
                   let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]) {
                    try? png.write(to: dir.appendingPathComponent("\(name)\(scheme == .dark ? "_dark" : "").png"))
                }
            }
            note("shot \(name) page=\(model.page) status=\(model.engine.status)")
        }
        func wait(_ what: String, timeout: Double = 40, _ cond: () -> Bool) async {
            let t0 = Date()
            while !cond() && Date().timeIntervalSince(t0) < timeout {
                try? await Task.sleep(for: .milliseconds(300))
            }
            note("\(what): \(cond() ? "ok" : "TIMEOUT") in \(String(format: "%.1f", Date().timeIntervalSince(t0)))s")
        }
        @MainActor func extra<V: View>(_ name: String, _ v: V) {
            let r = ImageRenderer(content: v.background(Palette.windowBG.opacity(0.4)))
            r.scale = 2
            if let cg = r.cgImage,
               let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]) {
                try? png.write(to: dir.appendingPathComponent("\(name).png"))
            }
            note("shot \(name)")
        }
        let e = model.engine

        Task {
            // 首次登录流程：存一份资料，确认 exists/displayName 都对（真机上填完就是这个效果）
            let err = model.saveProfileSetup(ProfileSetupData(name: "测试同学", nickname: "小测", age: 14,
                                                             hobbies: "篮球", avatar: nil, avatarURL: nil))
            note("profile save err=\(err ?? "nil") exists=\(ProfileStore.exists()) name=\(ProfileStore.displayName()) avatar=\(ProfileStore.avatarPath() ?? "-")")
            note("start hasLLM=\(e.hasLLM) source=\(model.source)")
            shot("01_home")
            model.restart()
            await wait("transcripts>=6", timeout: 60) { e.transcripts.count >= 6 }
            await wait("concept", timeout: 60) { e.current != nil }
            note("current=\(e.current?.topic ?? "-") timeline=\(e.timeline.map(\.topic)) thinking=\(e.thinking ?? "-") level=\(e.level)")
            shot("02_listen")
            model.go(.mini)
            shot("03_mini")

            // 课堂抽查（主动要题）
            model.go(.listen)
            model.askCheckinNow()
            await wait("checkin 出题") { model.checkinData != nil }
            note("checkin=\(model.checkinData.map { "\($0.topic) / \($0.question) / \($0.options)" } ?? "-")")
            shot("04_checkin")
            model.answerCheckin(0)
            await wait("checkin 判分") { model.checkinFeedback != nil }
            note("checkin result=\(model.checkinFeedback.map { "\($0.result) ans=\($0.answer)" } ?? "-")")
            shot("05_checkin_result")
            extra("19_checkin_card", CheckinCardView(data: model.checkinData, preparing: false,
                                                     feedback: model.checkinFeedback, onAnswer: { _ in }, onClose: {}))
            model.skipCheckin()
            try? await Task.sleep(for: .seconds(1))

            // 再要一题，故意答错：走「判错 → 记进错题本」这条路径
            model.askCheckinNow()
            await wait("checkin 再出题", timeout: 60) { model.checkinData != nil }
            let wrong = (e.pendingCheckin?.answerIndex == 0) ? 1 : 0
            model.answerCheckin(wrong)
            await wait("checkin 答错判分") { model.checkinFeedback != nil }
            note("答错分支 result=\(model.checkinFeedback?.result ?? "-") 选了\(wrong) 正确=\(e.pendingCheckin?.answerIndex.map(String.init) ?? "已清空/记不下来") note=\(model.checkinFeedback?.explain.prefix(20) ?? "-")")
            shot("05b_checkin_wrong")
            model.skipCheckin()

            // 我掉队了 → 补课
            model.lost()
            await wait("breakpoint") { e.breakpoint != nil }
            note("bp=\(e.breakpoint.map { "\($0.breakpointTC) \($0.concept) / \($0.missing)" } ?? "-") slice=\(e.breakpointTimeline.map(\.topic))")
            shot("06_break")
            model.askBreakpoint("为什么分母是 P(B)？")
            await wait("追问") { !model.askBusy }
            note("追问 \(model.askAnswer.count) 字, err=\(model.askError ?? "-")")
            shot("07_break_ask")
            model.goLesson()
            shot("08_lesson")
            model.markFixed()

            // 问 Echo（ASK 页，带上下文流式回答）
            model.openAsk()
            model.askSend("老师刚讲的贝叶斯公式是什么意思？")
            await wait("ask 页回答", timeout: 60) { !model.askLoading }
            note("ask 页 \(model.askMessages.count) 条消息")
            shot("09_ask")

            model.endLesson()
            await wait("report", timeout: 60) { e.report != nil }
            note("report skills=\(e.report?.skills.map { "\($0.name):\($0.status)" } ?? []) chain=\(e.report?.reviewChain ?? [])")
            shot("10_echo")

            try? await Task.sleep(for: .seconds(1))
            model.showHome()
            note("stats lessons=\(model.stats.lessons) pending=\(model.stats.pending) mastered=\(model.stats.mastered) due=\(model.stats.due)")
            shot("11_home_after")

            model.mindmapFromReport()
            await wait("mindmap 数据") { !model.mindmap.nodes.isEmpty }
            note("mindmap nodes=\(model.mindmap.nodes.map(\.topic))")
            shot("12_mindmap")
            if let first = model.mindmap.nodes.first(where: { $0.status != "ok" }) ?? model.mindmap.nodes.first {
                model.mindmap.select(first.topic)
                await wait("mindmap 详情/出题", timeout: 60) { !model.mindmap.loadingQuestions }
                note("mindmap 详情 \(model.mindmap.detail?.topic ?? "-") 题 \(model.mindmap.questions.count)")
                shot("13_mindmap_detail")
            }

            model.showCourses()
            note("courses=\(model.courses.map(\.name))")
            shot("14_courses")
            if let c = model.courses.first {
                model.showDetail(c.id)
                note("detail=\(model.detail?.title ?? "-") skills=\(model.detail?.skills.count ?? 0) summary=\((model.detail?.summary ?? "").count) 字")
                shot("15_detail")
            }

            model.showProfile()
            note("profile=\(model.profile.displayName) sub=\(model.profile.sub) avatar=\(model.profile.hasCustomAvatar) due=\(model.stats.due)")
            shot("16_profile")

            model.showLearned()
            note("learned nodes=\(model.learnedGraph?.nodes.count ?? 0) subjects=\(model.learnedGraph?.subjects ?? [])")
            shot("16b_learned")

            model.showWeekly()
            note("weekly skills=\(model.weeklySkills.map(\.name))")
            shot("16c_weekly")

            // 造两个到期的知识点，让「讲给 Echo 听」有内容
            ReviewStore.add(ReviewStore.load(), relapse: true)
            model.refreshStore()
            note("到期 \(model.stats.due) 个，hint=\(model.dueHint)")
            model.startRecall()
            await wait("recall 出题", timeout: 60) { model.recallInputEnabled || !model.recallMessages.isEmpty }
            note("recall 开场=\(model.recallMessages.first?.text ?? "-")")
            shot("17_recall")
            model.recallSend("我的理解是：先看 B 发生之后样本空间变成 B，所以要把 A 交 B 的概率除以 P(B)。")
            try? await Task.sleep(for: .seconds(1))
            if model.recallInputEnabled {
                model.recallSend("换个场景的话，比如检测呈阳性求真患病的概率，就是用贝叶斯把先验和准确率一起算。")
            }
            await wait("recall 判定", timeout: 150) { model.recallShowGrades }
            note("recall 消息 \(model.recallMessages.count) 条")
            shot("18_recall_result")

            model.go(.listen)
            model.pet.say("这节课的回响好了，点我看", ms: 9000, mood: .done)
            extra("20_pet", DeskPetView(model: model, onDrag: {}, onDragEnd: {})
                .frame(width: DeskPetView.size.width, height: DeskPetView.size.height))

            // 侧边收起：验证窗口真的缩成小球并贴到右边缘
            let scr = NSScreen.main?.visibleFrame ?? .zero
            model.pet.setDue(1, panelVisible: false)   // 让角标显出来
            model.pet.dock(.right)
            extra("23_pet_docked", DeskPetView(model: model, onDrag: {}, onDragEnd: {}))   // 立刻渲染：收起态
            try? await Task.sleep(for: .milliseconds(400))
            let dockedPanel = NSApp.windows.first { $0.frame.width == 48 }
            note("挂边 收起 size=\(model.pet.petSize) panel=\(dockedPanel.map { NSStringFromRect($0.frame) } ?? "未找到48宽窗口") 屏幕右缘=\(scr.maxX)")
            model.pet.setHover(true)
            try? await Task.sleep(for: .milliseconds(400))
            let expandedPanel = NSApp.windows.first { $0.frame.width > 200 && $0.frame.width < 300 && $0.isVisible }
            note("挂边 悬停展开 size=\(model.pet.petSize) panel=\(expandedPanel.map { NSStringFromRect($0.frame) } ?? "-")")
            extra("24_pet_docked_expanded", DeskPetView(model: model, onDrag: {}, onDragEnd: {}))
            model.pet.setHover(false)
            model.pet.undock()
            extra("21_profile_setup", ProfileSetupView(onSave: { _ in nil }, onCancel: {}))
            let thumb = NSImage(named: "face_confused") ?? NSImage()
            extra("22_ask_panel", AskPanelView(model: AskPanelModel(session: AskSession(engine: e), thumb: thumb,
                                                                    onMarkWarn: {}), onClose: {}))
            note("done")
        }
    }
}
#endif
