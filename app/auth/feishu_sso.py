"""Feishu OAuth SSO helpers for the SBAGENT web application.

The browser only receives a short-lived OAuth code. App credentials and the
code exchange stay on the server. OAuth state and PKCE verifiers are stored in
SQLite so the flow works with multiple uvicorn workers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import settings
from app.auth.permissions import is_full_kb_admin


AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"


class FeishuSSOError(RuntimeError):
    """A user-safe Feishu SSO failure."""


def is_enabled() -> bool:
    return bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET and settings.FEISHU_REDIRECT_URI)


def _db_path() -> Path:
    return Path(settings.DATA_DIR) / "users" / "feishu_sso.sqlite3"


def _open_db() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS oauth_states ("
        "state TEXT PRIMARY KEY, code_verifier TEXT NOT NULL, next_path TEXT NOT NULL, "
        "expires_at INTEGER NOT NULL)"
    )
    _ensure_binding_schema(conn)
    return conn


def _ensure_binding_schema(conn: sqlite3.Connection) -> None:
    """Migrate the legacy open_id primary key to tenant-scoped user_id.

    Existing usernames are copied unchanged, so chat history and knowledge
    permissions continue to point at the same internal SBAGENT identity.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_bindings'"
    ).fetchone()
    if exists:
        columns = conn.execute("PRAGMA table_info(user_bindings)").fetchall()
        primary = [row[1] for row in sorted((x for x in columns if x[5]), key=lambda x: x[5])]
        if primary != ["tenant_key", "user_id"]:
            conn.execute("ALTER TABLE user_bindings RENAME TO user_bindings_legacy")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_bindings ("
        "tenant_key TEXT NOT NULL, user_id TEXT NOT NULL, username TEXT NOT NULL, "
        "role TEXT NOT NULL DEFAULT 'user', display_name TEXT NOT NULL DEFAULT '', "
        "open_id TEXT NOT NULL DEFAULT '', union_id TEXT NOT NULL DEFAULT '', "
        "active INTEGER NOT NULL DEFAULT 1, deactivated_at INTEGER, "
        "updated_at INTEGER NOT NULL, PRIMARY KEY (tenant_key, user_id), UNIQUE (username))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_binding_aliases ("
        "tenant_key TEXT NOT NULL, id_type TEXT NOT NULL, id_value TEXT NOT NULL, "
        "user_id TEXT NOT NULL, updated_at INTEGER NOT NULL, "
        "PRIMARY KEY (tenant_key, id_type, id_value))"
    )
    legacy = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_bindings_legacy'"
    ).fetchone()
    if legacy:
        now = int(time.time())
        rows = conn.execute(
            "SELECT tenant_key, open_id, username, role, display_name, user_id, union_id, updated_at "
            "FROM user_bindings_legacy"
        ).fetchall()
        for row in rows:
            tenant_key, open_id = str(row[0]), str(row[1])
            stable_id = str(row[5] or "") or _legacy_subject_id(tenant_key, open_id)
            conn.execute(
                "INSERT OR IGNORE INTO user_bindings(tenant_key,user_id,username,role,display_name,"
                "open_id,union_id,active,updated_at) VALUES(?,?,?,?,?,?,?,1,?)",
                (tenant_key, stable_id, row[2], row[3], row[4], open_id, row[6], row[7] or now),
            )
            _upsert_alias(conn, tenant_key, "open_id", open_id, stable_id, now)
            if row[6]:
                _upsert_alias(conn, tenant_key, "union_id", str(row[6]), stable_id, now)
            if row[5]:
                _upsert_alias(conn, tenant_key, "user_id", str(row[5]), stable_id, now)
        conn.execute("DROP TABLE user_bindings_legacy")


def _legacy_subject_id(tenant_key: str, open_id: str) -> str:
    digest = hashlib.sha256(f"{tenant_key}:{open_id}".encode("utf-8")).hexdigest()[:24]
    return f"legacy-open:{digest}"


def _upsert_alias(
    conn: sqlite3.Connection,
    tenant_key: str,
    id_type: str,
    id_value: str,
    user_id: str,
    updated_at: int,
) -> None:
    if not id_value:
        return
    conn.execute(
        "INSERT INTO user_binding_aliases(tenant_key,id_type,id_value,user_id,updated_at) "
        "VALUES(?,?,?,?,?) ON CONFLICT(tenant_key,id_type,id_value) DO UPDATE SET "
        "user_id=excluded.user_id,updated_at=excluded.updated_at",
        (tenant_key, id_type, id_value, user_id, updated_at),
    )


@contextmanager
def _database():
    conn = _open_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _safe_next_path(value: str | None) -> str:
    value = (value or "/").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def with_sso_marker(next_path: str | None) -> str:
    """Return a safe local redirect that tells the frontend to prefer SSO.

    The marker is deliberately attached only to redirects originating from
    the Feishu entry point.  Normal visits to ``/`` therefore keep using the
    existing username/password session stored by the web frontend.
    """
    safe_path = _safe_next_path(next_path)
    parts = urlsplit(safe_path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["feishu_sso"] = "1"
    return urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment))


def create_oauth_request(next_path: str = "/") -> tuple[str, str]:
    """Create a one-time state and PKCE challenge, returning the authorize URL."""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    now = int(time.time())
    with _database() as conn:
        conn.execute("DELETE FROM oauth_states WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO oauth_states(state, code_verifier, next_path, expires_at) VALUES(?, ?, ?, ?)",
            (state, verifier, _safe_next_path(next_path), now + 600),
        )
    query = urlencode(
        {
            "client_id": settings.FEISHU_APP_ID,
            "response_type": "code",
            "redirect_uri": settings.FEISHU_REDIRECT_URI,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return state, f"{AUTHORIZE_URL}?{query}"


def consume_oauth_state(state: str) -> tuple[str, str]:
    """Consume a state exactly once and return ``(verifier, next_path)``."""
    now = int(time.time())
    with _database() as conn:
        row = conn.execute(
            "SELECT code_verifier, next_path, expires_at FROM oauth_states WHERE state = ?",
            (state,),
        ).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    if not row or int(row[2]) < now:
        raise FeishuSSOError("登录请求已失效，请从飞书重新打开速豹应用")
    return str(row[0]), _safe_next_path(str(row[1]))


def _api_data(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if payload.get("code") not in (None, 0):
        message = payload.get("msg") or payload.get("message") or operation
        raise FeishuSSOError(f"{operation}失败：{message}")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


async def exchange_code(code: str, code_verifier: str) -> str:
    import httpx

    body = {
        "grant_type": "authorization_code",
        "client_id": settings.FEISHU_APP_ID,
        "client_secret": settings.FEISHU_APP_SECRET,
        "code": code,
        "redirect_uri": settings.FEISHU_REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(TOKEN_URL, json=body)
            response.raise_for_status()
            data = _api_data(response.json(), "交换飞书授权码")
    except FeishuSSOError:
        raise
    except Exception as exc:
        raise FeishuSSOError("连接飞书认证服务失败") from exc
    token = data.get("access_token") or data.get("user_access_token")
    if not token:
        raise FeishuSSOError("飞书认证响应中缺少用户令牌")
    return str(token)


async def fetch_user_info(user_access_token: str) -> dict[str, Any]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                USER_INFO_URL,
                headers={"Authorization": f"Bearer {user_access_token}"},
            )
            response.raise_for_status()
            data = _api_data(response.json(), "读取飞书用户信息")
    except FeishuSSOError:
        raise
    except Exception as exc:
        raise FeishuSSOError("连接飞书用户服务失败") from exc
    if not data.get("open_id"):
        raise FeishuSSOError("飞书用户信息中缺少 open_id")
    return data


def _configured_mapping(user_id: str, open_id: str, tenant_key: str) -> tuple[str, str] | None:
    raw = (settings.FEISHU_ACCOUNT_MAP_JSON or "").strip()
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuSSOError("FEISHU_ACCOUNT_MAP_JSON 配置不是有效 JSON") from exc
    value = (
        mapping.get(f"{tenant_key}:{user_id}")
        or mapping.get(user_id)
        or mapping.get(f"{tenant_key}:{open_id}")
        or mapping.get(open_id)
    )
    if not value:
        return None
    if isinstance(value, str):
        from app.auth.user_manager import get_user_role

        return value, get_user_role(value) or "user"
    if isinstance(value, dict) and value.get("username"):
        role = value.get("role", "user")
        return str(value["username"]), role if role in {"admin", "user"} else "user"
    raise FeishuSSOError("飞书账号映射配置格式错误")


def _new_username(display_name: str, tenant_key: str, user_id: str) -> str:
    safe_name = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", display_name).strip("_")
    safe_name = safe_name[:20] or "user"
    digest = hashlib.sha256(f"{tenant_key}:{user_id}".encode("utf-8")).hexdigest()[:10]
    return f"fs_{safe_name}_{digest}"


def resolve_internal_identity(user_info: dict[str, Any]) -> tuple[str, str]:
    """Return a stable SBAGENT ``(username, role)`` for a Feishu user."""
    open_id = str(user_info.get("open_id") or "")
    actual_user_id = str(user_info.get("user_id") or "")
    tenant_key = str(user_info.get("tenant_key") or "default")
    display_name = str(user_info.get("name") or user_info.get("en_name") or "飞书用户")
    if not open_id:
        raise FeishuSSOError("飞书用户信息中缺少 open_id")

    try:
        from app.auth.feishu_contacts import contact_active_status

        status = contact_active_status(
            tenant_key, user_id=actual_user_id, open_id=open_id
        )
        if status is False:
            raise FeishuSSOError("该飞书员工已离职或停用，不能登录")
    except FeishuSSOError:
        raise
    except Exception:
        # Before the first contact sync there is no directory row yet.  Keep
        # SSO available and let the next full sync establish the status.
        pass

    subject_id = actual_user_id or _legacy_subject_id(tenant_key, open_id)
    configured = _configured_mapping(actual_user_id, open_id, tenant_key)
    if configured:
        username, role = configured
    else:
        with _database() as conn:
            row = conn.execute(
                "SELECT username, role, user_id FROM user_bindings WHERE tenant_key=? AND user_id=?",
                (tenant_key, subject_id),
            ).fetchone()
            if not row:
                alias = conn.execute(
                    "SELECT user_id FROM user_binding_aliases "
                    "WHERE tenant_key=? AND id_type='open_id' AND id_value=?",
                    (tenant_key, open_id),
                ).fetchone()
                if alias:
                    row = conn.execute(
                        "SELECT username, role, user_id FROM user_bindings "
                        "WHERE tenant_key=? AND user_id=?",
                        (tenant_key, str(alias[0])),
                    ).fetchone()
                    if row and actual_user_id and str(row[2]).startswith("legacy-open:"):
                        old_subject = str(row[2])
                        conn.execute(
                            "UPDATE user_bindings SET user_id=? WHERE tenant_key=? AND user_id=?",
                            (actual_user_id, tenant_key, old_subject),
                        )
                        conn.execute(
                            "UPDATE user_binding_aliases SET user_id=? "
                            "WHERE tenant_key=? AND user_id=?",
                            (actual_user_id, tenant_key, old_subject),
                        )
                        subject_id = actual_user_id
        if row:
            username, role = str(row[0]), str(row[1])
        else:
            username, role = _new_username(display_name, tenant_key, subject_id), "user"

    # Accounts explicitly granted full knowledge-base administration are also
    # administrators for the normal backend authorization checks.  This keeps
    # the role stable across subsequent Feishu SSO logins.
    if is_full_kb_admin(username):
        role = "admin"

    with _database() as conn:
        now = int(time.time())
        conn.execute(
            "INSERT INTO user_bindings(tenant_key, user_id, username, role, display_name, "
            "open_id, union_id, active, deactivated_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, 1, NULL, ?) "
            "ON CONFLICT(tenant_key, user_id) DO UPDATE SET "
            "username=excluded.username, role=excluded.role, display_name=excluded.display_name, "
            "open_id=excluded.open_id, union_id=excluded.union_id, active=1, "
            "deactivated_at=NULL, updated_at=excluded.updated_at",
            (
                tenant_key,
                subject_id,
                username,
                role,
                display_name,
                open_id,
                str(user_info.get("union_id") or ""),
                now,
            ),
        )
        _upsert_alias(conn, tenant_key, "open_id", open_id, subject_id, now)
        _upsert_alias(conn, tenant_key, "user_id", actual_user_id, subject_id, now)
        _upsert_alias(
            conn, tenant_key, "union_id", str(user_info.get("union_id") or ""), subject_id, now
        )
    return username, role


def deactivate_binding(tenant_key: str, *, user_id: str = "", open_id: str = "") -> int:
    """Disable a Feishu-created web identity immediately after offboarding."""
    now = int(time.time())
    with _database() as conn:
        subject = user_id
        if not subject and open_id:
            row = conn.execute(
                "SELECT user_id FROM user_binding_aliases "
                "WHERE tenant_key=? AND id_type='open_id' AND id_value=?",
                (tenant_key, open_id),
            ).fetchone()
            subject = str(row[0]) if row else ""
        if not subject:
            return 0
        cursor = conn.execute(
            "UPDATE user_bindings SET active=0,deactivated_at=?,updated_at=? "
            "WHERE tenant_key=? AND user_id=?",
            (now, now, tenant_key, subject),
        )
        return int(cursor.rowcount)


def is_username_active(username: str) -> bool:
    """Return False only for a known, explicitly disabled Feishu identity."""
    if not username:
        return False
    with _database() as conn:
        row = conn.execute(
            "SELECT active FROM user_bindings WHERE username=?", (username,)
        ).fetchone()
    return True if row is None else bool(row[0])
