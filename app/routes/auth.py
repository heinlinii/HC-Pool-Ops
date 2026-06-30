from fastapi import Request
from fastapi.responses import RedirectResponse


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    return current_user(request)


def role_of(user):
    return str((user or {}).get("role", "")).lower().strip()


def is_admin(user):
    return role_of(user) == "admin"


def is_office(user):
    return role_of(user) == "office"


def is_client(user):
    return role_of(user) == "client"


def is_employee(user):
    return role_of(user) in ("employee", "crew")


def login_redirect():
    return RedirectResponse("/login", status_code=303)


def admin_redirect(user):
    if is_client(user):
        return RedirectResponse("/client-portal", status_code=303)
    if is_employee(user):
        return RedirectResponse("/employee", status_code=303)
    if is_office(user):
        return RedirectResponse("/billing", status_code=303)
    return login_redirect()
