//
//  MenuBar.swift
//  Echo — 菜单栏图标（对应 Windows 托盘）
//    · 图标：线稿猫头（模板图，跟随菜单栏深浅色）；分析中 / 有新结果时右下角带小点
//    · 菜单：主页、我掉队了、圈一下问 AI、下课、错题复习、新的一节课、离线模式、桌宠、设置、退出
//

import SwiftUI
import AppKit

struct MenuBarMenu: View {
    var model: AppModel
    var keys: [HotkeyAction: String]

    var body: some View {
        Text(statusLine)
        Divider()
        Button(model.panelVisible ? tr("隐藏 Echo", "Hide Echo") : tr("显示 Echo", "Show Echo")) { model.togglePanel() }
            .keyboardShortcut(for: keys[.toggle])
        Divider()
        Button(tr("⌂  主页", "⌂  Home")) { model.showHome(); model.showPanel() }   // 先切页再显示，避免窗口先冒出来再改大小
        Button(tr("我掉队了", "I'm lost"), action: model.lost).keyboardShortcut(for: keys[.lost])
        Button(tr("圈一下问 AI", "Circle to ask AI"), action: model.onCircleAsk).keyboardShortcut(for: keys[.circleAsk])
        Button(tr("下课，生成回响", "End class & generate echo"), action: model.endLesson)
        Button(tr("错题复习", "Review mistakes")) { model.showReview(); model.showPanel() }
        Button(tr("开始新的一节课", "Start a new lesson"), action: model.restart)
        Divider()
        Menu(tr("音频来源", "Audio source")) {
            ForEach([SourceKind.system, .mic, .demo], id: \.self) { s in
                Toggle(s.menuTitle, isOn: Binding(get: { model.source == s }, set: { if $0 { model.setSource(s) } }))
            }
        }
        Toggle(tr("离线模式（不调 AI）", "Offline mode (no AI calls)"), isOn: Binding(get: { model.engine.offline }, set: { model.engine.setOffline($0) }))
        Divider()
        Button(model.pet.visible ? tr("隐藏桌宠", "Hide desk pet") : tr("显示桌宠", "Show desk pet")) { model.pet.visible.toggle() }
        Button(tr("设置…", "Settings…"), action: model.onOpenSettings).keyboardShortcut(",")
        Button(tr("退出 Echo", "Quit Echo"), action: model.onQuit).keyboardShortcut("q")
    }

    private var statusLine: String {
        var parts = ["Echo", model.engine.status.label]
        if let t = model.engine.current?.topic, [.listening, .analyzing].contains(model.engine.status) {
            parts.append(tr("老师在讲：\(t)", "Now teaching: \(t)"))
        }
        if model.engine.offline { parts.append(tr("离线", "Offline")) }
        return parts.joined(separator: " · ")
    }
}

private extension View {
    /// 菜单项里显示全局快捷键（只是提示，真正的快捷键由 Hotkeys 注册）
    @ViewBuilder func keyboardShortcut(for name: String?) -> some View {
        if let name, let ch = name.last, name.hasPrefix("⌃⌥") {
            keyboardShortcut(KeyEquivalent(Character(ch.lowercased())), modifiers: [.control, .option])
        } else {
            self
        }
    }
}

extension SourceKind {
    var menuTitle: String {
        switch self {
        case .system: tr("电脑正在播放的声音", "Computer audio")
        case .mic: tr("麦克风", "Microphone")
        case .demo: tr("示例课（离线演示）", "Sample lesson (offline demo)")
        }
    }
}

/// 线稿猫头菜单栏图标。badge：nil / busy（空心点）/ alert（实心点）
enum MenuBarIcon {
    static func image(badge: String?) -> NSImage {
        let img = NSImage(size: NSSize(width: 18, height: 18), flipped: true) { rect in
            let k = rect.width / 32
            let t = NSAffineTransform()
            t.scale(by: k)
            t.concat()
            let head = NSBezierPath()
            head.move(to: NSPoint(x: 6.2, y: 13))
            head.line(to: NSPoint(x: 5, y: 3.6))
            head.line(to: NSPoint(x: 12, y: 8.4))
            head.curve(to: NSPoint(x: 20, y: 8.4), controlPoint1: NSPoint(x: 14.7, y: 7.7), controlPoint2: NSPoint(x: 17.3, y: 7.7))
            head.line(to: NSPoint(x: 27, y: 3.6))
            head.line(to: NSPoint(x: 25.8, y: 13))
            head.curve(to: NSPoint(x: 16, y: 28.2), controlPoint1: NSPoint(x: 28.8, y: 19.8), controlPoint2: NSPoint(x: 24.6, y: 28.2))
            head.curve(to: NSPoint(x: 6.2, y: 13), controlPoint1: NSPoint(x: 7.4, y: 28.2), controlPoint2: NSPoint(x: 3.2, y: 19.8))
            head.lineWidth = 2.6
            head.lineJoinStyle = .round
            head.lineCapStyle = .round
            NSColor.black.setStroke()
            head.stroke()
            NSColor.black.setFill()
            NSBezierPath(ovalIn: NSRect(x: 9.4, y: 15.4, width: 4, height: 4)).fill()
            NSBezierPath(ovalIn: NSRect(x: 18.6, y: 15.4, width: 4, height: 4)).fill()
            if let badge {
                let dot = NSBezierPath(ovalIn: NSRect(x: 21, y: 21, width: 10, height: 10))
                if badge == "alert" { dot.fill() } else { dot.lineWidth = 2.4; dot.stroke() }
            }
            return true
        }
        img.isTemplate = true
        return img
    }
}
