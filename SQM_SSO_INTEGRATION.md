# SQM 接入速豹AI单点登录

本接口与飞书无关。SQM 后端确认当前用户身份后，向速豹申请一个 60 秒内有效、只能使用一次的登录链接，再将用户浏览器跳转到该链接。

## 1. 申请一次性登录链接

```http
POST https://47.114.99.132:8007/api/v1/auth/sqm/tickets
Content-Type: application/json
X-SQM-Client-ID: sqm-system
X-SQM-Timestamp: 1785744000
X-SQM-Nonce: 16至128位随机字符串
X-SQM-Signature: HMAC-SHA256十六进制小写签名
```

请求体只有两个业务字段，不需要部门：

```json
{"user_id":"100086","name":"张三"}
```

- `user_id`：必填。SQM 中稳定且唯一、以后不会改变的用户ID，最长128字符。
- `name`：选填，仅用于速豹页面显示和生成内部账号名称，不作为身份主键。

签名原文是以下字节顺序：

```text
UTF8(X-SQM-Timestamp + "\n" + X-SQM-Nonce + "\n") + HTTP原始请求体字节
```

签名算法：

```text
lowercase_hex(HMAC-SHA256(SQM_SSO_SHARED_SECRET, 签名原文))
```

签名时使用的 JSON 字节必须与实际发送的请求体完全一致。时间戳允许误差为正负 300 秒；同一个 Nonce 只能使用一次。

成功响应：

```json
{
  "success": true,
  "expires_in": 60,
  "login_url": "https://47.114.99.132:8007/api/v1/auth/sqm/login?ticket=..."
}
```

失败响应：

```json
{"detail":"SQM SSO request rejected"}
```

HTTP 状态码为 `401`。具体原因只写入速豹后端日志，避免向公网泄露验签细节。

## 2. 跳转用户浏览器

SQM 后端收到 `login_url` 后，对用户浏览器返回 HTTP 302，跳转到该地址。不要由 SQM 前端直接调用申请接口，也不要把共享密钥写入 JavaScript。

速豹消费一次性票据后会：

1. 按 `user_id` 查找或创建固定的内部普通用户。
2. 写入安全的 HttpOnly 登录 Cookie。
3. 直接进入速豹七大智能体页面，不显示登录页。

同一个 `user_id` 每次都会映射到同一个速豹账号，因此能够看到自己的历史聊天；不同 `user_id` 的聊天相互隔离。

## 3. 数据保留规则

- 仅 SQM 单点账号的聊天按最后活动时间保留 7 天。
- 超过 7 天的聊天正文、该聊天生成的下载文件和该聊天临时文件一并删除。
- SQM 聊天在 7 天内不受原有“每个智能体最多两个会话”的限制。
- 网页密码账号、飞书账号、知识库原始文档不受本规则影响。

## 4. 速豹服务器配置

```env
SQM_SSO_ENABLED=true
SQM_SSO_CLIENT_ID=sqm-system
SQM_SSO_SHARED_SECRET=双方单独安全传递的高强度随机密钥
SQM_SSO_PUBLIC_URL=https://47.114.99.132:8007
SQM_SSO_TICKET_EXPIRE_SECONDS=60
SQM_SSO_RETENTION_DAYS=7
SQM_SSO_SESSION_COOKIE=sbagent_session
```

修改 `.env` 后重启速豹后端。共享密钥不能提交到 GitHub，也不能通过普通聊天明文转发。
