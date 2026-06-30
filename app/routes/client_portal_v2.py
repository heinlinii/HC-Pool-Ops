from datetime import datetime, date

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.routes.auth import (
    require_login,
    login_redirect,
    admin_redirect,
    is_admin,
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


def _client_for_user(user, request: Request):
    if not user:
        return None

    # Admin preview by ?client_id=123
    if is_admin(user):
        client_id = request.query_params.get("client_id") or ""
        if client_id:
            return one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
        return one("SELECT * FROM poolops2_clients ORDER BY name LIMIT 1")

    if is_client(user):
        client = one("SELECT * FROM poolops2_clients WHERE id=?", (user.get("id"),))
        if client:
            return client

        username = user.get("username") or ""
        if username:
            client = one(
                "SELECT * FROM poolops2_clients WHERE lower(portal_username)=lower(?)",
                (username,),
            )
            if client:
                return client

        name = user.get("name") or ""
        if name:
            return one(
                "SELECT * FROM poolops2_clients WHERE lower(name)=lower(?)",
                (name,),
            )

    return None


def _money(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _status_open(status):
    return str(status or "").strip().lower() not in ("paid", "complete", "completed", "done", "closed")


def _safe_date(value):
    if not value:
        return ""
    return str(value)[:10]


@router.get("/client-portal-v2", response_class=HTMLResponse)
@router.get("/client-dashboard-v2", response_class=HTMLResponse)
def client_portal_v2(request: Request):
    user = require_login(request)
    if not user:
        return login_redirect()

    if not (is_client(user) or is_admin(user)):
        return admin_redirect(user)

    client = _client_for_user(user, request)
    if not client:
        return templates.TemplateResponse(
            "client_portal_v2.html",
            ctx(request, client=None, error="No client record is linked to this login yet.")
        )

    client_id = client.get("id")
    client_name = client.get("name") or ""

    properties = rows(
        """
        SELECT *
        FROM poolops2_properties
        WHERE client_id=? OR client=?
        ORDER BY address, property_name
        """,
        (client_id, client_name),
    )

    jobs = rows(
        """
        SELECT *
        FROM poolops2_jobs
        WHERE client=?
        ORDER BY COALESCE(scheduled_start, date, '') DESC, id DESC
        LIMIT 100
        """,
        (client_name,),
    )

    today = date.today().isoformat()
    upcoming_jobs = []
    recent_jobs = []

    for job in jobs:
        job_day = _safe_date(job.get("scheduled_start") or job.get("date"))
        status = str(job.get("status") or "").lower()
        if job_day and job_day >= today and status not in ("complete", "completed", "done"):
            upcoming_jobs.append(job)
        else:
            recent_jobs.append(job)

    photos = rows(
        """
        SELECT *
        FROM poolops2_photo_logs
        WHERE client=?
        ORDER BY id DESC
        LIMIT 60
        """,
        (client_name,),
    )

    invoices = rows(
        """
        SELECT *
        FROM poolops2_invoices
        WHERE client=?
        ORDER BY date DESC, id DESC
        LIMIT 100
        """,
        (client_name,),
    )

    open_total = sum(_money(inv.get("open_balance") if inv.get("open_balance") not in ("", None) else inv.get("amount")) for inv in invoices if _status_open(inv.get("status")))
    invoice_total = sum(_money(inv.get("amount")) for inv in invoices)

    equipment_by_property = {}
    for prop in properties:
        pid = prop.get("id")
        equipment_by_property[pid] = rows(
            "SELECT * FROM poolops2_equipment WHERE property_id=? ORDER BY equipment_type, brand, model",
            (pid,),
        )

    requests = rows(
        """
        SELECT *
        FROM invisible_office_items
        WHERE client=?
          AND category='Client Service Request'
        ORDER BY id DESC
        LIMIT 30
        """,
        (client_name,),
    )

    admin_clients = []
    if is_admin(user):
        admin_clients = rows("SELECT id, name FROM poolops2_clients ORDER BY name")

    return templates.TemplateResponse(
        "client_portal_v2.html",
        ctx(
            request,
            client=client,
            properties=properties,
            equipment_by_property=equipment_by_property,
            upcoming_jobs=upcoming_jobs[:20],
            recent_jobs=recent_jobs[:30],
            photos=photos,
            invoices=invoices,
            open_total=open_total,
            invoice_total=invoice_total,
            requests=requests,
            admin_clients=admin_clients,
            today=today,
        )
    )


@router.post("/client-portal-v2/request")
def client_portal_request(
    request: Request,
    property_id: int = Form(0),
    title: str = Form("Service Request"),
    details: str = Form(""),
    priority: str = Form("Normal"),
):
    user = require_login(request)
    if not user:
        return login_redirect()

    if not (is_client(user) or is_admin(user)):
        return admin_redirect(user)

    client = _client_for_user(user, request)
    if not client:
        return RedirectResponse("/client-portal-v2", status_code=303)

    client_name = client.get("name") or ""

    prop = None
    property_name = ""
    if property_id:
        prop = one(
            """
            SELECT *
            FROM poolops2_properties
            WHERE id=? AND (client_id=? OR client=?)
            """,
            (property_id, client.get("id"), client_name),
        )
        if prop:
            property_name = prop.get("property_name") or prop.get("address") or ""

    clean_title = (title or "Service Request").strip() or "Service Request"
    clean_details = (details or "").strip()
    clean_priority = (priority or "Normal").strip() or "Normal"

    body = clean_details or clean_title

    exec_sql(
        """
        INSERT INTO invisible_office_items
        (source, category, title, body, client, property, property_id, priority, status, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "Client Portal",
            "Client Service Request",
            clean_title,
            body,
            client_name,
            property_name,
            property_id or None,
            clean_priority,
            "Open",
            user.get("name") or user.get("username") or client_name,
            datetime.now().isoformat(timespec="seconds"),
        )
    )

    return RedirectResponse("/client-portal-v2", status_code=303)
