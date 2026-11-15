//
//  ProfilePage.swift
//  Echo — 资料页 + 首次登录填资料 + 圆形头像（对应 profile_page.py / profile_setup.py / avatar.py）
//

import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// 圆形头像：自定义图没有时显示默认喵喵
struct AvatarView: View {
    var image: NSImage?
    var size: CGFloat = 72
    var onClick: (() -> Void)?

    var body: some View {
        Button { onClick?() } label: {
            ZStack {
                if let image {
                    Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
                } else {
                    Image("face_smug").resizable().aspectRatio(contentMode: .fill)
                }
            }
            .frame(width: size, height: size)
            .clipShape(.circle)
            .overlay(Circle().strokeBorder(Palette.borderStrong, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(onClick == nil)
    }
}

struct StudyStatsVM: Equatable {
    var lessons = 0
    var pending = 0
    var mastered = 0
    var due = 0
}

struct ProfileVM: Equatable {
    var displayName: String
    var sub: String
    var hasCustomAvatar: Bool
}

struct ProfilePage: View {
    var profile: ProfileVM
    var avatar: NSImage?
    var stats: StudyStatsVM
    var onPickAvatar: () -> Void
    var onUseDefault: () -> Void
    var onHome: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .center, spacing: Spacing.lg) {
                AvatarView(image: avatar, size: 84, onClick: onPickAvatar)
                    .help(tr("点一下换头像", "Click to change your photo"))
                VStack(alignment: .leading, spacing: 3) {
                    Text(profile.displayName).font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Palette.textPrimary).wrap()
                    if !profile.sub.isEmpty {
                        Text(profile.sub).caption().wrap()
                    }
                    HStack(spacing: Spacing.sm) {
                        Button(tr("换一张", "Change photo"), action: onPickAvatar)
                            .buttonStyle(QuietButtonStyle(expand: false))
                        if profile.hasCustomAvatar {
                            Button(tr("用默认喵喵", "Use the default cat"), action: onUseDefault)
                                .buttonStyle(QuietButtonStyle(expand: false))
                        }
                    }
                }
                Spacer(minLength: 0)
            }

            Text(tr("学习情况", "Study stats")).caption()

            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading),
                                GridItem(.flexible(), alignment: .leading)],
                      alignment: .leading, spacing: Spacing.md) {
                stat(tr("听过的课", "Lessons"), stats.lessons)
                stat(tr("待复习", "To review"), stats.pending)
                stat(tr("已补上", "Fixed"), stats.mastered)
                stat(tr("今天该回响", "Due today"), stats.due)
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface.opacity(0.55), in: .rect(cornerRadius: Radius.md))
            .overlay(RoundedRectangle(cornerRadius: Radius.md).strokeBorder(Palette.border))

            Text(hint).font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()

            // 学习画像：按复习表现算出来的，喂给 AI 调口气用（不是 AI 猜的）
            HStack {
                Text(tr("学习画像", "Learning profile")).caption()
                Spacer()
                Button(tr("重置", "Reset")) { resetPersona() }
                    .buttonStyle(QuietButtonStyle(expand: false))
                    .help(tr("清空画像，下次会按最新的复习记录重新算",
                             "Clear it — next time it's recomputed from your latest record"))
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(personaHeadline).font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Palette.textPrimary).wrap()
                Text(personaDescribe).caption().wrap()
                if !personaWhen.isEmpty {
                    Text(personaWhen).font(.system(size: 11)).foregroundStyle(Palette.textDisabled).wrap()
                }
            }
            .card()

            // 反复卡住的地方：跨课看出来的「你以为卡在这章，其实地基没打牢」；没有结论就整块藏起来
            if !gapFindings.isEmpty {
                Text(tr("反复卡住的地方", "Recurring gaps")).caption()
                ForEach(gapFindings, id: \.concept) { g in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: Spacing.sm) {
                            Text("✦ \(g.concept)")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Palette.textPrimary).wrap()
                            Spacer(minLength: 0)
                            Text(tr("\(g.lessons) 节课都是它", "in \(g.lessons) lessons"))
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(Palette.accent)
                                .padding(.horizontal, 8).padding(.vertical, 1)
                                .background(Palette.accentSoft, in: .capsule)
                                .overlay(Capsule().strokeBorder(Palette.accentBorder))
                        }
                        if !g.sentence.isEmpty { Text(g.sentence).caption().wrap() }
                        if !g.topics.isEmpty {
                            Text(tr("这段时间卡在：", "You got stuck on: ") + g.topics.prefix(4).joined(separator: " · "))
                                .font(.system(size: 11)).foregroundStyle(Palette.textDisabled).wrap()
                        }
                    }
                    .card(border: Palette.accentBorder)
                    .overlay(alignment: .leading) {
                        UnevenRoundedRectangle(topLeadingRadius: Radius.md, bottomLeadingRadius: Radius.md)
                            .fill(Palette.accent).frame(width: 3)
                    }
                }
            }

            HStack {
                Spacer()
                Button(tr("回到主页", "Back to home"), action: onHome).buttonStyle(LinkButtonStyle())
            }
        }
    }

    private func stat(_ label: String, _ value: Int) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value > 0 ? "\(value)" : "–")
                .font(.system(size: 22, weight: .bold)).foregroundStyle(Palette.textPrimary)
            Text(label).font(.system(size: 12)).foregroundStyle(Palette.textSecondary)
        }
    }

    // MARK: - 学习画像 / 反复卡住的地方

    private var personaHeadline: String {
        let s = Persona.headline()
        return s.isEmpty ? "" : s
    }

    private var personaDescribe: String {
        let s = Persona.describe()
        return s.isEmpty ? tr("画像暂时算不出来。", "Couldn't compute this right now.") : s
    }

    /// 画像是「什么时候算的」；没算过就直说实时算的，别写「刚刚更新」
    private var personaWhen: String {
        let ts = Persona.updatedAt()
        guard ts > 0 else { return tr("按你现在的记录实时算的，还没重算过",
                                      "Computed live from your record so far — not recalculated yet") }
        let d = max(0, Date().timeIntervalSince1970 - ts)
        if d < 90 { return tr("刚刚更新", "Updated just now") }
        if d < 3600 { return tr("\(Int(d / 60)) 分钟前更新", "Updated \(Int(d / 60)) min ago") }
        if d < 86400 { return tr("\(Int(d / 3600)) 小时前更新", "Updated \(Int(d / 3600)) h ago") }
        return tr("\(Int(d / 86400)) 天前更新", "Updated \(Int(d / 86400)) d ago")
    }

    private var gapFindings: [GapFinding] { Gaps.recurring() }

    private func resetPersona() {
        Persona.reset()
    }

    private var hint: String {
        if stats.due > 0 {
            return tr("今天有 \(stats.due) 个知识点该回响了，去「讲给 Echo 听」过一遍吧。",
                      "\(stats.due) concepts due today — run through them in Talk it through.")
        }
        if stats.pending > 0 {
            return tr("今天到期的都过了，还有 \(stats.pending) 个在清单里排着队。",
                      "Nothing due today — \(stats.pending) more waiting in your list.")
        }
        return tr("还没有要复习的知识点，安心听课就好。", "Nothing to review yet — just enjoy the lesson.")
    }
}

// MARK: - 首次登录填资料

struct ProfileSetupData: Equatable {
    var name = ""
    var nickname = ""
    var age = 0
    var hobbies = ""
    var avatar: NSImage?
    var avatarURL: URL?
}

struct ProfileSetupView: View {
    @State private var data = ProfileSetupData()
    var onSave: (ProfileSetupData) -> String?     // 返回错误文案；nil 表示成功
    var onDone: () -> Void = {}                   // 保存成功后关窗
    var onCancel: () -> Void                      // 关掉窗/按 Esc = 退出 Echo，下次启动再问
    @State private var error: String?

    /// 选一张图（用系统文件选择器；读不了就提示换一张）
    private func pick() {
        let panel = NSOpenPanel()
        panel.title = tr("选一张头像", "Choose a photo")
        panel.allowedContentTypes = [.png, .jpeg, .webP, .bmp]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard let img = NSImage(contentsOf: url) else {
            error = tr("这张图读不了。换一张试试（支持 PNG / JPG / WebP / BMP）。",
                       "Can't read that image. Try another one (PNG / JPG / WebP / BMP).")
            return
        }
        error = nil
        data.avatar = img
        data.avatarURL = url
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(tr("先认识一下你吧", "Let's get to know you")).font(.system(size: 16, weight: .semibold))
            Text(tr("资料只保存在本机，不会上传。以后可以在设置里改用户名。",
                    "Your profile stays on this computer and is never uploaded. You can change your user name later in Settings."))
                .caption().wrap()

            HStack(alignment: .top, spacing: 14) {
                AvatarView(image: data.avatar, size: 72, onClick: pick)
                VStack(alignment: .leading, spacing: 8) {
                    Text(data.avatarURL != nil
                         ? tr("就用这张。不满意可以再选，或者换回喵喵。", "Looks good. Pick again anytime, or switch back to the cat.")
                         : tr("挑一张头像吧，不想挑就用默认的喵喵。", "Pick a photo — or just keep the default cat."))
                        .caption().wrap()
                    HStack(spacing: Spacing.sm) {
                        Button(tr("选一张图", "Choose a photo"), action: pick)
                            .buttonStyle(QuietButtonStyle(expand: false))
                        Button(tr("用默认喵喵", "Use the default cat")) {
                            data.avatar = nil
                            data.avatarURL = nil
                        }
                        .buttonStyle(QuietButtonStyle(expand: false))
                    }
                }
            }

            Form {
                TextField(tr("姓名：", "Name:"), text: $data.name,
                          prompt: Text(tr("必填", "Required")))
                TextField(tr("昵称：", "Nickname:"), text: $data.nickname,
                          prompt: Text(tr("必填，Echo 会这样叫你", "Required — what Echo will call you")))
                TextField(tr("年龄：", "Age:"), value: $data.age, format: .number,
                          prompt: Text(tr("不填", "Skip")))
                TextField(tr("爱好：", "Hobbies:"), text: $data.hobbies,
                          prompt: Text(tr("比如：篮球、画画、编程（选填）", "e.g. basketball, drawing, coding (optional)")))
            }
            .formStyle(.columns)

            if let error {
                Text(error).font(.system(size: 12)).foregroundStyle(Palette.danger).wrap()
            }

            HStack {
                Spacer()
                Button(tr("开始使用", "Get started"), action: save)
                    .buttonStyle(.glassProminent).tint(Palette.accent)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: 460)
        .onExitCommand(perform: onCancel)
    }

    private func save() {
        if data.name.trimmingCharacters(in: .whitespaces).isEmpty
            || data.nickname.trimmingCharacters(in: .whitespaces).isEmpty {
            error = tr("姓名和昵称都要填哦。", "Please fill in both your name and nickname.")
            return
        }
        error = onSave(data)
        if error == nil { onDone() }
    }
}
