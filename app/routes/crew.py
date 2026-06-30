# Add this whole block to the BOTTOM of app/routes/crew.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import Form
def core():
    from app import app as core_app
    return core_app

def rows(*args, **kwargs):
    return core().rows(*args, **kwargs)

def exec_sql(*args, **kwargs):
    return core().exec_sql(*args, **kwargs)

def table_columns(*args, **kwargs):
    return core().table_columns(*args, **kwargs)

def _try_exec(*args, **kwargs):
    return core()._try_exec(*args, **kwargs)

def use_postgres():
    return bool(core().USE_POSTGRES)
from app.routes.auth import (
    require_login,
    login_redirect,
    is_admin,
    admin_redirect,
)

class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)

templates = _TemplatesProxy()

def ctx(*args, **kwargs):
    return core().ctx(*args, **kwargs)

router = APIRouter()

@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    app_users = rows("""
        SELECT id, username, password, role, name, active
        FROM poolops2_users
        ORDER BY id
    """)

    return templates.TemplateResponse(
        "admin_users.html",
        ctx(request, app_users=app_users)
    )


@router.post("/admin/users/new")
def admin_user_new(
    request: Request,
    name: str = Form(""),
    username: str = Form(""),
    password: str = Form("changeme"),
    role: str = Form("crew"),
):
    u = require_login(request)
    if not u or not is_admin(u):
        return login_redirect()

    role = str(role or "crew").strip().lower()
    if role == "employee":
        role = "crew"
    if role not in ("admin", "office", "crew", "client"):
        role = "crew"

    username = username.strip() or name.strip().lower().replace(" ", ".")
    password = password.strip() or "changeme"
    active_value = True if use_postgres() else 1

    exec_sql(
        """
        INSERT INTO poolops2_users
        (username, password, role, name, active)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, password, role, name.strip() or username, active_value)
    )

    if role == "crew":
        existing_emp = rows("SELECT * FROM poolops2_employees WHERE lower(username)=lower(?)", (username,))
        if not existing_emp:
            exec_sql(
                """
                INSERT INTO poolops2_employees
                (name, role, phone, email, username, password, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name.strip() or username, "Crew", "", "", username, password, active_value)
            )

    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/save")
def admin_user_save(
    request: Request,
    user_id: int,
    name: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    role: str = Form("crew"),
    active: str = Form("1"),
):
    u = require_login(request)
    if not u or not is_admin(u):
        return login_redirect()

    role = str(role or "crew").strip().lower()
    if role == "employee":
        role = "crew"
    if role not in ("admin", "office", "crew", "client"):
        role = "crew"

    active_bool = str(active).strip().lower() in ("1", "true", "yes", "on", "active")

    cols = set(table_columns("poolops2_users"))
    updates = []
    values = []

    for col, val in [
        ("name", name),
        ("username", username),
        ("password", password),
        ("role", role),
        ("active", active_bool if use_postgres() else (1 if active_bool else 0)),
    ]:
        if col in cols:
            updates.append(f"{col}=?")
            values.append(val)

    if updates:
        values.append(user_id)
        exec_sql(
            f"UPDATE poolops2_users SET {', '.join(updates)} WHERE id=?",
            tuple(values)
        )

    if role == "crew":
        emp = rows("SELECT * FROM poolops2_employees WHERE lower(username)=lower(?)", (username,))
        if emp:
            exec_sql(
                """
                UPDATE poolops2_employees
                SET name=?, username=?, password=?, active=?
                WHERE id=?
                """,
                (
                    name.strip() or username,
                    username,
                    password,
                    active_bool if use_postgres() else (1 if active_bool else 0),
                    emp[0]["id"],
                )
            )
        else:
            exec_sql(
                """
                INSERT INTO poolops2_employees
                (name, role, phone, email, username, password, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip() or username,
                    "Crew",
                    "",
                    "",
                    username,
                    password,
                    active_bool if use_postgres() else (1 if active_bool else 0),
                )
            )

    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/delete")
def admin_user_delete(request: Request, user_id: int):
    u = require_login(request)
    if not u or not is_admin(u):
        return login_redirect()

    if str(u.get("id")) == str(user_id):
        return RedirectResponse("/admin/users", status_code=303)

    _try_exec("DELETE FROM poolops2_users WHERE id=?", (user_id,))
    return RedirectResponse("/admin/users", status_code=303)
