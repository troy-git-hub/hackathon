//
//  Config.swift
//  Echo 后端配置。读取顺序：环境变量 → UserDefaults → Secrets.plist（不入库）→ 默认值
//

import Foundation

/// 配置目录（Application Support/Echo），错题本 / 课程历史 / 资料 / 头像都放这里
enum EchoPaths {
    static var dir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let d = base.appendingPathComponent("Echo", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }
}

enum EchoConfig {
    private static let secrets: [String: Any] = {
        guard let url = Bundle.main.url(forResource: "Secrets", withExtension: "plist"),
              let data = try? Data(contentsOf: url),
              let dict = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
        else { return [:] }
        return dict
    }()

    private static func string(_ key: String, _ fallback: String = "") -> String {
        if let v = ProcessInfo.processInfo.environment[key], !v.isEmpty { return v }
        if let v = UserDefaults.standard.string(forKey: key), !v.isEmpty { return v }
        if let v = secrets[key] as? String, !v.isEmpty { return v }
        return fallback
    }

    private static func number(_ key: String, _ fallback: Double) -> Double {
        Double(string(key)) ?? fallback
    }

    // ---------- LLM (DeepSeek, OpenAI 兼容) ----------
    static var deepseekAPIKey: String { string("DEEPSEEK_API_KEY") }
    static var deepseekBaseURL: String { string("DEEPSEEK_BASE_URL", "https://api.deepseek.com") }
    static var deepseekModel: String { string("DEEPSEEK_MODEL", "deepseek-chat") }
    static var llmTimeout: Double { number("ECHO_LLM_TIMEOUT", 40) }

    // ---------- 「圈一下问 AI」视觉模型：优先 Qwen-VL（阿里云百炼），没 key 时退回 DeepSeek ----------
    static var dashscopeAPIKey: String { string("DASHSCOPE_API_KEY") }
    static var dashscopeBaseURL: String { string("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1") }
    static var qwenVLModel: String { string("ECHO_QWEN_VL_MODEL", "qwen-vl-plus") }
    static var visionModel: String { string("ECHO_VISION_MODEL", "deepseek-flash") }
    /// 强制离线：不调 LLM，全部走规则 / mock（断网演示用）
    static var offline: Bool { string("ECHO_OFFLINE") == "1" }

    // ---------- 课堂引擎 ----------
    static var conceptInterval: Double { number("ECHO_CONCEPT_INTERVAL", 30) }
    static var conceptMinChars: Int { Int(number("ECHO_CONCEPT_MIN_CHARS", 40)) }
    static var lostWindow: Double { number("ECHO_LOST_WINDOW", 300) }
    static var breakpointTimeout: Double { number("ECHO_BREAKPOINT_TIMEOUT", 12) }
    static var flushGrace: Double { number("ECHO_FLUSH_GRACE", 2) }

    // ---------- 课堂抽问（摸鱼探测） ----------
    static var checkinEnabled: Bool { string("ECHO_CHECKIN", "1") != "0" }
    /// 开课多久之后才允许第一次抽问（秒）
    static var checkinWarmup: Double { number("ECHO_CHECKIN_WARMUP", 240) }
    /// 两次抽问之间至少间隔多少秒
    static var checkinInterval: Double { number("ECHO_CHECKIN_INTERVAL", 420) }
    /// 学生多久没有任何互动就认为可能在摸鱼（秒）
    static var checkinIdle: Double { number("ECHO_CHECKIN_IDLE", 180) }
    /// 抽问的 LLM 超时，超时用规则题兜底
    static var checkinTimeout: Double { number("ECHO_CHECKIN_TIMEOUT", 10) }

    // ---------- 音频来源 ----------
    static var source: SourceKind { SourceKind(rawValue: string("ECHO_SOURCE", "system").lowercased()) ?? .system }
    static var demoLineInterval: Double { number("ECHO_DEMO_INTERVAL", 3) }
    static var asrPause: Double { number("ECHO_ASR_PAUSE", 1.2) }
    static var asrMaxSentence: Double { number("ECHO_ASR_MAX", 15) }

    // ---------- 界面语言（决定 AI 用哪种语言回答） ----------
    /// UI 层把界面语言写进 UserDefaults("language")，这里读它；也可用 ECHO_UI_LANG 环境变量覆盖。
    static var uiLang: String {
        let v = UserDefaults.standard.string(forKey: "language")
            ?? ProcessInfo.processInfo.environment["ECHO_UI_LANG"]
            ?? "zh"
        return v == "en" ? "en" : "zh"
    }

    static var english: Bool { uiLang == "en" }

    static func setUILang(_ value: String) {
        UserDefaults.standard.set(value == "en" ? "en" : "zh", forKey: "language")
    }
}
