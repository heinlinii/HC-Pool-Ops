from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter()


def _core():
    # Lazy import prevents circular import while app.py is still loading.
    from app import app as main
    return main


def _property_can_access(user, prop):
    main = _core()
    if main.is_admin(user):
        return True
    if not prop:
        return False
    if main.is_client(user):
        return main.client_can_access(user, prop.get("client_id"), prop.get("client"))
    if main.is_employee(user):
        return True
    return False


@router.get("/properties", response_class=HTMLResponse)
def properties(request: Request):
    main = _core()
    u = main.require_login(request)
    if not u:
        return main.login_redirect()

    if main.is_employee(u):
        return RedirectResponse("/employee", status_code=303)

    if main.is_client(u):
        property_rows = main.properties_for_user(u)
    elif main.is_admin(u):
        property_rows = main.rows("""
            SELECT *
            FROM poolops2_properties
            ORDER BY id DESC
        """)
    else:
        return main.login_redirect()

    return main.templates.TemplateResponse(
        "properties.html",
        main.ctx(
            request,
            properties=property_rows,
            records=property_rows,
            items=property_rows,
            property_list=property_rows,
        )
    )


@router.get("/properties/new", response_class=HTMLResponse)
def property_new_get(request: Request):
    main = _core()
    u = main.require_login(request)
    if not u:
        return main.login_redirect()
    if not main.is_admin(u):
        return main.admin_redirect(u)
    return RedirectResponse("/properties", status_code=303)


@router.post("/properties/new")
def property_new(
    request: Request,
    client: str = Form(""),
    address: str = Form("New Property"),
):
    main = _core()
    if not main.is_admin(main.require_login(request)):
        return main.login_redirect()

    pid = main.exec_sql(
        "INSERT INTO poolops2_properties (client,address) VALUES (?,?)",
        (client, address),
    )
    return RedirectResponse(f"/properties/{pid}", status_code=303)


@router.get("/properties/{property_id}", response_class=HTMLResponse)
def property_detail(request: Request, property_id: int):
    main = _core()
    u = main.require_login(request)
    if not u:
        return main.login_redirect()

    prop = main.one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop:
        return main.admin_redirect(u)

    if not _property_can_access(u, prop):
        return main.admin_redirect(u)

    photos = main.rows(
        "SELECT * FROM poolops2_photo_logs WHERE property_id=? ORDER BY id DESC",
        (property_id,),
    )
    equip = main.rows(
        "SELECT * FROM poolops2_equipment WHERE property_id=? ORDER BY id DESC",
        (property_id,),
    )
    jobs = main.rows(
        "SELECT * FROM poolops2_jobs WHERE address=? OR property=? ORDER BY id DESC",
        (prop["address"], prop["property_name"]),
    )

    return main.templates.TemplateResponse(
        "property_detail.html",
        main.ctx(request, prop=prop, photos=photos, equipment=equip, jobs=jobs),
    )


@router.post("/properties/{property_id}/save")
async def property_save(
    request: Request,
    property_id: int,
    client: str = Form(""),
    property_name: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    pool_type: str = Form(""),
    pool_size: str = Form(""),
    pool_depth: str = Form(""),
    cover_type: str = Form(""),
    finish_type: str = Form(""),
    pump_model: str = Form(""),
    filter_model: str = Form(""),
    heater_model: str = Form(""),
    sanitizer: str = Form(""),
    automation_system: str = Form(""),
    gate_code: str = Form(""),
    service_plan: str = Form(""),
    pool_notes: str = Form(""),
    equipment_notes: str = Form(""),
    notes: str = Form(""),
    card_image: UploadFile = File(None),
):
    main = _core()
    u = main.require_login(request)
    if not u:
        return main.login_redirect()

    prop = main.one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop or not _property_can_access(u, prop):
        return main.admin_redirect(u)

    url = await main.save_upload(card_image) if main.is_admin(u) else ""

    if main.is_admin(u):
        base = (
            client, property_name, address, city, state, zip_code,
            pool_type, pool_size, pool_depth, cover_type, finish_type,
            pump_model, filter_model, heater_model, sanitizer, automation_system,
            gate_code, service_plan, pool_notes, equipment_notes, notes,
        )
        if url:
            main.exec_sql(
                """
                UPDATE poolops2_properties
                SET client=?, property_name=?, address=?, city=?, state=?, zip_code=?,
                    pool_type=?, pool_size=?, pool_depth=?, cover_type=?, finish_type=?,
                    pump_model=?, filter_model=?, heater_model=?, sanitizer=?, automation_system=?,
                    gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=?, card_image=?
                WHERE id=?
                """,
                base + (url, property_id),
            )
        else:
            main.exec_sql(
                """
                UPDATE poolops2_properties
                SET client=?, property_name=?, address=?, city=?, state=?, zip_code=?,
                    pool_type=?, pool_size=?, pool_depth=?, cover_type=?, finish_type=?,
                    pump_model=?, filter_model=?, heater_model=?, sanitizer=?, automation_system=?,
                    gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=?
                WHERE id=?
                """,
                base + (property_id,),
            )
    else:
        main.exec_sql(
            """
            UPDATE poolops2_properties
            SET property_name=?, address=?, city=?, state=?, zip_code=?, pool_type=?, pool_size=?,
                pool_depth=?, cover_type=?, finish_type=?, pump_model=?, filter_model=?, heater_model=?,
                sanitizer=?, automation_system=?, gate_code=?, service_plan=?, pool_notes=?, equipment_notes=?, notes=?
            WHERE id=?
            """,
            (
                property_name, address, city, state, zip_code, pool_type, pool_size,
                pool_depth, cover_type, finish_type, pump_model, filter_model, heater_model,
                sanitizer, automation_system, gate_code, service_plan, pool_notes, equipment_notes,
                notes, property_id,
            ),
        )

    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@router.post("/properties/{property_id}/photo")
async def property_photo(
    request: Request,
    property_id: int,
    title: str = Form("Property Photo"),
    notes: str = Form(""),
    photo: UploadFile = File(None),
):
    main = _core()
    u = main.require_login(request)
    if not u:
        return main.login_redirect()

    if main.is_client(u):
        return RedirectResponse("/jarvis", status_code=303)

    prop = main.one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    url = await main.save_upload(photo)

    if url and prop:
        main.exec_sql(
            """
            INSERT INTO poolops2_photo_logs
            (property_id,client,photo_type,title,photo_url,date,notes)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                property_id,
                prop.get("client", ""),
                "Property",
                title,
                url,
                main.date.today().isoformat(),
                notes,
            ),
        )

    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@router.post("/properties/{property_id}/equipment")
def property_equipment(
    request: Request,
    property_id: int,
    equipment_type: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    serial: str = Form(""),
    installed_date: str = Form(""),
    notes: str = Form(""),
):
    main = _core()
    if not main.is_admin(main.require_login(request)):
        return main.login_redirect()

    main.exec_sql(
        """
        INSERT INTO poolops2_equipment
        (property_id,equipment_type,brand,model,serial,installed_date,notes)
        VALUES (?,?,?,?,?,?,?)
        """,
        (property_id, equipment_type, brand, model, serial, installed_date, notes),
    )

    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@router.post("/properties/{property_id}/delete")
def property_delete(request: Request, property_id: int):
    main = _core()
    if not main.is_admin(main.require_login(request)):
        return main.login_redirect()

    prop = main.one("SELECT * FROM poolops2_properties WHERE id=?", (property_id,))
    if not prop:
        return RedirectResponse("/properties", status_code=303)

    main._delete_photo_records(
        main.rows("SELECT * FROM poolops2_photo_logs WHERE property_id=?", (property_id,))
    )

    jobs = main.rows(
        "SELECT * FROM poolops2_jobs WHERE address=? OR property=?",
        (prop.get("address", ""), prop.get("property_name", "")),
    )
    for j in jobs:
        jid = j.get("id")
        main._delete_photo_records(
            main.rows("SELECT * FROM poolops2_photo_logs WHERE job_id=?", (jid,))
        )
        main._try_exec("DELETE FROM poolops2_job_costs WHERE job_id=?", (jid,))
        main._try_exec("DELETE FROM poolops2_invoices WHERE job_id=?", (jid,))
        main._try_exec("DELETE FROM poolops2_jobs WHERE id=?", (jid,))

    main._try_exec("DELETE FROM poolops2_equipment WHERE property_id=?", (property_id,))
    main._safe_delete_upload(prop.get("card_image", ""))
    main._try_exec("DELETE FROM poolops2_properties WHERE id=?", (property_id,))

    return RedirectResponse("/properties", status_code=303)
