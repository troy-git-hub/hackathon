# Echo — 项目约定

网课里的 AI 学习副驾驶（PyQt5 桌面应用）。跑法见 README；这里是**不看代码就会踩坑**的东西。

## 打包与发布

生成安装包：

```
python scripts/build_release.py        # 默认在独立 worktree 里打（推荐）
python scripts/build_release.py --skip-iscc   # 只出 dist/Echo/，不编安装包
```

产物落在 `dist/Echo-Setup-<版本>.exe`（**`dist/` 在 .gitignore 里，不进版本库**）。
版本号写在 `installer/setup.iss` 的 `MyAppVersion`，`build_release.py` 从那里读。

**必须在独立 worktree 里打**：PyInstaller 打的是「工作区源码」而不是 git HEAD。这个仓库
同时有多个 Claude 会话在改同一份工作区，半截改动会被打进安装包。脚本默认已经这么做了，
别用 `--in-place` 省事。

## 语音识别模型：不随包分发（v2.1 起）

**历史**：v2.0 及更早把 faster-whisper 的 `model.bin`（483MB）**塞进了安装包**，
装出来的 `Echo-Setup-2.0.exe` 有 **565MB**。后果是往 GitHub Release 传两次都在中途断流，
而且装完第一次开课还要等模型加载。

**v2.1 起改成按需下载**：

- `echo/backend/model_fetch.py` 负责下到 `%APPDATA%\Echo\models\faster-whisper-small`
- **app 启动时就开始下**（`main.py` 里 `model_fetch.ensure()`），不等第一次开课
- 进度由 UI 的定时器调 `poll_progress()` 扫盘算出来，显示在状态栏
- `_WhisperWorker.load` 会 `wait_ready()` 等下载完 —— 不等的话 WhisperModel 会拿模型名
  去 HF 缓存**再下一遍**，同样 483MB
- **打包侧不许再带 `models/`**：`build.bat` / `installer/setup.iss` 里已经没有它，
  `build_release.check_setup_tree()` 还会主动删掉构建目录里残留的 `models/`
- 结果：安装包 **565MB → 103MB**

**开发机不受影响**：`config.whisper_model_path()` 的优先级是
用户目录 > 项目 `models/` > 随包目录 > HF 模型名，本机 `models/faster-whisper-small` 照用。

**HF 下载的坑**：huggingface_hub 0.29.3 在文件已经进了 HF 缓存时，
`snapshot_download(local_dir=…)` 会把文件留在缓存目录、`local_dir` 反而是空的。
所以 `_materialize()` 下完自己核一遍，不在目标目录就拷过来。

## 分发渠道

- **源码**：Gitee（`origin`，国内快）+ GitHub（`github`）各一份
- **安装包**：只走 GitHub Release。**Gitee 附件单文件上限 100MB，103MB 的安装包放不下**
- 推送前先 `git fetch`：多个会话共用这一份工作区，别人可能刚推过

## 测试

```
python scripts/accept_check.py     # 全套离线验收（16 项）
```

自检脚本**必须**先把 `paths.config_dir` 指到临时目录。不隔离的话会往用户真实的
`lessons.json` / `review.json` 里写东西 —— `theme_check.py` 就这么干过：它调
`window._on_echo(...)` 测回响页配色，那条路会存课程，于是每跑一次自检就多一节假课，
用户攒了几十节内容一模一样的「贝叶斯课」。`accept_check` 现在有护栏会当场报出来。
