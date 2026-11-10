//
//  Theme.swift
//  Echo — 学习工具风格：中性底 + 唯一强调色（琥珀）只给「掉队/断点」，绿色只做弱提示
//  深浅色跟随系统；窗口和按钮用 macOS 液态玻璃（Liquid Glass）。
//

import SwiftUI
import AppKit

extension Color {
    /// 浅色 / 深色两套十六进制值，随系统外观切换
    init(light: UInt32, dark: UInt32) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return NSColor(hex: isDark ? dark : light)
        })
    }
}

extension NSColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                  green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255,
                  alpha: alpha)
    }
}

enum Palette {
    static let windowBG      = Color(light: 0xFBFBFA, dark: 0x1C1D21)
    static let windowBorder  = Color(light: 0xE3E3E0, dark: 0x2E3036)
    static let surface       = Color(light: 0xFFFFFF, dark: 0x24262B)
    static let surfaceHover  = Color(light: 0xF4F4F2, dark: 0x2B2D33)
    static let border        = Color(light: 0xE6E6E3, dark: 0x32343A)
    static let borderStrong  = Color(light: 0xD4D4D0, dark: 0x3E4047)
    static let codeBG        = Color(light: 0xF2F2EF, dark: 0x16171A)
    static let textPrimary   = Color(light: 0x1D1E20, dark: 0xECEDEF)
    static let textSecondary = Color(light: 0x6B6D72, dark: 0x9EA1A8)
    static let textDisabled  = Color(light: 0xA8AAAE, dark: 0x63666D)
    static let accent        = Color(light: 0xD9861A, dark: 0xF2A93B)
    static let accentSoft    = Color(light: 0xFCF1E0, dark: 0x2F2619)
    static let accentBorder  = Color(light: 0xEFCB92, dark: 0x6B4F22)
    static let onAccent      = Color(light: 0xFFFFFF, dark: 0x1B1406)
    static let okFG          = Color(light: 0x3E8E50, dark: 0x8CC79A)
    static let okSoft        = Color(light: 0xEAF5EC, dark: 0x1F2B23)
    static let nowFG         = Color(light: 0x1D1E20, dark: 0xECEDEF)
    static let danger        = Color(light: 0xD13438, dark: 0xFF6B6B)
    static let dangerBG      = Color(light: 0xFDE7E9, dark: 0x4A2426)
    static let primary       = Color(light: 0x0078D4, dark: 0x4CC2FF)
}

enum Spacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
}

enum Radius {
    static let sm: CGFloat = 4
    static let md: CGFloat = 10
    static let lg: CGFloat = 14
    static let window: CGFloat = 22
}

// MARK: - 按钮（液态玻璃）

/// 主操作：琥珀色玻璃（我掉队了 / 30 秒补上 / 开始今天的学习）
struct AccentButtonStyle: ButtonStyle {
    var fontSize: CGFloat = 15
    var minHeight: CGFloat = 44
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: fontSize, weight: .bold))
            .foregroundStyle(isEnabled ? .white : Palette.textDisabled)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity, minHeight: minHeight)
            .contentShape(.rect(cornerRadius: Radius.md))
            .glassEffect(isEnabled ? .regular.tint(Palette.accent).interactive() : .regular,
                         in: .rect(cornerRadius: Radius.md))
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.snappy(duration: 0.15), value: configuration.isPressed)
    }
}

/// 深色实心：「补上了，回到课堂」
struct SolidButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .bold))
            .foregroundStyle(Palette.windowBG)
            .frame(maxWidth: .infinity, minHeight: 42)
            .contentShape(.rect(cornerRadius: Radius.md))
            .glassEffect(.regular.tint(Palette.textPrimary.opacity(0.9)).interactive(), in: .rect(cornerRadius: Radius.md))
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
    }
}

/// 次要操作：无色玻璃（跟上了 / 有点懵 / 去复习 …）
struct QuietButtonStyle: ButtonStyle {
    var minHeight: CGFloat = 32
    var expand = true
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13))
            .foregroundStyle(isEnabled ? Palette.textPrimary : Palette.textDisabled)
            .padding(.horizontal, 12)
            .frame(maxWidth: expand ? .infinity : nil, minHeight: minHeight)
            .contentShape(.rect(cornerRadius: Radius.md))
            .glassEffect(isEnabled ? .regular.interactive() : .regular, in: .rect(cornerRadius: Radius.md))
            .opacity(isEnabled ? 1 : 0.6)
    }
}

struct LinkButtonStyle: ButtonStyle {
    @State private var hover = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13))
            .foregroundStyle(hover ? Palette.textPrimary : Palette.textSecondary)
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            .contentShape(.rect)
            .onHover { hover = $0 }
    }
}

struct IconButtonStyle: ButtonStyle {
    @State private var hover = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(hover ? Palette.textPrimary : Palette.textSecondary)
            .frame(width: 24, height: 24)
            .background(hover ? Palette.textPrimary.opacity(0.08) : .clear, in: .circle)
            .contentShape(.circle)
            .onHover { hover = $0 }
    }
}

// MARK: - 文字 / 卡片

extension View {
    func caption() -> some View {
        font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
    }

    func pageTitle() -> some View {
        font(.system(size: 17, weight: .bold)).foregroundStyle(Palette.textPrimary)
    }

    /// 玻璃上的半透明卡片
    func card(border: Color = Palette.border, padding: CGFloat = Spacing.lg) -> some View {
        self.padding(.horizontal, padding)
            .padding(.vertical, Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface.opacity(0.55), in: .rect(cornerRadius: Radius.md))
            .overlay(RoundedRectangle(cornerRadius: Radius.md).strokeBorder(border.opacity(0.8)))
    }

    /// 文字自动换行（SwiftUI 在 fixedSize 窗口里默认会把长文本截断）
    func wrap() -> some View {
        fixedSize(horizontal: false, vertical: true)
    }
}
