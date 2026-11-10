//
//  SettingsView.swift
//  Echo — 设置：API key（DeepSeek / 百炼 Qwen-VL 视觉）、音频来源。
//  保存到本机 UserDefaults，不会上传；下一节课（开始新的一节课）生效。
//

import SwiftUI

struct SettingsView: View {
    var onSave: (SourceKind) -> Void
    var onClose: () -> Void

    @State private var deepseek = UserDefaults.standard.string(forKey: "DEEPSEEK_API_KEY") ?? ""
    @State private var dashscope = UserDefaults.standard.string(forKey: "DASHSCOPE_API_KEY") ?? ""
    @State private var source = EchoConfig.source == .demo ? SourceKind.system : EchoConfig.source
    @State private var user = ProfileStore.load()?.username ?? ProfileStore.displayName()
    @State private var lang = I18n.current
    @State private var storageText = ""
    @State private var storageEmpty = true
    @State private var confirmClear = false
    @State private var cleared = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(tr("Echo 设置", "Echo Settings")).font(.system(size: 17, weight: .bold))
            Text(tr("API key 只保存在这台 Mac 上，不会上传。保存后从下一节课开始生效。", "API keys stay on this Mac and are never uploaded. Changes take effect from the next lesson."))
                .caption().wrap()

            Form {
                TextField(tr("用户：", "User:"), text: $user,
                          prompt: Text(tr("开机问候时怎么称呼你", "What Echo calls you when it starts")))
                Picker(tr("界面语言：", "Language:"), selection: $lang) {
                    Text("中文").tag(Lang.zh)
                    Text("English").tag(Lang.en)
                }
                .help(tr("界面文案重启后生效；AI 回答立刻跟着变", "UI text applies after restart; AI answers switch right away"))
                SecureField(tr("DeepSeek API Key：", "DeepSeek API Key:"), text: $deepseek, prompt: Text(placeholder(EchoConfig.deepseekAPIKey)))
                    .help(tr("课堂理解 / 掉队分析 / 追问（deepseek-chat）", "Class understanding / gap analysis / follow-up (deepseek-chat)"))
                SecureField(tr("百炼 API Key：", "Bailian API Key:"), text: $dashscope, prompt: Text(placeholder(EchoConfig.dashscopeAPIKey)))
                    .help(tr("圈一下问 AI 的视觉模型（Qwen-VL，选填，不填退回 DeepSeek）", "Vision model for Circle-to-ask-AI (Qwen-VL, optional; falls back to DeepSeek)"))
                Picker(tr("音频来源：", "Audio source:"), selection: $source) {
                    Text(tr("系统声音（网课/会议）", "System audio (online class / meeting)")).tag(SourceKind.system)
                    Text(tr("麦克风", "Microphone")).tag(SourceKind.mic)
                }
                LabeledContent(tr("语音识别：", "Speech recognition:")) {
                    Text(tr("Apple 语音识别（中文，本机）", "Apple speech recognition (Chinese, on-device)")).foregroundStyle(Palette.textSecondary)
                }
            }
            .formStyle(.columns)

            Divider()
            // 本机存了多少 + 一键清除（删之前把删什么、留什么摊开说清楚）
            VStack(alignment: .leading, spacing: 6) {
                Text(storageText).font(.system(size: 12)).foregroundStyle(Palette.textSecondary).wrap()
                HStack(spacing: Spacing.sm) {
                    Button(tr("清除所有缓存", "Clear all data")) { confirmClear = true }
                        .buttonStyle(QuietButtonStyle(expand: false))
                        .disabled(storageEmpty)
                    if cleared { Text(tr("已清空", "Cleared")).font(.system(size: 12)).foregroundStyle(Palette.okFG) }
                    Spacer()
                }
            }
            .onAppear(perform: refreshStorage)

            HStack {
                Spacer()
                Button(tr("取消", "Cancel"), action: onClose).keyboardShortcut(.cancelAction)
                Button(tr("保存", "Save"), action: save).keyboardShortcut(.defaultAction).buttonStyle(.glassProminent).tint(Palette.accent)
            }
        }
        .padding(20)
        .frame(width: 480)
        .alert(tr("清除所有缓存", "Clear all data"), isPresented: $confirmClear) {
            Button(tr("取消", "Cancel"), role: .cancel) {}
            Button(tr("清除", "Clear"), role: .destructive) {
                Cache.clear()
                cleared = true
                refreshStorage()
            }
        } message: {
            Text(clearMessage)
        }
    }

    private var clearMessage: String {
        let st = Cache.stats()
        let lessons = st.lessons
        let mistakes = st.mistakes
        if I18n.current == .en {
            return """
            This will delete:
            　· \(lessons) lesson records
            　· \(mistakes) mistakes (and their review progress)
            　· saved positions on the knowledge map

            Your name, photo, API keys and settings are kept.
            This can't be undone.
            """
        }
        return """
        会删掉：
        　· \(lessons) 节课的历史记录
        　· \(mistakes) 个错题（连同复习进度）
        　· 知识地图上记住的位置

        名字、头像、API key 和这里的设置都会保留。
        删掉之后没法恢复。
        """
    }

    private func refreshStorage() {
        cleared = false
        let st = Cache.stats()
        let lessons = st.lessons
        let mistakes = st.mistakes
        let bytes = st.bytes
        storageEmpty = Cache.isEmpty()
        storageText = storageEmpty
            ? tr("本机还没有攒下任何记录。", "Nothing stored on this computer yet.")
            : tr("本机存了 \(lessons) 节课的历史、\(mistakes) 个错题，共 \(Cache.sizeText(bytes))。",
                 "\(lessons) lessons and \(mistakes) mistakes on this computer, \(Cache.sizeText(bytes)) in total.")
    }

    /// 已经通过 Secrets.plist / 环境变量配好了 key 时，提示一下而不是显示空白
    private func placeholder(_ current: String) -> String {
        current.isEmpty ? tr("sk-…（留空则离线/退回另一家）", "sk-… (leave empty for offline / fall back to the other)") : tr("已配置（\(current.prefix(5))…），填写可覆盖", "Configured (\(current.prefix(5))…) — enter to override")
    }

    private func save() {
        let d = UserDefaults.standard
        for (k, v) in [("DEEPSEEK_API_KEY", deepseek), ("DASHSCOPE_API_KEY", dashscope)] {
            let v = v.trimmingCharacters(in: .whitespacesAndNewlines)
            if v.isEmpty { d.removeObject(forKey: k) } else { d.set(v, forKey: k) }
        }
        d.set(source.rawValue, forKey: "ECHO_SOURCE")
        // 用户名写进 profile（下次开机问候就用新名字）
        let name = user.trimmingCharacters(in: .whitespaces)
        if !name.isEmpty, var p = ProfileStore.load(), p.username != name {
            p.username = name
            ProfileStore.save(p)
        }
        // 语言：界面文案重启后生效，AI 回答立刻生效
        I18n.set(lang)
        EchoConfig.setUILang(lang.rawValue)
        onSave(source)
        onClose()
    }
}
