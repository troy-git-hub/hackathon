//
//  CheckinCard.swift
//  Echo — 课堂抽查卡（对应 echo/widgets/checkin.py）
//  插在听课页顶部；Echo 自动抽问，或学生点「考考我」主动要题。
//

import SwiftUI

struct CheckinData: Equatable {
    var topic: String
    var question: String
    var options: [String]
}

struct CheckinFeedback: Equatable {
    var result: String          // right / unsure / wrong
    var answer: String
    var explain: String
    var chosen: Int?
    var correctIndex: Int?
}

struct CheckinCardView: View {
    var data: CheckinData?
    var preparing: Bool
    var feedback: CheckinFeedback?
    var onAnswer: (Int) -> Void
    var onClose: () -> Void
    @State private var locked = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(tr("课堂抽查", "Quick check"))
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.accent)
                if let d = data, !d.topic.isEmpty {
                    Text(d.topic).font(.system(size: 12)).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
                Spacer(minLength: 0)
                Button(action: close) { Image(systemName: "xmark") }
                    .buttonStyle(IconButtonStyle())
                    .frame(width: 20, height: 20)
                    .help(tr("知道了，继续听课", "Got it, back to class"))
            }
            Text(questionText)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Palette.textPrimary)
                .wrap()
            if preparing || data == nil {
                Text(tr("出题中…", "Writing a question…"))
                    .font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array((data?.options ?? []).enumerated()), id: \.offset) { i, o in
                        optionButton(i, o)
                    }
                    if data?.options.isEmpty == true {
                        optionButton(0, tr("知道了", "Got it"))
                    }
                }
            }
            if let f = feedback {
                VStack(alignment: .leading, spacing: 4) {
                    Text(verdictText(f.result)).font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(verdictColor(f.result))
                    if !f.answer.isEmpty, f.result != "right" {
                        Text(tr("正确答案：", "Correct answer: ") + f.answer)
                            .font(.system(size: 13)).foregroundStyle(Palette.textPrimary).wrap()
                    }
                    if !f.explain.isEmpty {
                        Text(f.explain).font(.system(size: 13)).foregroundStyle(Palette.textPrimary).wrap()
                    }
                    if f.result != "right" {
                        Text(tr("已记进错题本，课后复习时会带上它。", "Saved to your mistakes — it'll come up in review."))
                            .font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
                    }
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.accentSoft, in: .rect(cornerRadius: Radius.lg))
        .overlay(RoundedRectangle(cornerRadius: Radius.lg).strokeBorder(Palette.accentBorder))
        .onChange(of: data) { _, _ in locked = false }
        .onChange(of: feedback) { _, f in if f != nil { locked = true } }
    }

    private var questionText: String {
        if preparing { return tr("Echo 正在看老师刚讲了什么…", "Echo is checking what the teacher just said…") }
        return data?.question ?? tr("Echo 正在看老师刚讲了什么…", "Echo is checking what the teacher just said…")
    }

    private func close() {
        locked = true
        onClose()
    }

    @ViewBuilder private func optionButton(_ i: Int, _ text: String) -> some View {
        let state = optionState(i)
        Button {
            guard !locked else { return }
            locked = true
            onAnswer(i)
        } label: {
            Text(text)
                .font(.system(size: 12))
                .foregroundStyle(state == .plain ? Palette.textPrimary : state == .right ? Palette.okFG : Palette.danger)
                .frame(maxWidth: .infinity, alignment: .leading)
                .wrap()
        }
        .buttonStyle(CheckinOptionStyle(state: state))
        .disabled(locked)
    }

    private func optionState(_ i: Int) -> CheckinOptionState {
        guard let f = feedback else { return .plain }
        if let c = f.correctIndex, c == i { return .right }
        if let chosen = f.chosen, chosen == i, f.result != "right" { return .wrong }
        return .plain
    }

    private func verdictText(_ r: String) -> String {
        switch r {
        case "right": tr("✓ 跟上了", "✓  Got it")
        case "unsure": tr("≈ 有点模糊", "≈  A bit fuzzy")
        default: tr("✗ 这里没跟上", "✗  Lost track here")
        }
    }

    private func verdictColor(_ r: String) -> Color {
        switch r {
        case "right": Palette.okFG
        case "unsure": Palette.accent
        default: Palette.danger
        }
    }
}

enum CheckinOptionState { case plain, right, wrong }

private struct CheckinOptionStyle: ButtonStyle {
    var state: CheckinOptionState
    @Environment(\.isEnabled) private var enabled
    @State private var hover = false

    func makeBody(configuration: Configuration) -> some View {
        let bg: Color = switch state {
        case .right: Palette.okSoft
        case .wrong: Palette.dangerBG
        case .plain: hover && enabled ? Palette.surfaceHover : Palette.surface
        }
        let border: Color = switch state {
        case .right: Palette.okFG
        case .wrong: Palette.danger
        case .plain: hover && enabled ? Palette.accent : Palette.border
        }
        configuration.label
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(bg, in: .rect(cornerRadius: Radius.md))
            .overlay(RoundedRectangle(cornerRadius: Radius.md).strokeBorder(border))
            .contentShape(.rect)
            .onHover { hover = $0 }
    }
}
