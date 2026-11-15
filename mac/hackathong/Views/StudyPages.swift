//
//  StudyPages.swift
//  Echo — 主页 / 错题复习 / AI 出题练习
//

import SwiftUI

// MARK: - 主页（启动页）

struct HomePage: View {
    var model: AppModel
    @State private var title = ""

    private var gap: GapFinding? { Gaps.recurring().first }

    var body: some View {
        let st = model.stats
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("今天也来听课", "Ready for another lesson?")).pageTitle()
                Text(subtitle).caption().wrap()
            }

            // 今天该回响（没有到期的就整卡隐藏）
            if st.due > 0 {
                VStack(alignment: .leading, spacing: 6) {
                    Text(tr("今天有 \(st.due) 个知识点需要确认", "\(st.due) knowledge points to confirm today"))
                        .font(.system(size: 14, weight: .semibold)).foregroundStyle(Palette.textPrimary).wrap()
                    Text(model.dueHint.isEmpty
                         ? tr("包括：\(dueNames)", "Including: \(dueNames)")
                         : model.dueHint)
                        .font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
                    if model.dueMinutes > 0 {
                        Text(tr("预计 \(model.dueMinutes) 分钟", "About \(model.dueMinutes) min")).caption()
                    }
                    HStack {
                        Spacer()
                        Button(tr("讲给 Echo 听", "Talk it through with Echo"), action: model.startRecall)
                            .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 40))
                            .frame(width: 170)
                            .help(tr("不做题，用你自己的话讲一遍，Echo 听你说完给判断",
                                     "No quizzes — explain it in your own words and Echo will judge"))
                    }
                }
                .card(border: Palette.accentBorder)
            }

            // 反复卡住的地方：跨课看出来的「你以为卡在这章，其实地基没打牢」；只显示最严重一条
            if let gap {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: Spacing.sm) {
                        Text("✦ \(gap.concept)").font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Palette.textPrimary).wrap()
                        Spacer(minLength: 0)
                        Text(tr("\(gap.lessons) 节课都是它", "in \(gap.lessons) lessons"))
                            .font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.accent)
                            .padding(.horizontal, 8).padding(.vertical, 1)
                            .background(Palette.accentSoft, in: .capsule)
                            .overlay(Capsule().strokeBorder(Palette.accentBorder))
                    }
                    if !gap.sentence.isEmpty { Text(gap.sentence).caption().wrap() }
                    HStack {
                        Spacer()
                        Button(tr("出道题", "Try a question")) { model.practiceGap(gap.concept) }
                            .buttonStyle(QuietButtonStyle(expand: false))
                    }
                }
                .card(border: Palette.accentBorder)
                .overlay(alignment: .leading) {
                    UnevenRoundedRectangle(topLeadingRadius: Radius.md, bottomLeadingRadius: Radius.md)
                        .fill(Palette.accent).frame(width: 3)
                }
            }

            Text(tr("这节课叫什么？", "What's this lesson called?")).caption()
            TextField(tr("例如：初二数学 · 正比例函数（留空默认用开课时间命名）",
                         "e.g. Grade 8 Math · Direct proportion (leave blank to name by start time)"),
                      text: $title)
                .textFieldStyle(.plain)
                .font(.system(size: 12))
                .padding(.horizontal, 10).padding(.vertical, 7)
                .background(Palette.surface.opacity(0.7), in: .rect(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.border))
                .onSubmit(start)

            Button(tr("开始今天的学习", "Start today's learning"), action: start)
                .buttonStyle(AccentButtonStyle(minHeight: 46))
                .help(tr("开一节新课，Echo 开始听你的网课", "Start a new lesson — Echo begins listening"))

            homeCard(tr("错题复习", "Review mistakes"),
                     st.pending > 0
                     ? tr("\(st.pending) 个掉队过的知识点等你回看", "\(st.pending) knowledge points waiting for review")
                     : tr("暂时没有错题，听课时点「我掉队了」就会收进来",
                          "No mistakes yet — tap \"I fell behind\" during a lesson and they'll show up here"),
                     tr("去复习", "Review"), enabled: st.pending > 0, action: model.showReview)
            homeCard(tr("错题练习", "Mistake practice"),
                     st.pending > 0
                     ? tr("让 AI 照着这 \(st.pending) 个错题出题，真的练一下",
                          "Have AI write questions from these \(st.pending) mistakes and actually practise")
                     : tr("有错题之后，AI 就能照着出题", "Once you have mistakes, AI can write questions from them"),
                     tr("开始练", "Practice"), enabled: st.pending > 0, action: model.startPractice)

            if !model.courses.isEmpty {
                homeCard(tr("课程管理", "Course manager"),
                         tr("\(model.courses.count) 节历史课，可搜索、重命名、批量删除",
                            "\(model.courses.count) past lessons — search, rename, bulk delete"),
                         tr("管理", "Manage"), enabled: true, action: model.showCourses)
                homeCard(tr("已学内容", "Learned so far"),
                         tr("看看学过的知识点怎么连起来的", "See how everything you've learned connects"),
                         tr("看看", "Open"), enabled: true, action: model.showLearned)
                homeCard(tr("一周学习回响", "Weekly review"),
                         tr("最近 7 天学了什么，一眼看完", "Everything from the last 7 days, at a glance"),
                         tr("看看", "Open"), enabled: true, action: model.showWeekly)
            }
        }
    }

    private func start() {
        model.lessonTitleInput = title
        title = ""
        model.startToday()
    }

    private var dueNames: String {
        model.reviewPending.prefix(3).map(\.topic).joined(separator: tr("、", ", "))
    }

    private var subtitle: String {
        let st = model.stats
        var bits: [String] = []
        if st.lessons > 0 { bits.append(tr("已经听过 \(st.lessons) 节课", "\(st.lessons) lessons so far")) }
        if st.mastered > 0 { bits.append(tr("补上了 \(st.mastered) 个知识点", "\(st.mastered) knowledge points caught up")) }
        if st.pending > 0 {
            bits.append(tr("还有 \(st.pending) 个错题要复习", "\(st.pending) mistakes left to review"))
        } else if st.lessons > 0 {
            bits.append(tr("目前没有待复习的知识点", "Nothing waiting for review right now"))
        } else {
            bits.append(tr("先开一节课，Echo 会记下没跟上的地方", "Start a lesson and Echo will note what you miss"))
        }
        return bits.joined(separator: " · ")
    }

    /// 主页上的一张功能卡：标题 + 说明 + 右侧按钮
    private func homeCard(_ title: String, _ desc: String, _ action: String, enabled: Bool,
                          action run: @escaping () -> Void) -> some View {
        HStack(spacing: Spacing.sm) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 14, weight: .semibold)).foregroundStyle(Palette.textPrimary)
                Text(desc).caption().wrap()
            }
            Spacer(minLength: 0)
            Button(action, action: run)
                .buttonStyle(QuietButtonStyle(expand: false))
                .disabled(!enabled)
        }
        .card(padding: Spacing.lg)
    }
}

// MARK: - 错题复习

struct ReviewPage: View {
    var model: AppModel
    @State private var folded: [String: Bool] = [:]

    var body: some View {
        let due = model.reviewPending
        let later = model.reviewLater
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("错题复习", "Review mistakes")).pageTitle()
                Text(due.isEmpty
                     ? tr("今天到期的都过完了", "Nothing due today")
                     : tr("今天该复习 · \(due.count) 个", "Due today · \(due.count)"))
                    .caption()
            }

            // 「讲给 Echo 听」入口（今天有到期才显示）
            if !due.isEmpty {
                HStack(spacing: Spacing.sm) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(tr("讲给 Echo 听", "Talk it through with Echo"))
                            .font(.system(size: 14, weight: .semibold)).foregroundStyle(Palette.textPrimary)
                        Text(tr("\(due.count) 个知识点一起聊，你先用自己的话讲一遍，再换个场景用一次",
                                "\(due.count) concepts this round — explain in your own words, then apply it to a new setting"))
                            .caption().wrap()
                    }
                    Spacer(minLength: 0)
                    Button(tr("开始", "Start"), action: model.startRecall)
                        .buttonStyle(AccentButtonStyle(fontSize: 13, minHeight: 32))
                        .frame(width: 74)
                }
                .card(border: Palette.accentBorder)
            }

            if due.isEmpty && later.isEmpty {
                Text(tr("还没有错题。听完一节课、点「我掉队了」之后，这里会收集你没跟上的地方。",
                        "No mistakes yet. After a lesson, tap \"I fell behind\" and the gaps land here."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            }

            ForEach(due) { it in card(it, due: true) }

            if !later.isEmpty {
                Text(tr("过几天再复习 · \(later.count) 个", "Coming up · \(later.count)")).caption()
                ForEach(later) { it in card(it, due: false) }
            }

            HStack {
                Spacer()
                Button(tr("开始新的一节课", "Start a new lesson"), action: model.restart).buttonStyle(LinkButtonStyle())
            }
        }
    }

    /// 折叠状态：今天该复习的默认展开，过几天再复习的默认收起；打完分重渲染也记得住
    private func isFolded(_ topic: String, due: Bool) -> Bool { folded[topic] ?? !due }

    private func card(_ it: ReviewItem, due: Bool) -> some View {
        let open = !isFolded(it.topic, due: due)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: Spacing.sm) {
                Text("✦ \(it.topic)").font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.textPrimary).wrap()
                Spacer(minLength: 0)
                Button {
                    folded[it.topic] = open
                } label: {
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle())
                .help(open ? tr("收起", "Collapse") : tr("展开", "Expand"))
            }
            // 「为什么要复习它」：收起状态下也要显示，这是让学生重视这步的那句话
            if !it.whyMatters.isEmpty {
                Text(it.whyMatters).font(.system(size: 12)).foregroundStyle(Palette.accent).wrap()
            }
            if open { body(it, due: due) }
        }
        .card()
    }

    @ViewBuilder private func body(_ it: ReviewItem, due: Bool) -> some View {
        let reason = ReviewStore.dueReason(for: it)
        if !reason.isEmpty {
            Text("◷ " + reason).font(.system(size: 11)).foregroundStyle(Palette.textDisabled).wrap()
        }
        let miss = !it.missing.isEmpty ? it.missing : (!it.reason.isEmpty ? it.reason : tr("这里没跟上", "Something here didn't land"))
        Text(tr("没跟上：", "Missed: ") + miss)
            .font(.system(size: 13)).foregroundStyle(Palette.accent).wrap()
        if !it.timecode.isEmpty {
            Text(tr("老师讲到 \(it.timecode)", "Taught at \(it.timecode)"))
                .font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
        }
        let lesson = it.microLesson.trimmingCharacters(in: .whitespacesAndNewlines)
        if !lesson.isEmpty {
            Text(lesson).font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
        }

        if due {
            Text(tr("想起来了吗？", "How well do you remember it?"))
                .font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
            HStack(spacing: Spacing.sm) {
                gradeButton(it, .again, tr("还是没懂", "Still lost"))
                gradeButton(it, .fuzzy, tr("有点模糊", "A bit fuzzy"))
                gradeButton(it, .clear, tr("记得很清楚", "I remember it"))
            }
        } else {
            Text(tr("\(it.daysLeft) 天后再确认一次", "Check again in \(it.daysLeft) days"))
                .font(.system(size: 12)).foregroundStyle(Palette.okFG)
        }

        HStack {
            Button(tr("想不起来？出道题试试", "Not sure? Try a question")) { model.practice(it) }
                .buttonStyle(LinkButtonStyle())
            Spacer()
            if due {
                Button(tr("✓ 掌握了", "✓ Mastered")) { withAnimation { model.markReviewed(it.topic) } }
                    .buttonStyle(QuietButtonStyle(expand: false))
            }
        }
    }

    /// 三档对应的下次确认间隔（与后端 CLEAR_LADDER 第一级一致）
    private func days(_ g: Grade) -> Int {
        switch g {
        case .again: 1
        case .fuzzy: 3
        case .clear: 7
        }
    }

    private func gradeButton(_ it: ReviewItem, _ g: Grade, _ title: String) -> some View {
        Button(title) { withAnimation { model.gradeReview(it.topic, g) } }
            .buttonStyle(QuietButtonStyle(expand: false))
            .help(tr("选这个 → \(days(g)) 天后再确认一次", "Pick this → next check in \(days(g)) days"))
    }
}

// MARK: - AI 出题练习

struct PracticePage: View {
    var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: 2) {
                Text(tr("错题练习", "Mistake practice")).pageTitle()
                Text(subtitle).caption()
            }
            if model.practiceLoading {
                LoadingCard(text: tr("AI 正在照着你的错题出题…", "AI is writing questions from your mistakes…"),
                            color: Palette.textSecondary)
                Button(tr("先用本地题", "Use local questions"), action: model.useLocalQuestions)
                    .buttonStyle(QuietButtonStyle(expand: false))
                    .help(tr("不等 AI 了，先用根据这个错题整理出的题练起来", "Skip the wait — practise with questions built from this mistake"))
            } else if model.practiceQs.indices.contains(model.practiceIndex) {
                question(model.practiceQs[model.practiceIndex])
            } else if model.practiceItem == nil {
                Text(tr("听课时点「我掉队了」，Echo 会把没跟上的地方收进来。课后就能在这里练。",
                        "Tap \"I fell behind\" during a lesson and Echo collects the gaps. Then practise them here."))
                    .font(.system(size: 13)).foregroundStyle(Palette.textSecondary).wrap()
            }
            HStack(spacing: Spacing.sm) {
                Button(tr("看答案", "Show answer")) { withAnimation { model.showAnswer = true } }
                    .buttonStyle(QuietButtonStyle(minHeight: 40))
                    .disabled(model.practiceLoading || model.showAnswer)
                Button(model.practiceIndex + 1 < model.practiceQs.count
                       ? tr("下一题", "Next") : tr("练完了", "All done"), action: model.nextQuestion)
                    .buttonStyle(AccentButtonStyle(fontSize: 14, minHeight: 40))
                    .disabled(model.practiceLoading)
            }
            HStack {
                Button(tr("✓ 这个我会了", "✓ Got this one"), action: model.practiceMastered).buttonStyle(LinkButtonStyle())
                Spacer()
                Button(tr("换一题练", "Practise another"), action: model.startPractice).buttonStyle(LinkButtonStyle())
            }
        }
    }

    private var subtitle: String {
        let topic = model.practiceItem?.topic ?? ""
        guard !model.practiceLoading, !model.practiceQs.isEmpty else {
            return tr("针对：\(topic)", "About: \(topic)")
        }
        var s = tr("针对：\(topic)　第 \(model.practiceIndex + 1) / \(model.practiceQs.count) 题",
                  "About: \(topic)　Question \(model.practiceIndex + 1) of \(model.practiceQs.count)")
        if !model.practiceSource.isEmpty { s += "　·　\(model.practiceSource)" }
        return s
    }

    private func question(_ q: PracticeQuestion) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(q.question).font(.system(size: 15, weight: .semibold)).foregroundStyle(Palette.textPrimary)
                .lineSpacing(4).wrap().textSelection(.enabled)
            if q.isChoice {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(q.options, id: \.self) { o in
                        Text(o).font(.system(size: 13)).foregroundStyle(Palette.textPrimary).wrap()
                    }
                }
            }
            if model.showAnswer {
                VStack(alignment: .leading, spacing: 4) {
                    Text(tr("答案：", "Answer: ") + q.answer)
                        .font(.system(size: 13, weight: .semibold)).foregroundStyle(Palette.textPrimary).wrap()
                    if !q.explain.isEmpty {
                        Text(q.explain).font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
                            .lineSpacing(3).wrap()
                    }
                }
                .textSelection(.enabled)
                .padding(.horizontal, Spacing.md)
                .padding(.vertical, Spacing.sm)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.codeBG.opacity(0.7), in: .rect(cornerRadius: 6))
                .overlay(alignment: .leading) { Rectangle().fill(Palette.accent).frame(width: 2) }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}
