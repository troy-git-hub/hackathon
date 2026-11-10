# Echo · macOS（Swift 版）

Echo —— 网课里的 AI 学习副驾驶。这是 macOS 原生版（SwiftUI + AppKit），
对应仓库根目录的 Python/PyQt 版，功能对齐同一套后端逻辑（课堂转写、知识断点、
间隔重复、出题/抽问、思维导图等）。

## 构建

用 Xcode 打开 `hackathong.xcodeproj`，直接 Run（Debug 或 Release 均可）。

- 最低系统：macOS 14+（Sonoma）
- 需要「屏幕与系统录音」「麦克风」「语音识别」权限，首次启动会依次弹窗

## API Key

出于开源安全考虑，`Secrets.plist` **不入库**（已加入 `.gitignore`）。
本地开发二选一：

1. 在 `hackathong/Backend/` 下新建 `Secrets.plist`：
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0"><dict>
     <key>DEEPSEEK_API_KEY</key><string>sk-你的key</string>
   </dict></plist>
   ```
2. 或运行时设置环境变量 `DEEPSEEK_API_KEY`。

没有 key 时 App 会退回离线/兜底演示模式，仍可跑通主流程。

## 结构

- `Backend/` —— 后端逻辑（对应根目录 `echo/backend/`，Swift 重写）
- `Views/` —— 各页面（主页 / 课程 / 复习 / 思维导图等）
- `DeskPet.swift` —— 桌宠 + 侧边收起
- `hackathongApp.swift` —— 菜单栏常驻 + 悬浮面板 + 全局快捷键
