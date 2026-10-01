# Echo — 网课里的 AI 学习副驾驶

不替你听课，而是在你掉队的时候，帮你找到自己从哪一步开始没听懂。

## 运行

```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # 填 DEEPSEEK_API_KEY
python main.py
```

打开网课（腾讯会议 / Zoom / B站 / 录播课）正常播放，Echo 会直接抓电脑播放的声音实时转写，不需要麦克风，戴耳机也行。
第一次启动会从 hf-mirror 下载 Whisper small 模型（约 480MB），建议演示前先跑一次让模型缓存好。

没有 key 时自动退化为 mock 数据，界面照常可用。

### 配置（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 不填 = 离线 mock |
| `ECHO_SOURCE` | `system` | `system` 抓系统声音 / `mic` 麦克风 / `demo` 回放示例讲稿 |
| `ECHO_AUDIO_DEVICE` | 空 | `mic` 时可填设备序号或名称片段 |
| `ECHO_WHISPER_MODEL` | `small` | `medium` 更准但更慢 |
| `ECHO_AUTO_DEMO` | `1` | 音频采集失败时自动改放示例讲稿 |
| `ECHO_OFFLINE` | `0` | `1` = 不调 LLM，全走规则 / mock（断网演示） |
| `ECHO_DEMO_INTERVAL` | `3` | 示例讲稿每句间隔秒数 |

### 现场演示

1. 稳妥路线：`.env` 里 `ECHO_SOURCE=demo`，Echo 自己回放贝叶斯示例课，约 1 分钟后点「! 我掉队了」→ 断点 → 「30 秒补上这一步」→「✓ 补上了」→「下课」看回响。
2. 真实路线：`ECHO_SOURCE=system`，B站放一段课，等时间轴出现 2～3 个知识点后再点掉队。
3. 兜底：声卡 / loopback 出错会自动切到示例讲稿（`ECHO_AUTO_DEMO`）；断网时设 `ECHO_OFFLINE=1`，掉队分析和回响走规则兜底，界面流程不变。
   代码里也可以随时切：`bridge.use_demo(offline=True)` / `bridge.switch_source("system")` / `bridge.set_offline(True)`，状态通过 `mode` 信号通知 UI。

自检（不开界面）：

```bash
python scripts/smoke_backend.py          # 喂示例讲稿 → 时间轴 → 掉队分析 → 补课 → 回响（有 key 走 DeepSeek）
python scripts/session_check.py          # 结束 / 重开课程后旧任务不串课
```

## 架构

```
音频来源 (echo/backend/sources.py)
  system : WASAPI loopback 抓系统播放声音 → 静音切句 → faster-whisper（热词=已识别知识点）
  mic    : 麦克风 → 同上
  demo   : 回放 demo_lesson.txt（离线兜底）
        │ add_transcript(text, t)
        ▼
EchoEngine (echo/backend/engine.py)
  ├─ Concept Timeline : 每 N 秒把新转写交给 DeepSeek 切分知识点片段
  ├─ feedback(ok/warn/lost) : 按时间归属到知识点
  ├─ Break Point Engine : 「我掉队了」→ 最近 5 分钟转写 + 时间轴 + 反馈 → 断点 + 30 秒补课
  └─ end_lesson() → 回响：掌握度 + 复习链
        │ 回调（后台线程）
        ▼
EchoBridge (echo/backend/qt_bridge.py) → Qt 信号 → FloatingWindow
```

| 信号 | 参数 | 含义 |
|---|---|---|
| `transcript` | `tc, text` | 新的一句转写 |
| `concept` | `Concept` | 时间轴新增/更新知识点 |
| `breakpoint` | `BreakPoint, List[Concept]` | 掉队分析结果 + 要展示的时间轴片段 |
| `echo` | `EchoReport(skills, review_chain, suggestion)` | 回响页 |
| `status` | `listening / analyzing / summarizing / loading_asr / done` | |
| `error` | `str` | |
| `mode` | `kind, offline` | 音频来源切换 / 在线离线切换 |

Prompt 都在 `echo/backend/prompts.py`，配置项见 `echo/backend/config.py`。
