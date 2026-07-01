from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


def _app_helpers():
    """
    Import app helpers lazily to avoid circular import problems.
    dashboard.py is included near the bottom of app.py after these helpers exist.
    """
    from app.app import (
        templates,
        ctx,
        require_login,
        login_redirect,
        admin_redirect,
        is_admin,
        is_client,
        is_employee,
        rows,
        jobs_for_user,
        schedule_date,
        USE_POSTGRES,
    )

    return {
        "templates": templates,
        "ctx": ctx,
        "require_login": require_login,
        "login_redirect": login_redirect,
        "admin_redirect": admin_redirect,
        "is_admin": is_admin,
        "is_client": is_client,
        "is_employee": is_employee,
        "rows": rows,
        "jobs_for_user": jobs_for_user,
        "schedule_date": schedule_date,
        "USE_POSTGRES": USE_POSTGRES,
    }


def _safe_rows(sql, params=()):
    h = _app_helpers()
    try:
        return h["rows"](sql, params)
    except Exception:
        return []


def _safe_jobs_for_user(user):
    h = _app_helpers()
    try:
        return h["jobs_for_user"](user)
    except Exception:
        return []


def _safe_schedule_date(job):
    h = _app_helpers()
    try:
        return h["schedule_date"](job)
    except Exception:
        val = job.get("scheduled_start") or job.get("date") or ""
        return str(val)[:10] if val else ""


def _open_status_clause():
    return """
        lower(coalesce(status,'')) NOT IN ('complete','completed','done','closed','deleted','archived')
    """


def mike_mode_data(user):
    h = _app_helpers()
    today = date.today().isoformat()

    job_rows = _safe_jobs_for_user(user)

    today_jobs = []
    overdue_jobs = []

    for job in job_rows:
        job_date = _safe_schedule_date(job)
        status = str(job.get("status") or "").lower().strip()

        is_done = status in ("complete", "completed", "done", "closed")

        if job_date == today and not is_done:
            today_jobs.append(job)

        if job_date and job_date < today and not is_done:
            overdue_jobs.append(job)

    clocked_in = []

    if h["is_admin"](user):
        try:
            clocked_value = True if h["USE_POSTGRES"] else 1
            clocked_in = _safe_rows(
                """
                SELECT *
                FROM poolops2_employees
                WHERE clocked_in=?
                ORDER BY name
                """,
                (clocked_value,),
            )
        except Exception:
            clocked_in = []

    client_requests = _safe_rows(
        f"""
        SELECT *
        FROM invisible_office_items
        WHERE category='Client Follow-Up'
          AND {_open_status_clause()}
        ORDER BY
            CASE WHEN lower(priority)='high' THEN 0 ELSE 1 END,
            id DESC
        LIMIT 8
        """
    )

    office_reminders = _safe_rows(
        f"""
        SELECT *
        FROM invisible_office_items
        WHERE category IN ('Material Needed','Billing Note','Schedule Task','Problem Found','Equipment Note','General Note')
          AND {_open_status_clause()}
        ORDER BY
            CASE WHEN lower(priority)='high' THEN 0 ELSE 1 END,
            id DESC
        LIMIT 10
        """
    )

    high_priority = _safe_rows(
        f"""
        SELECT *
        FROM invisible_office_items
        WHERE lower(priority)='high'
          AND {_open_status_clause()}
        ORDER BY id DESC
        LIMIT 5
        """
    )

    billing_notes = _safe_rows(
        f"""
        SELECT *
        FROM invisible_office_items
        WHERE category='Billing Note'
          AND {_open_status_clause()}
        ORDER BY id DESC
        LIMIT 5
        """
    )

    material_needs = _safe_rows(
        f"""
        SELECT *
        FROM invisible_office_items
        WHERE category='Material Needed'
          AND {_open_status_clause()}
        ORDER BY id DESC
        LIMIT 5
        """
    )

    stats = {
        "today_jobs": len(today_jobs),
        "overdue_jobs": len(overdue_jobs),
        "clocked_in": len(clocked_in),
        "client_requests": len(client_requests),
        "office_reminders": len(office_reminders),
        "high_priority": len(high_priority),
        "billing_notes": len(billing_notes),
        "material_needs": len(material_needs),
    }

    return {
        "today": today,
        "today_jobs": today_jobs[:8],
        "overdue_jobs": overdue_jobs[:8],
        "clocked_in": clocked_in,
        "client_requests": client_requests,
        "office_reminders": office_reminders,
        "high_priority": high_priority,
        "billing_notes": billing_notes,
        "material_needs": material_needs,
        "mike_mode_stats": stats,
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_redirect(request: Request):
    h = _app_helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if h["is_employee"](user):
        return RedirectResponse("/employee", status_code=303)

    if h["is_client"](user):
        return RedirectResponse("/client-portal", status_code=303)

    return RedirectResponse("/jarvis", status_code=303)


@router.get("/jarvis", response_class=HTMLResponse)
def jarvis_landing(request: Request):
    h = _app_helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if h["is_client"](user):
        return RedirectResponse("/client-portal", status_code=303)

    data = mike_mode_data(user)

    return h["templates"].TemplateResponse(
        "legacy_command_center.html",
        h["ctx"](request, **data),
    )


@router.get("/jarvis/search", response_class=HTMLResponse)
def jarvis_search_alias(request: Request, q: str = ""):
    h = _app_helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    q = (q or "").strip()

    if q:
        return RedirectResponse(f"/invisible-office/search?q={q}", status_code=303)

    return RedirectResponse("/invisible-office/search", status_code=303)


@router.get("/jarvis-tools", response_class=HTMLResponse)
def jarvis_tools_alias(request: Request):
    h = _app_helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    return RedirectResponse("/ai-systems", status_code=303)


@router.get("/command-center-design", response_class=HTMLResponse)
def command_center_design_alias(request: Request):
    h = _app_helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    return RedirectResponse("/design-studio", status_code=303)


@router.get("/legacy-command-center", response_class=HTMLResponse)
def legacy_command_center_alias(request: Request):
    h = _app_helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    return RedirectResponse("/jarvis", status_code=303)