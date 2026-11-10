//
//  Mindmap.swift
//  Echo - 知识地图（对应 Python echo/backend/mindmap.py）
//
//  一节课上完，把知识点画成一张图：节点是知识点，连线是「学这个之前得先懂那个」。
//
//  数据有两层来源：
//    1. 回响报告里的真实信息（EchoReport.skills / reviewChain）—— 结构最全
//    2. 历史课程记录只有 review_chain：退回用复习链 + 讲课顺序推导，
//       边弱一些但结构完整，所以主页翻出来的旧课也有知识地图。
//

import Foundation

// MARK: - 数据模型

nonisolated struct MindNode: Identifiable, Codable, Hashable, Sendable {
    var id: String            // 知识点名（同时也是 topic）
    var topic: String
    var level: Int            // 依赖层级：前置概念在第 0 层，依赖它的往上叠
    var status: String        // review 待回看 / fixed 补上了 / ok 已跟上
    var mastery: Double       // 0~1
    var timecode: String?     // 掉队或讲到这个知识点的时间码；没有则 nil

    // ===== 已学内容大图（build_all）才有的分区信息 =====
    var subject: String = ""       // 来自课程标题推断的学科；单课图里为空
    var subjectIndex: Int = 0      // 学科在 subjects 里的编号；单课图里为 0
    var hasMistake: Bool = false   // 这个知识点在错题本里有没有记录
}

nonisolated struct MindEdge: Identifiable, Codable, Hashable, Sendable {
    var from: String
    var to: String
    var id: String { "\(from)->\(to)" }   // 计算属性，不参与编解码（对应 Python 的 {from,to}）
}

nonisolated struct MindmapGraph: Codable, Hashable, Sendable {
    var nodes: [MindNode]
    var edges: [MindEdge]
    /// 最该先复习的根源概念（Python 的 review_first）；没有则空串。
    var reviewFirst: String = ""
    /// 学科列表（Python build_all 的 subjects，首次出现顺序）；单课图为空。
    var subjects: [String] = []
}

/// 「已学内容」聚合图 + 给节点详情 / 出题用的伪课程记录（对应 Python build_all 的返回）。
nonisolated struct MindmapCatalog: Sendable {
    var graph: MindmapGraph
    /// 合并后的 skills_detail 拼成的伪 lesson，够 nodeDetail / questions 用。
    var lesson: LessonRecord
}

nonisolated struct MindNodeDetail: Codable, Hashable, Sendable {
    var topic: String
    var timecode: String?     // 掉队时间码；没有则 nil
    var taught: String        // 老师怎么讲的（课程摘要里能对上这个知识点的部分）
    var missing: String       // 卡在哪
    var known: String         // 已经知道的
    var step: String          // 漏掉的那一步
    var microLesson: String   // 30 秒补课
    var status: String        // review / fixed / ok
    var reviewFirst: Bool     // 是不是「最该先复习的根源概念」
    var mastery: Double = 0   // 知识点掌握度 0~1（对应 Python node_detail 的 mastery）
    var hasMistake: Bool = false   // 错题本里有没有它（Python has_mistake）
    var now: String = ""      // 补完课「所以现在能听懂什么」（Python node_detail 的 now）

    enum CodingKeys: String, CodingKey {
        case topic, timecode, taught, missing, known, step, status, mastery, now
        case microLesson = "micro_lesson"
        case reviewFirst = "review_first"
        case hasMistake = "has_mistake"
    }
}

// MARK: - 知识地图

enum Mindmap {
    // 掌握状态：ok 已跟上 / fixed 掉队过但补上了 / review 待回看
    private enum Status {
        static let ok = "ok", fixed = "fixed", review = "review"
    }

    // 抽知识点时 AI 偶尔拿不准就填个占位名交差（「未知」「课堂内容」…），
    // 这种名字不该变成图里一个叫「（未知）」的节点。
    private static let placeholderTopics: Set<String> = [
        "未知", "未知知识点", "未知概念", "未命名", "未命名课程", "课堂内容",
        "内容", "无", "暂无", "不详", "待定", "其他", "其它", "略",
        // 「老师正在讲的内容」这种：AI 拿不准具体是什么知识点，就改去描述
        // 「现在正在发生什么」。它不是知识点名，抽查还会拿它当题干。
        "老师正在讲的内容", "正在讲的内容", "老师讲的内容", "现在讲的内容",
    ]
    private static let placeholderPrefixes = ["未知", "未命名", "不详", "待定", "未明确", "没有", "无法确定", "暂无"]

    // 「老师（正在）讲（的）内容/知识点/…」这类描述流程的占位说法。
    // 中间那个动词是必须匹配的，否则这个正则会把空串也算进来。
    // 单独写成正则（而不是穷举字符串），因为中间的「正在 / 的 / 名词」可以省略组合。
    nonisolated(unsafe) private static let placeholderFlowRegex: NSRegularExpression? =
        try? NSRegularExpression(pattern:
            "^(老师|现在|刚才|当前)?(正在)?(讲|说|提到|讲解)(的)?(内容|知识点|东西|部分|这段|话)?$")

    // 去掉空格标点，用于知识点名字的模糊匹配（「贝叶斯公式」↔「贝叶斯公式的推导」）。
    private static let normStrip: Set<Character> = Set("，,。.：:、（）()[]「」『』!?！？-—_. \t\n\r")

    private static func norm(_ s: String) -> String {
        var out = ""
        out.reserveCapacity(s.count)
        for ch in s.lowercased() where !ch.isWhitespace && !normStrip.contains(ch) {
            out.append(ch)
        }
        return out
    }

    /// 归一化后的知识点名：跨模块做模糊匹配的键（对应 Python mindmap._norm）。
    static func normKey(_ s: String) -> String { norm(s) }

    /// 这个「知识点名」是不是 AI 填的占位名（空、未知、课堂内容、老师正在讲的内容…）。
    static func isPlaceholderTopic(_ s: String) -> Bool {
        let n = norm(s)
        if n.isEmpty { return true }
        if placeholderTopics.contains(n) { return true }
        if placeholderPrefixes.contains(where: { n.hasPrefix($0) }) { return true }
        if let re = placeholderFlowRegex {
            let range = NSRange(n.startIndex..., in: n)
            if let m = re.firstMatch(in: n, options: [], range: range),
               m.range == range {
                return true
            }
        }
        return false
    }

    // MARK: - 内部课程形状
    //
    // Python 的 lesson 是一本 dict，带 skills_detail / graph / highlights / summary；
    // Swift 的 LessonRecord 只存 review_chain，所以这里做成一个统一的内部形状，
    // build(lesson:) 和 fromReport(_:) 都先转成它再走同一套推导。

    private struct MindSkill {
        var name: String
        var mastery: Double
        var status: String
    }

    private struct LessonData {
        var skills: [MindSkill] = []
        var reviewChain: [String] = []
        var graphNodes: [String] = []
        var graphEdges: [(String, String)] = []
        var times: [String: String] = [:]
        var summary: String = ""
        var highlights: [String] = []
    }

    private static func lessonData(_ lesson: LessonRecord?) -> LessonData {
        guard let lesson else { return LessonData() }
        var d = LessonData()
        d.skills = lesson.skills.compactMap { s in
            guard !s.name.isEmpty, !isPlaceholderTopic(s.name) else { return nil }
            return MindSkill(name: s.name, mastery: s.mastery, status: s.status.rawValue)
        }
        d.reviewChain = lesson.reviewChain
        d.summary = lesson.summary
        d.highlights = lesson.points
        d.graphNodes = lesson.graph.nodes
        d.graphEdges = lesson.graph.edges.compactMap { $0.count == 2 ? ($0[0], $0[1]) : nil }
        d.times = lesson.graph.times
        return d
    }

    // MARK: - 对外接口

    /// 把一节课变成可画的图（nodes 含状态/层级 + edges）。
    static func build(lesson: LessonRecord?, mistakes: [ReviewItem]) -> MindmapGraph {
        buildGraph(lessonData(lesson), mistakes: mistakes)
    }

    /// 把刚下课的回响转成知识地图（字段取 EchoReport.skills / reviewChain）。
    /// title 保留给调用方，图本身不携带课程标题。
    static func fromReport(_ report: EchoReport?, title: String) -> MindmapGraph {
        guard let report else { return MindmapGraph(nodes: [], edges: []) }
        var d = LessonData()
        d.skills = report.skills.compactMap { s in
            guard !s.name.isEmpty, !isPlaceholderTopic(s.name) else { return nil }
            return MindSkill(name: s.name, mastery: s.mastery, status: s.status.rawValue)
        }
        d.reviewChain = report.reviewChain.filter { !isPlaceholderTopic($0) }
        d.summary = report.summary
        d.highlights = report.highlights
        d.graphNodes = report.graph.nodes
        d.graphEdges = report.graph.edges.compactMap { $0.count == 2 ? ($0[0], $0[1]) : nil }
        d.times = report.graph.times
        return buildGraph(d)
    }

    // MARK: - 已学内容大图（按学科分区）

    /// 从课程标题推断学科（对应 Python mindmap.subject_of）：
    /// 取第一个分隔符之前的部分。「初二数学 · 正比例函数」→「初二数学」；
    /// 没有分隔符就用整条标题；仍空则「未分类」。
    static func subjectOf(_ title: String) -> String {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return "未分类" }
        for sep in ["·", "：", ":", "，", ",", "－", "-"] {
            if let r = t.range(of: sep) {
                let head = String(t[t.startIndex..<r.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
                if !head.isEmpty { return head }
            }
        }
        return t
    }

    /// 把所有历史课合并成一张大图，节点按学科分区（对应 Python mindmap.build_all）。
    ///
    /// 遍历每节课调 build() 得单课图，按知识点名（模糊匹配）归并同名节点：取最近一节课的
    /// mastery/status，并记下学科（来自那节课标题）。边并集、保连通。返回形状与 build() 一致，
    /// 节点多 subject / subjectIndex / hasMistake，graph.subjects 列学科；另附伪 lesson
    /// （合并后的 skills_detail），够 nodeDetail / questions 用。
    static func buildAll(lessons: [LessonRecord], mistakes: [ReviewItem] = []) -> MindmapCatalog {
        let ordered = lessons.sorted { $0.time < $1.time }   // 旧 → 新，后写的覆盖

        struct NodeRec {
            var topic: String; var status: String; var mastery: Double
            var subject: String; var hasMistake: Bool
        }
        var nodes: [String: NodeRec] = [:]     // 归一化键 -> 节点信息
        var nodeOrder: [String] = []           // 首次出现顺序（学科编号按它排）
        var edges: [(String, String)] = []
        var allSkills: [LessonSkill] = []

        for lesson in ordered {
            let subj = subjectOf(lesson.title)
            let g = build(lesson: lesson, mistakes: mistakes)
            for n in g.nodes {
                let topic = n.topic.trimmingCharacters(in: .whitespacesAndNewlines)
                if topic.isEmpty || isPlaceholderTopic(topic) { continue }
                let key = norm(topic)
                if nodes[key] == nil { nodeOrder.append(key) }
                nodes[key] = NodeRec(topic: topic,
                                     status: n.status.isEmpty ? Status.ok : n.status,
                                     mastery: n.mastery, subject: subj, hasMistake: n.hasMistake)
            }
            for e in g.edges where !e.from.isEmpty && !e.to.isEmpty && norm(e.from) != norm(e.to) {
                edges.append((e.from, e.to))
            }
            allSkills.append(contentsOf: lesson.skills.filter {
                !$0.name.isEmpty && !isPlaceholderTopic($0.name)
            })
        }

        // 学科编号（按首次出现顺序）
        var subjects: [String] = []
        var subjectIdx: [String: Int] = [:]
        for key in nodeOrder {
            guard let rec = nodes[key] else { continue }
            let ns = norm(rec.subject)
            if subjectIdx[ns] == nil { subjectIdx[ns] = subjects.count; subjects.append(rec.subject) }
        }

        var nodeList: [MindNode] = []
        for key in nodeOrder {
            guard let rec = nodes[key] else { continue }
            nodeList.append(MindNode(id: rec.topic, topic: rec.topic, level: 0, status: rec.status,
                                     mastery: rec.mastery, timecode: nil,
                                     subject: rec.subject, subjectIndex: subjectIdx[norm(rec.subject)] ?? 0,
                                     hasMistake: rec.hasMistake))
        }

        // 边：只留两端都在图里的，去自环、模糊去重
        let topicKeys = Set(nodeList.map { norm($0.topic) })
        var seen = Set<String>()
        var cleanEdges: [(String, String)] = []
        for (a, b) in edges {
            let na = norm(a), nb = norm(b)
            if na == nb || !topicKeys.contains(na) || !topicKeys.contains(nb) { continue }
            let kp = na < nb ? na + "\u{0}" + nb : nb + "\u{0}" + na
            if seen.contains(kp) { continue }
            seen.insert(kp)
            cleanEdges.append((a, b))
        }

        let levels = self.levels(nodes: nodeList.map(\.topic), edges: cleanEdges)
        for i in nodeList.indices { nodeList[i].level = levels[nodeList[i].topic] ?? 0 }

        // 伪 lesson：合并后的 skills_detail，给节点详情 / 出题用（Python 同款）
        let pseudo = LessonRecord(time: 0, title: "", date: "", total: allSkills.count,
                                  ok: allSkills.filter { $0.status == .ok }.count,
                                  review: allSkills.filter { $0.status != .ok }.count,
                                  reviewChain: [], suggestion: "", skills: allSkills)

        let graph = MindmapGraph(nodes: nodeList,
                                 edges: cleanEdges.map { MindEdge(from: $0.0, to: $0.1) },
                                 reviewFirst: "", subjects: subjects)
        return MindmapCatalog(graph: graph, lesson: pseudo)
    }

    /// 图上与这个知识点直接相连的其它知识点（前置/后继都算）—— 详情面板的「相关知识点」跳转用。
    static func related(to topic: String, in graph: MindmapGraph) -> [String] {
        var out: [String] = []
        for e in graph.edges {
            if same(e.from, topic) {
                if !out.contains(e.to) { out.append(e.to) }
            } else if same(e.to, topic) {
                if !out.contains(e.from) { out.append(e.from) }
            }
        }
        return out
    }

    /// 点开某个知识点要显示的东西：状态、老师怎么讲的、不懂时的讲解。
    /// reviewFirst 传大图的 review_first（buildAll 场景），不传就按这节课自己算。
    static func nodeDetail(lesson: LessonRecord?, topic: String, mistakes: [ReviewItem],
                           reviewFirst: String? = nil) -> MindNodeDetail {
        let data = lessonData(lesson)
        let sk = skillOf(data, topic: topic)
        let mk = mistakeOf(mistakes, topic: topic)
        let highlights = data.highlights.filter { same(topic, $0) || norm($0).contains(norm(topic)) }
        let taught = highlights.isEmpty ? data.summary : highlights.joined(separator: "\n")
        let status: String
        if let s = sk?.status, !s.isEmpty {
            status = s
        } else {
            status = mk != nil ? Status.review : Status.ok
        }
        let tc = mk?.timecode ?? ""
        // 大图的 review_first 是全局的；单课图没传时按复习链自己算。
        let isReviewFirst: Bool
        if let reviewFirst, !reviewFirst.isEmpty {
            isReviewFirst = same(topic, reviewFirst)
        } else {
            isReviewFirst = reviewFirstMatches(data, topic: topic, mistakes: mistakes)
        }
        return MindNodeDetail(topic: topic,
                              timecode: tc.isEmpty ? nil : tc,
                              taught: taught,
                              missing: mk?.missing ?? "",
                              known: mk?.known ?? "",
                              step: mk?.step ?? "",
                              microLesson: mk?.microLesson ?? "",
                              status: status,
                              reviewFirst: isReviewFirst,
                              mastery: sk?.mastery ?? 0,
                              hasMistake: mk != nil,
                              now: mk?.now ?? "")
    }

    /// 给某个知识点出 n 道题（带解析）。同步拼错题形状，再交给 Practice 调 AI / 兜底。
    static func questions(for topic: String, lesson: LessonRecord?, mistakes: [ReviewItem],
                          n: Int = 2) async -> [PracticeQuestion] {
        let item = makeItem(lessonData(lesson), topic: topic, mistake: mistakeOf(mistakes, topic: topic))
        return await Practice.generate(item, n: n)
    }

    // MARK: - 图构建

    private static func buildGraph(_ lesson: LessonData, mistakes: [ReviewItem] = []) -> MindmapGraph {
        var nodesSrc = lesson.graphNodes.filter {
            !$0.trimmingCharacters(in: .whitespaces).isEmpty && !isPlaceholderTopic($0)
        }
        var edgesSrc = lesson.graphEdges.filter { !isPlaceholderTopic($0.0) && !isPlaceholderTopic($0.1) }
        if nodesSrc.isEmpty {
            let derived = deriveGraph(lesson)
            nodesSrc = derived.nodes
            edgesSrc = derived.edges
        }

        // 去重但保序，方便稳定渲染
        var seenNodes = Set<String>()
        nodesSrc = nodesSrc.filter { seenNodes.insert($0).inserted }

        // 边只保留两端都在图里的（模糊匹配），并去掉自环和重复
        var edges: [(String, String)] = []
        var seenEdges = Set<String>()
        for (a, b) in edgesSrc {
            if a == b || !sameIn(a, nodesSrc) || !sameIn(b, nodesSrc) { continue }
            let key = a + "\u{0}" + b
            if seenEdges.contains(key) { continue }
            seenEdges.insert(key)
            edges.append((a, b))
        }
        edges = connectIsolated(nodes: nodesSrc, edges: edges)
        let levels = self.levels(nodes: nodesSrc, edges: edges)

        var nodes: [MindNode] = []
        for t in nodesSrc {
            let sk = skillOf(lesson, topic: t)
            let mk = mistakeOf(mistakes, topic: t)
            let status: String
            if let s = sk?.status, !s.isEmpty {
                status = s
            } else {
                status = mk != nil ? Status.review : Status.ok
            }
            var tc = mk?.timecode ?? ""
            if tc.isEmpty { tc = lesson.times[t] ?? "" }
            nodes.append(MindNode(id: t, topic: t, level: levels[t] ?? 0, status: status,
                                  mastery: sk?.mastery ?? 0, timecode: tc.isEmpty ? nil : tc,
                                  hasMistake: mk != nil))
        }
        // 复习链的最后一个是最该先补的根源（Python 的 review_first）
        let chainRoot = lesson.reviewChain.filter { !$0.isEmpty && !isPlaceholderTopic($0) }.last ?? ""
        let reviewFirst = chainRoot.isEmpty ? "" : (nodes.first { same($0.topic, chainRoot) }?.topic ?? "")
        return MindmapGraph(nodes: nodes, edges: edges.map { MindEdge(from: $0.0, to: $0.1) },
                            reviewFirst: reviewFirst)
    }

    /// 没有 graph 时的推导：复习链当主干，其余知识点按讲课顺序串起来。
    private static func deriveGraph(_ lesson: LessonData) -> (nodes: [String], edges: [(String, String)]) {
        var nodes = lesson.skills.map(\.name)
        var edges: [(String, String)] = []

        let chain = lesson.reviewChain.filter { !$0.isEmpty && !isPlaceholderTopic($0) }
        // review_chain 是「掉队点 → … → 最该先复习的根源概念」，反过来才是知识依赖方向
        let ordered = chain.reversed().map { $0 }
        if ordered.count >= 2 {
            for i in 0..<(ordered.count - 1) {
                let a = ordered[i], b = ordered[i + 1]
                edges.append((a, b))
                for t in [a, b] where !nodes.contains(where: { same(t, $0) }) {
                    nodes.append(t)
                }
            }
        }

        // 剩下的知识点按课堂顺序接在前一个后面，保证图是连通的
        var prev: String? = ordered.last
        for s in lesson.skills {
            let name = s.name
            if ordered.contains(where: { same(name, $0) }) { continue }
            if let p = prev, !same(p, name) { edges.append((p, name)) }
            prev = name
        }
        return (nodes, edges)
    }

    /// 按依赖深度分层：前置概念在第 0 层，依赖它的往上叠。有环也不会死循环。
    private static func levels(nodes: [String], edges: [(String, String)]) -> [String: Int] {
        var deps: [String: [String]] = [:]
        for n in nodes { deps[n] = [] }
        for (a, b) in edges where a != b {
            if deps[a] != nil, deps[b] != nil { deps[b]!.append(a) }
        }

        var level: [String: Int] = [:]
        func depth(_ n: String, _ seen: Set<String>) -> Int {
            if let l = level[n] { return l }
            if seen.contains(n) { return 0 }   // 有环，按 0 处理，别再往下钻
            var s = seen
            s.insert(n)
            var d = 0
            for p in deps[n] ?? [] { d = max(d, depth(p, s) + 1) }
            level[n] = d
            return d
        }
        for n in nodes { _ = depth(n, []) }
        return level
    }

    /// 把没有任何连线的知识点按顺序接入链里，保证图是一节课完整的知识链。
    private static func connectIsolated(nodes: [String], edges: [(String, String)]) -> [(String, String)] {
        var linked = Set<String>()
        for e in edges { linked.insert(e.0); linked.insert(e.1) }
        var out = edges
        var prev: String?
        for t in nodes {
            if let p = prev, !linked.contains(t) {
                out.append((p, t))
                linked.insert(t)
            }
            prev = t
        }
        return out
    }

    // MARK: - 小工具

    private static func same(_ a: String, _ b: String) -> Bool {
        let na = norm(a), nb = norm(b)
        if na.isEmpty || nb.isEmpty { return false }
        return na == nb || na.contains(nb) || nb.contains(na)
    }

    private static func sameIn(_ topic: String, _ nodes: [String]) -> Bool {
        nodes.contains { same(topic, $0) }
    }

    private static func skillOf(_ lesson: LessonData, topic: String) -> MindSkill? {
        lesson.skills.first { same($0.name, topic) }
    }

    private static func mistakeOf(_ mistakes: [ReviewItem], topic: String) -> ReviewItem? {
        mistakes.first { same($0.topic, topic) }
    }

    /// 复习链最后一项是「最该先复习的根源概念」（回响 prompt 里就是这么排的），
    /// 从后往前找第一个能在图里对上的节点，标出「从哪开始补」。
    private static func reviewFirstMatches(_ lesson: LessonData, topic: String, mistakes: [ReviewItem]) -> Bool {
        let nodes = buildGraph(lesson, mistakes: mistakes).nodes
        let chain = lesson.reviewChain.filter { !$0.isEmpty && !isPlaceholderTopic($0) }
        for cand in chain.reversed() {
            if let hit = nodes.first(where: { same(cand, $0.topic) }) {
                return same(topic, hit.topic)
            }
        }
        return false
    }

    private static func nonEmpty(_ s: String?) -> String? {
        guard let s, !s.isEmpty else { return nil }
        return s
    }

    /// 拼出一个「错题形状」的 ReviewItem，喂给 Practice 出题（没有错题也能出题）。
    private static func makeItem(_ lesson: LessonData, topic: String, mistake: ReviewItem?) -> ReviewItem {
        let mk = mistake
        let highlights = lesson.highlights.filter { same(topic, $0) || $0.contains(topic) }
        let sk = skillOf(lesson, topic: topic)
        var known = nonEmpty(mk?.known) ?? ""
        if known.isEmpty { known = highlights.first ?? "" }
        let status: String
        if let s = sk?.status, !s.isEmpty {
            status = s
        } else {
            status = mk != nil ? Status.review : Status.ok
        }
        return ReviewItem(topic: topic,
                          missing: nonEmpty(mk?.missing) ?? "「\(topic)」是怎么来的、什么时候用？",
                          reason: nonEmpty(mk?.reason) ?? "课后想再确认一下这个知识点",
                          microLesson: nonEmpty(mk?.microLesson) ?? lesson.summary,
                          known: known,
                          step: mk?.step ?? "",
                          now: mk?.now ?? "",
                          status: status)
    }
}
