//
//  ChatPages.swift
//  Echo — 对话页：问 Echo（ASK）与「讲给 Echo 听」（RECALL）
//  两者共用同一套气泡样式（对应 floating_window 的 _bubble）。
//

import SwiftUI

struct ChatMessage: Identifiable, Equatable {
    enum Kind { case echo, me, note }
    var id = UUID()
    var kind: Kind
    var text: String
    var label: String?
    var tone: String?        // "ok" 绿边 / "warn" 红边
}

/// 单个气泡
struct ChatBubbleView: View {
    var message: ChatMessage

    var body: some View {
        HStack {
            if message.kind == .me { Spacer(minLength: 0) }
            VStack(alignment: .leading, spacing: 2) {
                if let l = message.label, !l.isEmpty {
                    Text(l).font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(message.kind == .echo ? Palette.accent : Palette.textSecondary)
                }
                Text(message.text).font(.system(size: 13))
                    .foregroundStyle(message.kind == .me ? Palette.windowBG : Palette.textPrimary)
                    .lineSpacing(3)
                    .textSelection(.enabled)
                    .wrap()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(bg, in: .rect(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(border))
            .frame(maxWidth: 196, alignment: message.kind == .me ? .trailing : .leading)
            if message.kind != .me { Spacer(minLength: 0) }
        }
    }

    private var bg: Color {
        switch message.kind {
        case .echo: Palette.accentSoft
        case .me: Palette.accent
        case .note: Palette.codeBG
        }
    }

    private var border: Color {
        if message.tone == "ok" { return Palette.okFG }
        if message.tone == "warn" { return Palette.danger }
        return message.kind == .echo ? Palette.accentBorder : Palette.border
    }
}

/// 对话区 + 输入行（RECALL / ASK 共用）
struct ChatPanel: View {
    var messages: [ChatMessage]
    var loading: Bool
    var loadingText: String
    var placeholder: String
    var sendTitle: String
    var inputEnabled: Bool
    var enableMic: Bool = false
    var onSend: (String) -> Void
    @State private var input = ""
    @State private var micPlaceholder: String?

    /// 自检截图时 ImageRenderer 画不出 ScrollView 里的内容，直接平铺
    private var flat: Bool {
        #if DEBUG
        return DebugSnapshot.enabled
        #else
        return false
        #endif
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            if flat {
                chatList
            } else {
                ScrollViewReader { proxy in
                    ScrollView { chatList }
                        .frame(height: 240)
                        .onChange(of: messages.count) { proxy.scrollTo("end", anchor: .bottom) }
                        .onChange(of: messages.last?.text) { proxy.scrollTo("end", anchor: .bottom) }
                }
            }
            HStack(spacing: Spacing.sm) {
                TextField(micPlaceholder ?? placeholder, text: $input)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(Palette.surface.opacity(0.7), in: .rect(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.border))
                    .disabled(!inputEnabled)
                    .onSubmit(send)
                if enableMic {
                    MicButton(overridePlaceholder: $micPlaceholder) { input = $0 }
                        .disabled(!inputEnabled)
                }
                Button(sendTitle, action: send)
                    .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 32))
                    .frame(width: 64)
                    .disabled(!inputEnabled)
            }
        }
    }

    private var chatList: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(messages) { m in
                ChatBubbleView(message: m)
            }
            if loading {
                HStack(spacing: Spacing.sm) {
                    PulseDots(color: Palette.accent)
                    Text(loadingText).font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
                }
            }
            Color.clear.frame(height: 1).id("end")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func send() {
        let t = input.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty, inputEnabled else { return }
        input = ""
        onSend(t)
    }
}

// MARK: - 问 Echo

struct AskPage: View {
    var messages: [ChatMessage]
    var loading: Bool
    var onSend: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("问 Echo", "Ask Echo")).pageTitle()
                Text(tr("带着这节课的上下文回答；课后回来还能接着问",
                        "Answered with this lesson's context — resumable after class")).caption().wrap()
            }
            ChatPanel(messages: messages, loading: loading,
                      loadingText: tr("Echo 在想…", "Echo is thinking…"),
                      placeholder: tr("比如：老师刚说的「虚拟语气」是什么意思？", "e.g. what does \"subjunctive\" mean here?"),
                      sendTitle: tr("发送", "Send"), inputEnabled: true, onSend: onSend)
        }
    }
}

// MARK: - 讲给 Echo 听

struct RecallPage: View {
    var subtitle: String
    var messages: [ChatMessage]
    var loading: Bool
    var loadingText: String
    var placeholder: String
    var inputEnabled: Bool
    var showGrades: Bool
    var currentGrade: String
    var onSend: (String) -> Void
    var onGrade: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("讲给 Echo 听", "Talk it through with Echo")).pageTitle()
                Text(subtitle).caption().wrap()
            }
            ChatPanel(messages: messages, loading: loading, loadingText: loadingText,
                      placeholder: placeholder,
                      sendTitle: tr("发送", "Send"), inputEnabled: inputEnabled, enableMic: true, onSend: onSend)
            if showGrades {
                VStack(alignment: .leading, spacing: 6) {
                    Text(tr("我判得不准？点一下自己改，下次复习时间跟着变。",
                            "Got it wrong? Tap to set it yourself — the next review follows your call."))
                        .font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
                    HStack(spacing: Spacing.sm) {
                        gradeButton("clear", tr("清楚", "Clear"))
                        gradeButton("fuzzy", tr("模糊", "Fuzzy"))
                        gradeButton("unclear", tr("没理解", "Lost"))
                    }
                }
            }
        }
    }

    private func gradeButton(_ value: String, _ title: String) -> some View {
        let on = currentGrade == value
        return Button {
            onGrade(value)
        } label: {
            Text((on ? "● " : "") + title).font(.system(size: 13))
        }
        .buttonStyle(QuietButtonStyle(expand: false))
        .help(tr("改成这一档", "Set this instead"))
    }
}

// MARK: - 语音输入（讲给 Echo 听 / 断点追问共用）

/// 按一下说话：转成文字填进输入框，不自动发送。文案通过 overridePlaceholder 临时盖掉输入框占位符。
struct MicButton: View {
    @Binding var overridePlaceholder: String?
    var onText: (String) -> Void

    @State private var recorder = VoiceInputRecorder()
    @State private var recording = false
    @State private var busy = false

    var body: some View {
        Button(action: tap) {
            Text(recording ? "●" : tr("说", "Speak"))
                .font(.system(size: 13, weight: recording ? .bold : .regular))
                .foregroundStyle(recording ? Palette.danger : Palette.textPrimary)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(QuietButtonStyle(minHeight: 32))
        .frame(width: 40)
        .disabled(busy)
        .help(tr("按一下说话，Echo 把你说的话转成文字（不会自动发送）",
                 "Tap to speak — Echo turns it into text (it won't send automatically)"))
    }

    private func tap() {
        if recording {
            recording = false
            busy = true
            overridePlaceholder = tr("转写中…", "Transcribing…")
            Task {
                let text = await recorder.stopAndTranscribe()
                busy = false
                if text.isEmpty {
                    overridePlaceholder = tr("没听清，再说一次，或者直接打字", "Didn't catch that — try again or just type")
                    try? await Task.sleep(for: .seconds(2.5))
                    overridePlaceholder = nil
                } else {
                    overridePlaceholder = nil
                    onText(text)
                }
            }
        } else {
            Task {
                do {
                    try await recorder.start()
                    recording = true
                    overridePlaceholder = tr("在听你说…再按一下结束", "Listening… tap again to stop")
                } catch {
                    overridePlaceholder = nil
                }
            }
        }
    }
}

