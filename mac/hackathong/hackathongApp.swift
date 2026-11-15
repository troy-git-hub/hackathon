//
//  hackathongApp.swift
//  Echo — 网课里的 AI 学习副驾驶
//
//  菜单栏常驻（对应 Windows 托盘）+ 液态玻璃悬浮面板 + 桌宠 + 全局快捷键。
//  面板不抢焦点（网课窗口保持激活）、始终置顶、全屏会议上也能显示、整张卡片可拖动。
//

import SwiftUI
import AppKit
import UserNotifications

@main
struct hackathongApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var app

    var body: some Scene {
        MenuBarExtra {
            MenuBarMenu(model: app.model, keys: app.hotkeys?.names ?? [:])
        } label: {
            Image(nsImage: MenuBarIcon.image(badge: app.model.pending != nil ? "alert"
                                             : app.model.engine.status.isBusy ? "busy" : nil))
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, UNUserNotificationCenterDelegate {
    let engine = EchoEngine()
    lazy var model = AppModel(engine: engine, source: EchoConfig.source)
    private(set) var hotkeys: Hotkeys?
    private var panel: FloatingPanel!
    private var petPanel: FloatingPanel!
    private var petDrag: (mouse: NSPoint, origin: NSPoint)?
    private var panelDrag: (mouse: NSPoint, origin: NSPoint)?
    private var petY: CGFloat?
    private var circleAsk: CircleAskController!
    private var settings: NSWindow?
    private var setupWindow: NSWindow?
    private var setupFinishing = false
    private var dueTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)   // 不占 Dock，常驻菜单栏
        let model = model

        // 主面板：屏幕中央
        panel = FloatingPanel(movableByBackground: true)
        panel.setRoot(RootView(model: model))
        if let scr = NSScreen.main?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: scr.midX - panel.frame.width / 2, y: scr.midY - panel.frame.height / 2))
        }
        panel.orderFrontRegardless()

        // 桌宠：屏幕右下角，主面板左边
        petPanel = FloatingPanel(movableByBackground: false)
        petPanel.anchor = .none
        petPanel.setRoot(DeskPetView(model: model, onDrag: { [weak self] in self?.dragPet() },
                                     onDragEnd: { [weak self] in self?.endPetDrag() }))
        if let scr = NSScreen.main?.visibleFrame {
            let x = min(panel.frame.minX - petPanel.frame.width + 30, scr.maxX - petPanel.frame.width - 12)
            petPanel.setFrameOrigin(NSPoint(x: max(scr.minX, x), y: scr.minY + 4))
        }
        petPanel.orderFrontRegardless()

        circleAsk = CircleAskController(engine: engine,
                                        onMarkWarn: { model.feedback(.warn) },
                                        onError: { msg in model.pet.say(msg, ms: 6000, mood: .warn) })

        model.onShowPanel = { [weak self] in
            self?.panel.orderFrontRegardless()
            model.setPanelVisible(true)
            model.pet.clearBadge()
        }
        model.onHidePanel = { [weak self] in
            self?.panel.orderOut(nil)
            model.setPanelVisible(false)
        }
        model.onCircleAsk = { [weak self] in self?.circleAsk.start() }
        model.onOpenSettings = { [weak self] in self?.openSettings() }
        model.onQuit = { NSApp.terminate(nil) }
        model.onDragPanel = { [weak self] in
            guard let self else { return }
            let mouse = NSEvent.mouseLocation
            if panelDrag == nil { panelDrag = (mouse, panel.frame.origin) }
            guard let d = panelDrag else { return }
            panel.setFrameOrigin(NSPoint(x: d.origin.x + mouse.x - d.mouse.x, y: d.origin.y + mouse.y - d.mouse.y))
        }
        model.onDragPanelEnd = { [weak self] in self?.panelDrag = nil }

        hotkeys = Hotkeys { action in
            switch action {
            case .lost: model.lost()
            case .toggle: model.togglePanel()
            case .circleAsk: model.onCircleAsk()
            }
        }

        let nc = UNUserNotificationCenter.current()
        nc.delegate = self
        nc.requestAuthorization(options: [.alert, .sound]) { _, _ in }

        // 开机问候（带名字）+ 每 15 秒看一眼今天该回响几个
        #if DEBUG
        let skipSetupForSnapshot = DebugSnapshot.enabled
        #else
        let skipSetupForSnapshot = false
        #endif
        // 第一次用：先认识（填资料），填完才出主页。填过、或上次点了「以后再说」，就直接进主页。
        if needsSetup(skip: skipSetupForSnapshot) {
            panel.orderOut(nil)
            petPanel.orderOut(nil)
            showProfileSetup()
        } else {
            model.pet.greet()
            beginLesson()
        }
        pollDue()
        dueTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            self?.pollDue()
        }
        watchPetVisibility()
        watchPetDock()
        #if DEBUG
        if DebugSnapshot.enabled {
            model.source = .demo
            DebugSnapshot.run(model)
            return
        }
        DebugSnapshot.probe(engine)
        #endif
    }

    /// 还没填过资料、也没点过「以后再说」→ 这次先弹认识窗
    private func needsSetup(skip: Bool) -> Bool {
        if skip { return false }                                  // 自检模式不问
        if ProfileStore.exists() { return false }                 // 填过了就不再问
        return !UserDefaults.standard.bool(forKey: "profileSetupSkipped")
    }

    /// 认识完了 / 跳过了：亮出主页和桌宠，开始上课
    private func beginLesson() {
        if setupWindow == nil { NSApp.setActivationPolicy(.accessory) }   // 认识完了就收回菜单栏
        panel.orderFrontRegardless()
        model.setPanelVisible(true)
        if model.pet.visible { petPanel.orderFrontRegardless() }
        if model.source == .system && !CGPreflightScreenCaptureAccess() {
            requestScreenCaptureThenStart()
        } else {
            engine.start(source: model.source)
        }
    }

    /// 抓系统声音要「屏幕与系统录音」权限。菜单栏 app 不激活时弹窗出不来，
    /// 临时切成 regular 并强激活，等用户允许后自动重开一节课，再收回菜单栏。
    private func requestScreenCaptureThenStart() {
        NSApp.setActivationPolicy(.regular)
        NSRunningApplication.current.activate(options: [.activateIgnoringOtherApps])
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
            CGRequestScreenCaptureAccess()
        }
        Task { @MainActor in
            for _ in 0..<300 {   // 最多等 5 分钟
                if CGPreflightScreenCaptureAccess() {
                    NSApp.setActivationPolicy(.accessory)
                    model.restart()
                    return
                }
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        hotkeys?.unregister()
        engine.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    // 点通知：打开面板
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await MainActor.run { model.showPanel() }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner]
    }

    private func dragPet() {
        let mouse = NSEvent.mouseLocation
        if model.pet.docked {          // 开始拖动：先把收起的小球展开，按展开后的尺寸居中到鼠标
            model.pet.undock()
            petPanel.setFrameOrigin(NSPoint(x: mouse.x - PetModel.deskW / 2,
                                            y: mouse.y - PetModel.deskH / 2))
            petDrag = nil              // 展开后大小变了，重新记起点
        }
        if petDrag == nil { petDrag = (mouse, petPanel.frame.origin) }
        guard let d = petDrag else { return }
        petPanel.setFrameOrigin(NSPoint(x: d.origin.x + mouse.x - d.mouse.x, y: d.origin.y + mouse.y - d.mouse.y))
        clampPetPanel()
    }

    /// 拖完松手：鼠标松在屏幕最边上才收起（按鼠标位置判定 —— 按窗口边缘算的话，
    /// 从贴边状态拖出来一松手就会被重新吸回去）
    private func endPetDrag() {
        petDrag = nil
        guard let scr = petPanel.screen?.visibleFrame ?? NSScreen.main?.visibleFrame else { return }
        let mouse = NSEvent.mouseLocation
        let edge: CGFloat = 14
        if mouse.x - scr.minX < edge {
            model.pet.dock(.left)
        } else if scr.maxX - mouse.x < edge {
            model.pet.dock(.right)
        } else {
            model.pet.undock()
        }
        petY = petPanel.frame.minY
        clampPetPanel()
        layoutPetPanel()
    }

    /// 别让桌宠被拖出屏幕
    private func clampPetPanel() {
        guard let scr = petPanel.screen?.visibleFrame ?? NSScreen.main?.visibleFrame else { return }
        var f = petPanel.frame
        f.origin.x = min(max(f.origin.x, scr.minX), scr.maxX - f.width)
        f.origin.y = min(max(f.origin.y, scr.minY), scr.maxY - f.height)
        if f.origin != petPanel.frame.origin { petPanel.setFrame(f, display: true) }
    }

    /// 挂边后把小球贴死在边缘，竖直方向不跑出屏；悬停展开时朝屏幕内长
    private func layoutPetPanel() {
        guard let scr = petPanel.screen?.visibleFrame ?? NSScreen.main?.visibleFrame else { return }
        guard model.pet.docked else { return }
        petPanel.layoutIfNeeded()
        let s = petPanel.frame.size
        let y = min(max(petY ?? petPanel.frame.minY, scr.minY), scr.maxY - s.height)
        petY = y
        let x = model.pet.dockSide == .left ? scr.minX : scr.maxX - s.width
        petPanel.setFrameOrigin(NSPoint(x: x, y: y))
    }

    /// 挂边状态（收起 / 悬停展开）变化后重新贴边
    private func watchPetDock() {
        Task { [weak self] in
            guard let self else { return }
            for await _ in Observations({ (self.model.pet.docked, self.model.pet.dockSide, self.model.pet.hoverExpanded) }) {
                try? await Task.sleep(for: .milliseconds(30))   // 等窗口跟着内容改完大小
                layoutPetPanel()
            }
        }
    }

    private func pollDue() {
        model.pet.setDue(ReviewStore.dueSummary().due, panelVisible: model.panelVisible)
    }

    /// 首次登录：填资料（关掉就退出，下次启动再问）
    private func showProfileSetup() {
        let w = NSWindow(contentRect: .zero, styleMask: [.titled, .closable], backing: .buffered, defer: false)
        w.title = tr("欢迎使用 Echo", "Welcome to Echo")
        w.isReleasedWhenClosed = false
        w.delegate = self
        w.contentView = NSHostingView(rootView: ProfileSetupView(
            onSave: { [weak self] data in self?.model.saveProfileSetup(data) },
            onDone: { [weak self] in
                guard let self else { return }
                setupFinishing = true
                setupWindow?.close()
                setupWindow = nil
                model.pet.greet()
                beginLesson()
            },
            onCancel: { [weak self] in self?.skipSetup() }))
        w.center()
        setupWindow = w
        // 菜单栏 app 默认不激活，弹窗会被压在别的窗口后面；先切成普通 app 抢到前台
        NSApp.setActivationPolicy(.regular)
        NSRunningApplication.current.activate(options: [.activateIgnoringOtherApps])
        w.makeKeyAndOrderFront(nil)
    }

    func windowWillClose(_ notification: Notification) {
        guard let w = notification.object as? NSWindow, w === setupWindow, !setupFinishing else { return }
        skipSetup()   // 直接关窗：不退出、也不再每次弹
    }

    /// 「以后再说」：记一个标记，下次启动直接进主页（用户名可以之后在设置里改）
    private func skipSetup() {
        UserDefaults.standard.set(true, forKey: "profileSetupSkipped")
        setupFinishing = true
        setupWindow?.close()
        setupWindow = nil
        model.pet.greet()
        beginLesson()
    }

    private func watchPetVisibility() {
        Task { [weak self] in
            guard let self else { return }
            for await v in Observations({ self.model.pet.visible }) {
                if v { petPanel.orderFrontRegardless() } else { petPanel.orderOut(nil) }
            }
        }
    }

    private func openSettings() {
        if settings == nil {
            let w = NSWindow(contentRect: .zero, styleMask: [.titled, .closable], backing: .buffered, defer: false)
            w.title = "Echo 设置"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: SettingsView(
                onSave: { [weak self] s in self?.model.source = s },
                onClose: { [weak w] in w?.close() }))
            w.center()
            settings = w
        }
        NSApp.activate()
        if model.source == .system && !CGPreflightScreenCaptureAccess() {
            CGRequestScreenCaptureAccess()   // 把 Echo 加进「屏幕与系统录音」列表并弹窗
        }
        settings?.makeKeyAndOrderFront(nil)
    }
}

/// 无边框悬浮面板：不抢焦点、置顶、所有桌面空间可见；内容变大小时按 anchor 保持位置
final class FloatingPanel: NSPanel {
    enum Anchor {
        case center   // 默认保持中心不动，贴近屏幕边缘时改贴该边（主面板）
        case top      // 保持顶边不动（问答面板）
        case none
    }

    var anchor: Anchor = .center
    /// 拖动时的起点（鼠标按下位置 + 当时窗口原点）
    var dragAnchor: (mouse: NSPoint, origin: NSPoint)?

    /// 按全局鼠标位置移动窗口（窗口跟着动时，SwiftUI 的 translation 会抖）
    func dragStep() {
        let mouse = NSEvent.mouseLocation
        if dragAnchor == nil { dragAnchor = (mouse, frame.origin) }
        guard let d = dragAnchor else { return }
        setFrameOrigin(NSPoint(x: d.origin.x + mouse.x - d.mouse.x, y: d.origin.y + mouse.y - d.mouse.y))
    }
    var anchorCenter: Bool {
        get { anchor == .center }
        set { anchor = newValue ? .center : .top }
    }

    init(movableByBackground: Bool) {
        super.init(contentRect: NSRect(x: 0, y: 0, width: 380, height: 300),
                   styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
                   backing: .buffered, defer: false)
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        isFloatingPanel = true
        hidesOnDeactivate = false
        isMovableByWindowBackground = movableByBackground
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        isReleasedWhenClosed = false
    }

    override var canBecomeKey: Bool { true }

    func setRoot<V: View>(_ view: V) {
        let host = NSHostingView(rootView: view)
        host.sizingOptions = [.intrinsicContentSize]
        contentView = host
        setContentSize(host.fittingSize)
        invalidateShadow()
    }

    override func setFrame(_ frameRect: NSRect, display flag: Bool) {
        var r = frameRect
        let old = frame
        if anchor != .none, old.size != .zero, r.size != old.size, isVisible,
           let scr = (screen ?? NSScreen.main)?.visibleFrame {
            switch anchor {
            case .center:
                let edge: CGFloat = 40
                let nearR = old.maxX > scr.maxX - edge, nearL = old.minX < scr.minX + edge
                let nearB = old.minY < scr.minY + edge, nearT = old.maxY > scr.maxY - edge
                r.origin.x = nearR && !nearL ? old.maxX - r.width : nearL && !nearR ? old.minX : old.midX - r.width / 2
                r.origin.y = nearB && !nearT ? old.minY : nearT && !nearB ? old.maxY - r.height : old.midY - r.height / 2
            case .top:
                r.origin.x = old.minX
                r.origin.y = old.maxY - r.height
            case .none:
                break
            }
            r.origin.x = max(scr.minX, min(r.origin.x, scr.maxX - r.width))
            r.origin.y = max(scr.minY, min(r.origin.y, scr.maxY - r.height))
        }
        super.setFrame(r, display: flag)
        invalidateShadow()
    }
}
