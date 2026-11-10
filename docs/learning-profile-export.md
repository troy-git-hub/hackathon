# Echo 学习档案 JSON 接入

在「设置 → 导出学习档案（JSON）」选择保存位置。文件为 UTF-8、缩进两格的标准 JSON；无网络请求，不消耗模型额度。导出不会修改或清除学习记录。

- `format`: 固定为 `echo.learning-profile`。
- `schema_version`: 当前 `1.0.0`，与应用版本独立。接入方应检查主版本；同一主版本下允许增加字段，应忽略不认识的字段。
- 机器可读约束：[learning-profile.schema.json](learning-profile.schema.json)。[虚构样例](examples/learning-profile.json)不含真实用户数据。

| 字段 | 含义与用途 |
| --- | --- |
| `exported_at` / `producer` | 导出时间、应用名称与版本 |
| `learner.local_id` / `profile` | 本地档案标识、已填写的姓名/昵称/用户名/年龄/爱好；缺失字段省略 |
| `summary` | 知识点数、复习记录数及相对掌握/待加强/学习中的知识点 ID |
| `knowledge_points` | 知识点、学科、当前状态、判断原因、课程证据、最近复习与历史困难课程 ID |
| `recurring_difficulties` | 在至少两节不同的已保存课程中出现困难的知识点及对应课程 |
| `reviews` | 不懂的内容 `missing`、原因 `reason`、最近自评、复习次数、阶梯等级、下次复习时间 |
| `lessons` | 课程名称、摘要、时长、结束时间、知识点 ID、抽问题数/答对数/正确率 |
| `learning_preferences` | 根据最近复习自评计算的辅助信号；`needs_examples` 表示需要更多解释线索，`steady` 表示近期较稳定，`insufficient_data` 表示无样本 |
| `coverage` / `methodology` | 数据覆盖范围与判断口径，接入时应一并保留 |
| `excluded` / `warnings` | 明确排除的数据种类、异常字段说明 |

## 如何判断擅长与薄弱

`state` 为 `strength`（相对掌握）、`weakness`（待加强）、`developing`（学习中）或 `unknown`（未知）。最近复习记录晚于课程时优先使用复习：仍没懂/模糊/未复习归为待加强；最近自评清楚且复习阶梯至少 2 级归为相对掌握。否则看最近课程：标记待复习或掌握度低于 0.6 归为待加强；标记跟上且掌握度至少 0.8 归为相对掌握；其余为学习中。

`latest_mastery` 是课程记录中的 0～1 掌握指标，不是标准化测验成绩；复习可以改变当前状态，但不会改写历史课程的掌握指标。`reasons` 与 `observations` 保留判断依据。不要把 `review_sessions` 当作答错次数；反复困难统计的是不同课程数，含曾遇到问题而后已补上的 `fixed` 记录，不能等同于当前不会。

所有时间为 UTC ISO 8601（例如 `2026-11-10T10:00:00.000Z`）；未知为 `null`，不能按 0 分或未掌握处理。没有测验时 `quiz.accuracy` 为 `null`。旧记录缺少复习调度时间时保持未知，不补造时间。

## 关联到其他项目

知识点通过 `id` 关联，课程通过 `lesson_id` 关联。同一学科和同名知识点使用稳定 ID；学科目前取课程标题的前缀，属于启发式，可能需在你的项目里校正。不会用 AI 将相似名称自动合并。若同名知识点跨多个学科，而旧复习记录没有学科，该条复习以 `subject: null` 单独导出，避免误归属。

```javascript
// 浏览器：input 为 <input type="file" accept=".json">
const data = JSON.parse(await input.files[0].text());
if (data.format !== 'echo.learning-profile' ||
    data.schema_version.split('.')[0] !== '1') throw new Error('不支持的格式');
const byId = new Map(data.knowledge_points.map(p => [p.id, p]));
const needsHelp = data.summary.weakness_ids.map(id => byId.get(id));
console.table(needsHelp.map(p => ({ topic: p.topic, reason: p.reasons.join('；') })));
```

```python
import json
with open('Echo-learning-profile.json', encoding='utf-8') as f:
    data = json.load(f)
assert data['format'] == 'echo.learning-profile'
assert data['schema_version'].split('.')[0] == '1'
for item in data['recurring_difficulties']:
    print(item['topic'], item['affected_lesson_count'], item['lesson_ids'])
```

商业项目接入时，先让用户登录你的服务，再由用户选择文件导入，将这份快照绑定到已登录账号。`learner.local_id` 仅用于本地关联，不是登录凭证、全球唯一账号或身份验证。首次导入可以预览待加强知识点与课程数；重复导入按同一用户下的稳定 ID 更新，而不是重复累加次数。上传只在你的项目提供导入服务后发生，Echo 此按钮只保存本地文件。

## 覆盖范围

目前课程库最多保留最近 50 节课，所以导出不是终身完整档案；仅覆盖实际存在的已保存课程和复习记录，不包含正在上课的临时内容。当前存储没有逐题历史作答，因此仅导出每课抽问汇总，无法还原每次答错的原题和答案。若以后需要长期精确追踪，应增加逐题事件存储，并升级格式。

不导出 API Key、模型接口配置、原始录音、截图、头像、导入文档或 HTML 代码。课程摘要、个人资料及复习文字仍属于个人学习数据；接入方可让用户预览、选择用途，并提供删除功能。此格式是学习档案交换格式，不是 Echo 全量恢复备份，目前没有导入回 Echo 的功能。
