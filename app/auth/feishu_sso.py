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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_bindings ("
        "tenant_key TEXT NOT NULL, open_id TEXT NOT NULL, username TEXT NOT NULL, "
        "role TEXT NOT NULL DEFAULT 'user', display_name TEXT NOT NULL DEFAULT '', "
        "user_id TEXT NOT NULL DEFAULT '', union_id TEXT NOT NULL DEFAULT '', "
        "updated_at INTEGER NOT NULL, PRIMARY KEY (tenant_key, open_id), UNIQUE (username))"
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


def _configured_mapping(open_id: str, tenant_key: str) -> tuple[str, str] | None:
    raw = (settings.FEISHU_ACCOUNT_MAP_JSON or "").strip()
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeishuSSOError("FEISHU_ACCOUNT_MAP_JSON 配置不是有效 JSON") from exc
    value = mapping.get(f"{tenant_key}:{open_id}", mapping.get(open_id))
    if not value:
        return None
    if isinstance(value, str):
        from app.auth.user_manager import get_user_role

        return value, get_user_role(value) or "user"
    if isinstance(value, dict) and value.get("username"):
        role = value.get("role", "user")
        return str(value["username"]), role if role in {"admin", "user"} else "user"
    raise FeishuSSOError("飞书账号映射配置格式错误")


def _new_username(display_name: str, tenant_key: str, open_id: str) -> str:
    safe_name = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", display_name).strip("_")
    safe_name = safe_name[:20] or "user"
    digest = hashlib.sha256(f"{tenant_key}:{open_id}".encode("utf-8")).hexdigest()[:10]
    return f"fs_{safe_name}_{digest}"


def resolve_internal_identity(user_info: dict[str, Any]) -> tuple[str, str]:
    """Return a stable SBAGENT ``(username, role)`` for a Feishu user."""
    open_id = str(user_info.get("open_id") or "")
    tenant_key = str(user_info.get("tenant_key") or "default")
    display_name = str(user_info.get("name") or user_info.get("en_name") or "飞书用户")
    if not open_id:
        raise FeishuSSOError("飞书用户信息中缺少 open_id")

    configured = _configured_mapping(open_id, tenant_key)
    if configured:
        username, role = configured
    else:
        with _database() as conn:
            row = conn.execute(
                "SELECT username, role FROM user_bindings WHERE tenant_key = ? AND open_id = ?",
                (tenant_key, open_id),
            ).fetchone()
        if row:
            username, role = str(row[0]), str(row[1])
        else:
            username, role = _new_username(display_name, tenant_key, open_id), "user"

    with _database() as conn:
        conn.execute(
            "INSERT INTO user_bindings(tenant_key, open_id, username, role, display_name, "
            "user_id, union_id, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_key, open_id) DO UPDATE SET "
            "username=excluded.username, role=excluded.role, display_name=excluded.display_name, "
            "user_id=excluded.user_id, union_id=excluded.union_id, updated_at=excluded.updated_at",
            (
                tenant_key,
                open_id,
                username,
                role,
                display_name,
                str(user_info.get("user_id") or ""),
                str(user_info.get("union_id") or ""),
                int(time.time()),
            ),
        )
    return username, role
