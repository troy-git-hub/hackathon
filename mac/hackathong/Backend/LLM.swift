//
//  LLM.swift
//  Echo - DeepSeek JSON 调用封装（OpenAI 兼容 chat/completions）
//

import Foundation

struct LLMError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

typealias JSONDict = [String: Any]

final class LLM {
    private let apiKey: String
    private let session: URLSession

    init(apiKey: String = EchoConfig.deepseekAPIKey) throws {
        guard !apiKey.isEmpty else { throw LLMError(message: "缺少 DEEPSEEK_API_KEY") }
        self.apiKey = apiKey
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForResource = 120
        self.session = URLSession(configuration: cfg)
    }

    /// 调用 LLM 并返回解析后的 JSON；网络错误 / JSON 截断时重试。
    func json(system: String, user: String, temperature: Double = 0.3, maxTokens: Int = 1200,
              timeout: Double? = nil, attempts: Int = 2) async throws -> JSONDict {
        var last: Error = LLMError(message: "LLM 未调用")
        for attempt in 0..<attempts {
            do {
                let content = try await chat(system: system, user: user, temperature: temperature,
                                             maxTokens: attempt == 0 ? maxTokens : maxTokens * 3 / 2,
                                             timeout: timeout ?? EchoConfig.llmTimeout)
                return try parseJSON(content)
            } catch {
                last = error
                print("[echo.llm] LLM 调用失败（第 \(attempt + 1) 次）: \(error)")
            }
        }
        throw last as? LLMError ?? LLMError(message: "LLM 调用失败: \(last.localizedDescription)")
    }

    private func chat(system: String, user: String, temperature: Double, maxTokens: Int,
                      timeout: Double) async throws -> String {
        guard let url = URL(string: EchoConfig.deepseekBaseURL + "/chat/completions") else {
            throw LLMError(message: "DEEPSEEK_BASE_URL 无效")
        }
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        let body: JSONDict = [
            "model": EchoConfig.deepseekModel,
            "messages": [["role": "system", "content": system],
                         ["role": "user", "content": user]],
            "response_format": ["type": "json_object"],
            "temperature": temperature,
            "max_tokens": maxTokens,
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        // URLRequest 的 timeout 只管空闲时间，这里再加一层总超时
        let (data, resp) = try await withThrowingTaskGroup(of: (Data, URLResponse).self) { group in
            group.addTask { try await self.session.data(for: req) }
            group.addTask {
                try await Task.sleep(for: .seconds(timeout))
                throw LLMError(message: "LLM 超时（\(Int(timeout))s）")
            }
            defer { group.cancelAll() }
            return try await group.next()!
        }
        if let http = resp as? HTTPURLResponse, http.statusCode != 200 {
            let text = String(data: data, encoding: .utf8) ?? ""
            throw LLMError(message: "HTTP \(http.statusCode): \(text.prefix(200))")
        }
        guard let obj = try JSONSerialization.jsonObject(with: data) as? JSONDict,
              let choices = obj["choices"] as? [JSONDict],
              let message = choices.first?["message"] as? JSONDict
        else { throw LLMError(message: "LLM 响应格式异常") }
        return message["content"] as? String ?? ""
    }
}

// MARK: - 流式对话（追问 / 圈图问答）

enum LLMStream {
    /// OpenAI 兼容的流式 chat/completions，逐段吐出增量文本。取消外层 Task 即中断请求。
    static func chat(baseURL: String, apiKey: String, model: String, messages: [JSONDict],
                     temperature: Double = 0.4, maxTokens: Int = 900,
                     extra: JSONDict = [:]) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    guard let url = URL(string: baseURL + "/chat/completions") else {
                        throw LLMError(message: "API 地址无效：\(baseURL)")
                    }
                    var req = URLRequest(url: url, timeoutInterval: EchoConfig.llmTimeout)
                    req.httpMethod = "POST"
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    req.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
                    var body: JSONDict = ["model": model, "messages": messages, "stream": true,
                                          "temperature": temperature, "max_tokens": maxTokens]
                    body.merge(extra) { _, new in new }
                    req.httpBody = try JSONSerialization.data(withJSONObject: body)

                    let (bytes, resp) = try await URLSession.shared.bytes(for: req)
                    if let http = resp as? HTTPURLResponse, http.statusCode != 200 {
                        var text = ""
                        for try await line in bytes.lines { text += line; if text.count > 300 { break } }
                        throw LLMError(message: "HTTP \(http.statusCode): \(text.prefix(200))")
                    }
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        if payload == "[DONE]" { break }
                        guard let data = payload.data(using: .utf8),
                              let obj = try? JSONSerialization.jsonObject(with: data) as? JSONDict,
                              let choices = obj["choices"] as? [JSONDict],
                              let delta = choices.first?["delta"] as? JSONDict,
                              let content = delta["content"] as? String, !content.isEmpty
                        else { continue }
                        continuation.yield(content)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

func parseJSON(_ text: String) throws -> JSONDict {
    if let data = text.data(using: .utf8),
       let obj = try? JSONSerialization.jsonObject(with: data) as? JSONDict {
        return obj
    }
    // 兜底：截取第一个 { 到最后一个 }
    if let lo = text.firstIndex(of: "{"), let hi = text.lastIndex(of: "}"), lo < hi,
       let data = String(text[lo...hi]).data(using: .utf8),
       let obj = try? JSONSerialization.jsonObject(with: data) as? JSONDict {
        return obj
    }
    throw LLMError(message: "LLM 返回不是合法 JSON: \(text.prefix(200))")
}
