from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


def _helpers():
    from app.app import (
        templates,
        ctx,
        require_login,
        login_redirect,
        admin_redirect,
        is_admin,
        rows,
        one,
        exec_sql,
        table_columns,
        USE_POSTGRES,
    )

    return {
        "templates": templates,
        "ctx": ctx,
        "require_login": require_login,
        "login_redirect": login_redirect,
        "admin_redirect": admin_redirect,
        "is_admin": is_admin,
        "rows": rows,
        "one": one,
        "exec_sql": exec_sql,
        "table_columns": table_columns,
        "USE_POSTGRES": USE_POSTGRES,
    }


def active_value(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on", "active")


@router.get("/accounts", response_class=HTMLResponse)
@router.get("/admin/accounts", response_class=HTMLResponse)
@router.get("/login-manager", response_class=HTMLResponse)
def accounts_page(request: Request):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    users = h["rows"]("SELECT * FROM poolops2_users ORDER BY role, username")
    employees = h["rows"]("SELECT * FROM poolops2_employees ORDER BY name")

    return h["templates"].TemplateResponse(
        "accounts.html",
        h["ctx"](
            request,
            users=users,
            employees=employees,
        ),
    )


@router.post("/accounts/users/add")
def accounts_user_add(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    role: str = Form("admin"),
    name: str = Form(""),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    username = username.strip()
    password = password.strip()
    role = role.strip() or "admin"
    name = name.strip() or username

    if username and password:
        h["exec_sql"](
            """
            INSERT INTO poolops2_users
            (username, password, role, name)
            VALUES (?,?,?,?)
            """,
            (username, password, role, name),
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/users/{user_id}/save")
def accounts_user_save(
    request: Request,
    user_id: int,
    username: str = Form(""),
    password: str = Form(""),
    role: str = Form("admin"),
    name: str = Form(""),
    active: str = Form("1"),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    cols = set(h["table_columns"]("poolops2_users"))

    updates = []
    values = []

    for col, val in [
        ("username", username.strip()),
        ("password", password.strip()),
        ("role", role.strip()),
        ("name", name.strip()),
    ]:
        if col in cols:
            updates.append(f"{col}=?")
            values.append(val)

    if "active" in cols:
        updates.append("active=?")
        values.append(active_value(active))

    if updates:
        values.append(user_id)
        h["exec_sql"](
            f"UPDATE poolops2_users SET {', '.join(updates)} WHERE id=?",
            tuple(values),
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/employees/add")
def accounts_employee_add(
    request: Request,
    name: str = Form(""),
    role: str = Form("Crew"),
    phone: str = Form(""),
    email: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    name = name.strip()

    if name:
        h["exec_sql"](
            """
            INSERT INTO poolops2_employees
            (name, role, phone, email, username, password, active)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                name,
                role.strip() or "Crew",
                phone.strip(),
                email.strip(),
                username.strip() or name.lower().replace(" ", "."),
                password.strip() or "1234",
                True if h["USE_POSTGRES"] else 1,
            ),
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/employees/{employee_id}/save")
def accounts_employee_save(
    request: Request,
    employee_id: int,
    name: str = Form(""),
    role: str = Form("Crew"),
    phone: str = Form(""),
    email: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    active: str = Form("1"),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    cols = set(h["table_columns"]("poolops2_employees"))

    updates = []
    values = []

    for col, val in [
        ("name", name.strip()),
        ("role", role.strip()),
        ("phone", phone.strip()),
        ("email", email.strip()),
        ("username", username.strip()),
        ("password", password.strip()),
    ]:
        if col in cols:
            updates.append(f"{col}=?")
            values.append(val)

    if "active" in cols:
        updates.append("active=?")
        values.append(active_value(active))

    if updates:
        values.append(employee_id)
        h["exec_sql"](
            f"UPDATE poolops2_employees SET {', '.join(updates)} WHERE id=?",
            tuple(values),
        )

    return RedirectResponse("/accounts", status_code=303)