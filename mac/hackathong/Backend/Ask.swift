//
//  Ask.swift
//  Echo - 追问 / 「圈一下问 AI」（对应 Python echo/backend/vision.py 的 LessonAsk + VisionChat）
//
//  image == nil：文字追问，DeepSeek 文本模型 + 课堂上下文
//  image != nil：圈图问答，优先 Qwen-VL（DASHSCOPE_API_KEY），没有就退回 DeepSeek 视觉
//  一个 AskSession 对应一次圈选 / 一次掉队追问，后续追问共享历史。
//

import Foundation

final class AskSession {
    static let quickQuestions = ["这是什么意思？", "这一步是怎么来的？", "能举个例子吗？", "和老师现在讲的有什么关系？"]

    private let context: String
    private let image: Data?
    private var history: [JSONDict] = []
    private var busy = false
    private var current: Task<Void, Never>?

    init(engine: EchoEngine?, extraContext: String = "", image: Data? = nil) {
        var ctx = engine?.lessonContext().trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !extraContext.isEmpty { ctx = (ctx + "\n\n" + extraContext).trimmingCharacters(in: .whitespacesAndNewlines) }
        context = ctx
        self.image = image
    }

    /// 流式回答：逐段 yield 增量文本；完整答案会记进历史，供下一次追问。
    func ask(_ question: String) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            guard !busy else {
                continuation.finish(throwing: LLMError(message: "上一个问题还在回答中"))
                return
            }
            busy = true
            current = Task {
                defer { self.busy = false }
                do {
                    let (endpoint, msgs) = try self.prepare(question)
                    var answer = ""
                    for try await delta in LLMStream.chat(baseURL: endpoint.baseURL, apiKey: endpoint.key,
                                                          model: endpoint.model, messages: msgs,
                                                          maxTokens: self.image == nil ? 700 : 900,
                                                          extra: endpoint.extra) {
                        if Task.isCancelled { break }
                        answer += delta
                        continuation.yield(delta)
                    }
                    if !Task.isCancelled {
                        self.history = Array(msgs.dropFirst())
                            + [["role": "assistant", "content": answer.trimmingCharacters(in: .whitespacesAndNewlines)]]
                    }
                    continuation.finish()
                } catch {
                    print("[echo.ask] 回答失败: \(error)")
                    continuation.finish(throwing: LLMError(message: "AI 暂时回答不了：\(error.localizedDescription)"))
                }
            }
            continuation.onTermination = { [weak self] _ in Task { @MainActor in self?.current?.cancel() } }
        }
    }

    func cancel() { current?.cancel() }

    private struct Endpoint {
        var baseURL: String, key: String, model: String, extra: JSONDict = [:]
    }

    private func prepare(_ question: String) throws -> (Endpoint, [JSONDict]) {
        let endpoint: Endpoint
        if image == nil {
            guard !EchoConfig.deepseekAPIKey.isEmpty else { throw LLMError(message: "缺少 DEEPSEEK_API_KEY，离线模式下不能追问") }
            endpoint = Endpoint(baseURL: EchoConfig.deepseekBaseURL, key: EchoConfig.deepseekAPIKey, model: EchoConfig.deepseekModel)
        } else if !EchoConfig.dashscopeAPIKey.isEmpty {
            endpoint = Endpoint(baseURL: EchoConfig.dashscopeBaseURL, key: EchoConfig.dashscopeAPIKey, model: EchoConfig.qwenVLModel)
        } else if !EchoConfig.deepseekAPIKey.isEmpty {
            // DeepSeek 视觉：关掉思考模式，首字快且追问不会空答案
            endpoint = Endpoint(baseURL: EchoConfig.deepseekBaseURL, key: EchoConfig.deepseekAPIKey,
                                model: EchoConfig.visionModel, extra: ["thinking": ["type": "disabled"]])
        } else {
            throw LLMError(message: "缺少视觉模型 API key：请配置 DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY")
        }

        let text = history.isEmpty
            ? (context.isEmpty ? "" : context + "\n\n") + "【学生的问题】\(question)"
            : question
        let user: JSONDict
        if let image {
            // 追问时也把图带上，避免模型丢掉视觉上下文
            let url = "data:image/png;base64," + image.base64EncodedString()
            user = ["role": "user", "content": [["type": "text", "text": text],
                                                ["type": "image_url", "image_url": ["url": url]]]]
        } else {
            user = ["role": "user", "content": text]
        }
        let system = Prompts.system(image == nil ? Prompts.askSystem : Prompts.visionSystem)
        return (endpoint, [["role": "system", "content": system]] + history + [user])
    }
}
