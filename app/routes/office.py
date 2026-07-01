from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from app.routes.auth import (
    require_login,
    login_redirect,
    admin_redirect,
    is_admin,
    is_office,
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


class _TemplatesProxy:
    def __getattr__(self, name):
        return getattr(core().templates, name)


templates = _TemplatesProxy()


def money(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


@router.get("/office", response_class=HTMLResponse)
@router.get("/office-dashboard", response_class=HTMLResponse)
def office_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if not (is_admin(u) or is_office(u)):
        return admin_redirect(u)

    invoices = rows("""
        SELECT *
        FROM poolops2_invoices
        ORDER BY date DESC, id DESC
        LIMIT 200
    """)

    estimates = rows("""
        SELECT *
        FROM poolops2_estimates
        ORDER BY id DESC
        LIMIT 100
    """)

    job_costs = rows("""
        SELECT *
        FROM poolops2_job_costs
        ORDER BY id DESC
        LIMIT 100
    """)

    open_invoices = [
        inv for inv in invoices
        if str(inv.get("status") or "").lower() not in ("paid", "complete", "completed", "closed")
    ]

    paid_invoices = [
        inv for inv in invoices
        if str(inv.get("status") or "").lower() == "paid"
    ]

    total_billed = sum(money(inv.get("amount")) for inv in invoices)
    total_open = sum(
        money(inv.get("open_balance") if inv.get("open_balance") not in ("", None) else inv.get("amount"))
        for inv in open_invoices
    )
    total_paid = sum(money(inv.get("amount")) for inv in paid_invoices)

    draft_estimates = [
        e for e in estimates
        if str(e.get("status") or "").lower() in ("draft", "pending", "")
    ]

    today = date.today().isoformat()

    return templates.TemplateResponse(
        "office_dashboard.html",
        ctx(
            request,
            invoices=invoices,
            open_invoices=open_invoices,
            estimates=estimates,
            draft_estimates=draft_estimates,
            job_costs=job_costs,
            total_billed=total_billed,
            total_open=total_open,
            total_paid=total_paid,
            today=today,
        )
    )
