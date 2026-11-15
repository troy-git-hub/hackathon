# Echo Website

自托管官网，Node.js 动态版本 API + 现有 Python 签名更新服务 + Docker Compose + 宿主机 Nginx HTTPS。网页服务无 npm 依赖；账户服务提供登录、邀请码、加密学习数据、资料上传、每日练习和整卷考试。网页说明来自真实已实现功能。

## 本机预览

在本目录运行 `node server.mjs`，访问 http://127.0.0.1:8080。要显示动态版本数据，先在项目根目录运行 `python update-server/server.py --data update-server/data`。前端请求同源 `/api/release`，由官网服务转发固定更新接口，浏览器不跨域访问更新 API。

## 域名与端口

| 用途 | 公网入口 | 宿主机回环端口 | 容器端口 |
| --- | --- | --- | --- |
| 官网 | https://echo.xhbtroy.cn | 127.0.0.1:8088 | 8080 |
| 更新服务 | https://update.echo.xhbtroy.cn | 127.0.0.1:8787 | 8787 |
| 版本 API | https://update.echo.xhbtroy.cn/v1/releases/stable/windows-x64 | 同上 | 同上 |
| 安装包 | https://update.echo.xhbtroy.cn/artifacts/Echo-Setup-2.4.1.exe | 同上 | 同上 |

只开放 80/443 给网站访客，SSH 22 建议限制为管理者地址。8088/8787 不应开放公网。账户服务使用受限持久化 SQLite，网页与账户 API 经同源 Nginx 路由。现有其他服务保持原端口和容器。

## 部署

服务器需已有 Docker Compose、Nginx、Certbot；先检查已有容器和 80/443/8088/8787 的占用。复制本文件夹及相邻 `update-server` 到 `/opt/echo/`，不要上传 `.env`、学习数据、SSH 密钥或签名私钥。安装包约 149 MiB，保留 `update-server/data/stable.json` 和 `data/artifacts/` 原样一起上传。

```sh
cd '/opt/echo/Echo Website'
docker compose config --quiet
docker compose up -d --build
curl -f http://127.0.0.1:8088/healthz
curl -f http://127.0.0.1:8787/healthz
curl -f http://127.0.0.1:8088/api/release
```

DNS 两条 A 记录指向 `18.209.18.173`。建议先 DNS only 完成源站 HTTPS 验证。已有同名记录时先确认，避免覆盖别的服务。

首次签发证书（先确保对应 server_name 不在其他配置内重复）：

```sh
sudo mkdir -p /var/www/echo-acme
sudo cp deploy/bootstrap-http.conf /etc/nginx/conf.d/echo.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/echo-acme --cert-name echo.xhbtroy.cn -d echo.xhbtroy.cn -d update.echo.xhbtroy.cn --register-unsafely-without-email --agree-tos --non-interactive
sudo cp deploy/echo.nginx.conf /etc/nginx/conf.d/echo.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run
```

证书续期后需 reload Nginx，可安装 deploy hook：`/etc/letsencrypt/renewal-hooks/deploy/reload-nginx`，内容为 `#!/bin/sh` 与 `systemctl reload nginx`，权限 755。若使用 Cloudflare 代理，将 SSL 模式设为 Full (strict)，保留有效源站证书。`update.echo.xhbtroy.cn` 为多级子域，启用代理前须确认边缘证书包含该主机名；DNS only 则直接使用源站证书。

## 客户端

已安装 Echo 的「设置 → 更新服务地址」改为 `https://update.echo.xhbtroy.cn`。现有 2.4.0 安装包默认本地服务地址，不会被本次网页部署自动修改。源码 `echo/widgets/update_center.py` 的 DEFAULT_URL 已改为正式域名，后续重新构建的安装包使用此默认值，用户已保存的自定义设置仍优先。

## 加固与边界

容器非 root、只读文件系统、移除 capabilities、禁止提权、资源/日志限制；安装包仅只读挂载，签名私钥不进入服务器。官网只接受 GET/HEAD，固定上游，无任意 URL 代理；本地资源、CSP、防嵌入、nosniff。Nginx 提供 TLS、限流和下载并发限制。客户端继续验证 Ed25519 签名和 SHA-256。

这些措施降低风险，不能保证绝不会被攻击；应持续更新系统和基础镜像。GitHub 和 DNS 令牌不属于部署文件，不进入镜像。SSH 副本在用户 `.ssh` 目录，仅当前用户可读。

## 后续更新

遵循 `../update-server/README.md` 在本地签名发布，然后只同步发布目录；不要替换相同版本的不同安装包，也不要生成新签名密钥覆盖现有信任链。
