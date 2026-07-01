from datetime import datetime, date, timedelta
import re

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


class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)


templates = _TemplatesProxy()


def _clean(text):
    return (text or "").strip()


def _today_iso():
    return date.today().isoformat()


def _next_weekday_iso(word):
    days = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }
    target = days.get(str(word or "").lower())
    if target is None:
        return ""
    today = date.today()
    delta = (target - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return (today + timedelta(days=delta)).isoformat()


def guess_due_date(text):
    lower = text.lower()
    if "today" in lower:
        return date.today().isoformat()
    if "tomorrow" in lower:
        return (date.today() + timedelta(days=1)).isoformat()
    for word in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        if word in lower:
            return _next_weekday_iso(word)
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)
    return ""


def guess_category(text):
    lower = text.lower()
    if any(x in lower for x in ["schedule", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "come back", "return"]):
        return "Schedule Task"
    if any(x in lower for x in ["bill", "invoice", "charge", "payment", "quickbooks", "paid", "estimate", "quote"]):
        return "Billing Note"
    if any(x in lower for x in ["material", "materials", "bring", "need", "buy", "order", "pickup", "pick up", "valve", "pipe", "fitting", "sand", "cement", "glue"]):
        return "Material Needed"
    if any(x in lower for x in ["call", "text", "email", "follow up", "follow-up", "reach out"]):
        return "Client Follow-Up"
    if any(x in lower for x in ["problem", "issue", "leak", "broken", "failed", "cracked", "not working", "bad"]):
        return "Problem Found"
    return "General Note"


def guess_priority(text):
    lower = text.lower()
    if any(x in lower for x in ["urgent", "asap", "emergency", "today", "right now", "critical"]):
        return "High"
    return "Normal"


def find_client_match(text):
    clients = rows("SELECT * FROM poolops2_clients ORDER BY name")
    lower = text.lower()
    for c in clients:
        name = str(c.get("name") or "").strip()
        if name and name.lower() in lower:
            return c
    return None


def find_property_match(text, client_name=""):
    props = rows("SELECT * FROM poolops2_properties ORDER BY address")
    lower = text.lower()
    for p in props:
        for field in ["property_name", "address"]:
            value = str(p.get(field) or "").strip()
            if value and value.lower() in lower:
                return p
        if client_name and str(p.get("client") or "").strip().lower() == client_name.lower():
            return p
    return None


def find_employee_match(text):
    employees = rows("SELECT * FROM poolops2_employees ORDER BY name")
    lower = text.lower()
    for e in employees:
        name = str(e.get("name") or "").strip()
        username = str(e.get("username") or "").strip()
        if name and name.lower() in lower:
            return e
        if username and username.lower() in lower:
            return e
    return None


def extract_hours(text):
    lower = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours|hour|hrs|hr)\b", lower)
    if not m:
        return 0
    try:
        return float(m.group(1))
    except Exception:
        return 0


def extract_materials(text):
    lower = text.lower()
    chunks = []
    for pat in [
        r"bring\s+([^\.]+)",
        r"need\s+([^\.]+)",
        r"order\s+([^\.]+)",
        r"pick up\s+([^\.]+)",
        r"pickup\s+([^\.]+)",
        r"materials?\s*[:\-]\s*([^\.]+)",
    ]:
        for m in re.finditer(pat, lower):
            chunk = m.group(1)
            chunk = re.split(r"\bfor\b|\bto\b|\bbefore\b", chunk)[0]
            chunks.extend([x.strip(" -•\t") for x in re.split(r",|;|\band\b", chunk) if x.strip(" -•\t")])
    clean = []
    seen = set()
    for item in chunks:
        if not item or len(item) > 80:
            continue
        if item not in seen:
            clean.append(item)
            seen.add(item)
    return clean[:8]


def should_create_job(text):
    lower = text.lower()
    return any(x in lower for x in [
        "schedule", "come back", "return", "replace", "install", "repair", "open pool",
        "close pool", "winterize", "service", "fix", "do "
    ])


def should_create_billing(text):
    lower = text.lower()
    return any(x in lower for x in ["bill", "invoice", "charge", "labor", "payment", "paid"])


def should_create_material(text):
    lower = text.lower()
    return any(x in lower for x in ["bring", "need", "buy", "order", "pickup", "pick up", "material", "materials"])


def save_invisible_item(request, text, category, title, client="", property_name="", job_id=None, assigned_to="", due_date="", priority="Normal"):
    u = require_login(request) or {}
    exec_sql(
        """
        INSERT INTO invisible_office_items
        (source, category, title, body, client, property, job_id, assigned_to, due_date, priority, status, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "Work Engine",
            category,
            title,
            text,
            client,
            property_name,
            job_id,
            assigned_to,
            due_date,
            priority,
            "Open",
            u.get("name") or u.get("username") or "",
            datetime.now().isoformat(timespec="seconds"),
        )
    )


@router.get("/work-engine", response_class=HTMLResponse)
def work_engine_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/client-portal-v2", status_code=303)

    return templates.TemplateResponse("work_engine.html", ctx(request))


@router.post("/work-engine/handle", response_class=HTMLResponse)
def work_engine_handle(
    request: Request,
    message: str = Form(""),
    approve: str = Form(""),
    create_schedule: str = Form(""),
    create_billing: str = Form(""),
    create_material: str = Form(""),
    create_office: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/client-portal-v2", status_code=303)

    text = _clean(message)
    if not text:
        return RedirectResponse("/work-engine", status_code=303)

    client = find_client_match(text)
    client_name = client.get("name", "") if client else ""

    prop = find_property_match(text, client_name)
    property_name = ""
    address = ""
    if prop:
        property_name = prop.get("property_name") or prop.get("address") or ""
        address = prop.get("address") or ""
        if not client_name:
            client_name = prop.get("client") or ""

    employee = find_employee_match(text)
    assigned_to = employee.get("name", "") if employee else ""

    due_date = guess_due_date(text)
    category = guess_category(text)
    priority = guess_priority(text)
    hours = extract_hours(text)
    materials = extract_materials(text)

    schedule_suggested = should_create_job(text)
    billing_suggested = should_create_billing(text)
    material_suggested = should_create_material(text)
    office_suggested = category in ("Billing Note", "Client Follow-Up", "Material Needed")

    title = text[:80] + ("..." if len(text) > 80 else "")

    if approve != "yes":
        suggestions = {
            "message": text,
            "client": client_name,
            "property": property_name,
            "address": address,
            "assigned_to": assigned_to,
            "due_date": due_date,
            "category": category,
            "priority": priority,
            "hours": hours,
            "materials": materials,
            "schedule_suggested": schedule_suggested,
            "billing_suggested": billing_suggested,
            "material_suggested": material_suggested,
            "office_suggested": office_suggested,
        }
        return templates.TemplateResponse("work_engine.html", ctx(request, suggestions=suggestions))

    job_id = None
    structured_notes = text
    if materials:
        structured_notes += "\n\nMaterials: " + ", ".join(materials)
    if hours:
        structured_notes += f"\nLabor Hours: {hours}"

    if create_schedule == "yes":
        job_id = exec_sql(
            """
            INSERT INTO poolops2_jobs
            (client, property, address, job_type, status, crew, date, scheduled_start, priority, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                client_name,
                property_name,
                address,
                title,
                "Scheduled",
                assigned_to or "Unassigned",
                due_date or _today_iso(),
                due_date or _today_iso(),
                priority,
                structured_notes,
            )
        )

    save_invisible_item(
        request,
        text,
        category,
        title,
        client=client_name,
        property_name=property_name,
        job_id=job_id,
        assigned_to=assigned_to,
        due_date=due_date,
        priority=priority,
    )

    if create_billing == "yes":
        amount = 0
        notes = "Created from Work Engine"
        if hours:
            notes += f" | Labor hours mentioned: {hours}"
        exec_sql(
            """
            INSERT INTO poolops2_invoices
            (job_id, client, description, amount, status, date, notes, open_balance, source)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (job_id, client_name, title, amount, "Draft", _today_iso(), notes, amount, "Work Engine")
        )

    if create_material == "yes":
        save_invisible_item(
            request,
            text,
            "Material Needed",
            "Materials: " + (", ".join(materials) if materials else title),
            client=client_name,
            property_name=property_name,
            job_id=job_id,
            assigned_to=assigned_to,
            due_date=due_date,
            priority=priority,
        )

    if create_office == "yes":
        save_invisible_item(
            request,
            text,
            category if category in ("Billing Note", "Client Follow-Up") else "Office Task",
            title,
            client=client_name,
            property_name=property_name,
            job_id=job_id,
            assigned_to="Office",
            due_date=due_date or _today_iso(),
            priority=priority,
        )

    return RedirectResponse(f"/schedule-board?date={due_date or _today_iso()}", status_code=303)


@router.get("/client-login-help", response_class=HTMLResponse)
def client_login_help(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    clients = rows("SELECT * FROM poolops2_clients ORDER BY name")

    return templates.TemplateResponse("client_login_help.html", ctx(request, clients=clients))


@router.post("/client-login-help/{client_id}/save")
def client_login_save(
    request: Request,
    client_id: int,
    portal_username: str = Form(""),
    portal_password: str = Form(""),
):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    exec_sql(
        """
        UPDATE poolops2_clients
        SET portal_username=?, portal_password=?
        WHERE id=?
        """,
        (portal_username.strip(), portal_password.strip(), client_id)
    )

    return RedirectResponse("/client-login-help", status_code=303)
