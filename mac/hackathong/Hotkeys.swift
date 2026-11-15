//
//  Hotkeys.swift
//  Echo — 全局快捷键（看全屏网课时也能用），被别的软件占用时自动换下一个候选：
//      我掉队了        ⌃⌥L → ⌃⌥K → ⌃⌥J → ⌃⇧F9
//      显示 / 隐藏     ⌃⌥E → ⌃⌥H → ⌃⇧F10
//      圈一下问 AI     ⌃⌥Q → ⌃⌥W → ⌃⇧F11
//

import AppKit
import Carbon.HIToolbox

enum HotkeyAction: UInt32, CaseIterable {
    case lost = 1, toggle, circleAsk
}

final class Hotkeys {
    private struct Combo { let mods: Int; let key: Int; let name: String }

    private static let candidates: [HotkeyAction: [Combo]] = [
        .lost: [Combo(mods: controlKey | optionKey, key: kVK_ANSI_L, name: "⌃⌥L"),
                Combo(mods: controlKey | optionKey, key: kVK_ANSI_K, name: "⌃⌥K"),
                Combo(mods: controlKey | optionKey, key: kVK_ANSI_J, name: "⌃⌥J"),
                Combo(mods: controlKey | shiftKey, key: kVK_F9, name: "⌃⇧F9")],
        .toggle: [Combo(mods: controlKey | optionKey, key: kVK_ANSI_E, name: "⌃⌥E"),
                  Combo(mods: controlKey | optionKey, key: kVK_ANSI_H, name: "⌃⌥H"),
                  Combo(mods: controlKey | shiftKey, key: kVK_F10, name: "⌃⇧F10")],
        .circleAsk: [Combo(mods: controlKey | optionKey, key: kVK_ANSI_Q, name: "⌃⌥Q"),
                     Combo(mods: controlKey | optionKey, key: kVK_ANSI_W, name: "⌃⌥W"),
                     Combo(mods: controlKey | shiftKey, key: kVK_F11, name: "⌃⇧F11")],
    ]

    /// 实际注册成功的快捷键显示名
    private(set) var names: [HotkeyAction: String] = [:]
    private var refs: [EventHotKeyRef] = []
    private var handler: EventHandlerRef?
    private let onHotkey: (HotkeyAction) -> Void

    init(onHotkey: @escaping (HotkeyAction) -> Void) {
        self.onHotkey = onHotkey
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let me = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, event, ctx in
            var id = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &id)
            guard let ctx, let action = HotkeyAction(rawValue: id.id) else { return noErr }
            let hk = Unmanaged<Hotkeys>.fromOpaque(ctx).takeUnretainedValue()
            DispatchQueue.main.async { hk.onHotkey(action) }
            return noErr
        }, 1, &spec, me, &handler)

        for action in HotkeyAction.allCases {
            for c in Self.candidates[action] ?? [] {
                var ref: EventHotKeyRef?
                let id = EventHotKeyID(signature: OSType(0x4543484F), id: action.rawValue)   // 'ECHO'
                if RegisterEventHotKey(UInt32(c.key), UInt32(c.mods), id, GetApplicationEventTarget(), 0, &ref) == noErr,
                   let ref {
                    refs.append(ref)
                    names[action] = c.name
                    break
                }
            }
        }
    }

    func unregister() {
        refs.forEach { UnregisterEventHotKey($0) }
        refs.removeAll()
        if let handler { RemoveEventHandler(handler) }
    }
}
