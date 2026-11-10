//
//  Profile.swift
//  Echo - 用户资料（对应 Python echo/backend/profile.py）
//
//  首次启动时让学生填一次资料（姓名、昵称、年龄、爱好），存成 JSON 文档，
//  之后每次启动直接读。设置窗口里的「用户：」改的就是这里的 username。
//
//  存储位置：Application Support/Echo/profile.json（和 ReviewStore 同一个目录）。
//  头像图片单独放这个目录，profile.json 里只记文件名 —— 记绝对路径的话，
//  换台机器或换个安装位置就指向不存在的文件了。
//

import Foundation
import CoreGraphics
import ImageIO

nonisolated struct Profile: Codable, Equatable, Sendable {
    var name: String = ""
    var nickname: String = ""
    var age: Int?
    var hobbies: String = ""
    var username: String = ""

    init(name: String = "", nickname: String = "", age: Int? = nil,
         hobbies: String = "", username: String = "") {
        self.name = name
        self.nickname = nickname
        self.age = age
        self.hobbies = hobbies
        self.username = username
    }

    enum CodingKeys: String, CodingKey {
        case name, nickname, age, hobbies, username
    }

    // 宽松解码：缺字段用默认值，age 兼容数字 / 字符串（旧文件）。（多余字段如
    // created / updated / avatar 会被自动忽略。）
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        nickname = (try? c.decode(String.self, forKey: .nickname)) ?? ""
        hobbies = (try? c.decode(String.self, forKey: .hobbies)) ?? ""
        username = (try? c.decode(String.self, forKey: .username)) ?? ""
        if let i = try? c.decode(Int.self, forKey: .age) {
            age = i
        } else if let d = try? c.decode(Double.self, forKey: .age) {
            age = Int(d)
        } else if let s = try? c.decode(String.self, forKey: .age) {
            age = Int(s)
        } else {
            age = nil
        }
    }
}

enum ProfileStore {
    /// 头像本体单独放配置目录，profile.json 里只记文件名。
    static let avatarStem = "avatar"
    static let avatarExts = ["png", "jpg", "jpeg", "webp", "bmp"]
    /// 长边缩到这个像素数再存（够用又不占地方）。
    static let maxAvatarSide = 512

    private static var dir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let d = base.appendingPathComponent("Echo", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    private static var profileURL: URL { dir.appendingPathComponent("profile.json") }
    private static var avatarURL: URL { dir.appendingPathComponent("\(avatarStem).png") }

    // ================= 原始 JSON =================
    //
    // profile.json 除了资料字段，还有 created / updated / avatar 等，读取时整份保留，
    // 这样保存资料不会把头像记录冲掉。

    private static func readRaw() -> [String: Any]? {
        guard let data = try? Data(contentsOf: profileURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj
    }

    @discardableResult
    private static func writeRaw(_ obj: [String: Any]) -> Bool {
        guard let data = try? JSONSerialization.data(
            withJSONObject: obj, options: [.prettyPrinted, .withoutEscapingSlashes, .sortedKeys])
        else { return false }
        do {
            // .atomic = 先写临时文件再替换，写一半断电也不会把旧资料弄坏
            try data.write(to: profileURL, options: .atomic)
            return true
        } catch {
            print("[echo.profile] 资料保存失败: \(error.localizedDescription)")
            return false
        }
    }

    // ================= 资料 =================

    /// 首次登录填过没有。文件不存在或损坏（空）都算没填，重新问一遍。
    static func exists() -> Bool { load() != nil }

    /// 读资料，文件不存在或损坏时返回 nil。
    static func load() -> Profile? {
        guard let obj = readRaw(), !obj.isEmpty else { return nil }
        guard let data = try? JSONSerialization.data(withJSONObject: obj),
              let p = try? JSONDecoder().decode(Profile.self, from: data)
        else { return nil }
        return p
    }

    /// 写资料（并进旧文档，保留 created / updated / avatar 等）。
    static func save(_ p: Profile) {
        var cur = readRaw() ?? [:]
        cur["name"] = p.name
        cur["nickname"] = p.nickname
        cur["hobbies"] = p.hobbies
        cur["username"] = p.username
        if let age = p.age { cur["age"] = age }
        let now = Date().timeIntervalSince1970
        if cur["created"] == nil { cur["created"] = now }
        cur["updated"] = now
        writeRaw(cur)
    }

    /// 问候时怎么称呼学生：用户名 > 昵称 > 姓名。
    static func displayName() -> String {
        guard let p = load() else { return "" }
        for v in [p.username, p.nickname, p.name] {
            let t = v.trimmingCharacters(in: .whitespacesAndNewlines)
            if !t.isEmpty { return t }
        }
        return ""
    }

    // ================= 头像 =================

    /// 配置目录里现存的头像文件（可能有历史遗留的其它扩展名，一起收进来）。
    private static func avatarFiles() -> [URL] {
        let fm = FileManager.default
        return avatarExts.compactMap { ext in
            let u = dir.appendingPathComponent("\(avatarStem).\(ext)")
            return fm.fileExists(atPath: u.path) ? u : nil
        }
    }

    /// 当前头像的路径；没设过、或文件已经不在了 → nil（调用方用默认喵喵）。
    static func avatarPath() -> String? {
        guard let obj = readRaw(),
              let name = (obj["avatar"] as? String)?.trimmingCharacters(in: .whitespaces),
              !name.isEmpty,
              (name as NSString).lastPathComponent == name     // 防御：不接受带路径的名字
        else { return nil }
        let u = dir.appendingPathComponent(name)
        return FileManager.default.fileExists(atPath: u.path) ? u.path : nil
    }

    /// 头像图片数据，供 UI 层显示（backend 不碰 NSImage）。
    static func avatarData() -> Data? {
        guard let path = avatarPath() else { return nil }
        return try? Data(contentsOf: URL(fileURLWithPath: path))
    }

    /// 把选中的图片缩放后存成头像（长边 512、保持 EXIF 方向、统一存为 avatar.png）。
    /// 成功返回 true；格式不支持或图片读不出来返回 false。
    @discardableResult
    static func setAvatar(from sourceURL: URL) -> Bool {
        let ext = sourceURL.pathExtension.lowercased()
        guard avatarExts.contains(ext) else {
            print("[echo.profile] 不支持的头像格式: \(ext)")
            return false
        }
        guard let image = scaledImage(from: sourceURL, maxSide: maxAvatarSide) else {
            print("[echo.profile] 头像读取 / 缩放失败: \(sourceURL.lastPathComponent)")
            return false
        }
        clearAvatar()
        guard let dest = CGImageDestinationCreateWithURL(avatarURL as CFURL, "public.png" as CFString, 1, nil) else {
            return false
        }
        CGImageDestinationAddImage(dest, image, nil)
        guard CGImageDestinationFinalize(dest) else { return false }

        var cur = readRaw() ?? [:]
        cur["avatar"] = "\(avatarStem).png"
        let now = Date().timeIntervalSince1970
        if cur["created"] == nil { cur["created"] = now }
        cur["updated"] = now
        return writeRaw(cur)
    }

    /// 删掉头像文件，profile 里也不再记（回到默认的喵喵）。
    static func clearAvatar() {
        for u in avatarFiles() { try? FileManager.default.removeItem(at: u) }
        if let obj = readRaw(), (obj["avatar"] as? String)?.isEmpty == false {
            var cur = obj
            cur["avatar"] = ""
            writeRaw(cur)
        }
    }

    /// 用 ImageIO 生成缩略图：kCGImageSourceCreateThumbnailWithTransform 会按 EXIF
    /// 方向摆正，max pixel size 只缩不放，长边最大 512。
    private static func scaledImage(from url: URL, maxSide: Int) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        let opts: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxSide,
        ]
        return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
    }
}
