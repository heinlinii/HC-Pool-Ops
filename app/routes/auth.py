from fastapi import Request
from fastapi.responses import RedirectResponse


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    return current_user(request)


def is_admin(user):
    return user and str(user.get("role", "")).lower() == "admin"


def is_client(user):
    return user and str(user.get("role", "")).lower() == "client"


def is_employee(user):
    return user and str(user.get("role", "")).lower() in ("employee", "crew")


def login_redirect():
    return RedirectResponse("/login", status_code=303)


def admin_redirect(user):
    if is_client(user):
        return RedirectResponse("/client-portal", status_code=303)
    if is_employee(user):
        return RedirectResponse("/employee", status_code=303)
    return login_redirect()
