from datetime import date, datetime
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from app.routes.auth import require_login, login_redirect, is_admin, is_office, is_client

router = APIRouter()

def core():
    from app import app as core_app
    return core_app

def ctx(*args, **kwargs):
    return core().ctx(*args, **kwargs)

def rows(*args, **kwargs):
    return core().rows(*args, **kwargs)

def exec_sql(*args, **kwargs):
    return core().exec_sql(*args, **kwargs)

class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)

templates = _TemplatesProxy()

def money(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0

@router.get("/mike", response_class=HTMLResponse)
@router.get("/mike-mode", response_class=HTMLResponse)
@router.get("/command", response_class=HTMLResponse)
def mike_mode(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if is_client(u):
        return RedirectResponse("/client-portal-v2", status_code=303)

    today = date.today().isoformat()

    today_jobs = rows("""
        SELECT *
        FROM poolops2_jobs
        WHERE COALESCE(scheduled_start, date, '') LIKE ?
           OR date=?
        ORDER BY COALESCE(scheduled_start, date, '') ASC, id ASC
        LIMIT 40
    """, (f"{today}%", today))

    reminders = rows("""
        SELECT *
        FROM invisible_office_items
        WHERE status NOT IN ('Complete','Completed','Done','Closed')
        ORDER BY
          CASE priority WHEN 'Emergency' THEN 0 WHEN 'High' THEN 1 ELSE 5 END,
          due_date ASC,
          id DESC
        LIMIT 30
    """)

    client_requests = rows("""
        SELECT *
        FROM invisible_office_items
        WHERE category='Client Service Request'
          AND status NOT IN ('Complete','Completed','Done','Closed')
        ORDER BY id DESC
        LIMIT 10
    """)

    clocked_in = []
    open_invoices = []
    open_balance = 0

    if is_admin(u) or is_office(u):
        clocked_in = rows(
            "SELECT * FROM poolops2_employees WHERE clocked_in=? ORDER BY name",
            (True if core().USE_POSTGRES else 1,)
        )
        open_invoices = rows("""
            SELECT *
            FROM poolops2_invoices
            WHERE status NOT IN ('Paid','Complete','Completed','Closed')
            ORDER BY date DESC, id DESC
            LIMIT 30
        """)
        open_balance = sum(
            money(inv.get("open_balance") if inv.get("open_balance") not in ("", None) else inv.get("amount"))
            for inv in open_invoices
        )

    return templates.TemplateResponse(
        "mike_mode_dashboard.html",
        ctx(
            request,
            today=today,
            today_jobs=today_jobs,
            reminders=reminders,
            client_requests=client_requests,
            clocked_in=clocked_in,
            open_invoices=open_invoices,
            open_balance=open_balance,
        )
    )

@router.post("/mike/quick-note")
def mike_quick_note(request: Request, note: str = Form("")):
    u = require_login(request)
    if not u:
        return login_redirect()
    if is_client(u):
        return RedirectResponse("/client-portal-v2", status_code=303)

    text = (note or "").strip()
    if text:
        exec_sql("""
            INSERT INTO invisible_office_items
            (source, category, title, body, priority, status, created_by, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            "Mike Mode",
            "Quick Thought",
            text[:80],
            text,
            "Normal",
            "Open",
            u.get("name") or u.get("username") or "",
            datetime.now().isoformat(timespec="seconds"),
        ))

    return RedirectResponse("/mike", status_code=303)
