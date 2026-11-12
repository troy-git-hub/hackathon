# Echo 本地更新服务

服务是只读的 Docker 容器：提供已签名版本信息、Windows 安装包和健康检查，不接收学习记录、用户资料或模型 API Key。应用内「设置 → 更新中心」提供检查、发布说明、下载进度、取消/重试及验证后安装。

本工作区已经创建项目签名密钥并编入客户端公钥。私钥留在项目 `.build/update-secrets/release-private-key.pem`，不进入 Git、Docker 镜像或安装包；请自行备份。服务仅挂载发布目录，不需要私钥。

## 本地启动

在项目根目录执行：

```powershell
docker compose -f update-server/compose.yaml up -d --build
docker compose -f update-server/compose.yaml ps
```

默认地址 `http://127.0.0.1:8787`，Echo 默认更新地址与之相同。

- `GET /healthz`：健康检查。
- `GET /v1/releases/stable/windows-x64`：已签名稳定版本；未发布时返回 404。
- `GET /artifacts/Echo-Setup-<版本>.exe`：对应安装包；不提供目录浏览或上传接口。

镜像仅复制 `server.py`；容器非 root 运行、文件系统只读、丢弃 Linux capabilities，发布数据通过只读卷挂载。停止服务不会删除发布文件：

```powershell
docker compose -f update-server/compose.yaml stop
```

## 发布后续版本

1. 增加 `echo/version.py` 与 `installer/setup.iss` 的版本号；不能给已发布版本替换不同的安装包。
2. 在项目内独立 worktree 构建，并完成安装、启动和卸载自检。
3. 准备 UTF-8 文本发布说明，每行一条，再发布：

```powershell
.venv/Scripts/python.exe scripts/publish_update.py publish `
  --installer dist/Echo-Setup-2.4.0.exe --version 2.4.0 `
  --notes docs/releases/2.4.0.txt
```

脚本检查 Inno 安装器结构、计算大小和 SHA-256，用 Ed25519 私钥签名，并先放入安装包、最后原子替换 `data/stable.json`。同版本同文件可以重复发布说明；同版本不同文件、稳定渠道版本倒退会被拒绝。服务无需重启。

客户端内置 `assets/update-public-key.pem`，先验证版本信息签名，再下载，并验证大小、SHA-256 和 Windows 文件头；下载完成和安装前各做检查。下载失败或取消时不会把残片当安装包。服务不能通过 JSON 指定任意命令、任意下载站或安装参数。

当前私钥是这个项目在本机生成的发布密钥；**克隆源码不包含私钥**，应从自己的安全备份恢复。新发行者需要在首次构建前生成自己的密钥，不能随意更换公钥后期待已安装客户端自动信任：

```powershell
# 仅在两个目标文件都尚不存在的新发行环境中执行；脚本拒绝覆盖密钥。
.venv/Scripts/python.exe scripts/publish_update.py keys
```

## 自动检查与安装行为

- 开启自动检查后，应用空闲时每天检查一次；连接失败后至少一小时再自动尝试，不弹出错误窗口。
- 上课期间不自动检查，也不允许安装；用户主动打开更新中心仍可检查或下载。
- 下载和安装由用户点击。安装前复核签名和文件，启动安装器后退出 Echo；安装器结束页可以重新启动应用。不会静默替换正在运行的课堂。
- 2.3.0 及更早版本没有这个更新入口，需要先手动安装一次 2.4.0。2.4.0 之后发布更高版本，客户端才会显示可更新。
- 同版本或旧版本只显示已是最新，不触发降级。

## 将来放到服务器

当前 Compose 只绑定本机 `127.0.0.1`。放到自己的服务器后，可保留该绑定，由域名的 HTTPS 反向代理转发到 8787；再在 Echo 设置里保存该 HTTPS 根地址。客户端拒绝远程明文 HTTP、认证信息写进 URL、跨站下载和重定向。当前服务不包含账号、计费、灰度渠道或公钥轮换后台。

上线前使用自己的签名密钥并备份；HTTPS 证书、域名和发布权限由部署方管理。Ed25519 更新签名与 Windows Authenticode 代码签名不同，不会代替 Windows 的发布者证书。

本机 Inno Setup 6.7.3 编译器显示 `Non-commercial use only`。官方请求商业用户购买商业授权，商业发行时请按 [官方商业授权说明](https://jrsoftware.org/isorder.php)核对安排。

官方参考：[Docker Compose 服务配置](https://docs.docker.com/reference/compose-file/services/)。
