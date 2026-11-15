# Echo 快速更新渠道（源码已实现，未发布新客户端）

新客户端先检查 `https://update.echo.xhbtroy.cn/v2/releases/stable/windows-x64`；尚无 v2 版本时，仅在 HTTP 404 时回退到原来的 v1 安装包渠道，不会在签名失败时降级绕过验证。旧 2.4.0 客户端仍使用 v1，保持兼容。

v2 使用 `echo.update/2` 的 Ed25519 签名清单，文件名 `Echo-Update-X.Y.Z.zip`。这是完整目录包，省略重复的安装向导，**不是差分下载**，不保证包比 Inno 安装包更小。需要从现有安装版升级，首次安装仍用安装器。

客户端验证清单签名、文件大小、SHA-256、ZIP 结构、路径、Windows 保留文件名及 Echo.exe 格式。压缩包不能包含用户配置、课程数据、语音模型、符号链接或越界路径。先解压到安装目录的同级暂存目录，再由独立 PowerShell 辅助程序等待 Echo 退出，移动旧目录作备份，然后原位换入新目录并启动 Echo。目录替换/启动失败时尝试恢复旧目录；保留备份，不自动递归清理用户磁盘。

用户数据仍在 `%APPDATA%/Echo`；安装目录路径和快捷方式不变。复制原卸载器文件到新目录，保留现有卸载入口。该更新路径不重建卸载注册表版本号；需要更新安装注册信息时可使用完整安装器。默认每日空闲时检查，发现版本询问是否查看；下载和安装均需用户操作，课堂期间禁止安装。

发布命令（必须先在项目内独立 worktree 构建、完成运行验证）：

```powershell
.venv/Scripts/python.exe scripts/publish_fast_update.py --folder .build/windows/dist/Echo --version X.Y.Z --notes docs/releases/X.Y.Z.txt
```

使用现有 `.build/update-secrets/release-private-key.pem` 签名，私钥不上传服务器。把 `update-server/data/artifacts/Echo-Update-X.Y.Z.zip` 和 `stable-v2.json` 同步到服务器，先安装包、后清单。当前服务器已支持 v2 路由，但没有发布虚构版本或把测试包放到公网。

`scripts/fast_update_check.py` 覆盖签名 v2 清单、真实本地 HTTP 下载、校验、目录暂存、卸载器保留及恶意 ZIP 路径。PowerShell 辅助程序通过语法检查，并在项目内隔离目录中实际运行了新程序启动失败后恢复旧目录的验收（`scripts/fast_update_apply_check.py`）。尚未在真实 Echo 安装版本上完成成功更新与重启验收，发布客户端前必须补上这一项。
