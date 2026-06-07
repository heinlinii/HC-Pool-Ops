"""Role and access-control helpers for Core 1.0.
This file intentionally wraps existing session/login behavior instead of replacing it.
"""
from __future__ import annotations


def role_of(user) -> str:
    raw = getattr(user, "role", None) or getattr(user, "user_type", None) or getattr(user, "type", None) or "admin"
    return str(raw).strip().lower()


def is_admin(user) -> bool:
    return role_of(user) in {"admin", "owner", "manager"}


def is_employee(user) -> bool:
    return role_of(user) in {"employee", "crew", "tech", "technician"}


def is_client(user) -> bool:
    return role_of(user) in {"client", "customer"}


def user_client_id(user):
    return getattr(user, "client_id", None) or getattr(user, "linked_client_id", None)


def can_view_client(user, client_id: int) -> bool:
    if is_admin(user):
        return True
    if is_client(user):
        return str(user_client_id(user)) == str(client_id)
    return False


def can_delete(user) -> bool:
    return is_admin(user)
