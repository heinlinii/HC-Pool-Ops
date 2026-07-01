from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter()


def _helpers():
    from app.app import (
        templates,
        ctx,
        require_login,
        login_redirect,
        classify_invisible_office_item,
        save_invisible_office_item,
    )

    return {
        "templates": templates,
        "ctx": ctx,
        "require_login": require_login,
        "login_redirect": login_redirect,
        "classify_invisible_office_item": classify_invisible_office_item,
        "save_invisible_office_item": save_invisible_office_item,
    }


@router.post("/assistant-live/preview", response_class=HTMLResponse)
def assistant_live_preview(
    request: Request,
    message: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    due_date: str = Form(""),
    priority: str = Form(""),
):
    h = _helpers()
    u = h["require_login"](request)

    if not u:
        return h["login_redirect"]()

    raw_message = (message or "").strip()

    if not raw_message:
        return RedirectResponse("/assistant-interview-live", status_code=303)

    preview = h["classify_invisible_office_item"](raw_message)

    if priority.strip():
        preview["priority"] = priority.strip()

    return h["templates"].TemplateResponse(
        "jarvis_approve.html",
        h["ctx"](
            request,
            raw_message=raw_message,
            preview=preview,
            client=client,
            property=property,
            due_date=due_date,
        ),
    )


@router.post("/assistant-live/confirm")
def assistant_live_confirm(
    request: Request,
    category: str = Form("General Note"),
    priority: str = Form("Normal"),
    title: str = Form(""),
    body: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    due_date: str = Form(""),
):
    h = _helpers()
    u = h["require_login"](request)

    if not u:
        return h["login_redirect"]()

    text = (body or "").strip()

    if text:
        h["save_invisible_office_item"](
            request=request,
            body=text,
            source="Assistant Live",
            category=category,
            title=title,
            client=client,
            property=property,
            due_date=due_date,
            priority=priority,
        )

    return RedirectResponse("/invisible-office", status_code=303)