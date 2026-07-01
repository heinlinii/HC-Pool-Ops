from collections import defaultdict
from datetime import date, datetime, timedelta
import re

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.routes.auth import (
    require_login,
    login_redirect,
    admin_redirect,
    is_admin,
    is_office,
    is_employee,
    is_client,
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


class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)


templates = _TemplatesProxy()


def _safe_date(value):
    if not value:
        return ""
    return str(value)[:10]


def _pretty_date(day_text):
    try:
        d = date.fromisoformat(day_text)
        return d.strftime("%A, %B %d, %Y").replace(" 0", " ")
    except Exception:
        return day_text


def _add_days(day_text, amount):
    try:
        d = date.fromisoformat(day_text)
    except Exception:
        d = date.today()
    return (d + timedelta(days=amount)).isoformat()


def _is_done(status):
    return str(status or "").strip().lower() in ("complete", "completed", "done", "closed")


def _materials_from_text(text):
    text = text or ""
    found = []

    structured = re.search(r"Materials:\s*(.+)", text, flags=re.I)
    if structured:
        chunk = structured.group(1).split("\n", 1)[0]
        found.extend([x.strip(" -•\t") for x in re.split(r",|;|\band\b", chunk) if x.strip(" -•\t")])

    lower = text.lower()
    patterns = [
        r"bring\s+([^\\.\\n]+)",
        r"need\s+([^\\.\\n]+)",
        r"materials?\s*[:\-]\s*([^\\.\\n]+)",
        r"order\s+([^\\.\\n]+)",
        r"pick up\s+([^\\.\\n]+)",
        r"pickup\s+([^\\.\\n]+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, lower, flags=re.I):
            chunk = m.group(1)
            chunk = re.split(r"\bfor\b|\bto\b|\bbefore\b", chunk)[0]
            found.extend([x.strip(" -•\t") for x in re.split(r",|;|\band\b", chunk) if x.strip(" -•\t")])

    clean = []
    seen = set()
    for item in found:
        item = item.strip()
        if not item or len(item) > 80:
            continue
        key = item.lower()
        if key not in seen:
            clean.append(item)
            seen.add(key)
    return clean[:8]


def _property_link_for_job(job):
    address = str(job.get("address") or "").strip()
    property_name = str(job.get("property") or "").strip()
    client = str(job.get("client") or "").strip()

    prop = None
    if address:
        prop = one("SELECT * FROM poolops2_properties WHERE address=? LIMIT 1", (address,))
    if not prop and property_name:
        prop = one("SELECT * FROM poolops2_properties WHERE property_name=? LIMIT 1", (property_name,))
    if not prop and client:
        prop = one("SELECT * FROM poolops2_properties WHERE client=? ORDER BY id LIMIT 1", (client,))

    return prop.get("id") if prop else None


def _normalize_job(job):
    j = dict(job)
    notes = j.get("notes") or ""
    j["schedule_day"] = _safe_date(j.get("scheduled_start") or j.get("date"))
    j["materials"] = _materials_from_text(notes)
    j["property_id"] = _property_link_for_job(j)
    j["is_done"] = _is_done(j.get("status"))
    j["display_time"] = ""
    raw = str(j.get("scheduled_start") or "")
    if "T" in raw and len(raw) >= 16:
        j["display_time"] = raw[11:16]
    return j


def _office_items_for_day(day_text):
    items = rows(
        """
        SELECT *
        FROM invisible_office_items
        WHERE due_date=?
          AND status NOT IN ('Complete', 'Completed', 'Done', 'Closed')
        ORDER BY
          CASE priority
            WHEN 'High' THEN 1
            WHEN 'Emergency' THEN 0
            ELSE 5
          END,
          id DESC
        """,
        (day_text,),
    )

    grouped = defaultdict(list)
    for item in items:
        category = item.get("category") or "Office"
        grouped[category].append(item)
    return dict(grouped)


@router.get("/schedule-board", response_class=HTMLResponse)
def schedule_board(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/client-portal-v2", status_code=303)

    selected_day = request.query_params.get("date") or date.today().isoformat()
    show_done = request.query_params.get("show_done") == "1"

    job_rows = rows(
        """
        SELECT *
        FROM poolops2_jobs
        WHERE COALESCE(scheduled_start, date, '') LIKE ?
           OR date=?
        ORDER BY
          COALESCE(scheduled_start, date, '') ASC,
          id ASC
        """,
        (f"{selected_day}%", selected_day),
    )

    jobs = [_normalize_job(j) for j in job_rows]
    if not show_done:
        jobs = [j for j in jobs if not j["is_done"]]

    lanes = defaultdict(list)
    for job in jobs:
        crew = str(job.get("crew") or "").strip()
        if not crew or crew.lower() == "unassigned":
            lane = "Unassigned"
        else:
            lane = crew
        lanes[lane].append(job)

    lane_order = sorted([k for k in lanes.keys() if k != "Unassigned"])
    if "Unassigned" in lanes:
        lane_order.append("Unassigned")

    employees = rows("SELECT * FROM poolops2_employees WHERE coalesce(name,'') <> '' ORDER BY name")
    office_items = _office_items_for_day(selected_day)

    return templates.TemplateResponse(
        "schedule_board.html",
        ctx(
            request,
            selected_day=selected_day,
            pretty_day=_pretty_date(selected_day),
            prev_day=_add_days(selected_day, -1),
            next_day=_add_days(selected_day, 1),
            lanes=dict(lanes),
            lane_order=lane_order,
            employees=employees,
            office_items=office_items,
            show_done=show_done,
        )
    )


@router.post("/schedule-board/add")
def schedule_board_add(
    request: Request,
    selected_day: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    address: str = Form(""),
    job_type: str = Form("Task"),
    crew: str = Form("Unassigned"),
    priority: str = Form("Normal"),
    notes: str = Form(""),
    materials: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not (is_admin(u) or is_office(u)):
        return admin_redirect(u)

    day = selected_day or date.today().isoformat()
    clean_notes = notes.strip()
    if materials.strip():
        clean_notes = (clean_notes + "\n\n" if clean_notes else "") + f"Materials: {materials.strip()}"

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
            job_type.strip() or "Task",
            "Scheduled",
            crew.strip() or "Unassigned",
            day,
            day,
            priority.strip() or "Normal",
            clean_notes,
        )
    )

    return RedirectResponse(f"/schedule-board?date={day}", status_code=303)


@router.post("/schedule-board/job/{job_id}/status")
def schedule_board_job_status(
    request: Request,
    job_id: int,
    status: str = Form("Scheduled"),
    selected_day: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not (is_admin(u) or is_office(u) or is_employee(u)):
        return admin_redirect(u)

    exec_sql("UPDATE poolops2_jobs SET status=? WHERE id=?", (status, job_id))
    return RedirectResponse(f"/schedule-board?date={selected_day or date.today().isoformat()}", status_code=303)


@router.post("/schedule-board/job/{job_id}/assign")
def schedule_board_job_assign(
    request: Request,
    job_id: int,
    crew: str = Form("Unassigned"),
    selected_day: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not (is_admin(u) or is_office(u)):
        return admin_redirect(u)

    exec_sql("UPDATE poolops2_jobs SET crew=? WHERE id=?", (crew.strip() or "Unassigned", job_id))
    return RedirectResponse(f"/schedule-board?date={selected_day or date.today().isoformat()}", status_code=303)


@router.post("/schedule-board/office/{item_id}/status")
def schedule_board_office_status(
    request: Request,
    item_id: int,
    status: str = Form("Complete"),
    selected_day: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not (is_admin(u) or is_office(u)):
        return admin_redirect(u)

    exec_sql("UPDATE invisible_office_items SET status=? WHERE id=?", (status, item_id))
    return RedirectResponse(f"/schedule-board?date={selected_day or date.today().isoformat()}", status_code=303)
