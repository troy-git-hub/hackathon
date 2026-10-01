# Echo — 网课里的 AI 学习副驾驶

不替你听课，而是在你掉队的时候，帮你找到自己从哪一步开始没听懂。

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env      # 填 DEEPSEEK_API_KEY
python main.py
```

没有 key 时自动退化为 mock 数据，界面照常可用。

后端冒烟测试（不开界面）：

```bash
python scripts/smoke_backend.py          # 真实 DeepSeek
python scripts/smoke_backend.py --mock
```

## 架构

```
音频来源 (echo/backend/sources.py)
  demo : 回放 demo_lesson.txt（现场演示用，不依赖声卡/ASR）
  mic  : sounddevice 采集 → faster-whisper 本地转写
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
