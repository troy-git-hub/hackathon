# Echo 内测接口协作

更新：2026-11-15。此文件供同一工作区的两个开发会话交接，不包含凭证。

## 分工

- 官网会话：账户后端、学习点 token 计费、请求日志用途、云端记录与练习、内测下载鉴权、统一打包和部署、《开发记录.md》、Android/Git 环境。
- 客户端体验会话：主页布局、课堂分析频率、复习小册、做题与知识库相关体验。以对方回复为准，打包前确认就绪状态。
- `echo/widgets/settings.py` 为共享文件，改动需小范围补丁，保留对方新增内容。`floating_window.py` 本轮由客户端体验会话主要维护。

## 请求用途

账户协议将升级到 `echo.inference/2`，兼容读取旧 `echo.inference/1` 请求。新增 `purpose` 字段供服务端日志显示；它不授予权限，也不能修改服务端价格或余额。

用途约定：`blackboard`（AI 黑板）、`quiz`（出题）、`grading`（批改）、`classroom`（听课知识分析）、`catchup`（补课讲解）、`qa`（答疑）、`review`（复习）、`summary`（课堂总结）、`persona`（学习画像）、`booklet`（复习小册）、`problem_solving`（做题解析）、`vision`（截图识别）、`assistant`（通用辅助）。

本会话会扩展 `LLM.json(..., purpose='assistant')` 与账户模型适配器。直接 OpenAI 兼容调用可传 `extra_body={'echo_purpose':'blackboard'}`，适配器只取用途，不把客户端模型密钥或计费数据传给账户服务。个人 API 模式不要求发送 Echo 扩展字段。

学习点将按服务商实际 token 用量结算，不再固定一次一点；缺失用量时必须明确标注估算，不能伪装为服务商统计。界面使用小数学习点，内部使用整数最小单位。

## 同步与桌面发布

- 现有 `echo.sync/1` 与 learning-profile 2.0.0 保留；课堂记录使用新增的独立白名单字段，不能把 `.env`、模型密钥、任意目录或录音直接上传。
- 桌面原有皮肤保留；登录窗无边框；同步不会覆盖其他账户资料。
- 新桌面版本仅发布内测渠道；普通下载与 stable 清单继续指向原 2.4.0。
- 打包前双方确认当前源码和检查通过，随后制作独立快照。任何一方继续修改工作区不应影响已经开始构建的快照。

## 基础版交接补充（2026-11-15，代码就绪）

- 新增本地 booklets.json：小册主题/大类/章节/自测/来源快照。基础版不会自行上传；高级版同步如需纳入，请明确扩展白名单。其来源可能含选定课堂转写片段，但无录音、截图、模型配置或密钥。
- 新增用途已接好：LLM.json 的 booklet / blackboard / classroom；账户视觉请求通过 extra_body.echo_purpose=blackboard 标注，个人API不加Echo字段。
- 源码核心文件：新增 backend/booklets.py、widgets/booklet_window.py、board_chat.py、echo_combo.py；修改 floating_window.py、profile_page.py、settings.py（只加频率/知识库）、engine.py、prompts.py、backend/blackboard.py、widgets/blackboard.py、mock_data.py、web_lesson.py、config.py、context.py。
- 专项检查已通过；全套30/31，账户 /1→/2 旧断言由官网会话修正。未并行打包，源码可制作快照。完整说明：基础版-主页小册与黑板聊天.md。

## 下一轮本地入口交接（2026-11-15）

- 新指令优先：后续只本地修改，暂不上传。
- 客户端已将主页压紧，更多工具默认收起；小册统一UI名称“我的小本”，数据文件booklets.json和类名不变。
- 主页 _open_exam() 调用 open_exam_window(engine=self.echo.engine, parent=self)，保留返回窗口引用；我的小本工具栏通过父窗口同一路径进入，无父窗口时传 engine=self.engine、parent=self。
- 考试会话负责提供 echo.widgets.exam_window.open_exam_window、章节选择、完整试卷/答题界面和防作弊选项。客户端未修改exam.py或exam_window.py。
- 入口参数使用隔离桩验证通过；不代表考试后端已验收。界面/原功能专项通过，六主题174/174通过，无浏览器测试。

## 考试机专项交接（2026-11-15）

- 已接管并修复 backend/exam.py、widgets/exam_window.py；新增 scripts/exam_check.py。此次源码已就绪，交由官网/发布会话制作快照。
- 保留 echo.exam/1 协议；新增 validate/checkpoint 内部函数，public_paper 不输出答案/解析。主观题 pending，score=null；本地 Beta 未接入整卷主观AI批改，网页不可据此宣称完整自动判卷。
- 存档失败不提交内存结果；账户切换允许安全关闭；恢复读取最新数据并验证结构；失焦去重、exit 单独记录；过期恢复自动交卷。坏存档不覆写。
- exam_check、assessment_check、workspace_revision_check 通过，无真实模型请求、无网页浏览器测试。发布会话负责把 exam_check 纳入 accept_check 并统一验证构建快照。

## 网页学习空间前端冻结（2026-11-16）

- 前端已完成user.html、console.js、新study.js/css；没有修改account-server。接口均按 /api/account/me/study 契约，整份preferences保存时保留原每周安排。
- 手动付费与免费复用分开，资料题目核对confirm后入库，扫描PDF补文字/图片手动视觉解析，5题型作答与revision串行保存、冲突草稿恢复、服务端截止结算、手动主观AI批改均接好。
- 独立模拟浏览器专项 scripts/web_study_check.cjs 已通过（3hash直达/登录hook/登出清缓存/无自动AI/409无付费回退/上传解析确认/5题型/保存失败重试/冲突恢复/交卷待批手动批改/移动布局）；无真实模型消费。
- 前端源码就绪可制作部署快照；前端自检不代替后端API测试和生产验证。细节见 网页学习空间-体验与接口.md。部署仍由后端会话负责，不在本会话重复发布。

补充：已接错题免费重做 POST /attempts/id/retry，在结果页/历史列表按wrong_count显示；服务端新快照继续隐藏答案。资料confirm后刷新现有loadWorkspace，连接知识点复习/单题练习。最后web_study_check再次通过，前端已冻结可部署。

## 桌面UI本机交接（2026-11-16）

桌面会话已完成紧凑主页、统一自绘标题栏、小本/考试/登录/设置外观、个人学习中心与管理员入口下沉。仅改native widgets与专项，不改backend、网页、Android原生，不打包。账户摘要复用me/workspace/requests，无API字段缺口；异步捕获token并校验owner，旧账户本机资料不显示。六皮肤专项/原生截图、登录、账户、考试、入口、主题174/174均通过；数据全隔离，预览均为模拟数据。详见桌面UI-紧凑主页与学习中心.md；后续如需发布由主协作会话统一处理。
