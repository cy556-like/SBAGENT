# 飞书通讯录同步部署

## 飞书开放平台配置

应用身份至少需要下列只读权限，并将每项权限的数据范围设为“全部员工/全部部门”：

- `contact:contact.base:readonly`
- `contact:department.base:readonly`
- `contact:department.organize:readonly`
- `contact:user.base:readonly`
- `contact:user.employee_id:readonly`

事件订阅保持“长连接”，并添加：

- `contact.user.created_v3`
- `contact.user.updated_v3`
- `contact.user.deleted_v3`
- `contact.department.created_v3`
- `contact.department.updated_v3`
- `contact.department.deleted_v3`

权限、数据范围和事件变更后必须创建新版本并发布，未发布的修改不会对线上应用生效。

## 首次全量同步

先通过网页飞书 SSO 登录一次，让系统记录租户 `tenant_key`；也可以在 `.env` 显式设置：

```env
FEISHU_TENANT_KEY=你的租户tenant_key
FEISHU_CONTACT_SYNC_ENABLED=true
FEISHU_CONTACT_FULL_SCOPE_CONFIRMED=true
```

只有确认开放平台的数据范围为“全部员工”后，才把
`FEISHU_CONTACT_FULL_SCOPE_CONFIRMED` 设为 `true`。否则全量同步不会把本次不可见的
员工误判为离职；明确的员工离职事件仍会立即停用账号。

在项目目录运行：

```cmd
python -m app.feishu_contacts_cli sync --full
python -m app.feishu_contacts_cli status
```

同步数据库位于 `data\feishu\contacts.sqlite3`，现有员工查询工具使用的
`data\employees.json` 也会原子更新。

## 增量事件和离职停用

`python -m app.feishu_bot` 会接收员工和部门的新增、更新、删除事件。事件回调立即返回，
本地数据库写入在后台线程完成。员工删除或停用后，对应 SSO 映射立即标为停用，旧 JWT
也会在下一次请求时被拒绝；普通网页账号不受影响。

## Windows 每日任务

以管理员身份打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\register_feishu_contact_sync_task.ps1 -ProjectPath "C:\beifen\SBAGENT" -DailyAt "02:30"
```

任务使用服务器 `.env`，不会把 App Secret 写入任务计划。日志位于
`data\logs\feishu_contact_sync.log`。

## 后续：部门到智能体权限

当前版本只同步组织数据，不自动改变智能体权限。后续可增加独立策略表
`department_agent_policies(department_id, agent_id, permission)`，由管理员显式配置；
不要直接把部门名称硬编码到权限逻辑，以免改名或调岗造成越权。
