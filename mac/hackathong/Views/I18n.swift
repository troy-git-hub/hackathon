//
//  I18n.swift
//  Echo — 界面语言（中/英），对应 Python 的 echo/i18n.py
//  语言存 UserDefaults("language")，取值 "zh" / "en"；改完重启 Echo 生效。
//  后端也读同一个 key，让 AI 的回答跟着界面语言走。
//

import Foundation

enum Lang: String {
    case zh, en
}

enum I18n {
    static let key = "language"

    static var current: Lang {
        // 环境变量优先（开发/自检用，与后端 EchoConfig.uiLang 的兜底一致），其次用户设置
        if let env = ProcessInfo.processInfo.environment["ECHO_UI_LANG"], !env.isEmpty {
            return Lang(rawValue: env.lowercased()) ?? .zh
        }
        return Lang(rawValue: UserDefaults.standard.string(forKey: key) ?? "zh") ?? .zh
    }

    static func set(_ l: Lang) {
        UserDefaults.standard.set(l.rawValue, forKey: key)
    }
}

/// 按当前语言返回文本；英文留空时兜底中文（与 Python tr() 一致）
func tr(_ zh: String, _ en: String = "") -> String {
    I18n.current == .en && !en.isEmpty ? en : zh
}
