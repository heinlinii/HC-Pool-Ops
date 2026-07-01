from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter()


def _helpers():
    from app.app import (
        templates,
        ctx,
        require_login,
        login_redirect,
        admin_redirect,
        is_admin,
        one,
        exec_sql,
    )

    return {
        "templates": templates,
        "ctx": ctx,
        "require_login": require_login,
        "login_redirect": login_redirect,
        "admin_redirect": admin_redirect,
        "is_admin": is_admin,
        "one": one,
        "exec_sql": exec_sql,
    }


@router.get("/invisible-office/{item_id}/edit", response_class=HTMLResponse)
def invisible_office_edit_page(request: Request, item_id: int):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    item = h["one"](
        "SELECT * FROM invisible_office_items WHERE id=?",
        (item_id,),
    )

    if not item:
        return RedirectResponse("/invisible-office", status_code=303)

    return h["templates"].TemplateResponse(
        "invisible_office_edit.html",
        h["ctx"](
            request,
            item=item,
        ),
    )


@router.post("/invisible-office/{item_id}/edit")
def invisible_office_edit_save(
    request: Request,
    item_id: int,
    category: str = Form("General Note"),
    title: str = Form(""),
    body: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    job_id: str = Form(""),
    assigned_to: str = Form(""),
    due_date: str = Form(""),
    priority: str = Form("Normal"),
    status: str = Form("Open"),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not h["is_admin"](user):
        return h["admin_redirect"](user)

    existing = h["one"](
        "SELECT * FROM invisible_office_items WHERE id=?",
        (item_id,),
    )

    if not existing:
        return RedirectResponse("/invisible-office", status_code=303)

    clean_job_id = None

    try:
        if str(job_id or "").strip():
            clean_job_id = int(str(job_id).strip())
    except Exception:
        clean_job_id = None

    h["exec_sql"](
        """
        UPDATE invisible_office_items
        SET category=?,
            title=?,
            body=?,
            client=?,
            property=?,
            job_id=?,
            assigned_to=?,
            due_date=?,
            priority=?,
            status=?
        WHERE id=?
        """,
        (
            category.strip() or "General Note",
            title.strip(),
            body.strip(),
            client.strip(),
            property.strip(),
            clean_job_id,
            assigned_to.strip(),
            due_date.strip(),
            priority.strip() or "Normal",
            status.strip() or "Open",
            item_id,
        ),
    )

    return RedirectResponse("/invisible-office", status_code=303)