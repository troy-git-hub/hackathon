# Echo — 网课里的 AI 学习副驾驶

## Windows 2.2.0 发布版

安装包使用 Echo 定制的深色安装界面，可选择路径与桌面快捷方式，默认安装到当前用户目录。
应用内首次设置模型 API Key；安装包不包含密钥、课程记录或语音模型，语音模型在应用内按需下载。

- 源码运行：`python main.py`
- 发布构建：`python scripts/build_release.py`（独立 worktree，需要 PyInstaller 与 Inno Setup 6.6+）
- 打包自检：`Echo.exe --self-test --report check.json`（临时隔离数据，验证语音运行库、窗口和 HTML 交互）
- 安装器脚本：`installer/setup.iss` 与 `installer/echo_wizard.iss`

当前板书默认跟随知识点；课堂抽问支持单选、判断、填空、连线和简答。语文/历史演示使用统一教学布局，
包含角度探索、原话对照、概念比较与理解检查。笔记导出位于本节课的回响/回顾页面。


课堂页新增 **AI 黑板 · 梳理这段课**，只在上课时显示与使用。
课堂疑问统一在黑板中提问，听课页已去掉重复的「答疑」按钮，折叠条的「黑板」也通向同一入口。
黑板与 HTML 演示使用当前界面主题的强调色；所有看图入口统一读取设置中的「视觉模型」。
默认是约 460×560 的可调整置顶小窗，点「收起」变为约 300×44 的一条；「来源」按需打开，
板书、演示、来源使用同一个内容区，不再并排占屏。可关闭置顶，窗口隐藏后重点捕捉仍能继续。
点击后以步骤卡片整理最近约 5 分钟（最多 40 句）的讲解；支持沿用现有的圈画、荧光笔、文字批注截图，
确认截图后先附到黑板，用户再主动发送问题。附图走视觉模型，无图走文字模型。
黑板根据学科呈现时间线、因果链、推导链或概念脉络；点击来源可定位到当时的老师原话或参考资料。
包含易混点、可展开的自测答案，支持导出 Markdown 及来源快照。
每节课保留最近 12 块黑板，课后随课程归档并可只读回看。原始截图只保留在本次会话内，不写入课程文件。
下课后停止生成；切课、取消后丢弃迟到结果。无模型时只摘录真实原话，不把示例知识点当课堂事实。

**重点捕捉**：先「选择课件范围」，再打开开关。开启后请把课件保持在这个范围内。
只在讲解有更新时，最多每30秒冻结这片区域的截图及最近90秒的转写；文字模型判断值得保留后，
才把同一时刻的截图送给视觉模型解释，避免翻页造成错配。不重要的候选图片直接丢弃。
新增重点只更新课堂入口，不主动弹窗。每节最多12块自动黑板，间隔至少90秒；下课、切课或关闭开关即停止。
屏幕布局改变后需要重新选择范围。本地范围截图不会写入课程文件。

**HTML 交互讲解**：「演示」里自带按板书逐步展开的本地演示，进入后会自动展开深入讲解，也可点击「深入讲解」让当前文字模型
针对难点生成独立 HTML/CSS/JavaScript，例如可调参数的图解或事件展开。已生成的交互讲解可随课程回放、导出HTML。
演示嵌入隔离的浏览器视图，不开放网络、本地文件、宿主接口、存储或跳转。缺少模型配置时，仍可使用本地分步演示。
开发环境需安装更新后的 `requirements.txt`（新增 PyQtWebEngine）。DeepSeek 视觉默认使用 `deepseek-flash`，
依据[官方视觉接口文档](https://api-docs.deepseek.com/guides/vision/)；旧的纯文字模型名不应直接假定支持图片。

主页的「课前资料库」支持导入 UTF-8 TXT / Markdown、编辑与搜索笔记，保存在 `knowledge.json`。
课堂文字答疑与黑板会按问题检索相关片段，并要求模型标注资料来源；这不是联网查证。
在线生成时相关片段和本次确认附上的截图会发送给你配置的模型提供商。暂不支持 PDF、Word 文档导入和语义向量检索。

设置新增森林书屋、海盐蓝、樱花手记、羊皮纸界面主题（保存后重启生效），
桌宠新增焦糖橘猫、薄荷猫、薰衣草猫和星夜猫（保存或桌宠右键切换，立即生效）。

新功能离线验收：`python scripts/studio_check.py`；完整验收：`python scripts/accept_check.py`。
真实嵌入式浏览器/滑块/捕捉时序验收：`python scripts/accept_check.py --with-web`（Windows需桌面，不调用模型）。
交互演示窗口：`python scripts/blackboard_visual_check.py --desktop`（隔离数据，本地演示课件）。
多人网课、服务器和支付的后续落地方案见 [商业化草案](COMMERCIALIZATION.md)。当前未接入真实支付或部署云服务。

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
| 回响 | 下课后一张掌握度地图：**这节课讲了什么**（一段话总结 + 3~5 条要点）、时长/知识点数/转写字数、每个知识点 ✓/⚠/!，掉队点一路追溯到该复习的前置 |
| 错题复习 | 每节课的掉队点自动存进错题本（review.json），重启后主页里可回看、标掌握 |
| AI 出题练习 | 照着你的错题让 DeepSeek 出题（选择题 + 简答题），带答案和解析，离线也有兜底题 |
| 主页 | 启动页：给这节课命名并开始 · 错题复习 · AI 出题 · 历史课程（点进去看回顾） |
| 桌面宠物 | 常驻桌面的小猫（经典表情包猫），旁边声纹条跟着老师声音真实起伏 |
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
ECHO_SOURCE=system             # system 系统声音 / mic 麦克风
ECHO_WHISPER_MODEL=small       # small（快）/ medium（更准更慢）
ECHO_WHISPER_THREADS=4         # Whisper CPU 线程数；内存紧张报 mkl_malloc 时降到 2 或 1
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

安装包会**内置 Whisper `small` 模型**（约 480MB），装好即可离线转写，不联网下载模型。

```bash
pip install pyinstaller
# 0) 准备模型（models/ 在 .gitignore 里，不随 git 分发）
#    先 python main.py 跑一次把模型下到 HF 缓存，再复制成：
#    models/faster-whisper-small/{config.json, model.bin, tokenizer.json, vocabulary.txt}
build.bat                        # 产出 dist/Echo/（内含模型）
# 用 Inno Setup 打开 installer/setup.iss 编译 → dist/Echo-Setup-1.3.exe
```

> 克隆仓库后没放模型就 build.bat 会失败（找不到 `models/faster-whisper-small`），先按第 0 步准备。
> 开发态不用管 models/：直接 `python main.py` 会自动下载，打包才需要把模型塞进去。

---

*Echo 1.3 — 49 小时产品冲刺产物。*
