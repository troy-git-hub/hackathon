# Echo — 网课里的 AI 学习副驾驶

不替你听课，而是在你掉队的时候，帮你找到自己从哪一步开始没听懂。

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env      # 填 DEEPSEEK_API_KEY
python main.py
```

打开网课（腾讯会议 / Zoom / B站 / 录播课）正常播放，Echo 会直接抓电脑播放的声音实时转写，不需要麦克风，戴耳机也行。
第一次启动会从 hf-mirror 下载 Whisper small 模型（约 480MB）。

没有 key 时自动退化为 mock 数据，界面照常可用。

自检（不开界面）：

```bash
python scripts/live_check.py --direct    # TTS 朗读示例课 → 切句 → Whisper → DeepSeek → 掉队分析
python scripts/live_check.py             # 同上，但真的从扬声器播放、走系统音频 loopback
python scripts/smoke_backend.py          # 只测 LLM 部分（直接喂讲稿文字）
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

Prompt 都在 `echo/backend/prompts.py`，配置项见 `echo/backend/config.py`。
