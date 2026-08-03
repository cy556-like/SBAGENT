"""SQM server-to-server SSO and scoped retention management.

SQM authenticates the employee itself, then calls SBAGENT to obtain a short-
lived, one-time browser login URL. No user password is shared between the
systems. A stable SQM ``user_id`` maps to one stable internal username, so the
same employee sees the same chat history on later visits.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import settings


class SQMSSOError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(
        settings.SQM_SSO_ENABLED
        and settings.SQM_SSO_CLIENT_ID
        and settings.SQM_SSO_SHARED_SECRET
        and settings.SQM_SSO_PUBLIC_URL
    )


def _database_path() -> Path:
    return Path(settings.DATA_DIR) / "users" / "sqm_sso.sqlite3"


@contextmanager
def _database():
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_bindings ("
        "user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, "
        "display_name TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
        "last_login_at INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS login_tickets ("
        "ticket_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
        "created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, consumed_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS request_nonces ("
        "nonce TEXT PRIMARY KEY, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)"
    )
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _safe_user_id(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 128:
        raise SQMSSOError("user_id must contain 1-128 characters")
    if any(ord(char) < 32 for char in value):
        raise SQMSSOError("user_id contains invalid control characters")
    return value


def _safe_display_name(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", "", str(value or "")).strip()
    return value[:80] or "SQM user"


def _new_username(user_id: str, display_name: str) -> str:
    safe_name = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", display_name)
    safe_name = safe_name.strip("_")[:20] or "user"
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:10]
    return f"sqm_{safe_name}_{digest}"


def _signature_payload(timestamp: str, nonce: str, raw_body: bytes) -> bytes:
    return timestamp.encode("ascii") + b"\n" + nonce.encode("utf-8") + b"\n" + raw_body


def calculate_signature(timestamp: str, nonce: str, raw_body: bytes) -> str:
    """Return the lowercase HMAC-SHA256 signature used by SQM."""
    return hmac.new(
        settings.SQM_SSO_SHARED_SECRET.encode("utf-8"),
        _signature_payload(timestamp, nonce, raw_body),
        hashlib.sha256,
    ).hexdigest()


def verify_partner_request(
    *, client_id: str, timestamp: str, nonce: str, signature: str, raw_body: bytes
) -> None:
    if not is_enabled():
        raise SQMSSOError("SQM SSO is not fully configured")
    if not hmac.compare_digest(str(client_id), settings.SQM_SSO_CLIENT_ID):
        raise SQMSSOError("invalid SQM client_id")
    try:
        request_time = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise SQMSSOError("invalid SQM timestamp") from exc
    now = int(time.time())
    if abs(now - request_time) > 300:
        raise SQMSSOError("SQM request timestamp has expired")
    if not re.fullmatch(r"[A-Za-z0-9._~-]{16,128}", str(nonce or "")):
        raise SQMSSOError("invalid SQM nonce")
    expected = calculate_signature(str(timestamp), str(nonce), raw_body)
    if not hmac.compare_digest(expected, str(signature or "").lower()):
        raise SQMSSOError("invalid SQM request signature")

    # A signed request can still be replayed. Persist each nonce and accept it
    # only once within the signature time window.
    with _database() as conn:
        conn.execute("DELETE FROM request_nonces WHERE expires_at < ?", (now,))
        try:
            conn.execute(
                "INSERT INTO request_nonces(nonce,created_at,expires_at) VALUES(?,?,?)",
                (nonce, now, now + 600),
            )
        except sqlite3.IntegrityError as exc:
            raise SQMSSOError("SQM request nonce has already been used") from exc


def _resolve_binding(user_id: str, display_name: str) -> tuple[str, str]:
    now = int(time.time())
    with _database() as conn:
        row = conn.execute(
            "SELECT username,active FROM user_bindings WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            if not bool(row[1]):
                raise SQMSSOError("this SQM user has been disabled")
            username = str(row[0])
            conn.execute(
                "UPDATE user_bindings SET display_name=?,updated_at=?,last_login_at=? "
                "WHERE user_id=?",
                (display_name, now, now, user_id),
            )
            return username, "user"

        username = _new_username(user_id, display_name)
        conn.execute(
            "INSERT INTO user_bindings(user_id,username,display_name,active,created_at,"
            "updated_at,last_login_at) VALUES(?,?,?,1,?,?,?)",
            (user_id, username, display_name, now, now, now),
        )
        return username, "user"


def create_login_ticket(user_id: str, display_name: str = "") -> dict[str, Any]:
    user_id = _safe_user_id(user_id)
    display_name = _safe_display_name(display_name)
    # Create the stable binding when the signed server request is received,
    # not from untrusted browser query parameters.
    _resolve_binding(user_id, display_name)
    ticket = secrets.token_urlsafe(48)
    ticket_hash = hashlib.sha256(ticket.encode("ascii")).hexdigest()
    now = int(time.time())
    ttl = max(30, min(int(settings.SQM_SSO_TICKET_EXPIRE_SECONDS), 300))
    with _database() as conn:
        conn.execute("DELETE FROM login_tickets WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO login_tickets(ticket_hash,user_id,created_at,expires_at) "
            "VALUES(?,?,?,?)",
            (ticket_hash, user_id, now, now + ttl),
        )
    public_url = settings.SQM_SSO_PUBLIC_URL.rstrip("/")
    return {
        "success": True,
        "expires_in": ttl,
        "login_url": f"{public_url}/api/v1/auth/sqm/login?ticket={quote(ticket)}",
    }


def consume_login_ticket(ticket: str) -> tuple[str, str]:
    if not ticket or len(ticket) > 256:
        raise SQMSSOError("invalid SQM login ticket")
    ticket_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    now = int(time.time())
    with _database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT user_id,expires_at,consumed_at FROM login_tickets WHERE ticket_hash=?",
            (ticket_hash,),
        ).fetchone()
        if not row or row[2] is not None or int(row[1]) < now:
            raise SQMSSOError("SQM login link is invalid, expired, or already used")
        binding = conn.execute(
            "SELECT username,active FROM user_bindings WHERE user_id=?", (str(row[0]),)
        ).fetchone()
        if not binding or not bool(binding[1]):
            raise SQMSSOError("this SQM user has been disabled")
        conn.execute(
            "UPDATE login_tickets SET consumed_at=? WHERE ticket_hash=? AND consumed_at IS NULL",
            (now, ticket_hash),
        )
        conn.execute(
            "UPDATE user_bindings SET last_login_at=?,updated_at=? WHERE user_id=?",
            (now, now, str(row[0])),
        )
        return str(binding[0]), "user"


def is_username_active(username: str) -> bool:
    if not username:
        return False
    with _database() as conn:
        row = conn.execute(
            "SELECT active FROM user_bindings WHERE username=?", (username,)
        ).fetchone()
    return True if row is None else bool(row[0])


def sqm_usernames() -> set[str]:
    with _database() as conn:
        return {str(row[0]) for row in conn.execute("SELECT username FROM user_bindings")}


def is_sqm_username(username: str) -> bool:
    if not username:
        return False
    with _database() as conn:
        return conn.execute(
            "SELECT 1 FROM user_bindings WHERE username=?", (username,)
        ).fetchone() is not None


def is_sqm_chat_id(chat_id: str) -> bool:
    return any(str(chat_id).startswith(f"{username}_") for username in sqm_usernames())


def cleanup_expired_sqm_data(now: float | None = None) -> dict[str, int]:
    """Delete only SQM chats and their generated/session files after 7 days."""
    now = float(now if now is not None else time.time())
    retention = max(1, int(settings.SQM_SSO_RETENTION_DAYS)) * 86400
    cutoff = now - retention
    result = {"chats": 0, "conversation_files": 0, "export_dirs": 0, "temp_dirs": 0}

    from app.memory.manager import (
        _load_user_chats,
        _save_user_chats,
        clear_session_history,
        flush_user_chats_cache,
    )

    flush_user_chats_cache()
    for username in sqm_usernames():
        chats = _load_user_chats(username)
        expired = [
            chat
            for chat in chats
            if float(chat.get("updated_at") or chat.get("created_at") or 0) < cutoff
        ]
        if not expired:
            continue
        expired_ids = {str(chat.get("chat_id") or "") for chat in expired}
        expired_ids.discard("")
        _save_user_chats(
            username,
            [chat for chat in chats if str(chat.get("chat_id") or "") not in expired_ids],
        )
        result["chats"] += len(expired_ids)
        for chat_id in expired_ids:
            conversation_file = Path(settings.DATA_DIR) / "conversations" / f"{chat_id}.json"
            existed = conversation_file.exists()
            clear_session_history(chat_id)
            if existed:
                result["conversation_files"] += 1
            for key, base in (
                ("export_dirs", Path(settings.DATA_DIR) / "export"),
                ("temp_dirs", Path(settings.DATA_DIR) / "temp"),
            ):
                target = base / chat_id
                if target.is_dir():
                    shutil.rmtree(target)
                    result[key] += 1
    return result
