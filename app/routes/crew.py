from datetime import datetime, date

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.routes.auth import (
    require_login,
    is_admin,
    is_client,
    is_employee,
    login_redirect,
    admin_redirect,
)

router = APIRouter()


def core():
    from app import app as core_app
    return core_app


def ctx(*args, **kwargs):
    return core().ctx(*args, **kwargs)


def rows(*args, **kwargs):
    return core().rows(*args, **kwargs)


def one(*args, **kwargs):
    return core().one(*args, **kwargs)


def exec_sql(*args, **kwargs):
    return core().exec_sql(*args, **kwargs)


def table_columns(*args, **kwargs):
    return core().table_columns(*args, **kwargs)


def jobs_for_user(*args, **kwargs):
    return core().jobs_for_user(*args, **kwargs)


def photos_for_user(*args, **kwargs):
    return core().photos_for_user(*args, **kwargs)


def schedule_date(*args, **kwargs):
    return core().schedule_date(*args, **kwargs)


def _try_exec(*args, **kwargs):
    return core()._try_exec(*args, **kwargs)


def use_postgres():
    return bool(core().USE_POSTGRES)


class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)


templates = _TemplatesProxy()

@router.get("/crew-login", response_class=HTMLResponse)
def crew_login_alias(request: Request):
    return RedirectResponse("/login", status_code=303)


@router.get("/crew-portal", response_class=HTMLResponse)
def crew_portal_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/employee", status_code=303)


@router.get("/employees", response_class=HTMLResponse)
def employees_alias(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/crew", status_code=303)


@router.get("/crew/my-day", response_class=HTMLResponse)
def crew_my_day(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    today = date.today().isoformat()
    job_rows = jobs_for_user(u)

    my_jobs = []
    for j in job_rows:
        jd = schedule_date(j)
        status = str(j.get("status", "") or "").lower()
        if jd == today and status not in ("complete", "completed", "done"):
            my_jobs.append(j)

    return templates.TemplateResponse(
        "crew_my_day.html",
        ctx(request, today=today, my_jobs=my_jobs)
    )

@router.get("/crew", response_class=HTMLResponse)
def crew(request: Request):
    u = require_login(request)
    if not u: return login_redirect()
    if not is_admin(u): return admin_redirect(u)
    employee_rows = rows("""
        SELECT *
        FROM poolops2_employees
        WHERE coalesce(name,'') <> ''
        ORDER BY name
    """)
    return templates.TemplateResponse("crew.html", ctx(request, employees=employee_rows))

@router.post("/crew/new")
def crew_new(request: Request, name: str = Form("New Employee"), role: str = Form("Crew"), phone: str = Form(""), email: str = Form(""), username: str = Form(""), password: str = Form("")):
    u = require_login(request)
    if not is_admin(u): return login_redirect()
    eid = exec_sql("INSERT INTO poolops2_employees (name,role,phone,email,username,password,active) VALUES (?,?,?,?,?,?,?)", (name.strip() or "New Employee", role.strip() or "Crew", phone, email, username or name.strip().lower().replace(" ", "."), password or "1234", True if use_postgres() else 1))
    return RedirectResponse("/crew", status_code=303)

@router.post("/crew/{emp_id}/delete")
def crew_delete(request: Request, emp_id: int):
    u = require_login(request)
    if not is_admin(u): return login_redirect()
    _try_exec("DELETE FROM poolops2_employees WHERE id=?", (emp_id,))
    return RedirectResponse("/crew", status_code=303)

@router.post("/crew/{emp_id}/save")
def crew_save(
    request: Request,
    emp_id: int,
    name: str = Form(""),
    role: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    active: str = Form("1"),
):
    if not is_admin(require_login(request)):
        return login_redirect()

    # Render/Postgres stores active as a real boolean in some deployments,
    # while the old local SQLite build used 1/0. Passing integer 1 into a
    # Postgres boolean column can throw a save error, so normalize it here.
    active_value = str(active).strip().lower() in ("1", "true", "yes", "on", "active")

    # Some live employee tables were created before username/password existed.
    # Update only columns that are actually present so Crew save never crashes
    # from a schema mismatch.
    cols = set(table_columns("poolops2_employees"))
    updates = []
    values = []
    for col, val in [
        ("name", name),
        ("role", role),
        ("phone", phone),
        ("email", email),
        ("username", username),
        ("password", password),
        ("active", active_value),
    ]:
        if col in cols:
            updates.append(f"{col}=?")
            values.append(val)

    if updates:
        values.append(emp_id)
        exec_sql(f"UPDATE poolops2_employees SET {', '.join(updates)} WHERE id=?", tuple(values))

    return RedirectResponse("/crew", status_code=303)



@router.get("/employee", response_class=HTMLResponse)
def employee_portal(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/jarvis", status_code=303)

    employee = None

    if is_employee(u):
        employee = one(
            "SELECT * FROM poolops2_employees WHERE id=?",
            (u.get("id"),)
        )

    return templates.TemplateResponse(
        "employee_portal.html",
        ctx(
            request,
            employee=employee,
            jobs=jobs_for_user(u),
            photos=photos_for_user(u)
        )
    )

@router.post("/employee/profile")
def employee_profile_save(request: Request, name: str = Form(""), phone: str = Form(""), email: str = Form(""), username: str = Form(""), password: str = Form("")):
    u = require_login(request)
    if not u: return login_redirect()
    if not is_employee(u): return admin_redirect(u)
    exec_sql("UPDATE poolops2_employees SET name=?, phone=?, email=?, username=?, password=? WHERE id=?", (name, phone, email, username, password, u.get("id")))
    u.update({"name": name, "username": username})
    request.session["user"] = u
    return RedirectResponse("/employee", status_code=303)
    

@router.post("/employee/clock")
def employee_clock(request: Request, action: str = Form("in"), lat: str = Form(""), lng: str = Form("")):
    u = require_login(request)
    if not u or not is_employee(u):
        return login_redirect()

    now = datetime.now().isoformat(timespec="minutes")
    clocked = action == "in"

    exec_sql(
        "UPDATE poolops2_employees SET clocked_in=?, clock_lat=?, clock_lng=?, clocked_in_at=?, last_seen_at=? WHERE id=?",
        (
            clocked,
            float(lat) if lat else None,
            float(lng) if lng else None,
            now if clocked else "",
            now,
            u.get("id")
        )
    )

    return RedirectResponse("/employee", status_code=303)
