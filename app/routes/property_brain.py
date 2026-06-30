from datetime import date, datetime
from math import radians, sin, cos, sqrt, atan2

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


def rows(*args, **kwargs):
    return core().rows(*args, **kwargs)


def one(*args, **kwargs):
    return core().one(*args, **kwargs)


def exec_sql(*args, **kwargs):
    return core().exec_sql(*args, **kwargs)


def ctx(*args, **kwargs):
    return core().ctx(*args, **kwargs)


class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)


templates = _TemplatesProxy()


def role_of(user):
    return str((user or {}).get("role", "")).lower().strip()


def can_see_money(user):
    return is_admin(user) or role_of(user) == "office"


def client_name_for_user(user):
    try:
        return core().client_name_for_user(user)
    except Exception:
        return ""


def client_can_access(user, client_id=None, client_name=""):
    try:
        return core().client_can_access(user, client_id, client_name)
    except Exception:
        if is_admin(user):
            return True
        if not is_client(user):
            return False
        return str(user.get("id")) == str(client_id)


def property_can_access(user, prop):
    try:
        return core().property_can_access(user, prop)
    except Exception:
        if is_admin(user) or is_employee(user) or role_of(user) == "office":
            return True
        if is_client(user) and prop:
            return client_can_access(user, prop.get("client_id"), prop.get("client"))
        return False


def schedule_date(job):
    try:
        return core().schedule_date(job)
    except Exception:
        return str(job.get("scheduled_start") or job.get("date") or "")[:10]


def _today():
    return date.today().isoformat()


def _money(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _text(v):
    return str(v or "").strip()


def _contains_problem(text):
    lower = _text(text).lower()
    words = ["leak", "broken", "failed", "failure", "problem", "issue", "crack", "cracked", "bad", "not working", "trip", "tripped", "corrosion", "drip", "urgent"]
    return any(w in lower for w in words)


def _haversine_miles(lat1, lng1, lat2, lng2):
    r = 3958.7613
    p1 = radians(lat1)
    p2 = radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c


def _nearby_gps_visits(prop):
    lat = prop.get("latitude")
    lng = prop.get("longitude")
    try:
        lat = float(lat)
        lng = float(lng)
    except Exception:
        return []

    points = rows(
        """
        SELECT *
        FROM employee_location_points
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1500
        """
    )

    visits = []
    seen = set()
    for p in points:
        try:
            plat = float(p.get("latitude"))
            plng = float(p.get("longitude"))
        except Exception:
            continue

        distance = _haversine_miles(lat, lng, plat, plng)
        if distance <= 0.12:
            day = str(p.get("created_at") or "")[:10]
            employee = p.get("employee_name") or "Crew"
            key = (day, employee)
            if key in seen:
                continue
            seen.add(key)
            item = dict(p)
            item["distance_miles"] = round(distance, 3)
            item["day"] = day
            item["employee"] = employee
            visits.append(item)

    return visits[:30]


def _invoice_summary(invoices):
    total = sum(_money(i.get("amount")) for i in invoices)
    open_total = sum(_money(i.get("open_balance")) for i in invoices)
    paid = total - open_total
    return {"total": total, "open": open_total, "paid": paid, "count": len(invoices)}


def _build_property_context(request: Request, property_id: int):
    user = require_login(request)
    if not user:
        return None, login_redirect()

    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop or not property_can_access(user, prop):
        return None, admin_redirect(user)

    cname = prop.get("client", "")
    client = None
    if prop.get("client_id"):
        client = one("SELECT * FROM poolops2_clients WHERE id=?", (prop.get("client_id"),))
    if not client and cname:
        client = one("SELECT * FROM poolops2_clients WHERE name=?", (cname,))

    if client and not cname:
        cname = client.get("name", "")

    property_name = prop.get("property_name") or prop.get("address") or ""
    address = prop.get("address") or ""

    jobs = rows(
        """
        SELECT * FROM poolops2_jobs
        WHERE address=? OR property=? OR client=?
        ORDER BY id DESC
        LIMIT 250
        """,
        (address, property_name, cname),
    )

    today = _today()
    upcoming_jobs = []
    completed_jobs = []
    for job in jobs:
        status = _text(job.get("status")).lower()
        jd = schedule_date(job)
        if jd >= today and status not in ("complete", "completed", "done"):
            upcoming_jobs.append(job)
        if status in ("complete", "completed", "done"):
            completed_jobs.append(job)

    photos = rows(
        """
        SELECT * FROM poolops2_photo_logs
        WHERE property_id=? OR client=?
        ORDER BY id DESC
        LIMIT 120
        """,
        (property_id, cname),
    )

    equipment = rows("SELECT * FROM poolops2_equipment WHERE property_id=? ORDER BY id DESC", (property_id,))

    try:
        core().ensure_legacy_schema()
    except Exception:
        pass

    lessons = rows(
        """
        SELECT * FROM hfo_legacy_lessons
        WHERE address=? OR property=? OR client=?
        ORDER BY id DESC
        LIMIT 80
        """,
        (address, property_name, cname),
    )

    field_logs = rows(
        """
        SELECT * FROM field_logs
        WHERE address=? OR property=? OR client=?
        ORDER BY id DESC
        LIMIT 100
        """,
        (address, property_name, cname),
    )

    invisible_items = rows(
        """
        SELECT * FROM invisible_office_items
        WHERE property=? OR client=? OR body LIKE ? OR title LIKE ?
        ORDER BY id DESC
        LIMIT 120
        """,
        (property_name, cname, f"%{address}%", f"%{address}%"),
    )

    invoices = rows(
        """
        SELECT * FROM poolops2_invoices
        WHERE client=? OR description LIKE ? OR notes LIKE ?
        ORDER BY id DESC
        LIMIT 120
        """,
        (cname, f"%{address}%", f"%{address}%"),
    ) if can_see_money(user) else []

    estimates = rows(
        """
        SELECT * FROM poolops2_estimates
        WHERE client=? OR property=? OR notes LIKE ?
        ORDER BY id DESC
        LIMIT 80
        """,
        (cname, property_name, f"%{address}%"),
    ) if can_see_money(user) else []

    gps_visits = _nearby_gps_visits(prop)

    known_problems = []
    for job in jobs:
        combined = " ".join([_text(job.get("job_type")), _text(job.get("notes")), _text(job.get("status"))])
        if _contains_problem(combined):
            known_problems.append({
                "source": "Job",
                "title": job.get("job_type") or "Job issue",
                "date": job.get("date") or job.get("scheduled_start") or "",
                "body": job.get("notes") or "",
                "href": f"/jobs/{job.get('id')}",
            })
    for log in field_logs:
        combined = " ".join([_text(log.get("issues")), _text(log.get("work_completed")), _text(log.get("next_steps"))])
        if _contains_problem(combined):
            known_problems.append({
                "source": "Field Log",
                "title": log.get("issues") or log.get("work_completed") or "Field issue",
                "date": log.get("date") or log.get("created_at") or "",
                "body": combined,
                "href": "/field-logs",
            })
    for lesson in lessons:
        if lesson.get("problem"):
            known_problems.append({
                "source": "Legacy",
                "title": lesson.get("problem") or "Legacy lesson",
                "date": lesson.get("created_at") or "",
                "body": lesson.get("lesson") or lesson.get("fix") or "",
                "href": "/legacy",
            })

    hidden_details = []
    for label, value in [
        ("Gate Code / Access", prop.get("gate_code")),
        ("Service Plan", prop.get("service_plan")),
        ("Pool Notes", prop.get("pool_notes")),
        ("Equipment Notes", prop.get("equipment_notes")),
        ("Property Notes", prop.get("notes")),
    ]:
        if _text(value):
            hidden_details.append({"label": label, "value": value})

    known_pool = any(_text(prop.get(k)) for k in ["pool_type", "pool_size", "pool_depth", "finish_type", "cover_type"])
    known_equipment = bool(equipment) or any(_text(prop.get(k)) for k in ["pump_model", "filter_model", "heater_model", "sanitizer", "automation_system"])
    known_access = bool(_text(prop.get("gate_code")) or _text(prop.get("notes")))

    pool_summary_parts = []
    if prop.get("pool_type"):
        pool_summary_parts.append(f"{prop.get('pool_type')} pool")
    if prop.get("pool_size"):
        pool_summary_parts.append(f"size {prop.get('pool_size')}")
    if prop.get("pool_depth"):
        pool_summary_parts.append(f"depth {prop.get('pool_depth')}")
    if prop.get("pump_model"):
        pool_summary_parts.append(f"pump {prop.get('pump_model')}")
    if prop.get("filter_model"):
        pool_summary_parts.append(f"filter {prop.get('filter_model')}")
    if prop.get("heater_model"):
        pool_summary_parts.append(f"heater {prop.get('heater_model')}")
    pool_summary = "; ".join(pool_summary_parts) if pool_summary_parts else "We do not have enough recorded details yet. Add pool specs, equipment, access notes, photos, and field logs to build this brain."

    brain_summary = {
        "job_count": len(jobs),
        "upcoming_count": len(upcoming_jobs),
        "completed_count": len(completed_jobs),
        "photo_count": len(photos),
        "lesson_count": len(lessons),
        "problem_count": len(known_problems),
        "field_log_count": len(field_logs),
        "invoice_count": len(invoices),
        "estimate_count": len(estimates),
        "gps_visit_count": len(gps_visits),
        "office_item_count": len(invisible_items),
        "known_pool": known_pool,
        "known_equipment": known_equipment,
        "known_access": known_access,
    }

    context = ctx(
        request,
        prop=prop,
        client=client,
        jobs=jobs,
        upcoming_jobs=upcoming_jobs,
        completed_jobs=completed_jobs,
        photos=photos,
        equipment=equipment,
        lessons=lessons,
        field_logs=field_logs,
        invisible_items=invisible_items,
        invoices=invoices,
        estimates=estimates,
        gps_visits=gps_visits,
        known_problems=known_problems[:25],
        hidden_details=hidden_details,
        brain_summary=brain_summary,
        pool_summary=pool_summary,
        invoice_summary=_invoice_summary(invoices),
        can_see_money=can_see_money(user),
    )
    return context, None


@router.get("/property-brain-v2/{property_id}", response_class=HTMLResponse)
@router.get("/properties/{property_id}/brain2", response_class=HTMLResponse)
def property_brain_v2(request: Request, property_id: int):
    context, redirect = _build_property_context(request, property_id)
    if redirect:
        return redirect
    return templates.TemplateResponse("property_brain_v2.html", context)


@router.post("/properties/{property_id}/brain2/save")
def property_brain_v2_save(
    request: Request,
    property_id: int,
    gate_code: str = Form(""),
    service_plan: str = Form(""),
    pool_notes: str = Form(""),
    equipment_notes: str = Form(""),
    notes: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()

    prop = one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop or not property_can_access(user, prop):
        return admin_redirect(user)

    if is_client(user):
        return RedirectResponse(f"/property-brain-v2/{property_id}", status_code=303)

    exec_sql(
        """
        UPDATE poolops2_properties
        SET gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=?
        WHERE id=?
        """,
        (gate_code, service_plan, pool_notes, equipment_notes, notes, property_id),
    )

    return RedirectResponse(f"/property-brain-v2/{property_id}", status_code=303)
