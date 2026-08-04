# SQM 固定演示账号自动登录

本功能用于项目立项前的演示阶段，不是按 SQM 用户隔离的正式单点登录。所有访问者均进入速豹现有普通账号 `jiangxy`，因此共享聊天记录。

## SQM 侧使用的固定链接

```text
https://47.114.99.132:8007/api/v1/auth/sqm/demo-login?key=服务器生成的入口密钥
```

SQM 只需把该完整链接配置为“速豹AI平台”按钮的跳转地址。速豹验证入口密钥后，在后端生成 `jiangxy` 登录会话并跳转七大智能体页面；用户名、密码和 JWT 均不出现在链接中。

## 服务器配置

```env
SQM_DEMO_LOGIN_ENABLED=true
SQM_DEMO_USERNAME=jiangxy
SQM_DEMO_ENTRY_KEY=高强度随机密钥
SQM_DEMO_RETENTION_DAYS=7
SQM_DEMO_SESSION_COOKIE=sbagent_session
```

修改 `.env` 后重启 FastAPI。入口密钥泄露后只需生成新密钥并重启，不需要修改 `jiangxy` 密码或应用 JWT 主密钥。

## 数据规则

- 所有访问者共享 `jiangxy` 的聊天记录。
- `jiangxy` 的聊天按最后活动时间保留 7 天。
- 过期聊天正文、该聊天的导出文件和临时文件一并删除。
- 其他网页账号、飞书账号和知识库原始文档不受本规则影响。
