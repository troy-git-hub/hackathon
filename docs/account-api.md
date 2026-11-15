# Echo 账户专用 API · echo.inference/1

公网根地址固定为 `https://api.echo.xhbtroy.cn`。桌面端使用 Echo 专用 JSON 协议，不把模型供应商密钥分发给用户。自定义模型仅在高级设置中显式启用，使用用户自己的服务和额度。

## 注册与登录

- 注册：`POST /v1/auth/register`，字段 `email`、`name`、`invite`、`code`、`password`、`confirm_password`。密码 12–128 字符，使用 Argon2id 保存。邀请码必须有效且只可使用一次；邮件验证码证明邮箱所有权。
- 登录：`POST /v1/auth/login`，已注册账户用 `email + password` 或 `email + code`。登录不会自动注册新账户。
- 获取验证码：`POST /v1/auth/code`，字段 `email`、`purpose`；purpose 为 login、register 或 password。注册用途还需 invite。
- 桌面登录加 `client: "desktop"`，响应包含会话令牌。桌面保存在系统凭据库。网页使用 Secure/HttpOnly/SameSite=Strict Cookie。
- 后续写操作必须带 `X-Echo-CSRF: 1`，桌面认证为 `Authorization: Bearer <会话令牌>`。不要在每次模型请求中重复传账户密码。
- 免费邮件模式下，管理员先在邮件开通管理中向指定邮箱发送 Cloudflare 验证邀请；收件人点击后才可以接收 Echo 验证码。这个动作不会自动创建 Echo 用户。

## 模型请求

`POST /v1/echo/inference`

```json
{
  "protocol": "echo.inference/1",
  "account_id": "登录响应中的账户 ID",
  "request_id": "32 位随机 UUID，重试时保持相同",
  "task": "text",
  "context": {
    "messages": [{"role": "user", "content": "请解释这一步"}],
    "max_tokens": 1200,
    "temperature": 0.3
  }
}
```

task 只能为 text 或 vision。context 可选 `response_format: {"type":"json_object"}`。服务端不接受用户指定模型供应商地址、API Key、工具执行或扣点金额。

```json
{
  "protocol": "echo.inference/1",
  "request_id": "同一个请求 UUID",
  "result": {"text": "模型回复", "finish_reason": "stop", "usage": {}},
  "account": {"id": "账户 ID", "balance": 99, "charged_points": 1}
}
```

服务端以会话确定用户，再核对 account_id。仅改 JSON 中的账户 ID 不能冒充别人；知道协议格式也无法绕过登录、余额和限流。自定义格式不宣称能够阻止付费点数账户自行写客户端。

## 学习点与重试

当前默认每个成功的模型请求消耗 1 学习点。服务端事务预扣，失败、超时或服务重启后未完成的请求返还；余额不足返回 402，根本不会调用模型。管理员也遵守余额检查。

同一账户的同一 request_id：

- 正在处理：409，不重复调用、不再次扣点。
- 已成功，内容相同：10 分钟缓存期内返回同一结果，不再次扣点。
- 内容不同：409，拒绝复用请求编号。
- 已失败：409，原请求的学习点已返还，用户主动重试应创建新编号。
- 缓存过期：409，保留已处理记录，不重新扣点或重新调用。

响应缓存使用带认证加密，定时清除过期密文；不持久化请求原文或截图。后台显示状态、任务、时间、请求编号和点数，不展示课堂内容。全站最多 8 个并行模型请求，每账户最多 2 个；同时保留每分钟、每日和 Nginx 限流。

旧 `POST /v1/chat/completions` 已关闭，已登录访问返回 410。当前公开的 2.4.0 安装包使用用户自己的模型配置，不依赖此新账户协议；本次不发布新安装包。

## 后台管理

- `/v1/admin/invitations`：创建与分页查询注册邀请码、学习点兑换码，可按类型/状态/邮箱/备注查询。
- `/v1/admin/invitations/{id}/revoke`：停用未使用的码。
- `/v1/admin/invitations/{id}/replace`：补发未使用的有效码，旧码同时停用。用于旧版无法恢复原文的历史码；后台操作前提示重新通知受邀人。
- `/v1/admin/users`：用户搜索与分页。
- `/v1/admin/users/{id}/access`：账户启停和 AI 权限开通。
- `/v1/admin/users/{id}/sessions/revoke`：撤销其他账户的全部会话。
- `/v1/admin/users/{id}/credits`：调整内测学习点，必须有原因、写入流水，禁止负余额。
- `/v1/admin/mail/recipients`：查看邮箱待验证/已开通状态。
- `/v1/admin/mail/verify-recipient`：向指定邮箱发起 Cloudflare 验证。
- `/v1/admin/requests`：查看最近 AI 请求及消耗。
- `/v1/me/password`、`/v1/me/ledger`、`/v1/me/requests`：用户自己的密码、学习点流水及调用记录。

新码加密保存，管理员可查看原文与使用者。旧版仅存哈希的码不能恢复原文，已用记录仍保留；未用的旧码可补发。不要更换或丢失运行配置中的账户密钥，否则已有会话和密文将失效；应把受限配置与数据库分别安全备份。
