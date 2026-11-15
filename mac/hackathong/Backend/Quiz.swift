//
//  Quiz.swift
//  Echo - 出题（对应 Python echo/backend/quiz.py）
//
//  两种题：
//    · 课中抽问（check-in）：老师正在讲，Echo 拿刚讲过的知识点出一道 10 秒小題，
//      看学生跟不跟得上；答错记进错题本。
//    · 课后练习（lesson quiz）：一节课结束，按要点出几道题趁热巩固。
//  没 key / 连不上 AI 时退化成自评题（记得 / 有点模糊 / 没跟上），永远不返回空。
//

import Foundation

nonisolated struct CheckinQuestion: Identifiable, Codable, Sendable {
    var id: Int = 0
    var topic: String
    var tc: String             // 时间码
    var question: String
    var options: [String]
    var answer: String         // 正确选项字母，如 "B"；自评题 / 无选项时为空
    var explain: String
    var selfReport: Bool       // Python 的 self_report：不判对错，学生自评
    var why: String = ""       // 触发兜底的原因（如 "noconcept"）；正常出题时为空

    /// 兼容命名：有些调用点用 timecode。
    var timecode: String { tc }

    /// 正确选项下标（Python answer 是选项字母，Swift 侧判分用下标）；对不上时为 nil。
    var answerIndex: Int? {
        guard !answer.isEmpty, !options.isEmpty else { return nil }
        let letter = String(answer.trimmingCharacters(in: .whitespacesAndNewlines).uppercased().prefix(1))
        return options.firstIndex { $0.trimmingCharacters(in: .whitespaces).uppercased().hasPrefix(letter) }
    }
}

/// 一次抽问的答题记录。
nonisolated struct CheckinRecord: Codable, Sendable {
    var question: String
    var chosen: Int?           // 学生选的选项下标
    var result: String         // right / wrong / unsure
    var answer: String         // 正确选项文字（Quiz.correctText）
    var explain: String
}

enum Quiz {
    static let right = "right"      // 答对 / 自评「记得」
    static let wrong = "wrong"      // 答错 / 自评「没跟上」
    static let unsure = "unsure"    // 自评「有点模糊」

    /// 离线自评题的选项：选第一项算跟上，其余都记进错题本。
    static let selfOptions = ["A. 记得，能说个大概", "B. 有点模糊", "C. 完全没跟上"]
    private static let selfGrade = [right, unsure, wrong]

    // MARK: - 出题

    /// 生成一道抽问题。永远返回非空结果（最差也有自评题兜底）。
    /// focus 是学生此刻的状态（刚掉队过的地方、之前抽问答错的知识点），出题时带上它。
    static func checkin(timeline: String, transcript: String, current: String,
                        timecode: String = "", focus: String = "") async -> CheckinQuestion {
        let key = EchoConfig.deepseekAPIKey
        if !EchoConfig.offline && !key.isEmpty {
            do {
                let llm = try LLM(apiKey: key)
                let data = try await llm.json(
                    system: Prompts.system(Prompts.checkinSystem),
                    user: Prompts.checkinUser(
                        timeline: timeline.isEmpty ? "（暂无）" : timeline,
                        transcript: transcript.isEmpty ? "（暂无）" : transcript,
                        current: current.isEmpty ? "（还没识别到知识点）" : current,
                        focus: focus.isEmpty ? "（没什么特别的，正常听课）" : focus),
                    temperature: 0.6, maxTokens: 500,
                    timeout: Double(EchoConfig.checkinTimeout), attempts: 1)
                if let q = cleanCheckin(data, tc: timecode) { return q }
                // LLM 说「这段还不适合出题」→ 不硬出选择题，退成自评题
                print("[echo.quiz] LLM 判断当前内容不适合出题，改用自评题")
            } catch {
                print("[echo.quiz] 抽问 LLM 失败，改用自评题: \(error.localizedDescription)")
            }
        }
        return selfCheckin(topic: current, timecode: timecode)
    }

    /// 自评兜底题：不判断对错，让学生自己说跟没跟上。
    /// 知识点名拿不出手时（空、或「老师正在讲的内容」这类占位名）不往题干里塞，改成不点名地问。
    static func selfCheckin(topic: String, timecode: String, why: String = "") -> CheckinQuestion {
        let name = topic.trimmingCharacters(in: .whitespacesAndNewlines)
        let ok = !name.isEmpty && !Mindmap.isPlaceholderTopic(name)
        let question = ok ? "老师刚讲了「\(name)」，你现在还记得它是怎么回事吗？" : "刚才这段课你跟上节奏了吗？"
        return CheckinQuestion(topic: ok ? name : "", tc: timecode, question: question,
                               options: selfOptions, answer: "", explain: "", selfReport: true, why: why)
    }

    // MARK: - 判分

    /// 判分：choice 是学生选的选项下标。返回 right / unsure / wrong。
    static func grade(_ q: CheckinQuestion, choice: Int) -> String {
        guard choice >= 0, choice < q.options.count else { return wrong }
        if q.selfReport {
            return choice < selfGrade.count ? selfGrade[choice] : wrong
        }
        guard let ai = q.answerIndex else { return wrong }
        return choice == ai ? right : wrong
    }

    /// 正确答案的文字，用于错题本和讲解。
    static func correctText(_ q: CheckinQuestion) -> String {
        if let ai = q.answerIndex, ai >= 0, ai < q.options.count { return q.options[ai] }
        if let first = q.options.first { return first }
        return q.explain
    }


    // MARK: - 课后练习

    /// 按一节课的要点出课后练习题。没有 key / 离线 / 传不到课 时返回 []，由调用方决定换别的入口。
    static func lessonQuiz(lesson: LessonRecord?, n: Int = 4) async -> [PracticeQuestion] {
        guard let lesson else { return [] }
        if EchoConfig.offline { return [] }
        let key = EchoConfig.deepseekAPIKey
        guard !key.isEmpty else { return [] }
        do {
            let llm = try LLM(apiKey: key)
            let data = try await llm.json(
                system: Prompts.system(Prompts.lessonQuizSystem(n: n)),
                user: Prompts.lessonQuizUser(
                    summary: lesson.summary.isEmpty ? "（无）" : lesson.summary,
                    highlights: lesson.points,
                    skills: skillsText(lesson), n: n),
                temperature: 0.5, maxTokens: 1400)
            return cleanQuestions(data, n: n)
        } catch {
            print("[echo.quiz] 课后练习出题失败: \(error.localizedDescription)")
            return []
        }
    }

    // MARK: - 规范化

    /// 把 LLM 返回的单道抽问题规范化；不适合出题时返回 nil。
    private static func cleanCheckin(_ data: JSONDict, tc: String) -> CheckinQuestion? {
        let question = str(data["question"])
        guard !question.isEmpty else { return nil }

        var options: [String] = []
        if let raw = data["options"] as? [Any] {
            options = raw.map { "\($0)".trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        }

        // Python 的 answer 是选项字母；校验它确实对应某个选项，否则退化为自评题
        var answer = str(data["answer"]).uppercased()
        answer = answer.isEmpty ? "" : String(answer.prefix(1))
        if !options.isEmpty && !options.indices.map(letter).contains(answer) {
            print("[echo.quiz] 抽问题答案 \(answer) 与选项不匹配，退化为自评题")
            options = []
            answer = ""
        }

        return CheckinQuestion(topic: str(data["topic"]), tc: tc, question: question,
                               options: options, answer: answer,
                               explain: str(data["explain"]), selfReport: options.isEmpty, why: "")
    }

    /// 规范化一批练习题；形状与 practice.py 的输出保持一致。
    private static func cleanQuestions(_ data: JSONDict, n: Int) -> [PracticeQuestion] {
        guard let items = data["questions"] as? [Any] else { return [] }
        var out: [PracticeQuestion] = []
        for case let raw as JSONDict in items {
            let question = str(raw["question"])
            guard !question.isEmpty else { continue }
            let options = ((raw["options"] as? [Any]) ?? [])
                .map { "\($0)".trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            out.append(PracticeQuestion(question: question, options: options,
                                        answer: str(raw["answer"]), explain: str(raw["explain"])))
            if out.count >= n { break }
        }
        return out
    }

    // MARK: - 工具

    /// 知识点掌握情况（课前出题用它优先考薄弱点）
    private static func skillsText(_ lesson: LessonRecord) -> String {
        let lines = lesson.skills.filter { !$0.name.isEmpty }.map {
            "- \($0.name)（掌握度 \(String(format: "%.2f", $0.mastery))，\($0.status.rawValue)）"
        }
        return lines.isEmpty ? "（无）" : lines.joined(separator: "\n")
    }

    private static func str(_ v: Any?) -> String {
        (v as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 选项下标 → 选项字母（0 → "A"）。
    private static func letter(_ i: Int) -> String {
        guard let scalar = UnicodeScalar(UInt32(65 + i)) else { return "" }
        return String(Character(scalar))
    }
}
