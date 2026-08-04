"""Fixed-account SQM demo login and scoped retention.

This is deliberately not per-user SSO.  A protected demo entry URL signs every
visitor into one existing SBAGENT account (``jiangxy`` by default).  The access
key is an independent, rotatable credential and never exposes the account
password or SBAGENT's JWT signing secret.
"""

from __future__ import annotations

import hmac
import shutil
import time
from pathlib import Path

from app.auth.user_manager import get_user_role
from app.config import settings


class SQMDemoLoginError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(
        settings.SQM_DEMO_LOGIN_ENABLED
        and settings.SQM_DEMO_USERNAME.strip()
        and settings.SQM_DEMO_ENTRY_KEY.strip()
    )


def authenticate_demo_entry(entry_key: str) -> tuple[str, str]:
    """Validate the shared demo entry key and resolve the fixed web account."""
    if not is_enabled():
        raise SQMDemoLoginError("SQM demo login is not configured")
    if not hmac.compare_digest(
        str(entry_key or ""), settings.SQM_DEMO_ENTRY_KEY.strip()
    ):
        raise SQMDemoLoginError("invalid SQM demo entry key")

    username = settings.SQM_DEMO_USERNAME.strip()
    role = get_user_role(username)
    if not role:
        raise SQMDemoLoginError("configured SQM demo account does not exist")
    return username, role


def is_demo_username(username: str) -> bool:
    return bool(
        username
        and settings.SQM_DEMO_USERNAME.strip()
        and hmac.compare_digest(str(username), settings.SQM_DEMO_USERNAME.strip())
    )


def is_demo_chat_id(chat_id: str) -> bool:
    username = settings.SQM_DEMO_USERNAME.strip()
    return bool(username and str(chat_id or "").startswith(f"{username}_"))


def cleanup_expired_demo_data(now: float | None = None) -> dict[str, int]:
    """Delete only the fixed demo account's chats and generated files after 7 days."""
    now = float(now if now is not None else time.time())
    retention = max(1, int(settings.SQM_DEMO_RETENTION_DAYS)) * 86400
    cutoff = now - retention
    result = {
        "chats": 0,
        "conversation_files": 0,
        "export_dirs": 0,
        "temp_dirs": 0,
    }

    username = settings.SQM_DEMO_USERNAME.strip()
    if not username:
        return result

    from app.memory.manager import (
        _load_user_chats,
        _save_user_chats,
        clear_session_history,
        flush_user_chats_cache,
    )

    flush_user_chats_cache()
    chats = _load_user_chats(username)
    expired_ids = {
        str(chat.get("chat_id") or "")
        for chat in chats
        if float(chat.get("updated_at") or chat.get("created_at") or 0) < cutoff
    }
    expired_ids.discard("")
    if not expired_ids:
        return result

    _save_user_chats(
        username,
        [chat for chat in chats if str(chat.get("chat_id") or "") not in expired_ids],
    )
    result["chats"] = len(expired_ids)

    for chat_id in expired_ids:
        conversation_file = (
            Path(settings.DATA_DIR) / "conversations" / f"{chat_id}.json"
        )
        existed = conversation_file.exists()
        clear_session_history(chat_id)
        if existed:
            result["conversation_files"] += 1

        for result_key, base in (
            ("export_dirs", Path(settings.DATA_DIR) / "export"),
            ("temp_dirs", Path(settings.DATA_DIR) / "temp"),
        ):
            target = base / chat_id
            if target.is_dir():
                shutil.rmtree(target)
                result[result_key] += 1

    return result
