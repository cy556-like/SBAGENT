"""Feishu contact directory synchronization and local read model.

The module intentionally uses the tenant-scoped ``user_id`` as the primary
identity.  ``open_id`` is retained only as an alias because it changes between
Feishu applications.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import settings


logger = logging.getLogger(__name__)
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
API_ROOT = "https://open.feishu.cn/open-apis"


class FeishuContactError(RuntimeError):
    pass


def _db_path() -> Path:
    configured = str(getattr(settings, "FEISHU_CONTACTS_DB", "") or "").strip()
    return Path(configured) if configured else Path(settings.DATA_DIR) / "feishu" / "contacts.sqlite3"


def _open_db() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS departments (
            tenant_key TEXT NOT NULL,
            open_department_id TEXT NOT NULL,
            department_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            parent_department_id TEXT NOT NULL DEFAULT '',
            leader_user_id TEXT NOT NULL DEFAULT '',
            order_value TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            raw_json TEXT NOT NULL DEFAULT '{}',
            updated_at INTEGER NOT NULL,
            deleted_at INTEGER,
            PRIMARY KEY (tenant_key, open_department_id)
        );
        CREATE INDEX IF NOT EXISTS idx_departments_id
            ON departments(tenant_key, department_id);
        CREATE TABLE IF NOT EXISTS users (
            tenant_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            open_id TEXT NOT NULL DEFAULT '',
            union_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            en_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            mobile TEXT NOT NULL DEFAULT '',
            employee_no TEXT NOT NULL DEFAULT '',
            job_title TEXT NOT NULL DEFAULT '',
            department_ids TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1,
            status_json TEXT NOT NULL DEFAULT '{}',
            raw_json TEXT NOT NULL DEFAULT '{}',
            updated_at INTEGER NOT NULL,
            deactivated_at INTEGER,
            PRIMARY KEY (tenant_key, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_users_open_id
            ON users(tenant_key, open_id);
        CREATE INDEX IF NOT EXISTS idx_users_active
            ON users(tenant_key, active);
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_key TEXT NOT NULL,
            mode TEXT NOT NULL,
            source TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            status TEXT NOT NULL,
            department_count INTEGER NOT NULL DEFAULT 0,
            user_count INTEGER NOT NULL DEFAULT 0,
            deactivated_count INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT ''
        );
        """
    )
    return conn


@contextmanager
def _database():
    conn = _open_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        return result if isinstance(result, dict) else {}
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {}


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _tenant_from_sso_db() -> str:
    configured = str(getattr(settings, "FEISHU_TENANT_KEY", "") or "").strip()
    if configured:
        return configured
    path = Path(settings.DATA_DIR) / "users" / "feishu_sso.sqlite3"
    if path.exists():
        try:
            with sqlite3.connect(str(path)) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT tenant_key FROM user_bindings WHERE tenant_key <> ''"
                ).fetchall()
            if len(rows) == 1:
                return str(rows[0][0])
        except sqlite3.Error:
            pass
    raise FeishuContactError(
        "无法确定 tenant_key：请先通过飞书登录一次，或在 .env 设置 FEISHU_TENANT_KEY"
    )


def _status_is_active(user: dict[str, Any]) -> bool:
    status = user.get("status")
    if not isinstance(status, dict):
        return not bool(user.get("is_resigned") or user.get("deleted"))
    if status.get("is_resigned") or status.get("is_frozen"):
        return False
    return bool(status.get("is_activated", True))


def upsert_department(tenant_key: str, department: dict[str, Any], *, active: bool = True) -> str:
    item = _as_dict(department)
    open_department_id = str(item.get("open_department_id") or item.get("department_id") or "")
    if not open_department_id:
        raise FeishuContactError("部门事件缺少 open_department_id")
    now = int(time.time())
    with _database() as conn:
        conn.execute(
            """INSERT INTO departments(
                tenant_key, open_department_id, department_id, name,
                parent_department_id, leader_user_id, order_value, active,
                raw_json, updated_at, deleted_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_key, open_department_id) DO UPDATE SET
                department_id=excluded.department_id, name=excluded.name,
                parent_department_id=excluded.parent_department_id,
                leader_user_id=excluded.leader_user_id, order_value=excluded.order_value,
                active=excluded.active, raw_json=excluded.raw_json,
                updated_at=excluded.updated_at, deleted_at=excluded.deleted_at""",
            (
                tenant_key,
                open_department_id,
                str(item.get("department_id") or ""),
                str(item.get("name") or ""),
                str(item.get("parent_department_id") or ""),
                str(item.get("leader_user_id") or ""),
                str(item.get("order") or ""),
                int(active),
                json.dumps(item, ensure_ascii=False, default=str),
                now,
                None if active else now,
            ),
        )
    return open_department_id


def upsert_user(tenant_key: str, user: dict[str, Any], *, active: bool | None = None) -> str:
    item = _as_dict(user)
    user_id = str(item.get("user_id") or "")
    if not user_id:
        raise FeishuContactError("用户数据缺少稳定的 user_id")
    is_active = _status_is_active(item) if active is None else bool(active)
    now = int(time.time())
    departments = item.get("department_ids") or []
    if not isinstance(departments, list):
        departments = [departments]
    with _database() as conn:
        conn.execute(
            """INSERT INTO users(
                tenant_key, user_id, open_id, union_id, name, en_name, email,
                mobile, employee_no, job_title, department_ids, active,
                status_json, raw_json, updated_at, deactivated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_key, user_id) DO UPDATE SET
                open_id=excluded.open_id, union_id=excluded.union_id,
                name=excluded.name, en_name=excluded.en_name, email=excluded.email,
                mobile=excluded.mobile, employee_no=excluded.employee_no,
                job_title=excluded.job_title, department_ids=excluded.department_ids,
                active=excluded.active, status_json=excluded.status_json,
                raw_json=excluded.raw_json, updated_at=excluded.updated_at,
                deactivated_at=excluded.deactivated_at""",
            (
                tenant_key,
                user_id,
                str(item.get("open_id") or ""),
                str(item.get("union_id") or ""),
                str(item.get("name") or ""),
                str(item.get("en_name") or ""),
                str(item.get("email") or ""),
                str(item.get("mobile") or ""),
                str(item.get("employee_no") or ""),
                str(item.get("job_title") or ""),
                json.dumps(departments, ensure_ascii=False),
                int(is_active),
                json.dumps(item.get("status") or {}, ensure_ascii=False, default=str),
                json.dumps(item, ensure_ascii=False, default=str),
                now,
                None if is_active else now,
            ),
        )
    return user_id


def mark_user_inactive(tenant_key: str, *, user_id: str = "", open_id: str = "") -> int:
    now = int(time.time())
    with _database() as conn:
        if user_id:
            cursor = conn.execute(
                "UPDATE users SET active=0, deactivated_at=?, updated_at=? "
                "WHERE tenant_key=? AND user_id=?",
                (now, now, tenant_key, user_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE users SET active=0, deactivated_at=?, updated_at=? "
                "WHERE tenant_key=? AND open_id=?",
                (now, now, tenant_key, open_id),
            )
    try:
        from app.auth.feishu_sso import deactivate_binding

        deactivate_binding(tenant_key, user_id=user_id, open_id=open_id)
    except Exception:
        logger.exception("停用飞书 SSO 映射失败")
    return int(cursor.rowcount)


def contact_active_status(tenant_key: str, *, user_id: str = "", open_id: str = "") -> bool | None:
    with _database() as conn:
        if user_id:
            row = conn.execute(
                "SELECT active FROM users WHERE tenant_key=? AND user_id=?",
                (tenant_key, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT active FROM users WHERE tenant_key=? AND open_id=?",
                (tenant_key, open_id),
            ).fetchone()
    return None if row is None else bool(row[0])


@dataclass
class FeishuContactClient:
    app_id: str
    app_secret: str
    timeout: float = 30.0

    async def _request(self, method: str, path: str, *, token: str = "", params=None, json_body=None):
        import httpx

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method, f"{API_ROOT}{path}", headers=headers, params=params, json=json_body
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") not in (None, 0):
            raise FeishuContactError(f"飞书通讯录 API 失败：{payload.get('msg') or payload.get('message')}")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    async def tenant_token(self) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") not in (None, 0) or not payload.get("tenant_access_token"):
            raise FeishuContactError(f"获取 tenant_access_token 失败：{payload.get('msg', '')}")
        return str(payload["tenant_access_token"])

    async def _paged(self, path: str, *, token: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            page_params = dict(params)
            if page_token:
                page_params["page_token"] = page_token
            data = await self._request("GET", path, token=token, params=page_params)
            items.extend(x for x in (data.get("items") or []) if isinstance(x, dict))
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return items

    async def all_departments(self, token: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        queue = ["0"]
        visited: set[str] = set()
        while queue:
            parent = queue.pop(0)
            if parent in visited:
                continue
            visited.add(parent)
            children = await self._paged(
                f"/contact/v3/departments/{parent}/children",
                token=token,
                params={
                    "department_id_type": "open_department_id",
                    "user_id_type": "user_id",
                    "fetch_child": "false",
                    "page_size": 50,
                },
            )
            for item in children:
                dep_id = str(item.get("open_department_id") or item.get("department_id") or "")
                if dep_id:
                    found[dep_id] = item
                    queue.append(dep_id)
        return list(found.values())

    async def users_in_department(self, token: str, department_id: str) -> list[dict[str, Any]]:
        return await self._paged(
            "/contact/v3/users/find_by_department",
            token=token,
            params={
                "department_id": department_id,
                "department_id_type": "open_department_id",
                "user_id_type": "user_id",
                "page_size": 50,
            },
        )


def _export_employees(tenant_key: str) -> None:
    with _database() as conn:
        users = conn.execute(
            "SELECT * FROM users WHERE tenant_key=? AND active=1 ORDER BY name", (tenant_key,)
        ).fetchall()
        departments = {
            row["open_department_id"]: row["name"]
            for row in conn.execute(
                "SELECT open_department_id, name FROM departments WHERE tenant_key=? AND active=1",
                (tenant_key,),
            ).fetchall()
        }
    result = []
    for user in users:
        department_ids = json.loads(user["department_ids"] or "[]")
        names = [departments.get(dep, dep) for dep in department_ids]
        result.append(
            {
                "id": user["user_id"],
                "name": user["name"],
                "department": " / ".join(x for x in names if x),
                "position": user["job_title"],
                "email": user["email"],
                "phone": user["mobile"],
            }
        )
    path = Path(settings.EMPLOYEES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


async def run_full_sync(*, tenant_key: str = "", source: str = "cli", client=None) -> dict[str, Any]:
    tenant_key = tenant_key or _tenant_from_sso_db()
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        raise FeishuContactError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
    api = client or FeishuContactClient(settings.FEISHU_APP_ID, settings.FEISHU_APP_SECRET)
    started = int(time.time())
    with _database() as conn:
        cursor = conn.execute(
            "INSERT INTO sync_runs(tenant_key, mode, source, started_at, status) VALUES(?, 'full', ?, ?, 'running')",
            (tenant_key, source, started),
        )
        run_id = int(cursor.lastrowid)
    try:
        token = await api.tenant_token()
        departments = await api.all_departments(token)
        for department in departments:
            upsert_department(tenant_key, department)
        department_ids = ["0"] + [
            str(x.get("open_department_id") or x.get("department_id") or "") for x in departments
        ]
        users_by_id: dict[str, dict[str, Any]] = {}
        for department_id in dict.fromkeys(x for x in department_ids if x):
            for user in await api.users_in_department(token, department_id):
                if user.get("user_id"):
                    users_by_id[str(user["user_id"])] = user
        for user in users_by_id.values():
            upsert_user(tenant_key, user)
        deactivated: list[str] = []
        with _database() as conn:
            existing = conn.execute(
                "SELECT user_id FROM users WHERE tenant_key=? AND active=1", (tenant_key,)
            ).fetchall()
        received = set(users_by_id)
        if bool(getattr(settings, "FEISHU_CONTACT_FULL_SCOPE_CONFIRMED", False)):
            for row in existing:
                if str(row[0]) not in received:
                    mark_user_inactive(tenant_key, user_id=str(row[0]))
                    deactivated.append(str(row[0]))
        elif existing:
            logger.warning(
                "未确认全员通讯录范围，跳过缺失用户批量停用，避免误停正常账号"
            )
        _export_employees(tenant_key)
        with _database() as conn:
            conn.execute(
                "UPDATE sync_runs SET finished_at=?, status='success', department_count=?, "
                "user_count=?, deactivated_count=? WHERE id=?",
                (int(time.time()), len(departments), len(users_by_id), len(deactivated), run_id),
            )
        return {
            "run_id": run_id,
            "tenant_key": tenant_key,
            "departments": len(departments),
            "users": len(users_by_id),
            "deactivated": len(deactivated),
        }
    except Exception as exc:
        with _database() as conn:
            conn.execute(
                "UPDATE sync_runs SET finished_at=?, status='failed', error=? WHERE id=?",
                (int(time.time()), str(exc)[:2000], run_id),
            )
        raise


def apply_contact_event(event_type: str, tenant_key: str, payload: Any) -> None:
    """Persist a Feishu contact event without waiting on an external API call."""
    data = _as_dict(payload)
    event = _as_dict(data.get("event")) or data
    tenant_key = tenant_key or str(_nested(data, "header", "tenant_key") or "")
    if not tenant_key:
        tenant_key = str(getattr(settings, "FEISHU_TENANT_KEY", "") or "default")
    event_type = event_type or str(_nested(data, "header", "event_type") or "")
    # Contact v3 events use ``event.object`` for both users and departments.
    # The named keys are kept for compatibility with test/webhook adapters.
    event_object = _as_dict(event.get("object"))
    user = _as_dict(event.get("user")) or event_object
    department = _as_dict(event.get("department")) or event_object
    if ".user." in event_type:
        user_id = str(user.get("user_id") or event.get("user_id") or "")
        open_id = str(user.get("open_id") or event.get("open_id") or "")
        if event_type.endswith("deleted_v3"):
            mark_user_inactive(tenant_key, user_id=user_id, open_id=open_id)
        elif user_id:
            upsert_user(tenant_key, user)
    elif ".department." in event_type:
        if event_type.endswith("deleted_v3"):
            dep_id = str(
                department.get("open_department_id")
                or event.get("open_department_id")
                or event.get("department_id")
                or ""
            )
            if dep_id:
                with _database() as conn:
                    conn.execute(
                        "UPDATE departments SET active=0, deleted_at=?, updated_at=? "
                        "WHERE tenant_key=? AND open_department_id=?",
                        (int(time.time()), int(time.time()), tenant_key, dep_id),
                    )
        elif department:
            upsert_department(tenant_key, department)


def latest_sync_status() -> dict[str, Any] | None:
    with _database() as conn:
        row = conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
