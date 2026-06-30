from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.routes.auth import (
    require_login,
    login_redirect,
    admin_redirect,
    is_admin,
    is_client,
    is_employee,
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


def jobs_for_user(*args, **kwargs):
    return core().jobs_for_user(*args, **kwargs)


def schedule_date(*args, **kwargs):
    return core().schedule_date(*args, **kwargs)


def can_accounting(*args, **kwargs):
    return core().can_accounting(*args, **kwargs)


class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)


templates = _TemplatesProxy()


def is_office_user(user):
    return user and str(user.get("role", "")).lower().strip() == "office"


def _today():
    return date.today()


def _safe_date(raw):
    raw = str(raw or "").strip()
    if not raw:
        return _today().isoformat()
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except Exception:
        return _today().isoformat()


def _date_nav(selected_day):
    d = date.fromisoformat(selected_day)
    return {
        "today": _today().isoformat(),
        "prev": (d - timedelta(days=1)).isoformat(),
        "next": (d + timedelta(days=1)).isoformat(),
        "pretty": d.strftime("%A, %B %d, %Y").replace(" 0", " ") if hasattr(d, "strftime") else selected_day,
    }


def _normalize_crew(value):
    value = str(value or "").strip()
    if not value:
        return "Unassigned"
    return value


def _lane_sort_key(name):
    lower = str(name or "").lower()
    if lower == "office":
        return (0, lower)
    if lower == "unassigned":
        return (99, lower)
    return (10, lower)


def _job_visible_to_user(user, job):
    if is_admin(user) or is_office_user(user):
        return True
    if is_employee(user):
        crew = str(job.get("crew") or "").lower()
        name = str(user.get("name") or "").lower()
        username = str(user.get("username") or "").lower()
        return crew in ("", "unassigned") or (name and name in crew) or (username and username in crew)
    return False


def _jobs_for_day(user, selected_day):
    job_rows = rows("SELECT * FROM poolops2_jobs ORDER BY scheduled_start, date, id")
    visible = []
    for j in job_rows:
        if schedule_date(j) != selected_day:
            continue
        if _job_visible_to_user(user, j):
            visible.append(j)
    return visible


def _office_items_for_day(user, selected_day):
    if not (is_admin(user) or is_office_user(user)):
        return []
    try:
        return rows(
            """
            SELECT *
            FROM invisible_office_items
            WHERE COALESCE(status,'Open') NOT IN ('Done','Complete','Completed')
              AND (
                    due_date=?
                 OR (COALESCE(due_date,'')='' AND category IN ('Billing Note','Client Follow-Up','Material Needed','Schedule Task','General Note'))
              )
            ORDER BY
              CASE priority WHEN 'High' THEN 1 WHEN 'Normal' THEN 2 ELSE 3 END,
              id DESC
            LIMIT 200
            """,
            (selected_day,),
        )
    except Exception:
        return []


def _employees():
    try:
        return rows("SELECT * FROM poolops2_employees WHERE COALESCE(name,'')<>'' ORDER BY name")
    except Exception:
        return []


def _clients():
    try:
        return rows("SELECT * FROM poolops2_clients ORDER BY name")
    except Exception:
        return []


def _build_lanes(user, selected_day):
    lanes = {}

    for job in _jobs_for_day(user, selected_day):
        crew = _normalize_crew(job.get("crew"))
        lanes.setdefault(crew, {"name": crew, "jobs": [], "office_items": []})
        lanes[crew]["jobs"].append(job)

    office_items = _office_items_for_day(user, selected_day)
    if office_items:
        lanes.setdefault("Office", {"name": "Office", "jobs": [], "office_items": []})
        lanes["Office"]["office_items"].extend(office_items)

    if not lanes:
        lanes["Unassigned"] = {"name": "Unassigned", "jobs": [], "office_items": []}

    return [lanes[k] for k in sorted(lanes.keys(), key=_lane_sort_key)]


@router.get("/schedule-board", response_class=HTMLResponse)
def schedule_board(request: Request):
    user = require_login(request)
    if not user:
        return login_redirect()
    if is_client(user):
        return RedirectResponse("/client-portal", status_code=303)

    selected_day = _safe_date(request.query_params.get("date"))
    lanes = _build_lanes(user, selected_day)

    return templates.TemplateResponse(
        "schedule_board.html",
        ctx(
            request,
            selected_day=selected_day,
            nav=_date_nav(selected_day),
            lanes=lanes,
            employees=_employees(),
            clients=_clients(),
            can_edit=(is_admin(user) or is_office_user(user)),
        ),
    )


@router.get("/schedule/board", response_class=HTMLResponse)
def schedule_board_alias(request: Request):
    selected_day = request.query_params.get("date") or _today().isoformat()
    return RedirectResponse(f"/schedule-board?date={selected_day}", status_code=303)


@router.post("/schedule-board/add-job")
def schedule_board_add_job(
    request: Request,
    client: str = Form(""),
    property: str = Form(""),
    address: str = Form(""),
    job_type: str = Form("Work Item"),
    crew: str = Form("Unassigned"),
    scheduled_date: str = Form(""),
    priority: str = Form("Normal"),
    notes: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()
    if not (is_admin(user) or is_office_user(user)):
        return admin_redirect(user)

    selected_day = _safe_date(scheduled_date)

    exec_sql(
        """
        INSERT INTO poolops2_jobs
        (client, property, address, job_type, status, crew, date, scheduled_start, priority, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            client.strip(),
            property.strip(),
            address.strip(),
            job_type.strip() or "Work Item",
            "Scheduled",
            crew.strip() or "Unassigned",
            selected_day,
            selected_day,
            priority.strip() or "Normal",
            notes.strip(),
        ),
    )

    return RedirectResponse(f"/schedule-board?date={selected_day}", status_code=303)


@router.post("/schedule-board/add-office-task")
def schedule_board_add_office_task(
    request: Request,
    title: str = Form("Office Task"),
    body: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    assigned_to: str = Form("Office"),
    due_date: str = Form(""),
    category: str = Form("Schedule Task"),
    priority: str = Form("Normal"),
):
    user = require_login(request)
    if not user:
        return login_redirect()
    if not (is_admin(user) or is_office_user(user)):
        return admin_redirect(user)

    selected_day = _safe_date(due_date)
    exec_sql(
        """
        INSERT INTO invisible_office_items
        (source, category, title, body, client, property, assigned_to, due_date, priority, status, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "Schedule Board",
            category.strip() or "Schedule Task",
            title.strip() or "Office Task",
            body.strip(),
            client.strip(),
            property.strip(),
            assigned_to.strip() or "Office",
            selected_day,
            priority.strip() or "Normal",
            "Open",
            user.get("name") or user.get("username") or "",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return RedirectResponse(f"/schedule-board?date={selected_day}", status_code=303)


@router.post("/schedule-board/jobs/{job_id}/status")
def schedule_board_job_status(
    request: Request,
    job_id: int,
    status: str = Form("Scheduled"),
    selected_day: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()
    if not (is_admin(user) or is_employee(user) or is_office_user(user)):
        return admin_redirect(user)

    job = one("SELECT * FROM poolops2_jobs WHERE id=?", (job_id,))
    if not job or not _job_visible_to_user(user, job):
        return RedirectResponse("/schedule-board", status_code=303)

    exec_sql("UPDATE poolops2_jobs SET status=? WHERE id=?", (status.strip() or "Scheduled", job_id))
    return RedirectResponse(f"/schedule-board?date={_safe_date(selected_day)}", status_code=303)


@router.post("/schedule-board/items/{item_id}/status")
def schedule_board_item_status(
    request: Request,
    item_id: int,
    status: str = Form("Open"),
    selected_day: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()
    if not (is_admin(user) or is_office_user(user)):
        return admin_redirect(user)

    completed_at = datetime.now().isoformat(timespec="seconds") if status in ("Done", "Complete", "Completed") else ""
    try:
        exec_sql("UPDATE invisible_office_items SET status=?, completed_at=? WHERE id=?", (status, completed_at, item_id))
    except Exception:
        exec_sql("UPDATE invisible_office_items SET status=? WHERE id=?", (status, item_id))

    return RedirectResponse(f"/schedule-board?date={_safe_date(selected_day)}", status_code=303)
