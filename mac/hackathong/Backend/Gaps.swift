//
//  Gaps.swift
//  Echo - 反复缺失的前置知识（对应 Python echo/backend/gaps.py）
//
//  回答的是**跨课**的问题，不是单节课的复盘：
//
//      第一次：导数没听懂      → 缺的是「极限」
//      第二次：瞬时速度没听懂  → 又缺「极限」
//      第三次：洛必达法则不会用 → 还是卡在「极限条件」
//      这时才能说：你最近三次掉队都和「极限」有关。
//
//  为什么从课程归档算、而不是从错题本算：错题记录里既没有「属于哪节课」，也没有前置
//  概念。这里改用每节课归档里的 skills_detail（哪些点没掌握）+ graph（谁是谁的前置），
//  数据本来就是齐的，不用新增任何存储字段。
//
//  为什么只数「根源」前置：一节课的图可能是 极限 → 导数定义 → 洛必达法则。学生卡在
//  洛必达法则时，直接前置是导数定义，但真正不稳的地基是链条最上游那个。往下追到没有
//  前置的节点才算，正好对应回响里说的「源泉概念」。
//

import Foundation

/// 一条「反复缺失的前置知识」结论。
/// 对应 Python recurring() 返回的 {"concept","lessons","topics","first_seen","last_seen","sentence"}。
nonisolated struct GapFinding: Codable, Hashable, Sendable {
    var concept: String
    var lessons: Int
    var topics: [String]
    var firstSeen: Double
    var lastSeen: Double
    var sentence: String

    enum CodingKeys: String, CodingKey {
        case concept, lessons, topics, sentence
        case firstSeen = "first_seen"
        case lastSeen = "last_seen"
    }
}

enum Gaps {
    static let window = 10       // 只看最近这么多节课。再往前的和现在的学习状态关系不大
    static let threshold = 3     // 跨几节**不同的课**才算「反复」。两次可能只是巧合
    static let maxTopics = 4     // finding 里最多列几个知识点（资料页排版限制）

    private static func t(_ zh: String, _ en: String) -> String {
        EchoConfig.english ? en : zh
    }

    // MARK: - 名字归一（与 mindmap.py 的 _norm / _same 同一套）

    // Python gaps.py 直接复用 mindmap._same/_norm；Swift 侧 Mindmap 把它们收成了 private，
    // 这里按同一套规则复刻一份（改动 Mindmap 会破坏「别改现有文件」的约束）。
    private static let normStrip: Set<Character> = Set("，,。.：:、（）()[]「」『』!?！？-—_. \t\n\r")

    private static func norm(_ s: String) -> String {
        var out = ""
        out.reserveCapacity(s.count)
        for ch in s.lowercased() where !ch.isWhitespace && !normStrip.contains(ch) {
            out.append(ch)
        }
        return out
    }

    /// 包含判同：「极限」和「极限条件」算同一个概念。
    private static func same(_ a: String, _ b: String) -> Bool {
        let na = norm(a), nb = norm(b)
        if na.isEmpty || nb.isEmpty { return false }
        return na == nb || na.contains(nb) || nb.contains(na)
    }

    // MARK: - 课程 → 薄弱点 / 根源

    /// topic 的「根源前置概念」：顺着前置边往上走，走到没有前置的那些点。
    /// edges 的 from 是前置、to 是后继。返回去重后的名字列表。
    private static func rootsOf(_ topic: String, edges: [MindEdge]) -> [String] {
        var pres: [String: [String]] = [:]          // 后继 → [前置, ...]
        for e in edges { pres[e.to, default: []].append(e.from) }
        var seen: Set<String> = [topic]
        var stack: [String] = pres[topic] ?? []
        var roots: [String] = []
        while let cur = stack.popLast() {
            if seen.contains(cur) { continue }
            seen.insert(cur)
            let ups = pres[cur] ?? []
            if ups.isEmpty {
                roots.append(cur)                   // 没有前置 → 它自己就是根源
            } else {
                stack.append(contentsOf: ups)
            }
        }
        return roots
    }

    /// 这节课里学生没掌握的知识点（status 不是 ok）。
    private static func weakTopics(_ graph: MindmapGraph) -> [String] {
        graph.nodes.compactMap { n in
            let topic = n.topic.trimmingCharacters(in: .whitespaces)
            guard !topic.isEmpty, n.status != "ok" else { return nil }
            return topic
        }
    }

    /// 模板兜底句。**永远非空**——资料页那块不能因为没配 key 就空着。
    ///
    /// 注意：这是**跨课结论**，所以课次数直接用 n（调用方只在 n >= threshold 时才用它）。
    private static func sentence(_ concept: String, n: Int) -> String {
        t("你最近 \(n) 节课都和「\(concept)」有关。问题可能不在当前章节，"
          + "而是这个前置知识还不稳定。",
          "Your last \(n) lessons kept coming back to \"\(concept)\". The problem may not be "
          + "this chapter at all — that prerequisite still isn't solid.")
    }

    // MARK: - 聚合

    private struct Agg {
        var name: String
        var lessons: Set<Double>
        var topics: [String]
        var firstSeen: Double
        var lastSeen: Double
    }

    /// 把「这节课的这个薄弱点源于 root」记一笔。
    ///
    /// 归并要按**包含**判同（同 mindmap._same）：用户例子里「极限」和「极限条件」是同一个
    /// 概念但字面不同，按精确字符串分组会把那三次拆成两条、永远凑不够 3 次。
    /// 显示名取更短的那个：「极限」短于「极限条件」，而短的一般才是概念本身。
    private static func bump(_ agg: inout [Agg], root rawRoot: String, ts: Double, weakTopic: String) {
        let root = rawRoot.trimmingCharacters(in: .whitespacesAndNewlines)
        if root.isEmpty { return }

        if let i = agg.firstIndex(where: { same($0.name, root) }) {
            if norm(root).count < norm(agg[i].name).count { agg[i].name = root }
            agg[i].lessons.insert(ts)
            if ts != 0 {
                let base = agg[i].firstSeen == 0 ? ts : agg[i].firstSeen
                agg[i].firstSeen = min(base, ts)
                agg[i].lastSeen = max(agg[i].lastSeen, ts)
            }
            if !agg[i].topics.contains(weakTopic) { agg[i].topics.append(weakTopic) }
        } else {
            agg.append(Agg(name: root, lessons: [ts], topics: [weakTopic],
                           firstSeen: ts, lastSeen: ts))
        }
    }

    // MARK: - 对外接口

    /// 找出反复挡在薄弱知识点后面的根源前置概念。
    ///
    /// 返回按「跨了几节课」从多到少排序的 finding 列表。lessons 是跨了几节不同的课
    /// （= 判据的分子），topics 是那些没掌握的知识点。
    static func recurring(lessons: [LessonRecord]? = nil,
                          window: Int = Gaps.window,
                          threshold: Int = Gaps.threshold) -> [GapFinding] {
        // Python 读课程归档失败会返回 []；Swift 的 ReviewStore.listLessons 不抛异常。
        let rows = lessons ?? ReviewStore.listLessons()

        var agg: [Agg] = []
        for ls in rows.prefix(window) {
            let graph = Mindmap.build(lesson: ls, mistakes: [])
            let weak = weakTopics(graph)
            if weak.isEmpty { continue }
            let ts = ls.time
            if !ls.graph.nodes.isEmpty {
                // 新课：边就是 AI 报的 prerequisites，谁是谁的前置说得清清楚楚
                let edges = graph.edges
                for w in weak {
                    for root in rootsOf(w, edges: edges) where !Mindmap.isPlaceholderTopic(root) {
                        bump(&agg, root: root, ts: ts, weakTopic: w)
                    }
                }
            } else {
                // 旧课没有依赖图。只用它**自己报的那个根源概念**（回响里「最该先复习的」），
                // 不顺着讲课顺序推出来的边去认前置——那些边是给地图页排版用的，
                // 拿它断言「你的问题在这」是在说我们并不知道的事。
                let root = graph.reviewFirst
                if !root.isEmpty && !Mindmap.isPlaceholderTopic(root) {
                    for w in weak { bump(&agg, root: root, ts: ts, weakTopic: w) }
                }
            }
        }

        var out: [GapFinding] = []
        for a in agg {
            let n = a.lessons.count
            if n < threshold { continue }
            out.append(GapFinding(concept: a.name, lessons: n,
                                  topics: Array(a.topics.prefix(maxTopics)),
                                  firstSeen: a.firstSeen, lastSeen: a.lastSeen,
                                  sentence: sentence(a.name, n: n)))
        }
        // 课次数多的排前面；并列时最近还在卡着的先出来
        out.sort { lhs, rhs in
            if lhs.lessons != rhs.lessons { return lhs.lessons > rhs.lessons }
            return lhs.lastSeen > rhs.lastSeen
        }
        return out
    }

    // MARK: - AI 叙述

    /// 把结论整理成喂给模型的条目（固定中文，不进 UI 语言分支）。
    private static func formatFindings(_ findings: [GapFinding]) -> String {
        var lines: [String] = []
        for f in findings {
            lines.append("- 根源概念：\(f.concept)（最近 \(f.lessons) 节不同的课都指向它）")
            if !f.topics.isEmpty {
                lines.append("  他这几节课没掌握的知识点：\(f.topics.joined(separator: "、"))")
            }
        }
        return lines.joined(separator: "\n")
    }

    /// 让 AI 把结论讲成一段话。拿不到就返回空串，调用方退回模板句子。
    /// 离线 / 没 key 直接返回空：这段是锦上添花，不能因为它把画像整块拖住。
    @MainActor static func narrate(_ findings: [GapFinding]) async -> String {
        do {
            return try await narrateThrowing(findings)
        } catch {
            print("[echo.gaps] 生成前置知识叙述失败（退回模板句子）: \(error.localizedDescription)")
            return ""
        }
    }

    @MainActor private static func narrateThrowing(_ findings: [GapFinding]) async throws -> String {
        if findings.isEmpty { return "" }
        if EchoConfig.offline || EchoConfig.deepseekAPIKey.isEmpty { return "" }
        let system = Prompts.system(GapsPrompts.system)
        let user = GapsPrompts.user.replacingOccurrences(of: "{items}", with: formatFindings(findings))
        let data = try await LLM().json(system: system, user: user, temperature: 0.6, maxTokens: 500)
        return ((data["narrative"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 后台生成叙述。成功时 onDone(文本)（可能是空串），失败 onError(str)。
    static func narrateAsync(_ findings: [GapFinding],
                             onDone: @escaping (String) -> Void,
                             onError: @escaping (String) -> Void) {
        Task { @MainActor in
            do {
                let text = try await narrateThrowing(findings)
                await MainActor.run { onDone(text) }
            } catch {
                await MainActor.run { onError(error.localizedDescription) }
            }
        }
    }
}

/// GAPS 提示词（对应 Python prompts.GAPS_SYSTEM / GAPS_USER）。
/// 没能放进 Prompts.swift（不改现有文件），用 Prompts.system() 做英文界面追加。
nonisolated private enum GapsPrompts {
    static let system = """
    你是 Echo，一个陪学生听网课的 AI 学习副驾驶。
    系统已经统计出：学生最近几节课掉队的地方，反复指向同一个前置知识。请把这件事
    讲给他听。

    这是**跨课的规律**，不是某一节课的问题 —— 要说清这一点：他每次以为自己卡在
    当前章节，其实底下是同一个地基没打牢。

    要求：
    - 直接说结论，不要复述统计数字、不要「根据数据分析」这种腔调
    - 说人话。像一个真的看懂了他的学长，不是在念报告
    - 不要安慰、不要说教、不要「别灰心」这类话 —— 学生需要的是被点醒，不是被哄
    - 2~3 句，60~100 字
    - 只根据给的信息说，不要编造他没学过的章节或没发生过的经历

    只输出 JSON，格式：
    {
      "narrative": "说给学生听的那段话"
    }
    """

    static let user = """
    统计结果：

    {items}

    请写一段话，把这个规律讲给这个学生听。
    """
}
