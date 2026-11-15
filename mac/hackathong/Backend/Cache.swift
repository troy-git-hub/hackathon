//
//  Cache.swift
//  Echo - 本机数据总管（对应 Python echo/backend/cache.py）
//
//  清的是「攒下来的记录」——课程历史（lessons.json）、错题本（review.json）、
//  知识地图记住的位置（mindmap.json）。**不动** profile.json / 头像 / API key / 界面设置。
//

import Foundation

nonisolated struct CacheStats: Codable, Hashable, Sendable {
    var lessons: Int = 0
    var mistakes: Int = 0
    var layout: MapLayoutStats = MapLayoutStats()
    var bytes: Int = 0
}

enum EchoCache {
    /// 算占用用的文件路径（顺序同 Python _file_paths）
    static func filePaths() -> [String] {
        let dir = EchoPaths.dir
        var seen = Set<String>()
        return ["lessons.json", "review.json", "mindmap.json"]
            .map { dir.appendingPathComponent($0).path }
            .filter { seen.insert($0).inserted }
    }

    private static func size(_ path: String) -> Int {
        ((try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? Int) ?? 0
    }

    /// 当前占用。读不到都当 0。
    static func stats() -> CacheStats {
        CacheStats(lessons: ReviewStore.listLessons(limit: nil).count,
                   mistakes: ReviewStore.load().count,
                   layout: MapLayout.stats(),
                   bytes: filePaths().reduce(0) { $0 + size($1) })
    }

    /// 有没有东西可清。看条数不看字节（清空后文件还在，内容是空数组）。
    static func isEmpty(_ st: CacheStats? = nil) -> Bool {
        let s = st ?? stats()
        return !(s.lessons > 0 || s.mistakes > 0 || s.layout.lessons > 0)
    }

    /// 人看的体积。
    static func sizeText(_ n: Int) -> String {
        if n < 1024 { return "\(n) B" }
        if n < 1024 * 1024 { return String(format: "%.1f KB", Double(n) / 1024) }
        return String(format: "%.1f MB", Double(n) / 1024 / 1024)
    }

    /// 清空，返回清空前的数量（给界面回显用）。
    /// 课程/错题走 ReviewStore 现成的 clearAll（持它自己的锁，对应 Python store.clear_all）；地图位置自己清。
    @discardableResult
    static func clear() -> CacheStats {
        let before = stats()
        _ = ReviewStore.clearAll()
        MapLayout.clear()
        return before
    }
}

/// 兼容旧名（Views/SettingsView.swift 在用 Cache.xxx）
typealias Cache = EchoCache
