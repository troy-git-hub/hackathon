# Echo 个人学习画像 JSON（2.0.0）

在「设置 → 导出学习档案（JSON）」先勾选个人数据项，再选择保存位置。可选：个人资料、知识掌握、薄弱与反复困难、复习进度、学习偏好。未勾选的字段不会出现在文件中。无需逐课操作；所有指标在本地从已保存记录汇总，不调用 AI、不修改原始记录。

**这是个人画像，不是逐课备份。** 不包含课程列表、课程摘要、课时 ID、转写原文、每课笔记、截图、录音、HTML 或模型接口密钥。JSON 为 UTF-8、缩进两格。

| 字段 | 含义 |
| --- | --- |
| `format` / `schema_version` | 固定 `echo.learning-profile` / `2.0.0`，与应用版本独立 |
| `selected_sections` | 本次勾选的项目：`profile`、`mastery`、`difficulties`、`reviews`、`preferences` |
| `learner`（选个人资料时） | 本地档案 ID，以及已填写的姓名、昵称、年龄和爱好等；未知资料不补造 |
| `knowledge_points`（选知识掌握时） | 每个知识点的 ID、主题、学科、状态、判断原因、最近掌握指标、涉及学习次数和困难次数 |
| `difficulties.weaknesses`（选薄弱与反复困难时） | 当前待加强的知识点，每项直接包含主题和原因，无需再读取课程 |
| `difficulties.recurring` | 在至少两节已保存课程出现困难的知识点，以及受影响课程数；不包含具体课程 |
| `reviews`（选复习进度时） | 知识点主题、疑点 `missing`、原因 `reason`、最近自评、复习次数、阶梯等级与下次复习时间 |
| `learning_preferences`（选学习偏好时） | 近期复习自评的辅助信号：需要更多解释、较稳定、样本不足 |
| `coverage` / `methodology` / `warnings` | 指标来源的覆盖范围、判断口径、异常说明；应与导入结果一并保留 |

每个数据项独立可用。例如仅选择薄弱项时，直接读 `difficulties.weaknesses`，不会附带姓名、全部知识点或复习明细。`coverage.saved_lesson_count` 仅是汇总所依据的课程数量，不是课程明细。

## 接入示例

[机器格式约束](learning-profile.schema.json) · [完整虚构样例](examples/learning-profile.json)

```javascript
// input 为 <input type="file" accept=".json">
const data = JSON.parse(await input.files[0].text());
if (data.format !== 'echo.learning-profile' ||
    data.schema_version.split('.')[0] !== '2') throw new Error('不支持的格式');
const weakTopics = data.difficulties?.weaknesses ?? [];
console.table(weakTopics.map(p => ({ topic: p.topic, reason: p.reasons.join('；') })));
// 未勾选的数据项没有对应字段，不应按「没有薄弱点」解释。
```

```python
import json
with open('Echo-learning-profile.json', encoding='utf-8') as f:
    data = json.load(f)
assert data['format'] == 'echo.learning-profile'
assert data['schema_version'].split('.')[0] == '2'
if 'difficulties' in data['selected_sections']:
    for item in data['difficulties']['recurring']:
        print(item['topic'], item['affected_lesson_count'])
```

商业项目可先让用户登录你的服务，再由用户选择文件，预览所选数据后导入并绑定到该账号。`learner.local_id` 只用于本地关联，不是全球唯一账号或登录凭证；用户未勾选资料时此字段不存在，也可以通过导入时的登录账号绑定。

同一学科的同名知识点使用稳定 ID。同一用户重复导入时按稳定 ID 更新快照，不要重复累加 `learning_sessions` 或 `review_sessions`。复习条目自带 `topic`，因此未选择知识掌握数据也能使用。学科从课程标题前缀推断；同名知识点跨学科、旧复习未记学科时，保留为 `subject: null`，不随意归属。

## 指标解释与范围

`state`：`strength` 为相对掌握，`weakness` 为待加强，`developing` 为学习中，`unknown` 为未知。最近复习晚于课程记录时优先采用复习：仍没懂/模糊/未复习归为待加强；最近自评清楚且阶梯至少 2 级归为相对掌握。否则采用最近课程：待复习标记或掌握度低于 0.6 为待加强；跟上标记且掌握度至少 0.8 为相对掌握；其余为学习中。`reasons` 说明原因。

`latest_mastery` 是 0～1 课程掌握指标，不是考试分数。复习后的状态变化不会改写这一历史指标。`difficulty_sessions` 包括曾遇到困难后已补上的记录，不能等同于现在仍不会。`review_sessions` 是复习次数，不是答错次数。当前没有逐题历史作答存储，不能导出完整原题、作答与每次错误。

时间为 UTC ISO 8601（例如 `2026-11-12T10:00:00.000Z`）。未知值用 `null`，不能当作 0 分；旧记录缺时间时不补造。课程库目前最多保存最近 50 节，画像以实际保留的数据为依据，不是完整终身能力结论；不含当前尚未保存的课堂临时内容。

`learning_preferences.style=needs_examples` 是近期未懂自评比例达到阈值的辅助信号；不是经实验认证的学习风格。样本不足应保持未知。

## 从 1.0.0 迁移

2.0.0 移除了 `lessons`、逐课证据和课程 ID；不再使用顶层 `summary` 和 `recurring_difficulties`。直接读所选类别和 `difficulties`。解析器应检查主版本，兼容同一主版本下新增字段。旧版 1.x 文件不会被改写，请保留旧导入适配器。

此按钮只保存本地文件；不会自动上传到其他服务，也不是 Echo 全量恢复备份。接入方可以提供预览、用途选择和删除功能。
