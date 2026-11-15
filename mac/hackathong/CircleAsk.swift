//
//  CircleAsk.swift
//  Echo — 「圈一下问 AI」
//
//    ① 截鼠标所在屏幕（ScreenCaptureKit，排除 Echo 自己的窗口），全屏变暗
//    ② 学生像截图工具一样：用画笔圈 / 荧光笔标 / 写文字批注（右键或 Esc 取消）
//    ③ 确认后，把圈过、批注过的区域截图 + 课堂上下文 → AskPanel 流式回答，可追问
//
//  画笔 / 批注真的画进截图里，AI 看到的就是学生圈的那张图。
//

import SwiftUI
import AppKit
import ScreenCaptureKit

private let snipColors: [(String, Color)] = [
    ("红", Color(red: 1, green: 0.30, blue: 0.31)), ("橙", Color(red: 0.98, green: 0.55, blue: 0.09)),
    ("黄", Color(red: 0.98, green: 0.86, blue: 0.08)), ("绿", Color(red: 0.32, green: 0.77, blue: 0.10)),
    ("蓝", Color(red: 0.09, green: 0.47, blue: 1)),
]
private let snipWidths: [(String, CGFloat)] = [("细", 3), ("中", 6), ("粗", 11)]

enum SnipTool { case pen, highlighter, text }

struct SnipStroke {
    var tool: SnipTool
    var color: Color
    var width: CGFloat
    var points: [CGPoint]
}

struct SnipNote {
    var pos: CGPoint
    var text: String
    var color: Color
}

@Observable
final class SnipModel {
    var tool: SnipTool = .pen
    var color = snipColors[0].1
    var width: CGFloat = 6
    var strokes: [SnipStroke] = []
    var notes: [SnipNote] = []
    var current: SnipStroke?
    var editingAt: CGPoint?
    var editingText = ""

    var hasMarks: Bool { !strokes.isEmpty || !notes.isEmpty }

    func undo() {
        if !notes.isEmpty { notes.removeLast() } else if !strokes.isEmpty { strokes.removeLast() }
    }

    func clear() {
        strokes.removeAll()
        notes.removeAll()
    }

    func commitText() {
        let t = editingText.trimmingCharacters(in: .whitespaces)
        if let p = editingAt, !t.isEmpty { notes.append(SnipNote(pos: p, text: t, color: color)) }
        editingAt = nil
        editingText = ""
        tool = .pen
    }

    /// 所有笔迹 + 批注的包围盒，加一点边距
    func bounds(in size: CGSize) -> CGRect {
        var r = CGRect.null
        for s in strokes {
            for p in s.points { r = r.union(CGRect(origin: p, size: .zero)) }
        }
        for n in notes {
            let w = CGFloat(n.text.count) * 15 + 16
            r = r.union(CGRect(x: n.pos.x, y: n.pos.y, width: w, height: 26))
        }
        guard !r.isNull else { return .null }
        return r.insetBy(dx: -48, dy: -48).offsetBy(dx: 0, dy: 6)
            .intersection(CGRect(origin: .zero, size: size))
    }
}

/// 笔迹和批注（屏幕预览和烧进截图共用）
struct SnipMarks: View {
    var model: SnipModel

    var body: some View {
        ZStack(alignment: .topLeading) {
            Canvas { g, _ in
                for s in model.strokes + (model.current.map { [$0] } ?? []) {
                    var p = Path()
                    p.addLines(s.points)
                    let hl = s.tool == .highlighter
                    g.stroke(p, with: .color(hl ? s.color.opacity(0.47) : s.color),
                             style: StrokeStyle(lineWidth: hl ? s.width * 3 : s.width, lineCap: .round, lineJoin: .round))
                }
            }
            ForEach(Array(model.notes.enumerated()), id: \.offset) { _, n in
                Text(n.text)
                    .font(.system(size: 15))
                    .foregroundStyle(Color(white: 0.1))
                    .fixedSize()
                    .padding(.horizontal, 6)
                    .padding(.vertical, 4)
                    .background(.white.opacity(0.88), in: .rect(cornerRadius: 6))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(n.color, lineWidth: 2))
                    .offset(x: n.pos.x, y: n.pos.y)
            }
        }
    }
}

// MARK: - ① 全屏圈选 + 批注

struct SnipOverlayView: View {
    var shot: NSImage
    var model: SnipModel
    var onCommit: (CGRect) -> Void
    var onCancel: () -> Void
    @FocusState private var noteFocused: Bool

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                Image(nsImage: shot).resizable().frame(width: geo.size.width, height: geo.size.height)
                Color.black.opacity(0.38)
                SnipMarks(model: model)
                Color.clear
                    .contentShape(.rect)
                    .gesture(DragGesture(minimumDistance: 0)
                        .onChanged { v in
                            guard model.editingAt == nil, model.tool != .text else { return }
                            if model.current == nil {
                                model.current = SnipStroke(tool: model.tool, color: model.color, width: model.width, points: [v.startLocation])
                            }
                            model.current?.points.append(v.location)
                        }
                        .onEnded { v in
                            if model.tool == .text {
                                if model.editingAt != nil { model.commitText() }
                                model.editingAt = v.location
                                model.tool = .text
                                noteFocused = true
                            } else if let s = model.current {
                                model.strokes.append(s)
                                model.current = nil
                            }
                        })
                    .contextMenu { Button("取消", action: onCancel) }
                if let p = model.editingAt {
                    TextField("写下你的问题…", text: Bindable(model).editingText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 15))
                        .foregroundStyle(Color(white: 0.1))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .frame(width: 260)
                        .background(.white, in: .rect(cornerRadius: 6))
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(model.color))
                        .focused($noteFocused)
                        .onSubmit { model.commitText() }
                        .offset(x: p.x, y: p.y)
                }
                VStack(spacing: 8) {
                    toolbar(size: geo.size)
                    Text(model.hasMarks ? "点「✓ 问 AI」让 Echo 讲解" : "用画笔圈出看不懂的地方，或点「批注」写下你的问题，再点「问 AI」")
                        .font(.system(size: 13))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 4)
                        .glassEffect(.regular.tint(.black.opacity(0.4)), in: .capsule)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 14)
            }
        }
        .ignoresSafeArea()
        .onExitCommand {
            if model.editingAt != nil { model.editingAt = nil } else { onCancel() }
        }
    }

    private func toolbar(size: CGSize) -> some View {
        GlassEffectContainer {
            HStack(spacing: 4) {
                toolButton(.pen, "画笔", "pencil.tip")
                toolButton(.highlighter, "荧光笔", "highlighter")
                toolButton(.text, "批注", "character.textbox")
                Divider().frame(height: 18).padding(.horizontal, 4)
                ForEach(snipColors, id: \.0) { name, c in
                    Button { model.color = c } label: {
                        Circle().fill(c).frame(width: 18, height: 18)
                            .overlay(Circle().stroke(.white, lineWidth: model.color == c ? 2 : 0))
                    }
                    .buttonStyle(.plain).help(name)
                }
                Divider().frame(height: 18).padding(.horizontal, 4)
                ForEach(snipWidths, id: \.0) { name, w in
                    Button { model.width = w } label: {
                        Circle().fill(.white).frame(width: 4 + w, height: 4 + w)
                            .frame(width: 26, height: 26)
                            .background(model.width == w ? .white.opacity(0.2) : .clear, in: .circle)
                    }
                    .buttonStyle(.plain).help("\(name)线（\(Int(w))px）")
                }
                Divider().frame(height: 18).padding(.horizontal, 4)
                Button("↶ 撤销", action: model.undo).buttonStyle(.plain).foregroundStyle(.white)
                Button("清空", action: model.clear).buttonStyle(.plain).foregroundStyle(.white).padding(.horizontal, 6)
                Button("取消", action: onCancel).buttonStyle(.plain).foregroundStyle(.white).padding(.trailing, 6)
                Button("✓ 问 AI") {
                    if model.editingAt != nil { model.commitText() }
                    let r = model.bounds(in: size)
                    if !r.isNull, r.width >= 16, r.height >= 16 { onCommit(r) }
                }
                .buttonStyle(.plain)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(model.hasMarks ? Color(red: 0.11, green: 0.08, blue: 0.02) : .white.opacity(0.5))
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
                .glassEffect(model.hasMarks ? .regular.tint(Palette.accent).interactive() : .regular, in: .capsule)
                .disabled(!model.hasMarks)
            }
            .font(.system(size: 13))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .glassEffect(.regular.tint(.black.opacity(0.55)), in: .capsule)
        }
        .fixedSize()
    }

    private func toolButton(_ t: SnipTool, _ label: String, _ icon: String) -> some View {
        Button { model.tool = t } label: {
            Label(label, systemImage: icon)
                .foregroundStyle(model.tool == t ? Color(red: 1, green: 0.82, blue: 0.54) : .white)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(model.tool == t ? Palette.accent.opacity(0.3) : .clear, in: .capsule)
        }
        .buttonStyle(.plain)
    }
}

/// 全屏覆盖窗口：Esc 取消
final class SnipWindow: NSWindow {
    var onEscape: () -> Void = {}
    override var canBecomeKey: Bool { true }
    override func cancelOperation(_ sender: Any?) { onEscape() }
}

// MARK: - ② 问答面板

@Observable
final class AskPanelModel {
    let session: AskSession
    let thumb: NSImage
    private(set) var turns: [(q: String, a: String, error: Bool)] = []
    private(set) var busy = false
    private(set) var marked = false
    private var task: Task<Void, Never>?
    let onMarkWarn: () -> Void

    init(session: AskSession, thumb: NSImage, onMarkWarn: @escaping () -> Void) {
        self.session = session
        self.thumb = thumb
        self.onMarkWarn = onMarkWarn
    }

    var lastAnswer: String { turns.last(where: { !$0.error })?.a ?? "" }

    func send(_ q: String) {
        let q = q.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !busy else { return }
        turns.append((q, "", false))
        busy = true
        let i = turns.count - 1
        task = Task {
            do {
                for try await d in session.ask(q) { turns[i].a += d }
            } catch {
                turns[i] = (q, "AI 暂时回答不了：\(error.localizedDescription)", true)
            }
            busy = false
        }
    }

    func markWarn() {
        onMarkWarn()
        marked = true
    }

    func cancel() {
        task?.cancel()
        session.cancel()
    }
}

struct AskPanelView: View {
    var model: AskPanelModel
    var onClose: () -> Void
    var onDrag: () -> Void = {}
    var onDragEnd: () -> Void = {}
    @State private var input = ""
    @FocusState private var focused: Bool

    /// 拖动面板（标题栏 / 缩略图都可以拖）
    private var drag: some Gesture {
        DragGesture(minimumDistance: 2)
            .onChanged { _ in onDrag() }
            .onEnded { _ in onDragEnd() }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(model.busy ? "Echo 正在看你圈的地方…" : "问问 Echo").font(.system(size: 14, weight: .semibold))
                Spacer()
                Button(action: onClose) { Image(systemName: "xmark") }.buttonStyle(IconButtonStyle())
            }
            .contentShape(.rect)
            .gesture(drag)
            Image(nsImage: model.thumb)
                .resizable().aspectRatio(contentMode: .fit)
                .frame(maxWidth: .infinity, maxHeight: 130)
                .padding(6)
                .background(Palette.codeBG.opacity(0.7), in: .rect(cornerRadius: 8))
                .contentShape(.rect)
                .gesture(drag)

            if model.turns.isEmpty {
                let qs = AskSession.quickQuestions
                Grid(horizontalSpacing: 6, verticalSpacing: 6) {
                    ForEach(Array(stride(from: 0, to: qs.count, by: 2)), id: \.self) { i in
                        GridRow {
                            ForEach(qs[i..<min(i + 2, qs.count)], id: \.self) { q in
                                Button(q) { model.send(q) }
                                    .buttonStyle(QuietButtonStyle(minHeight: 28))
                            }
                        }
                    }
                }
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array(model.turns.enumerated()), id: \.offset) { _, t in
                                Text("你：\(t.q)").font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(Palette.accent).padding(.top, 8).wrap()
                                Text(t.a.isEmpty ? "Echo 正在看你圈的地方…" : plain(t.a))
                                    .font(.system(size: 13))
                                    .foregroundStyle(t.error ? Palette.danger : t.a.isEmpty ? Palette.textSecondary : Palette.textPrimary)
                                    .lineSpacing(4)
                                    .textSelection(.enabled)
                                    .wrap()
                            }
                            Color.clear.frame(height: 1).id("end")
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(height: 300)
                    .onChange(of: model.turns.last?.a) { proxy.scrollTo("end", anchor: .bottom) }
                }
            }

            HStack(spacing: 8) {
                TextField(model.turns.isEmpty ? "想问什么？比如：为什么分母是 P(B)？" : "还有哪里不懂？接着问", text: $input)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Palette.surface.opacity(0.7), in: .rect(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(focused ? Palette.accent : Palette.border))
                    .focused($focused)
                    .onSubmit(send)
                Button("问", action: send)
                    .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 32))
                    .frame(width: 52)
                    .disabled(model.busy)
            }
            if !model.turns.isEmpty && !model.busy {
                HStack {
                    Button(model.marked ? "已记下 ✓" : "记为「有点懵」", action: model.markWarn)
                        .buttonStyle(LinkButtonStyle())
                        .disabled(model.marked)
                        .help("记到课堂时间轴，下课的回响里会提醒你复习")
                    Button("复制回答") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(model.lastAnswer, forType: .string)
                    }
                    .buttonStyle(LinkButtonStyle())
                    Spacer()
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 14)
        .frame(width: 400)
        .glassEffect(.regular, in: .rect(cornerRadius: 16))
        .fixedSize(horizontal: false, vertical: true)
        .onAppear { focused = true }
        .onExitCommand(perform: onClose)
    }

    private func send() {
        model.send(input)
        input = ""
    }
}

// MARK: - 入口

@MainActor
final class CircleAskController {
    private var overlay: SnipWindow?
    private var panels: [NSPanel] = []
    private var busy = false
    var engine: EchoEngine
    var onMarkWarn: () -> Void
    var onError: (String) -> Void

    init(engine: EchoEngine, onMarkWarn: @escaping () -> Void, onError: @escaping (String) -> Void) {
        self.engine = engine
        self.onMarkWarn = onMarkWarn
        self.onError = onError
    }

    func start() {
        guard !busy else { return }
        busy = true
        let screen = NSScreen.screens.first { NSMouseInRect(NSEvent.mouseLocation, $0.frame, false) } ?? NSScreen.main!
        Task {
            do {
                let shot = try await capture(screen)
                showOverlay(shot, on: screen)
            } catch {
                busy = false
                onError("截屏失败：请在「系统设置 → 隐私与安全性 → 屏幕与系统录音」里允许 Echo（\(error.localizedDescription)）")
            }
        }
    }

    /// 截整块屏幕，排除 Echo 自己的窗口（不用先把面板 / 桌宠藏起来）
    private func capture(_ screen: NSScreen) async throws -> CGImage {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
        guard let display = content.displays.first(where: { $0.displayID == id }) ?? content.displays.first else {
            throw CocoaError(.featureUnsupported)
        }
        let me = content.applications.filter { $0.processID == ProcessInfo.processInfo.processIdentifier }
        let filter = SCContentFilter(display: display, excludingApplications: me, exceptingWindows: [])
        let cfg = SCStreamConfiguration()
        cfg.width = Int(screen.frame.width * screen.backingScaleFactor)
        cfg.height = Int(screen.frame.height * screen.backingScaleFactor)
        cfg.showsCursor = false
        return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg)
    }

    private func showOverlay(_ shot: CGImage, on screen: NSScreen) {
        let model = SnipModel()
        let image = NSImage(cgImage: shot, size: screen.frame.size)
        let w = SnipWindow(contentRect: screen.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        w.level = .screenSaver
        w.isOpaque = true
        w.backgroundColor = .black
        w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        w.isReleasedWhenClosed = false
        let cancel: () -> Void = { [weak self] in self?.closeOverlay() }
        w.onEscape = cancel
        w.contentView = NSHostingView(rootView: SnipOverlayView(shot: image, model: model, onCommit: { [weak self] rect in
            self?.commit(rect, model: model, shot: shot, screen: screen)
        }, onCancel: cancel))
        w.setFrame(screen.frame, display: true)
        NSApp.activate()
        w.makeKeyAndOrderFront(nil)
        overlay = w
    }

    private func closeOverlay() {
        overlay?.orderOut(nil)
        overlay = nil
        busy = false
    }

    private func commit(_ rect: CGRect, model: SnipModel, shot: CGImage, screen: NSScreen) {
        let png = render(rect, model: model, shot: shot, scale: screen.backingScaleFactor)
        closeOverlay()
        guard let png, let thumb = NSImage(data: png) else { return }
        // 视图坐标（左上原点）→ 屏幕坐标（左下原点）
        let anchor = CGRect(x: screen.frame.minX + rect.minX, y: screen.frame.maxY - rect.maxY,
                            width: rect.width, height: rect.height)
        showPanel(png: png, thumb: thumb, anchor: anchor, screen: screen)
    }

    /// 把圈过的区域连同笔迹 / 批注一起渲染成 PNG（最长边不超过 1600px）
    private func render(_ rect: CGRect, model: SnipModel, shot: CGImage, scale: CGFloat) -> Data? {
        let px = CGRect(x: rect.minX * scale, y: rect.minY * scale, width: rect.width * scale, height: rect.height * scale)
        guard let crop = shot.cropping(to: px) else { return nil }
        let view = ZStack(alignment: .topLeading) {
            Image(decorative: crop, scale: scale)
            SnipMarks(model: model).offset(x: -rect.minX, y: -rect.minY)
        }
        .frame(width: rect.width, height: rect.height, alignment: .topLeading)
        .clipped()
        let r = ImageRenderer(content: view)
        r.scale = min(scale, 1600 / max(rect.width, rect.height))
        guard let cg = r.cgImage else { return nil }
        return NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])
    }

    private func showPanel(png: Data, thumb: NSImage, anchor: CGRect, screen: NSScreen) {
        let session = AskSession(engine: engine, image: png)
        let model = AskPanelModel(session: session, thumb: thumb, onMarkWarn: onMarkWarn)
        let panel = FloatingPanel(movableByBackground: true)
        panel.anchor = .top
        weak var weakPanel = panel
        panel.setRoot(AskPanelView(model: model, onClose: { [weak self] in
            model.cancel()
            guard let p = weakPanel else { return }
            p.orderOut(nil)
            self?.panels.removeAll { $0 === p }
        }, onDrag: { weakPanel?.dragStep() }, onDragEnd: { weakPanel?.dragAnchor = nil }))
        // 放在圈选区域右边，放不下就放左边
        let g = screen.visibleFrame
        var x = anchor.maxX + 8
        if x + panel.frame.width > g.maxX { x = anchor.minX - panel.frame.width - 8 }
        x = max(g.minX, min(x, g.maxX - panel.frame.width))
        let top = min(anchor.maxY + 14, g.maxY)
        panel.setFrameTopLeftPoint(NSPoint(x: x, y: max(top, g.minY + panel.frame.height)))
        panel.makeKeyAndOrderFront(nil)
        panels.append(panel)
    }
}
