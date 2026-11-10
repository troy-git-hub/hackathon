//
//  Practice.swift
//  Echo - 错题练习出题（对应 Python echo/backend/practice.py）
//  针对一个掉队点让 DeepSeek 出几道练习题；没 key / 失败时用错题自己的字段拼兜底题，永远不返回空。
//

import Foundation

nonisolated struct PracticeQuestion: Identifiable, Hashable, Sendable {
    var id = UUID()
    var question: String
    var options: [String]      // 简答题为 []
    var answer: String         // 选择题为选项字母；简答题为参考答案
    var explain: String
    var source: String = "ai"  // "local" 本地兜底题 / "ai" AI 出的题（界面据此提示「这是本地题」）

    var isChoice: Bool { !options.isEmpty }
}

enum Practice {
    static func generate(_ item: ReviewItem, n: Int = 3) async -> [PracticeQuestion] {
        let key = EchoConfig.deepseekAPIKey
        // 离线模式下不许联网：只看 key 会漏掉这个开关，断网演示时会卡到超时
        guard !EchoConfig.offline, !key.isEmpty else { return fallback(item) }
        do {
            let llm = try LLM(apiKey: key)
            let data = try await llm.json(system: Prompts.system(Prompts.practiceSystem(n: n)),
                                          user: Prompts.practiceUser(item: item, n: n),
                                          temperature: 0.5, maxTokens: 1200,
                                          // 练习页有人在等题：网络卡住时尽快交还本地题，别等两次 40 秒
                                          timeout: min(EchoConfig.llmTimeout, 20), attempts: 1)
            var out: [PracticeQuestion] = []
            for case let q as JSONDict in (data["questions"] as? [Any]) ?? [] {
                let question = (q["question"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !question.isEmpty else { continue }
                let options = ((q["options"] as? [Any]) ?? []).map { "\($0)".trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                out.append(PracticeQuestion(question: question, options: options,
                                            answer: "\(q["answer"] ?? "")".trimmingCharacters(in: .whitespacesAndNewlines),
                                            explain: "\(q["explain"] ?? "")".trimmingCharacters(in: .whitespacesAndNewlines)))
                if out.count >= n { break }
            }
            if !out.isEmpty { return out }
            print("[echo.practice] 出题结果为空，退回兜底题")
        } catch {
            print("[echo.practice] 出题失败: \(error.localizedDescription)")
        }
        return fallback(item)
    }

    /// 兜底练习题：用错题自己的字段拼出题，保证离线也有东西练。
    static func fallback(_ item: ReviewItem) -> [PracticeQuestion] {
        let missing = item.missing.isEmpty ? "这个知识点" : item.missing
        let micro = item.microLesson.isEmpty ? "回顾一下老师刚才讲的内容，把缺的这一步补上。" : item.microLesson
        var out = [PracticeQuestion(question: item.known.isEmpty ? "说说：\(missing)" : "结合已掌握的「\(item.known)」，说说：\(missing)",
                                    options: [], answer: item.step.isEmpty ? micro : item.step, explain: micro, source: "local")]
        if !item.now.isEmpty {
            out.append(PracticeQuestion(question: "补上这一步之后，再回到老师现在讲的内容：\(item.now)。请简述你的理解。",
                                        options: [], answer: item.now, explain: micro, source: "local"))
        }
        return out
    }
}
