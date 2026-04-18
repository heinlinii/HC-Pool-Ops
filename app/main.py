import csv
import hashlib
import io
import os
from datetime import date
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote_plus

from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .database import SessionLocal, engine, Base
from .models import (
    Client,
    Property,
    PropertyPhoto,
    BeforeAfterPhoto,
    ActivityLog,
    ServiceStop,
    ScheduleItem,
    Employee,
    ClientRequest,
    User,
)

app = FastAPI(title="PoolOps Pro")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-me"))

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = Path("app/static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def money(value):
    return f"${float(value or 0):,.2f}"


def urlencode(value):
    return quote_plus(str(value or ""))


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def add_property_activity(db: Session, property_id: int, activity_type: str, message: str):
    db.add(
        ActivityLog(
            property_id=property_id,
            activity_type=activity_type,
            message=message,
            created_on=str(date.today()),
        )
    )


templates.env.filters["money"] = money
templates.env.filters["urlencode"] = urlencode


def get_current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return (
        db.query(User)
        .options(joinedload(User.employee))
        .filter(User.id == user_id, User.is_active == True)
        .first()
    )


def require_login(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_roles(request: Request, db: Session, allowed_roles: list[str]):
    user = require_login(request, db)
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Not authorized")
    return user


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .options(joinedload(User.employee))
        .filter(User.username == username.strip(), User.is_active == True)
        .first()
    )

    if not user or not verify_password(password.strip(), user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=400,
        )

    request.session["user_id"] = user.id

    if user.role in ["admin", "office"]:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/field", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def office_dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])

    properties = db.query(Property).filter(Property.is_archived == False).count()
    clients = db.query(Client).filter(Client.is_archived == False).count()
    employees = db.query(Employee).count()
    users = db.query(User).filter(User.is_active == True).count()
    open_requests = db.query(ClientRequest).filter(ClientRequest.status != "closed").count()
    unpaid_stops = db.query(ServiceStop).filter(ServiceStop.paid_status != "paid").count()
    estimates_sent = db.query(Property).filter(
        Property.estimate_status == "sent", Property.is_archived == False
    ).count()
    estimates_approved = db.query(Property).filter(
        Property.estimate_status == "approved", Property.is_archived == False
    ).count()

    upcoming = (
        db.query(ScheduleItem)
        .join(Property)
        .options(
            joinedload(ScheduleItem.property).joinedload(Property.client),
            joinedload(ScheduleItem.employee),
        )
        .filter(Property.is_archived == False)
        .order_by(ScheduleItem.date.asc(), ScheduleItem.start_time.asc(), ScheduleItem.id.asc())
        .limit(8)
        .all()
    )

    recent_stops = (
        db.query(ServiceStop)
        .options(joinedload(ServiceStop.property).joinedload(Property.client))
        .order_by(ServiceStop.id.desc())
        .limit(8)
        .all()
    )

    open_request_list = db.query(ClientRequest).order_by(ClientRequest.id.desc()).limit(8).all()

    return templates.TemplateResponse(
        "office_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "stats": {
                "properties": properties,
                "clients": clients,
                "employees": employees,
                "users": users,
                "open_requests": open_requests,
                "unpaid_stops": unpaid_stops,
                "estimates_sent": estimates_sent,
                "estimates_approved": estimates_approved,
            },
            "upcoming": upcoming,
            "recent_stops": recent_stops,
            "open_request_list": open_request_list,
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    q = q.strip()

    client_results = []
    property_results = []
    request_results = []

    if q:
        client_results = (
            db.query(Client)
            .filter(
                Client.is_archived == False,
                or_(
                    Client.name.ilike(f"%{q}%"),
                    Client.phone.ilike(f"%{q}%"),
                    Client.email.ilike(f"%{q}%"),
                    Client.billing_address.ilike(f"%{q}%"),
                ),
            )
            .order_by(Client.name.asc())
            .all()
        )

        property_results = (
            db.query(Property)
            .options(joinedload(Property.client))
            .join(Client)
            .filter(
                Property.is_archived == False,
                or_(
                    Property.address.ilike(f"%{q}%"),
                    Property.city.ilike(f"%{q}%"),
                    Property.state.ilike(f"%{q}%"),
                    Property.pool_type.ilike(f"%{q}%"),
                    Property.cover_type.ilike(f"%{q}%"),
                    Property.notes.ilike(f"%{q}%"),
                    Client.name.ilike(f"%{q}%"),
                ),
            )
            .order_by(Property.address.asc())
            .all()
        )

        request_results = (
            db.query(ClientRequest)
            .filter(
                or_(
                    ClientRequest.client_name.ilike(f"%{q}%"),
                    ClientRequest.phone.ilike(f"%{q}%"),
                    ClientRequest.address.ilike(f"%{q}%"),
                    ClientRequest.request_type.ilike(f"%{q}%"),
                    ClientRequest.description.ilike(f"%{q}%"),
                )
            )
            .order_by(ClientRequest.id.desc())
            .all()
        )

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "current_user": current_user,
            "q": q,
            "client_results": client_results,
            "property_results": property_results,
            "request_results": request_results,
        },
    )


@app.get("/archived", response_class=HTMLResponse)
def archived_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    archived_clients = db.query(Client).filter(Client.is_archived == True).order_by(Client.name.asc()).all()
    archived_properties = (
        db.query(Property)
        .options(joinedload(Property.client))
        .filter(Property.is_archived == True)
        .order_by(Property.address.asc())
        .all()
    )
    return templates.TemplateResponse(
        "archived.html",
        {
            "request": request,
            "current_user": current_user,
            "archived_clients": archived_clients,
            "archived_properties": archived_properties,
        },
    )


@app.post("/clients/{client_id}/restore")
def client_restore(request: Request, client_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.is_archived = False
    db.commit()
    return RedirectResponse("/archived", status_code=303)


@app.post("/properties/{property_id}/restore")
def property_restore(request: Request, property_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.is_archived = False
    db.commit()
    return RedirectResponse("/archived", status_code=303)


@app.get("/field", response_class=HTMLResponse)
def field_dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    today_string = str(date.today())

    query = (
        db.query(ScheduleItem)
        .join(Property)
        .options(
            joinedload(ScheduleItem.property).joinedload(Property.client),
            joinedload(ScheduleItem.employee),
        )
        .filter(ScheduleItem.date == today_string, Property.is_archived == False)
    )

    if current_user.role == "field" and current_user.employee_id:
        query = query.filter(ScheduleItem.employee_id == current_user.employee_id)

    today_items = query.order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc()).all()

    return templates.TemplateResponse(
        "field_dashboard.html",
        {"request": request, "current_user": current_user, "today_items": today_items, "today_string": today_string},
    )


@app.get("/today", response_class=HTMLResponse)
def today_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    today_string = str(date.today())

    query = (
        db.query(ScheduleItem)
        .join(Property)
        .options(
            joinedload(ScheduleItem.property).joinedload(Property.client),
            joinedload(ScheduleItem.employee),
        )
        .filter(ScheduleItem.date == today_string, Property.is_archived == False)
    )

    if current_user.role == "field" and current_user.employee_id:
        query = query.filter(ScheduleItem.employee_id == current_user.employee_id)

    today_items = query.order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc()).all()

    return templates.TemplateResponse(
        "today.html",
        {"request": request, "current_user": current_user, "today_items": today_items, "today_string": today_string},
    )


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    query = db.query(Client).filter(Client.is_archived == False)

    if q.strip():
        term = q.strip()
        query = query.filter(
            or_(
                Client.name.ilike(f"%{term}%"),
                Client.phone.ilike(f"%{term}%"),
                Client.email.ilike(f"%{term}%"),
                Client.billing_address.ilike(f"%{term}%"),
            )
        )

    clients = query.order_by(Client.name.asc()).all()
    return templates.TemplateResponse(
        "clients.html",
        {"request": request, "current_user": current_user, "clients": clients, "q": q},
    )


@app.get("/clients/new", response_class=HTMLResponse)
def client_new_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    return templates.TemplateResponse("client_new.html", {"request": request, "current_user": current_user})


@app.post("/clients/new")
def client_create(
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    billing_address: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    if not name.strip():
        raise HTTPException(status_code=400, detail="Client name is required")

    client = Client(
        name=name.strip(),
        phone=phone.strip(),
        email=email.strip(),
        billing_address=billing_address.strip(),
        notes=notes.strip(),
    )
    db.add(client)
    db.commit()
    return RedirectResponse("/clients", status_code=303)


@app.get("/clients/{client_id}/edit", response_class=HTMLResponse)
def client_edit_form(request: Request, client_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return templates.TemplateResponse("client_edit.html", {"request": request, "current_user": current_user, "client": client})


@app.post("/clients/{client_id}/edit")
def client_edit_submit(
    request: Request,
    client_id: int,
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    billing_address: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.name = name.strip()
    client.phone = phone.strip()
    client.email = email.strip()
    client.billing_address = billing_address.strip()
    client.notes = notes.strip()
    db.commit()
    return RedirectResponse("/clients", status_code=303)


@app.post("/clients/{client_id}/archive")
def client_archive(request: Request, client_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.is_archived = True
    db.commit()
    return RedirectResponse("/clients", status_code=303)


@app.post("/clients/{client_id}/delete")
def client_delete(request: Request, client_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
    return RedirectResponse("/clients", status_code=303)


@app.get("/clients/import", response_class=HTMLResponse)
def clients_import_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    return templates.TemplateResponse(
        "clients_import.html",
        {"request": request, "current_user": current_user, "imported_count": None, "skipped_count": None, "preview_headers": []},
    )


@app.post("/clients/import", response_class=HTMLResponse)
async def clients_import_submit(
    request: Request,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    current_user = require_roles(request, db, ["admin", "office"])

    if not file or not file.filename:
        return templates.TemplateResponse(
            "clients_import.html",
            {
                "request": request,
                "current_user": current_user,
                "imported_count": 0,
                "skipped_count": 0,
                "preview_headers": [],
                "message": "Please choose a CSV file.",
            },
            status_code=400,
        )

    content = await file.read()
    decoded = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(decoded))

    headers = reader.fieldnames or []
    imported_count = 0
    skipped_count = 0

    for row in reader:
        name = (row.get("name") or row.get("Name") or row.get("Customer") or row.get("Customer Name") or "").strip()
        phone = (row.get("phone") or row.get("Phone") or row.get("Main Phone") or row.get("Mobile") or "").strip()
        email = (row.get("email") or row.get("Email") or row.get("Main Email") or "").strip()
        billing_address = (
            row.get("billing_address")
            or row.get("Billing Address")
            or row.get("Address")
            or row.get("Bill Address")
            or ""
        ).strip()
        notes = (row.get("notes") or row.get("Notes") or "").strip()

        if not name:
            skipped_count += 1
            continue

        existing = db.query(Client).filter(Client.is_archived == False, Client.name == name, Client.phone == phone).first()

        if not existing and email:
            existing = db.query(Client).filter(Client.is_archived == False, Client.email == email).first()

        if existing:
            skipped_count += 1
            continue

        db.add(
            Client(
                name=name,
                phone=phone,
                email=email,
                billing_address=billing_address,
                notes=notes,
            )
        )
        imported_count += 1

    db.commit()

    return templates.TemplateResponse(
        "clients_import.html",
        {
            "request": request,
            "current_user": current_user,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "preview_headers": headers,
            "message": "Import completed.",
        },
    )


@app.get("/properties", response_class=HTMLResponse)
def properties_page(
    request: Request,
    q: str = "",
    estimate_status: str = "",
    db: Session = Depends(get_db),
):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    query = (
        db.query(Property)
        .options(joinedload(Property.client))
        .join(Client)
        .filter(Property.is_archived == False)
    )

    if q.strip():
        term = q.strip()
        query = query.filter(
            or_(
                Property.address.ilike(f"%{term}%"),
                Property.city.ilike(f"%{term}%"),
                Property.state.ilike(f"%{term}%"),
                Property.pool_type.ilike(f"%{term}%"),
                Property.cover_type.ilike(f"%{term}%"),
                Property.notes.ilike(f"%{term}%"),
                Client.name.ilike(f"%{term}%"),
            )
        )

    if estimate_status.strip():
        query = query.filter(Property.estimate_status == estimate_status.strip())

    properties = query.order_by(Property.id.desc()).all()
    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "current_user": current_user,
            "properties": properties,
            "q": q,
            "estimate_status": estimate_status,
        },
    )


@app.get("/properties/new", response_class=HTMLResponse)
def new_property(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    clients = db.query(Client).filter(Client.is_archived == False).order_by(Client.name.asc()).all()
    return templates.TemplateResponse("property_new.html", {"request": request, "current_user": current_user, "clients": clients})


@app.post("/properties/new")
def create_property(
    request: Request,
    client_id: str = Form(""),
    client_name: str = Form(""),
    client_phone: str = Form(""),
    client_email: str = Form(""),
    billing_address: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    pool_type: str = Form(""),
    cover_type: str = Form(""),
    gate_code: str = Form(""),
    install_year: str = Form(""),
    estimate_status: str = Form("none"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    if not address.strip():
        raise HTTPException(status_code=400, detail="Property address is required")

    selected_client = None

    if client_id.strip():
        selected_client = db.query(Client).filter(Client.id == int(client_id)).first()

    if not selected_client:
        if not client_name.strip():
            raise HTTPException(status_code=400, detail="Client name is required if no existing client is selected")

        selected_client = Client(
            name=client_name.strip(),
            phone=client_phone.strip(),
            email=client_email.strip(),
            billing_address=billing_address.strip(),
        )
        db.add(selected_client)
        db.commit()
        db.refresh(selected_client)

    prop = Property(
        address=address.strip(),
        city=city.strip(),
        state=state.strip(),
        zip_code=zip_code.strip(),
        pool_type=pool_type.strip(),
        cover_type=cover_type.strip(),
        gate_code=gate_code.strip(),
        install_year=install_year.strip(),
        estimate_status=estimate_status.strip() or "none",
        notes=notes.strip(),
        client_id=selected_client.id,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)

    add_property_activity(db, prop.id, "property_created", "Property created.")
    db.commit()

    return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


@app.get("/properties/{property_id}/edit", response_class=HTMLResponse)
def property_edit_form(request: Request, property_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    prop = db.query(Property).options(joinedload(Property.client)).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    clients = db.query(Client).filter(Client.is_archived == False).order_by(Client.name.asc()).all()
    return templates.TemplateResponse(
        "property_edit.html",
        {"request": request, "current_user": current_user, "property": prop, "clients": clients},
    )


@app.post("/properties/{property_id}/edit")
def property_edit_submit(
    request: Request,
    property_id: int,
    client_id: int = Form(...),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    pool_type: str = Form(""),
    cover_type: str = Form(""),
    gate_code: str = Form(""),
    install_year: str = Form(""),
    estimate_status: str = Form("none"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    prop.client_id = client_id
    prop.address = address.strip()
    prop.city = city.strip()
    prop.state = state.strip()
    prop.zip_code = zip_code.strip()
    prop.pool_type = pool_type.strip()
    prop.cover_type = cover_type.strip()
    prop.gate_code = gate_code.strip()
    prop.install_year = install_year.strip()
    prop.estimate_status = estimate_status.strip() or "none"
    prop.notes = notes.strip()
    add_property_activity(db, prop.id, "property_updated", "Property details updated.")
    db.commit()

    return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


@app.post("/properties/{property_id}/archive")
def property_archive(request: Request, property_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.is_archived = True
    db.commit()
    return RedirectResponse("/properties", status_code=303)


@app.post("/properties/{property_id}/delete")
def property_delete(request: Request, property_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    db.delete(prop)
    db.commit()
    return RedirectResponse("/properties", status_code=303)


@app.get("/properties/import", response_class=HTMLResponse)
def properties_import_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    clients = db.query(Client).filter(Client.is_archived == False).order_by(Client.name.asc()).all()
    return templates.TemplateResponse(
        "properties_import.html",
        {"request": request, "current_user": current_user, "clients": clients, "message": "", "imported_count": None, "skipped_count": None},
    )


@app.post("/properties/import", response_class=HTMLResponse)
async def properties_import_submit(
    request: Request,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    current_user = require_roles(request, db, ["admin", "office"])

    if not file or not file.filename:
        return templates.TemplateResponse(
            "properties_import.html",
            {"request": request, "current_user": current_user, "clients": [], "message": "Please choose a CSV file.", "imported_count": 0, "skipped_count": 0},
            status_code=400,
        )

    content = await file.read()
    decoded = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(decoded))

    imported_count = 0
    skipped_count = 0

    for row in reader:
        client_name = (row.get("client_name") or row.get("Client") or row.get("Client Name") or "").strip()
        address = (row.get("address") or row.get("Address") or "").strip()
        city = (row.get("city") or row.get("City") or "").strip()
        state = (row.get("state") or row.get("State") or "").strip()
        zip_code = (row.get("zip_code") or row.get("ZIP") or row.get("Zip") or "").strip()
        pool_type = (row.get("pool_type") or row.get("Pool Type") or "").strip()
        cover_type = (row.get("cover_type") or row.get("Cover Type") or "").strip()
        gate_code = (row.get("gate_code") or row.get("Gate Code") or "").strip()
        install_year = (row.get("install_year") or row.get("Install Year") or "").strip()
        notes = (row.get("notes") or row.get("Notes") or "").strip()

        if not client_name or not address:
            skipped_count += 1
            continue

        client = db.query(Client).filter(Client.is_archived == False, Client.name == client_name).first()
        if not client:
            skipped_count += 1
            continue

        existing = db.query(Property).filter(Property.client_id == client.id, Property.address == address, Property.is_archived == False).first()
        if existing:
            skipped_count += 1
            continue

        new_prop = Property(
            client_id=client.id,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            pool_type=pool_type,
            cover_type=cover_type,
            gate_code=gate_code,
            install_year=install_year,
            notes=notes,
            estimate_status="none",
        )
        db.add(new_prop)
        db.flush()
        add_property_activity(db, new_prop.id, "property_imported", "Property imported from CSV.")
        imported_count += 1

    db.commit()

    clients = db.query(Client).filter(Client.is_archived == False).order_by(Client.name.asc()).all()
    return templates.TemplateResponse(
        "properties_import.html",
        {
            "request": request,
            "current_user": current_user,
            "clients": clients,
            "message": "Property import completed.",
            "imported_count": imported_count,
            "skipped_count": skipped_count,
        },
    )


@app.post("/properties/{property_id}/estimate-status")
def update_estimate_status(
    request: Request,
    property_id: int,
    estimate_status: str = Form("none"),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    prop.estimate_status = estimate_status.strip() or "none"
    add_property_activity(db, prop.id, "estimate_status", f"Estimate status changed to {prop.estimate_status}.")
    db.commit()
    return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


@app.get("/properties/{property_id}", response_class=HTMLResponse)
def property_detail(request: Request, property_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    prop = (
        db.query(Property)
        .options(
            joinedload(Property.client),
            joinedload(Property.service_stops),
            joinedload(Property.schedule_items).joinedload(ScheduleItem.employee),
            joinedload(Property.photos),
            joinedload(Property.activities),
            joinedload(Property.before_after_photos),
        )
        .filter(Property.id == property_id)
        .first()
    )

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    activities = sorted(prop.activities, key=lambda x: x.id, reverse=True)

    return templates.TemplateResponse(
        "property_detail.html",
        {"request": request, "current_user": current_user, "property": prop, "activities": activities},
    )


@app.post("/properties/{property_id}/photos")
async def property_photo_upload(
    request: Request,
    property_id: int,
    caption: str = Form(""),
    photo: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office", "field"])

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if not photo or not photo.filename:
        raise HTTPException(status_code=400, detail="Photo is required")

    ext = Path(photo.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="Photo must be jpg, jpeg, png, or webp")

    filename = f"{uuid4().hex}{ext}"
    output_path = UPLOAD_DIR / filename
    content = await photo.read()
    output_path.write_bytes(content)

    db.add(
        PropertyPhoto(
            property_id=prop.id,
            image_path=f"/static/uploads/{filename}",
            caption=caption.strip(),
            uploaded_on=str(date.today()),
        )
    )
    add_property_activity(db, prop.id, "photo_uploaded", f"Property photo uploaded. {caption.strip()}".strip())
    db.commit()

    return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


@app.get("/before-after", response_class=HTMLResponse)
def before_after_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    properties = (
        db.query(Property)
        .options(joinedload(Property.client))
        .filter(Property.is_archived == False)
        .order_by(Property.address.asc())
        .all()
    )
    photos = (
        db.query(BeforeAfterPhoto)
        .options(joinedload(BeforeAfterPhoto.property).joinedload(Property.client))
        .order_by(BeforeAfterPhoto.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "before_after.html",
        {
            "request": request,
            "current_user": current_user,
            "properties": properties,
            "photos": photos,
        },
    )


@app.post("/before-after/upload")
async def before_after_upload(
    request: Request,
    property_id: int = Form(...),
    photo_type: str = Form("before"),
    label: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office", "field"])

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if not photo or not photo.filename:
        raise HTTPException(status_code=400, detail="Photo is required")

    ext = Path(photo.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="Photo must be jpg, jpeg, png, or webp")

    filename = f"{uuid4().hex}{ext}"
    output_path = UPLOAD_DIR / filename
    content = await photo.read()
    output_path.write_bytes(content)

    item = BeforeAfterPhoto(
        property_id=property_id,
        image_path=f"/static/uploads/{filename}",
        photo_type=photo_type.strip() or "before",
        label=label.strip(),
        notes=notes.strip(),
        uploaded_on=str(date.today()),
    )
    db.add(item)
    add_property_activity(db, property_id, "before_after_photo", f"{item.photo_type.title()} photo uploaded.")
    db.commit()

    return RedirectResponse("/before-after", status_code=303)


@app.get("/before-after/{photo_id}/edit", response_class=HTMLResponse)
def before_after_edit_form(request: Request, photo_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    item = (
        db.query(BeforeAfterPhoto)
        .options(joinedload(BeforeAfterPhoto.property).joinedload(Property.client))
        .filter(BeforeAfterPhoto.id == photo_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Photo not found")

    return templates.TemplateResponse(
        "before_after_edit.html",
        {"request": request, "current_user": current_user, "item": item},
    )


@app.post("/before-after/{photo_id}/edit")
def before_after_edit_submit(
    request: Request,
    photo_id: int,
    photo_type: str = Form("before"),
    label: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office", "field"])
    item = db.query(BeforeAfterPhoto).filter(BeforeAfterPhoto.id == photo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Photo not found")

    item.photo_type = photo_type.strip() or "before"
    item.label = label.strip()
    item.notes = notes.strip()
    db.commit()

    return RedirectResponse("/before-after", status_code=303)


@app.post("/before-after/{photo_id}/delete")
def before_after_delete(request: Request, photo_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office", "field"])
    item = db.query(BeforeAfterPhoto).filter(BeforeAfterPhoto.id == photo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Photo not found")

    db.delete(item)
    db.commit()
    return RedirectResponse("/before-after", status_code=303)


@app.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    employees = db.query(Employee).order_by(Employee.name.asc()).all()
    return templates.TemplateResponse("employees.html", {"request": request, "current_user": current_user, "employees": employees})


@app.get("/employees/new", response_class=HTMLResponse)
def employee_new_form(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    return templates.TemplateResponse("employee_new.html", {"request": request, "current_user": current_user})


@app.post("/employees/new")
def employee_create(
    request: Request,
    name: str = Form(""),
    role: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    status: str = Form("active"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    if not name.strip():
        raise HTTPException(status_code=400, detail="Employee name is required")

    employee = Employee(
        name=name.strip(),
        role=role.strip(),
        phone=phone.strip(),
        email=email.strip(),
        status=status.strip() or "active",
        notes=notes.strip(),
    )
    db.add(employee)
    db.commit()
    return RedirectResponse("/employees", status_code=303)


@app.get("/employees/{employee_id}/edit", response_class=HTMLResponse)
def employee_edit_form(request: Request, employee_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return templates.TemplateResponse("employee_edit.html", {"request": request, "current_user": current_user, "employee": employee})


@app.post("/employees/{employee_id}/edit")
def employee_edit_submit(
    request: Request,
    employee_id: int,
    name: str = Form(""),
    role: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    status: str = Form("active"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    employee.name = name.strip()
    employee.role = role.strip()
    employee.phone = phone.strip()
    employee.email = email.strip()
    employee.status = status.strip()
    employee.notes = notes.strip()
    db.commit()

    return RedirectResponse("/employees", status_code=303)


@app.post("/employees/{employee_id}/delete")
def employee_delete(request: Request, employee_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin", "office"])
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.query(User).filter(User.employee_id == employee.id).delete()
    db.delete(employee)
    db.commit()
    return RedirectResponse("/employees", status_code=303)


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin"])
    users = db.query(User).options(joinedload(User.employee)).order_by(User.username.asc()).all()
    employees = db.query(Employee).order_by(Employee.name.asc()).all()
    return templates.TemplateResponse("users.html", {"request": request, "current_user": current_user, "users": users, "employees": employees})


@app.post("/users/new")
def user_create(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    role: str = Form("field"),
    employee_id: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin"])

    if not username.strip() or not password.strip():
        raise HTTPException(status_code=400, detail="Username and password are required")

    existing = db.query(User).filter(User.username == username.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    employee_ref = int(employee_id) if employee_id.strip() else None

    user = User(
        username=username.strip(),
        password_hash=hash_password(password.strip()),
        role=role.strip() or "field",
        employee_id=employee_ref,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/password")
def user_change_password(
    request: Request,
    user_id: int,
    new_password: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not new_password.strip():
        raise HTTPException(status_code=400, detail="Password is required")
    user.password_hash = hash_password(new_password.strip())
    db.commit()
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/toggle")
def user_toggle_active(request: Request, user_id: int, db: Session = Depends(get_db)):
    require_roles(request, db, ["admin"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse("/users", status_code=303)


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    schedule_items = (
        db.query(ScheduleItem)
        .join(Property)
        .options(
            joinedload(ScheduleItem.property).joinedload(Property.client),
            joinedload(ScheduleItem.employee),
        )
        .filter(Property.is_archived == False)
        .order_by(ScheduleItem.date.asc(), ScheduleItem.start_time.asc(), ScheduleItem.id.asc())
        .all()
    )
    return templates.TemplateResponse("schedule.html", {"request": request, "current_user": current_user, "schedule_items": schedule_items})


@app.get("/schedule/new", response_class=HTMLResponse)
def new_schedule_item(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    properties = (
        db.query(Property)
        .options(joinedload(Property.client))
        .filter(Property.is_archived == False)
        .order_by(Property.address.asc())
        .all()
    )
    employees = db.query(Employee).order_by(Employee.name.asc()).all()
    requests_list = db.query(ClientRequest).order_by(ClientRequest.id.desc()).all()
    return templates.TemplateResponse(
        "schedule_new.html",
        {"request": request, "current_user": current_user, "properties": properties, "employees": employees, "requests_list": requests_list},
    )


@app.post("/schedule/new")
def create_schedule_item(
    request: Request,
    property_id: int = Form(...),
    employee_id: str = Form(""),
    date: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    assigned_to: str = Form(""),
    job_type: str = Form(""),
    status: str = Form("scheduled"),
    priority: str = Form("normal"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    employee_ref = int(employee_id) if employee_id.strip() else None

    item = ScheduleItem(
        property_id=property_id,
        employee_id=employee_ref,
        date=date.strip(),
        start_time=start_time.strip(),
        end_time=end_time.strip(),
        assigned_to=assigned_to.strip(),
        job_type=job_type.strip(),
        status=status.strip() or "scheduled",
        priority=priority.strip() or "normal",
        notes=notes.strip(),
    )
    db.add(item)
    add_property_activity(db, property_id, "schedule_created", f"Scheduled {job_type.strip() or 'job'} on {date.strip()}.")
    db.commit()
    return RedirectResponse("/schedule", status_code=303)


@app.get("/properties/{property_id}/service-stop/new", response_class=HTMLResponse)
def new_service_stop(request: Request, property_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    prop = db.query(Property).options(joinedload(Property.client)).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return templates.TemplateResponse("service_stop_new.html", {"request": request, "current_user": current_user, "property": prop})


@app.post("/properties/{property_id}/service-stop/new")
async def create_service_stop(
    request: Request,
    property_id: int,
    date: str = Form(""),
    tech_name: str = Form(""),
    problem_reported: str = Form(""),
    work_performed: str = Form(""),
    recommendation: str = Form(""),
    billed_amount: float = Form(0),
    labor_hours: float = Form(0),
    labor_rate: float = Form(0),
    material_cost: float = Form(0),
    trip_charge: float = Form(0),
    tax: float = Form(0),
    paid_status: str = Form("unpaid"),
    invoice_notes: str = Form(""),
    status: str = Form("completed"),
    photo: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office", "field"])

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    photo_path = ""
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(status_code=400, detail="Photo must be jpg, jpeg, png, or webp")
        filename = f"{uuid4().hex}{ext}"
        output_path = UPLOAD_DIR / filename
        content = await photo.read()
        output_path.write_bytes(content)
        photo_path = f"/static/uploads/{filename}"

    stop = ServiceStop(
        date=date.strip(),
        tech_name=tech_name.strip(),
        problem_reported=problem_reported.strip(),
        work_performed=work_performed.strip(),
        recommendation=recommendation.strip(),
        billed_amount=billed_amount or 0,
        labor_hours=labor_hours or 0,
        labor_rate=labor_rate or 0,
        material_cost=material_cost or 0,
        trip_charge=trip_charge or 0,
        tax=tax or 0,
        paid_status=paid_status.strip() or "unpaid",
        invoice_notes=invoice_notes.strip(),
        status=status.strip() or "completed",
        photo_path=photo_path,
        property_id=prop.id,
    )
    db.add(stop)
    db.flush()
    add_property_activity(db, prop.id, "service_stop", f"Service stop logged by {tech_name.strip() or 'tech'}.")
    db.commit()
    db.refresh(stop)
    return RedirectResponse(url=f"/service-stops/{stop.id}", status_code=303)


@app.post("/service-stops/{stop_id}/paid-status")
def update_paid_status(
    request: Request,
    stop_id: int,
    paid_status: str = Form("unpaid"),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    stop = db.query(ServiceStop).filter(ServiceStop.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Service stop not found")

    stop.paid_status = paid_status.strip() or "unpaid"
    add_property_activity(db, stop.property_id, "paid_status", f"Paid status changed to {stop.paid_status}.")
    db.commit()
    return RedirectResponse(url=f"/service-stops/{stop.id}", status_code=303)


@app.get("/service-stops/{stop_id}", response_class=HTMLResponse)
def service_stop_detail(request: Request, stop_id: int, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    stop = (
        db.query(ServiceStop)
        .options(joinedload(ServiceStop.property).joinedload(Property.client))
        .filter(ServiceStop.id == stop_id)
        .first()
    )
    if not stop:
        raise HTTPException(status_code=404, detail="Service stop not found")

    labor_total = float(stop.labor_hours or 0) * float(stop.labor_rate or 0)
    invoice_total = labor_total + float(stop.billed_amount or 0) + float(stop.material_cost or 0) + float(stop.trip_charge or 0) + float(stop.tax or 0)

    return templates.TemplateResponse(
        "service_stop_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "service_stop": stop,
            "labor_total": labor_total,
            "invoice_total": invoice_total,
        },
    )


@app.get("/requests", response_class=HTMLResponse)
def requests_page(
    request: Request,
    status_filter: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    current_user = require_roles(request, db, ["admin", "office"])
    query = db.query(ClientRequest)

    if status_filter.strip():
        query = query.filter(ClientRequest.status == status_filter.strip())

    if q.strip():
        term = q.strip()
        query = query.filter(
            or_(
                ClientRequest.client_name.ilike(f"%{term}%"),
                ClientRequest.phone.ilike(f"%{term}%"),
                ClientRequest.address.ilike(f"%{term}%"),
                ClientRequest.request_type.ilike(f"%{term}%"),
                ClientRequest.description.ilike(f"%{term}%"),
            )
        )

    requests_list = query.order_by(ClientRequest.id.desc()).all()
    return templates.TemplateResponse(
        "requests.html",
        {"request": request, "current_user": current_user, "requests_list": requests_list, "status_filter": status_filter, "q": q},
    )


@app.post("/requests/{request_id}/status")
def update_request_status(
    request: Request,
    request_id: int,
    status: str = Form("new"),
    db: Session = Depends(get_db),
):
    require_roles(request, db, ["admin", "office"])

    req = db.query(ClientRequest).filter(ClientRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    req.status = status.strip() or "new"
    db.commit()
    return RedirectResponse("/requests", status_code=303)


@app.get("/portal/request", response_class=HTMLResponse)
def portal_request_form(request: Request):
    return templates.TemplateResponse("portal_request.html", {"request": request})


@app.post("/portal/request")
def portal_request_submit(
    client_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    request_type: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    if not client_name.strip():
        raise HTTPException(status_code=400, detail="Client name is required")

    item = ClientRequest(
        client_name=client_name.strip(),
        phone=phone.strip(),
        email=email.strip(),
        address=address.strip(),
        request_type=request_type.strip(),
        description=description.strip(),
        status="new",
    )
    db.add(item)
    db.commit()
    return RedirectResponse("/portal/thanks", status_code=303)


@app.get("/portal/thanks", response_class=HTMLResponse)
def portal_thanks(request: Request):
    return templates.TemplateResponse("portal_thanks.html", {"request": request})


@app.get("/dev/seed")
def seed(db: Session = Depends(get_db)):
    if db.query(Client).first():
        return {"status": "already seeded"}

    client1 = Client(name="John Smith", phone="812-555-1212", email="john@email.com", billing_address="1234 Oak Hill Rd")
    client2 = Client(name="Sarah Bennett", phone="812-555-4545", email="sarah@email.com", billing_address="77 Lakeview Dr")
    db.add_all([client1, client2])
    db.commit()
    db.refresh(client1)
    db.refresh(client2)

    employee1 = Employee(name="Mike Heinlin", role="Owner / Lead Tech", phone="812-449-6198", email="mike@example.com")
    employee2 = Employee(name="Jake Turner", role="Service Tech", phone="812-555-3131", email="jake@example.com")
    db.add_all([employee1, employee2])
    db.commit()
    db.refresh(employee1)
    db.refresh(employee2)

    admin_user = User(username="mike", password_hash=hash_password("1234"), role="admin", employee_id=employee1.id)
    office_user = User(username="office", password_hash=hash_password("1234"), role="office")
    field_user = User(username="jake", password_hash=hash_password("1234"), role="field", employee_id=employee2.id)
    db.add_all([admin_user, office_user, field_user])
    db.commit()

    property1 = Property(
        client_id=client1.id,
        address="1234 Oak Hill Rd",
        city="Evansville",
        state="IN",
        zip_code="47720",
        pool_type="Gunite",
        cover_type="Automatic Cover",
        gate_code="1942",
        install_year="2018",
        estimate_status="sent",
        notes="Auto cover drags on right side after heavy storms.",
    )
    property2 = Property(
        client_id=client2.id,
        address="77 Lakeview Dr",
        city="Newburgh",
        state="IN",
        zip_code="47630",
        pool_type="Fiberglass",
        cover_type="Manual Safety Cover",
        gate_code="",
        install_year="2022",
        estimate_status="approved",
        notes="Weekly maintenance and spring opening.",
    )
    db.add_all([property1, property2])
    db.commit()
    db.refresh(property1)
    db.refresh(property2)

    add_property_activity(db, property1.id, "property_created", "Property created.")
    add_property_activity(db, property2.id, "property_created", "Property created.")
    db.commit()

    stop = ServiceStop(
        property_id=property1.id,
        date="2026-04-12",
        tech_name="Mike Heinlin",
        status="completed",
        problem_reported="Customer reported cover dragging on right side.",
        work_performed="Adjusted track, cleaned debris, tested motor, verified alignment.",
        recommendation="Monitor over the next week and inspect rope tension if drag returns.",
        labor_hours=2.5,
        labor_rate=95,
        material_cost=18,
        trip_charge=35,
        tax=19.04,
        billed_amount=0,
        paid_status="unpaid",
        invoice_notes="Customer requested emailed invoice.",
        photo_path="",
    )
    db.add(stop)
    db.flush()
    add_property_activity(db, property1.id, "service_stop", "Initial service stop seeded.")

    today_string = str(date.today())

    schedule1 = ScheduleItem(
        property_id=property1.id,
        employee_id=employee1.id,
        date=today_string,
        start_time="08:00",
        end_time="10:30",
        assigned_to="Mike Heinlin",
        job_type="Service Call",
        status="scheduled",
        priority="high",
        notes="Inspect automatic cover and test key switch.",
    )
    schedule2 = ScheduleItem(
        property_id=property2.id,
        employee_id=employee2.id,
        date=today_string,
        start_time="09:00",
        end_time="12:00",
        assigned_to="Jake Turner",
        job_type="Opening / Cleaning",
        status="scheduled",
        priority="normal",
        notes="Opening chemicals on truck. Confirm access at gate.",
    )
    db.add_all([schedule1, schedule2])
    db.flush()
    add_property_activity(db, property1.id, "schedule_created", f"Scheduled Service Call on {today_string}.")
    add_property_activity(db, property2.id, "schedule_created", f"Scheduled Opening / Cleaning on {today_string}.")

    request1 = ClientRequest(
        client_name="Amanda Cole",
        phone="812-555-7878",
        email="amanda@email.com",
        address="200 Meadow Run",
        request_type="Estimate Request",
        description="Interested in resurfacing and new tile this season.",
        status="new",
    )
    request2 = ClientRequest(
        client_name="Chris Lane",
        phone="812-555-9999",
        email="chris@email.com",
        address="15 Oak Terrace",
        request_type="Automatic Cover Issue",
        description="Cover is binding on one side and stopping halfway.",
        status="contacted",
    )
    db.add_all([request1, request2])
    db.commit()

    return {
        "status": "seeded",
        "logins": [
            {"username": "mike", "password": "1234", "role": "admin"},
            {"username": "office", "password": "1234", "role": "office"},
            {"username": "jake", "password": "1234", "role": "field"},
        ],
    }