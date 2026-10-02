# Echo — 网课里的 AI 学习副驾驶

不替你听课，而是在你掉队的时候，帮你找到自己从哪一步开始没听懂。

听网课时 Echo 在后台抓取课程声音，实时转写、理解知识点，建出一条「课堂时间轴」。你随时点
**✓ 跟上了 / ? 有点懵 / ! 我掉队了**，Echo 就回看最近几分钟，找到你可能开始没听懂的那一步，
用 30 秒把它补上，再把你送回课堂。

---

## 它能做什么

| 功能 | 说明 |
|---|---|
| 实时听课 | 抓系统声音（腾讯会议 / Zoom / B站 / 录播课都行），Whisper 实时转写，戴耳机也能用 |
| 课堂时间轴 | 每 20~60 秒把老师讲的内容切成知识点片段（概念 / 前置 / 一句话总结） |
| 我掉队了 | 核心能力：定位知识断点，只补「缺失的那一步」，不重讲整节课 |
| 三段式补课 | 你已经知道 → 中间漏了这一步 → 所以现在能听懂 |
| 追问 | 断点页直接打字追问，Echo 带上课堂上下文让 DeepSeek 解答 |
| 圈一下问 AI | 全屏圈画 + 批注，把看不懂的地方截图给 Qwen-VL 视觉模型讲解（支持追问） |
| 回响 | 下课后一张掌握度地图：每个知识点 ✓/⚠/!，掉队点一路追溯到该复习的前置 |
| 桌面宠物 | 常驻桌面的小猫，跟着课堂变表情；旁边 Siri 风格声纹条，老师说话时起伏 |
| 系统托盘 | 关掉窗口仍在听课；全局快捷键、托盘通知、右键菜单一应俱全 |

## 运行（开发方式）

```bash
pip install -r requirements.txt
cp .env.example .env          # 或启动后右键托盘 → 设置… 里填
python main.py
```

打开网课正常播放，Echo 会自动抓电脑播放的声音开始转写。第一次启动会从镜像站下载
Whisper `small` 模型（约 480MB，之后走本地缓存）。

> 没有 API key 时自动退化为 mock 数据，界面照常可用。

## 配置

设置界面（托盘右键 → **设置…**）或直接编辑 `.env`：

```ini
DEEPSEEK_API_KEY=sk-…          # 课堂理解 / 掉队分析 / 追问（deepseek-chat）
DASHSCOPE_API_KEY=sk-…         # 圈一下问 AI 的视觉模型（Qwen-VL，选填，不填退回 DeepSeek 视觉）
ECHO_SOURCE=system             # system 系统声音 / mic 麦克风 / demo 示例课
ECHO_WHISPER_MODEL=small       # small（快）/ medium（更准更慢）
ECHO_PET_SKIN=modern           # modern 矢量 AI 猫 / classic 表情包猫
```

## 快捷键

| 快捷键 | 作用 |
|---|---|
| `Ctrl+Alt+L` | 我掉队了（被占用时自动换 K/J/F9） |
| `Ctrl+Alt+E` | 显示 / 隐藏 Echo |
| `Ctrl+Alt+Q` | 圈一下问 AI |

## 自检（不开界面）

```bash
python scripts/smoke_backend.py        # 后端全链路（转写→时间轴→掉队→回响）
python scripts/session_check.py        # 课程隔离（6/6）
python scripts/tray_check.py           # 托盘 / 快捷键 / 关闭到托盘（10/10）
```

## 架构

```
音频来源 (echo/backend/sources.py)
  system : WASAPI loopback → 静音切句 → faster-whisper（热词=已识别知识点）
  mic    : 麦克风 → 同上
  demo   : 回放 demo_lesson.txt（离线兜底）
        │ add_transcript(text, t, session)
        ▼
EchoEngine (echo/backend/engine.py)
  ├─ Concept Timeline  每 N 秒把新转写交给 DeepSeek 切知识点
  ├─ feedback(ok/warn/lost)  按时间归属到知识点
  ├─ Break Point Engine  「我掉队了」→ 最近 5 分钟转写 + 时间轴 + 反馈 → 断点 + 30 秒补课
  └─ end_lesson()  回响：掌握度 + 复习链
        │ 回调（后台线程）
        ▼
EchoBridge (echo/backend/qt_bridge.py) → Qt 信号（带 session 隔离）→ FloatingWindow
视觉问答  vision.py：Qwen-VL / DeepSeek 视觉（圈画）+ LessonAsk 文字追问
桌宠 / 托盘  desk_pet.py / tray.py
圈画标注    snip.py：全屏画笔 + 荧光笔 + 文字批注
```

## 打包安装包

```bash
pip install pyinstaller
build.bat                        # 产出 dist/Echo/
# 用 Inno Setup 打开 installer/setup.iss 编译 → Echo-Setup.exe
```

---

*Echo 1.0 — 49 小时产品冲刺产物。*
