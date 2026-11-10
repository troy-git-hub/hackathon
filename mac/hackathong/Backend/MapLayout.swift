//
//  MapLayout.swift
//  Echo - 知识地图的位置记忆（对应 Python echo/backend/layout.py）
//
//  记的是「相对自动排布的偏移」，只记真的挪动过的节点，取整到像素。
//  文件：EchoPaths.dir/mindmap.json，格式 {课次键: {知识点: [dx, dy]}}，与 Python 一致。
//  纯缓存：删掉只是地图回到默认排布。
//

import Foundation
import CoreGraphics

nonisolated struct MapLayoutStats: Codable, Hashable, Sendable {
    var lessons: Int = 0
    var nodes: Int = 0
    var bytes: Int = 0
}

enum MapLayout {
    /// 最多记这么多节课，超了丢最早的（按写入先后）
    static let MAX_LESSONS = 60

    private static let lock = NSRecursiveLock()

    static var url: URL { EchoPaths.dir.appendingPathComponent("mindmap.json") }

    /// 读全部记录，保持文件里的键顺序（= 写入先后）。文件不在或坏了返回空。
    private static func load() -> [(key: String, value: [String: Any])] {
        lock.lock(); defer { lock.unlock() }
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [] }
        // JSONSerialization 不保序：按「"键":{」在原文里的位置恢复顺序
        let raw = String(decoding: data, as: UTF8.self)
        func pos(_ k: String) -> Int {
            guard let enc = try? JSONSerialization.data(withJSONObject: [k], options: [.fragmentsAllowed]) else { return .max }
            var s = String(decoding: enc, as: UTF8.self)
            s.removeFirst(); s.removeLast()           // 去掉 [ ]
            if let r = raw.range(of: s + ":{") ?? raw.range(of: s + ": {") {
                return raw.distance(from: raw.startIndex, to: r.lowerBound)
            }
            return .max
        }
        return obj.compactMap { k, v in (v as? [String: Any]).map { (k, $0) } }
            .map { (k: $0.0, v: $0.1, p: pos($0.0)) }
            .sorted { $0.p < $1.p }
            .map { (key: $0.k, value: $0.v) }
    }

    private static func write(_ items: [(key: String, value: [String: Any])]) {
        lock.lock(); defer { lock.unlock() }
        // 手拼顶层以保留顺序，内层交给 JSONSerialization
        var parts: [String] = []
        for (k, v) in items {
            guard let kd = try? JSONSerialization.data(withJSONObject: k, options: [.fragmentsAllowed]),
                  let vd = try? JSONSerialization.data(withJSONObject: v) else { continue }
            parts.append(String(decoding: kd, as: UTF8.self) + ":" + String(decoding: vd, as: UTF8.self))
        }
        let text = "{" + parts.joined(separator: ",") + "}"
        try? Data(text.utf8).write(to: url, options: .atomic)   // 记不下来不致命
    }

    private static func num(_ x: Any) -> Double? {
        if let n = x as? NSNumber { return n.doubleValue }
        if let s = x as? String { return Double(s) }
        return nil
    }

    /// 取某节课记下的偏移：{知识点: (dx, dy)}。没有记录返回 [:]（= 用自动排布）。
    static func get(key: String) -> [String: CGPoint] {
        guard !key.isEmpty, let raw = load().first(where: { $0.key == key })?.value else { return [:] }
        var out: [String: CGPoint] = [:]
        for (topic, d) in raw {
            guard let arr = d as? [Any], arr.count >= 2,
                  let dx = num(arr[0]), let dy = num(arr[1]) else { continue }  // 坏条目跳过
            out[topic] = CGPoint(x: dx, y: dy)
        }
        return out
    }

    /// 记下一节课的位置。offsets 传空 = 这节课回到自动排布（删掉记录）。
    static func save(key: String, offsets: [String: CGPoint]) {
        guard !key.isEmpty else { return }
        lock.lock(); defer { lock.unlock() }
        var data = load().filter { $0.key != key }   // 摘掉旧的再塞回末尾 = 最新
        if !offsets.isEmpty {
            var entry: [String: Any] = [:]
            for (t, v) in offsets {
                let dx = Int(v.x.rounded()), dy = Int(v.y.rounded())
                if dx != 0 || dy != 0 { entry[t] = [dx, dy] }
            }
            data.append((key: key, value: entry))
        }
        if data.count > MAX_LESSONS { data.removeFirst(data.count - MAX_LESSONS) }
        write(data)
    }

    /// 清掉所有位置记录，返回删掉的课次数。
    @discardableResult
    static func clear() -> Int {
        lock.lock(); defer { lock.unlock() }
        let n = load().count
        if n > 0 { write([]) }
        return n
    }

    /// 给设置页显示用：记了几节课、几个节点、文件多大。
    static func stats() -> MapLayoutStats {
        let data = load()
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int) ?? 0
        return MapLayoutStats(lessons: data.count,
                              nodes: data.reduce(0) { $0 + $1.value.count },
                              bytes: size)
    }
}
