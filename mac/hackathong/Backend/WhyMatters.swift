//
//  WhyMatters.swift
//  Echo - 「为什么要复习它」（对应 Python echo/backend/why_matters.py）
//
//  错题卡上有一行说明，回答的不是「这题为什么错」，而是**这个知识点跟学生后面要学的
//  东西有什么关系**——让他觉得这步值得认真补，而不是又一条待办。
//
//  一次调用批量生成一整批：每张卡各调一次 API 既慢又贵，而且模型看不到彼此，写出来
//  容易是同一句套话。
//
//  生成结果由调用方写进错题本的 why_matters 字段，走 ReviewStore.setWhy()（不是 add()
//  ——那个会把同一道错题的 missing / microLesson 一起抹掉）。拿不到结果时返回空 dict、
//  不抛：没有 AI 说明就不显示这一行。
//

import Foundation

nonisolated enum WhyMatters {
    // 一批最多问几个：一次调用的 token 会随条数线性涨，一条错题两句话其实很省，
    // 卡在 12 是给「错题本攒了很久、第一次打开复习页」那种情况兜底——超出的留到下一次
    // 渲染再问，不在一屏里硬塞。
    static let maxPerCall = 12

    /// 挑出还没有「为什么要复习它」的条目。已生成的不用再问，省一次调用。
    static func needs(_ items: [ReviewItem]) -> [ReviewItem] {
        items.filter {
            let topic = $0.topic.trimmingCharacters(in: .whitespacesAndNewlines)
            let why = $0.whyMatters.trimmingCharacters(in: .whitespacesAndNewlines)
            return !topic.isEmpty && why.isEmpty
        }
    }

    private static func formatItems(_ items: [ReviewItem]) -> String {
        var blocks: [String] = []
        for (i, it) in items.enumerated() {
            let topic = it.topic.trimmingCharacters(in: .whitespacesAndNewlines)
            var miss = it.missing.trimmingCharacters(in: .whitespacesAndNewlines)
            if miss.isEmpty { miss = it.reason.trimmingCharacters(in: .whitespacesAndNewlines) }
            var lines = ["\(i + 1). \(topic)"]
            if !miss.isEmpty { lines.append("   他卡在：\(miss)") }
            blocks.append(lines.joined(separator: "\n"))
        }
        return blocks.joined(separator: "\n")
    }

    /// 把模型返回的 reasons 收成 {topic: why}，只认输入里真实存在的 topic。
    ///
    /// 模型的 topic 可能多一个空格、少一个「的」——所以按去空格后的精确匹配来认，
    /// 对不上就丢掉这一条：宁可少显示一行，也不要把说明挂到别的知识点上。
    private static func clean(_ data: JSONDict, wanted: [String]) -> [String: String] {
        guard let rows = data["reasons"] as? [Any] else { return [:] }
        var byTopic: [String: String] = [:]
        for t in wanted {
            let key = t.trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty { byTopic[key] = t }
        }
        var out: [String: String] = [:]
        for case let row as JSONDict in rows {
            let topic = ((row["topic"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let why = ((row["why"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if let orig = byTopic[topic], !why.isEmpty { out[orig] = why }
        }
        return out
    }

    /// 同步批量生成，返回 {topic: 说明}。离线 / 没 key / 调用失败一律返回 [:]。
    @MainActor static func planBatch(_ items: [ReviewItem]) async -> [String: String] {
        do {
            return try await planBatchThrowing(items)
        } catch {
            print("[echo.why_matters] 「为什么要复习它」生成失败: \(error.localizedDescription)")
            return [:]
        }
    }

    @MainActor private static func planBatchThrowing(_ items: [ReviewItem]) async throws -> [String: String] {
        let filtered = items.filter { !$0.topic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let batch = Array(filtered.prefix(maxPerCall))
        if batch.isEmpty { return [:] }
        // 离线模式（ECHO_OFFLINE=1）下不许联网，理由同 Practice.generate
        if EchoConfig.offline || EchoConfig.deepseekAPIKey.isEmpty { return [:] }
        let system = Prompts.system(WhyMattersPrompts.system)
        let user = WhyMattersPrompts.user.replacingOccurrences(of: "{items}", with: formatItems(batch))
        let data = try await LLM().json(system: system, user: user, temperature: 0.6, maxTokens: 900)
        let reasons = clean(data, wanted: batch.map(\.topic))
        if reasons.isEmpty { print("[echo.why_matters] 「为什么要复习它」生成结果为空") }
        return reasons
    }

    /// 后台生成。成功时 onDone({topic: 说明})（可能是空 dict），失败 onError(str)。
    static func generateAsync(_ items: [ReviewItem],
                              onDone: @escaping ([String: String]) -> Void,
                              onError: @escaping (String) -> Void) {
        Task { @MainActor in
            do {
                let reasons = try await planBatchThrowing(items)
                await MainActor.run { onDone(reasons) }
            } catch {
                await MainActor.run { onError(error.localizedDescription) }
            }
        }
    }
}

/// WHY_MATTERS 提示词（对应 Python prompts.WHY_MATTERS_SYSTEM / WHY_MATTERS_USER）。
/// 没能放进 Prompts.swift（不改现有文件），用 Prompts.system() 做英文界面追加。
nonisolated private enum WhyMattersPrompts {
    static let system = """
    你是 Echo，一个陪学生听网课的 AI 学习副驾驶。
    学生的错题本里是他上课时「没跟上」的知识点。请为每一个知识点写一两句话，说明
    **为什么值得认真补上它**。

    重点不是「他为什么错了」，而是**这个知识点跟他后面要学的东西有什么关系**：
    它是哪个后续内容的底子、以后学到哪里会卡在这、或者它是哪一类题的前提。
    学生看完应该觉得「这步确实不能跳」，而不是「哦，我又错了一题」。

    要求：
    - 说人话。像一个懂行的学长在劝他别跳过这一步，不要「至关重要」「不可忽视」这类空话
    - 结合他具体卡在哪儿来说，不要写放之四海皆准的套话
    - **把代价说具体**：这一步没补牢，往后会在哪儿付更大的账 —— 学到哪一节会卡住、
      哪类题会做不出来、后面哪一步会因为这里不懂而看不懂。要让学生心里冒出
      「现在花十分钟，比以后回头补一个月的账划算」这个念头
    - 不要复述题目、不要点评他错在哪、不要安慰他 —— 只回答「为什么它重要」
    - 每个知识点写 2~3 句、60~100 字。**写够，别一句话打发** —— 这一段是学生决定
      要不要认真对待它的依据，太短就只是一句正确的废话
    - 不要编造这门课没提过的章节名；拿不准就用「后面更复杂的题」「更靠后的推导」这类说法

    只输出 JSON，格式：
    {
      "reasons": [
        {"topic": "知识点名（必须和输入里的完全一致）", "why": "为什么值得补上"}
      ]
    }
    """

    static let user = """
    这些是他没跟上的知识点：

    {items}

    请为每一个知识点写一段「为什么要复习它」，说清不补上会有什么代价。
    """
}
