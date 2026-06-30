from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import date

router = APIRouter()

from app.app import (
    templates,
    ctx,
    rows,
    one,
    exec_sql,
    save_upload,
    _safe_delete_upload,
    _try_exec,
    _delete_photo_records,
    require_login,
    login_redirect,
    admin_redirect,
    is_admin,
    is_client,
    client_can_access,
)


@router.get("/clients", response_class=HTMLResponse)
def clients(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_client(u):
        return RedirectResponse("/client-portal", status_code=303)

    if not is_admin(u):
        return admin_redirect(u)

    client_rows = rows("""
        SELECT *
        FROM poolops2_clients
        ORDER BY name ASC
    """)

    return templates.TemplateResponse(
        "clients.html",
        ctx(
            request,
            clients=client_rows,
            records=client_rows,
            items=client_rows,
            client_list=client_rows,
            q="",
        )
    )


@router.get("/clients/new", response_class=HTMLResponse)
def client_new_get(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)
    return RedirectResponse("/clients", status_code=303)


@router.post("/clients/new")
async def client_new(request: Request, name: str = Form("New Client")):
    if not is_admin(require_login(request)):
        return login_redirect()

    cid = exec_sql(
        "INSERT INTO poolops2_clients (name) VALUES (?)",
        (name.strip() or "New Client",)
    )

    return RedirectResponse(f"/clients/{cid}", status_code=303)


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, client_id: int):
    u = require_login(request)
    if not u:
        return login_redirect()

    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client:
        return admin_redirect(u)

    if not client_can_access(u, client_id, client.get("name", "")):
        return admin_redirect(u)

    props = rows(
        "SELECT * FROM poolops2_properties WHERE client_id=? OR client=? ORDER BY address",
        (client_id, client["name"])
    )
    jobs = rows("SELECT * FROM poolops2_jobs WHERE client=? ORDER BY id DESC", (client["name"],))
    photos = rows("SELECT * FROM poolops2_photo_logs WHERE client=? ORDER BY id DESC", (client["name"],))

    return templates.TemplateResponse(
        "client_detail.html",
        ctx(request, client=client, properties=props, jobs=jobs, photos=photos)
    )


@router.post("/clients/{client_id}/photo")
async def client_photo_upload(
    request: Request,
    client_id: int,
    title: str = Form("Client Photo"),
    notes: str = Form(""),
    photo: UploadFile = File(None),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client or not client_can_access(u, client_id, client.get("name", "")):
        return admin_redirect(u)

    url = await save_upload(photo)

    if url:
        exec_sql(
            """
            INSERT INTO poolops2_photo_logs
            (client, photo_type, title, photo_url, date, notes)
            VALUES (?,?,?,?,?,?)
            """,
            (
                client.get("name", ""),
                "Client",
                title.strip() or "Client Photo",
                url,
                date.today().isoformat(),
                notes,
            )
        )

    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/save")
async def client_save(
    request: Request,
    client_id: int,
    name: str = Form(""),
    contact_name: str = Form(""),
    phone: str = Form(""),
    mobile: str = Form(""),
    email: str = Form(""),
    billing_address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    notes: str = Form(""),
    portal_username: str = Form(""),
    portal_password: str = Form(""),
    card_image: UploadFile = File(None),
):
    u = require_login(request)
    if not u:
        return login_redirect()

    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client or not client_can_access(u, client_id, client.get("name", "")):
        return admin_redirect(u)

    url = await save_upload(card_image) if is_admin(u) else ""

    if is_admin(u):
        if url:
            exec_sql(
                """
                UPDATE poolops2_clients
                SET name=?, contact_name=?, phone=?, mobile=?, email=?, billing_address=?, city=?, state=?, zip_code=?, notes=?, portal_username=?, portal_password=?, card_image=?
                WHERE id=?
                """,
                (name, contact_name, phone, mobile, email, billing_address, city, state, zip_code, notes, portal_username, portal_password, url, client_id)
            )
        else:
            exec_sql(
                """
                UPDATE poolops2_clients
                SET name=?, contact_name=?, phone=?, mobile=?, email=?, billing_address=?, city=?, state=?, zip_code=?, notes=?, portal_username=?, portal_password=?
                WHERE id=?
                """,
                (name, contact_name, phone, mobile, email, billing_address, city, state, zip_code, notes, portal_username, portal_password, client_id)
            )
    else:
        exec_sql(
            """
            UPDATE poolops2_clients
            SET name=?, contact_name=?, phone=?, mobile=?, email=?, billing_address=?, city=?, state=?, zip_code=?, notes=?
            WHERE id=?
            """,
            (name, contact_name, phone, mobile, email, billing_address, city, state, zip_code, notes, client_id)
        )

    return RedirectResponse("/jarvis" if is_client(u) else f"/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/delete")
def client_delete(request: Request, client_id: int):
    if not is_admin(require_login(request)):
        return login_redirect()

    client = one("SELECT * FROM poolops2_clients WHERE id=?", (client_id,))
    if not client:
        return RedirectResponse("/clients", status_code=303)

    client_name = client.get("name", "")
    props = rows(
        "SELECT * FROM poolops2_properties WHERE client_id=? OR client=?",
        (client_id, client_name)
    )
    prop_ids = [p.get("id") for p in props if p.get("id") is not None]

    photo_rows = rows("SELECT * FROM poolops2_photo_logs WHERE client=?", (client_name,))
    for pid in prop_ids:
        photo_rows += rows("SELECT * FROM poolops2_photo_logs WHERE property_id=?", (pid,))

    seen = set()
    unique_photos = []
    for ph in photo_rows:
        if ph.get("id") not in seen:
            seen.add(ph.get("id"))
            unique_photos.append(ph)

    _delete_photo_records(unique_photos)

    jobs = rows("SELECT * FROM poolops2_jobs WHERE client=?", (client_name,))
    for j in jobs:
        jid = j.get("id")
        _try_exec("DELETE FROM poolops2_job_costs WHERE job_id=?", (jid,))
        _try_exec("DELETE FROM poolops2_invoices WHERE job_id=?", (jid,))
        _try_exec("DELETE FROM poolops2_jobs WHERE id=?", (jid,))

    for pid in prop_ids:
        _try_exec("DELETE FROM poolops2_equipment WHERE property_id=?", (pid,))
        _try_exec("DELETE FROM poolops2_properties WHERE id=?", (pid,))

    _safe_delete_upload(client.get("card_image", ""))
    _try_exec("DELETE FROM poolops2_clients WHERE id=?", (client_id,))

    return RedirectResponse("/clients", status_code=303)