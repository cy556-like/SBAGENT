"""Centralized account capability checks.

Knowledge-base permissions must be enforced by the backend.  The frontend
only uses the returned capability flag to show or hide controls.
"""

from app.config import settings


DEFAULT_FULL_KB_ADMINS = {"adminsubao"}


def full_kb_admin_usernames() -> set[str]:
    configured = {
        item.strip()
        for item in (settings.FULL_KB_ADMIN_USERNAMES or "").split(",")
        if item.strip()
    }
    return DEFAULT_FULL_KB_ADMINS | configured


def is_full_kb_admin(username: str) -> bool:
    return bool(username and username in full_kb_admin_usernames())
