//
//  Persona.swift
//  Echo - 学生画像（根据复习表现生成，不是 AI 猜的）
//  对应 Python echo/backend/persona.py
//
//  从错题本的客观数据里算：容易卡在哪一类反馈上（经常「还是没懂」还是一遍就「清楚」）、
//  整体状态是在进步还是吃力。算出来的 toneHint 会喂给「讲给 Echo 听」的提示词，
//  让 AI 说话的方式跟着这个学生调整——容易没听懂的学生，解释要更慢更具体；
//  吸收快的学生，不用啰嗦复述。
//
//  存在 profile.json 的 persona 字段里，跟资料一起落盘。
//
//  **多久重算一次**：画像不是每答一道题就变，攒够了新数据才重算——又上完
//  LESSON_STEP 节课，或者又判过 REVIEW_STEP 次复习，谁先到算谁。上次是在什么进度上
//  算的记在 profile.json 的 persona_baseline_* 里。
//
//  **两个出口别混**：describe() 是给学生看的一段话，toneHint() 是喂给模型的祈使句。
//

import Foundation

/// 画像数据（对应 Python persona.compute() 返回的那个 dict）。
nonisolated struct PersonaData: Codable, Hashable, Sendable {
    var style: String = "steady"
    var trend: String = "steady"
    var againRate: Double = 0
    var clearRate: Double = 0
    var sample: Int = 0

    init(style: String = "steady", trend: String = "steady",
         againRate: Double = 0, clearRate: Double = 0, sample: Int = 0) {
        self.style = style
        self.trend = trend
        self.againRate = againRate
        self.clearRate = clearRate
        self.sample = sample
    }

    enum CodingKeys: String, CodingKey {
        case style, trend, sample
        case againRate = "again_rate"
        case clearRate = "clear_rate"
    }

    // 宽松解码：缺字段 / 坏字段用中性默认值（老文件可能没有 persona 之外的键）。
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        style = (try? c.decode(String.self, forKey: .style)) ?? "steady"
        trend = (try? c.decode(String.self, forKey: .trend)) ?? "steady"
        sample = (try? c.decode(Int.self, forKey: .sample)) ?? 0
        againRate = (try? c.decode(Double.self, forKey: .againRate)) ?? 0
        clearRate = (try? c.decode(Double.self, forKey: .clearRate)) ?? 0
    }
}

/// profile.json 的原始读写。persona 只动 persona_* 几个键，其余（姓名/头像/created…）
/// 原样保留——对应 Python profile.save()/_update() 的「白名单 + 合并 + 原子替换」。
/// ProfileStore 目前只暴露了 Profile 结构（丢掉了 persona 字段），所以这里自己读原始 JSON；
/// 用 EchoPaths.dir，跟 ProfileStore 落的是同一个 Application Support/Echo/profile.json。
private enum PersonaProfile {
    static var url: URL { EchoPaths.dir.appendingPathComponent("profile.json") }

    static func load() -> [String: Any] {
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return [:] }
        return obj
    }

    /// 把 patch 并进 profile.json 并落盘（临时文件 + 原子替换，写一半断电不会弄坏旧资料）。
    static func update(_ patch: [String: Any]) {
        var cur = load()
        for (k, v) in patch { cur[k] = v }
        let now = Date().timeIntervalSince1970
        if cur["created"] == nil { cur["created"] = now }
        cur["updated"] = now
        guard let data = try? JSONSerialization.data(
            withJSONObject: cur, options: [.prettyPrinted, .withoutEscapingSlashes])
        else { return }
        do {
            try data.write(to: url, options: .atomic)
        } catch {
            print("[echo.persona] 画像保存失败: \(error.localizedDescription)")
        }
    }
}

enum Persona {
    // 攒够这些新数据就重算一次。定得太小画像会随每道题抖，太大又跟不上学生的变化。
    static let lessonStep = 3        // 又上完几节课
    static let reviewStep = 8        // 又判过几次复习（按「判过的次数」算，不是条目数）

    static let styleNeedsExamples = "needs_examples"
    static let styleConcise = "concise"
    static let styleSteady = "steady"

    static let trendImproving = "improving"
    static let trendStruggling = "struggling"
    static let trendSteady = "steady"

    /// 按界面语言二选一。跟 Python 一样读 EchoConfig，而不是 UI 层的 tr()：
    /// tr 走 I18n / UserDefaults（UI 层），后端不该把 UI 依赖拖进导入链。
    /// 注意 persona 这组是**静态界面文案**（阈值算出来之后拼的固定句子），
    /// 模型生成的内容走 Prompts.system() 的英文追加，是另一套机制。
    private static func t(_ zh: String, _ en: String) -> String {
        EchoConfig.english ? en : zh
    }

    /// Python 的 round()（四舍六入五成双）——画像的比率要跟 Python 存出来的值一致。
    private static func pyRound(_ x: Double, _ digits: Int) -> Double {
        let f = pow(10.0, Double(digits))
        return (x * f).rounded(.toNearestOrEven) / f
    }

    // ================= 计算 =================

    /// 从错题本的客观数据里算一份画像。没有复习历史时给中性的默认值。
    ///
    /// 只看 reviewCount > 0（真的被问过、判过的）——刚记下来还没确认过的
    /// 错题不该拉低画像的准头。
    static func compute() -> PersonaData {
        let graded = ReviewStore.load().filter { $0.reviewCount > 0 }
        let n = graded.count
        if n == 0 {
            return PersonaData(style: styleSteady, trend: trendSteady,
                               againRate: 0, clearRate: 0, sample: 0)
        }

        let again = graded.filter { $0.lastGrade == Grade.again.rawValue }.count
        let clear = graded.filter { $0.lastGrade == Grade.clear.rawValue }.count
        let againRate = Double(again) / Double(n)
        let clearRate = Double(clear) / Double(n)
        let avgLevel = Double(graded.reduce(0) { $0 + max(0, $1.level) }) / Double(n)

        let style: String
        if againRate >= 0.4 {
            style = styleNeedsExamples
        } else if avgLevel >= 1.5 && againRate <= 0.15 {
            style = styleConcise
        } else {
            style = styleSteady
        }

        let trend: String
        if clearRate >= 0.6 {
            trend = trendImproving
        } else if againRate >= 0.5 {
            trend = trendStruggling
        } else {
            trend = trendSteady
        }

        return PersonaData(style: style, trend: trend,
                           againRate: pyRound(againRate, 2), clearRate: pyRound(clearRate, 2),
                           sample: n)
    }

    /// 读画像：profile.json 里存过就直接用，没存过就现算一份（不自动落盘）。
    static func get() -> PersonaData {
        if let dict = PersonaProfile.load()["persona"] as? [String: Any], !dict.isEmpty,
           let data = try? JSONSerialization.data(withJSONObject: dict),
           let p = try? JSONDecoder().decode(PersonaData.self, from: data) {
            return p
        }
        return compute()
    }

    // ================= 水位线（多久重算一次） =================

    /// 现在的进度：上过几节课、判过几次复习。
    ///
    /// 「判过几次」不能拿 ReviewStore.stats().mastered——那是「复习过的条目数」，
    /// 同一个知识点练三遍只算一次，攒不到触发线。得把每条自己的 reviewCount 加起来。
    private static func progress() -> (lessons: Int, reviews: Int) {
        let lessons = ReviewStore.stats().lessons
        let reviews = ReviewStore.load().reduce(0) { $0 + max(0, $1.reviewCount) }
        return (lessons, reviews)
    }

    /// 上次重算时的进度。没记过、或记坏了，都当全 0。
    private static func baseline() -> (lessons: Int, reviews: Int) {
        let d = PersonaProfile.load()
        return (intValue(d["persona_baseline_lessons"]), intValue(d["persona_baseline_reviews"]))
    }

    private static func intValue(_ v: Any?) -> Int {
        if let n = v as? Int { return n }
        if let d = v as? Double { return Int(d) }
        if let s = v as? String, let n = Int(s) { return n }
        return 0
    }

    private static func doubleValue(_ v: Any?) -> Double {
        if let d = v as? Double { return d }
        if let n = v as? Int { return Double(n) }
        if let s = v as? String, let d = Double(s) { return d }
        return 0
    }

    /// 攒够新数据了没。两个维度谁先到算谁。
    static func needsRefresh() -> Bool {
        let now = progress(), was = baseline()
        return (now.lessons - was.lessons >= lessonStep
                || now.reviews - was.reviews >= reviewStep)
    }

    /// 重算 + 落盘，并记下这次是在什么进度上算的。不管攒没攒够都算。
    @discardableResult
    static func refresh() -> PersonaData {
        let data = compute()
        let now = progress()
        PersonaProfile.update(["persona": encode(data),
                               "persona_baseline_lessons": now.lessons,
                               "persona_baseline_reviews": now.reviews,
                               "persona_updated_at": Date().timeIntervalSince1970])
        return data
    }

    /// 攒够了才重算。重算了返回新画像；没重算返回 nil——调用方据此决定
    /// 要不要跟学生说一声「我更新了对你了解」。
    static func maybeRefresh() -> PersonaData? {
        guard needsRefresh() else { return nil }
        return refresh()
    }

    /// 上次重算的时间戳（0 = 还没重算过）。
    static func updatedAt() -> Double {
        doubleValue(PersonaProfile.load()["persona_updated_at"])
    }

    /// 把画像存进 profile.json。不传 data 就重新算一份当前的存下去。
    @discardableResult
    static func save(_ data: PersonaData? = nil) -> PersonaData {
        let d = data ?? compute()
        PersonaProfile.update(["persona": encode(d)])
        return d
    }

    /// 清掉画像，并把水位线挪到当前进度。
    ///
    /// 水位线必须跟着挪：只清画像的话，学生一点重置，下次 maybeRefresh() 就发现
    /// 「攒够了」，立刻重算一遍盖回来——刚点完重置就弹「画像已更新」，很莫名其妙。
    /// 归零 updated_at 而不是写 now：重置之后本机确实没有「已算好的画像」，
    /// 资料页据此显示「实时计算」而不是骗人的「刚刚更新」。
    static func reset() {
        let now = progress()
        PersonaProfile.update(["persona": [String: Any](),
                               "persona_baseline_lessons": now.lessons,
                               "persona_baseline_reviews": now.reviews,
                               "persona_updated_at": 0.0])
    }

    private static func encode(_ p: PersonaData) -> [String: Any] {
        guard let d = try? JSONEncoder().encode(p),
              let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
        else { return [:] }
        return obj
    }

    // ================= 对外文案 =================

    /// 画像的短标签，当资料页那一块的小标题用。长解释在 describe()。
    static func headline(_ data: PersonaData? = nil) -> String {
        let d = data ?? get()
        guard d.sample > 0 else { return t("还没攒够记录", "not enough data yet") }
        var labels: [String] = []
        switch d.style {
        case styleNeedsExamples: labels.append(t("容易没听懂，适合多举例子", "benefits from more examples"))
        case styleConcise: labels.append(t("吸收得快，说重点就行", "picks things up quickly"))
        case styleSteady: labels.append(t("按正常节奏讲解", "steady pace works well"))
        default: break
        }
        switch d.trend {
        case trendImproving: labels.append(t("最近在进步", "improving lately"))
        case trendStruggling: labels.append(t("最近比较吃力", "struggling lately"))
        case trendSteady: labels.append(t("状态平稳", "steady"))
        default: break
        }
        return labels.joined(separator: " · ")
    }

    /// 资料页里显示的一段话——给学生看的「我理解到的你」。
    ///
    /// 读者跟 toneHint() 完全不同，所以是两套独立的字符串：这一份要让学生看懂
    /// 「记录没白记、而且跟我后面要学的东西有关」，所以给依据（看了多少条）、
    /// 给结论（我发现了什么）、给接下来（我会怎么配合你）。喂模型那份只写祈使句。
    static func describe(_ data: PersonaData? = nil) -> String {
        let d = data ?? get()
        let n = d.sample
        if n == 0 {
            return t("还没有复习记录。多做几次「讲给 Echo 听」，我就慢慢知道该怎么给你讲了。",
                     "No review record yet. A few rounds of “Talk it through” and I'll start "
                     + "to know how to explain things in a way that works for you.")
        }

        let again = Int(pyRound(d.againRate * Double(n), 0))
        let clear = Int(pyRound(d.clearRate * Double(n), 0))

        var parts: [String] = []
        parts.append(t("从你复习过的 \(n) 个知识点里，我看到的你：",
                       "From the \(n) knowledge points you've reviewed, here's what I see:"))
        if d.style == styleNeedsExamples {
            parts.append(t("其中 \(again) 次是「还是没懂」——不是你不行，是第一次讲的时候那一步被跳过去了。"
                           + "接下来我会把步子放慢，多举一个具体例子再往下走。",
                           "\(again) of them ended in “still don't get it” — not because you can't, "
                           + "but because a step got skipped the first time. I'll slow down and work "
                           + "through a concrete example before moving on."))
        } else if d.style == styleConcise {
            parts.append(t("大部分一次就清楚，说明这些内容你接得住。"
                           + "那我就少铺垫，直接说重点，不浪费时间复述你已经会的。",
                           "Most of them clicked right away, so these are within reach. I'll skip the "
                           + "warm-up and get to the point instead of repeating what you already know."))
        } else {
            parts.append(t("整体接得比较稳，偶尔卡一两次，这是正常范围。",
                           "Overall you keep up steadily, with the occasional stumble — "
                           + "that's squarely normal."))
        }
        if d.trend == trendImproving {
            parts.append(t("最近这批里有 \(clear) 次一遍就想起来了，在往上走。",
                           "\(clear) of the recent ones you recalled straight away — "
                           + "you're trending up."))
        } else if d.trend == trendStruggling {
            parts.append(t("最近连着几次都没想起来——先别急，我们把前面的地基补牢再往下学，"
                           + "不然越往后越吃力。",
                           "A few in a row didn't come back to you — no rush. Let's shore up the "
                           + "foundations first, or it only gets harder further on."))
        }
        parts.append(t("这些只记在本机，跟着你的复习记录走，随时可以在下面重置。",
                       "This stays on this computer and follows your review record. "
                       + "You can reset it below whenever you like."))
        // 中文句子以「。」收尾，直接接下一句；英文要在句号后留一个空格
        let sep = EchoConfig.english ? " " : ""
        return parts.joined(separator: sep)
    }

    /// 喂给 AI 的一句话，让它说话的方式跟着这个学生调整。
    ///
    /// 没有足够数据时返回空串——system prompt 不需要为了「还没有画像」专门写一句话，
    /// 调用方（Recall）判断空串就不把这行塞进 prompt。
    static func toneHint(_ data: PersonaData? = nil) -> String {
        let d = data ?? get()
        guard d.sample > 0 else { return "" }
        var bits: [String] = []
        if d.style == styleNeedsExamples {
            bits.append("这个学生容易没听懂，解释时要放慢、多举一个具体例子再问他")
        } else if d.style == styleConcise {
            bits.append("这个学生吸收得快，不用啰嗦复述，说重点就行")
        }
        if d.trend == trendStruggling {
            bits.append("最近连续几次都没想起来，语气要耐心，别让他觉得自己很差")
        } else if d.trend == trendImproving {
            bits.append("最近进步明显，可以在反馈里肯定一下")
        }
        return bits.joined(separator: "；")
    }
}
