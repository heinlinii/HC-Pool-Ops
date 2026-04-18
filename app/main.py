import csv
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
from sqlalchemy.orm import Session, joinedload

from .database import SessionLocal, engine, Base
from .models import Client, Property, ServiceStop, ScheduleItem, Employee, ClientRequest, User

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


templates.env.filters["money"] = money
templates.env.filters["urlencode"] = urlencode


def get_current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return (
        db.query(User)
        .options(joinedload(User.employee))
        .filter(User.id == user_id)
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
        .filter(User.username == username.strip())
        .first()
    )

    if not user or user.password != password.strip():
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

    properties = db.query(Property).count()
    clients = db.query(Client).count()
    employees = db.query(Employee).count()
    open_requests = db.query(ClientRequest).filter(ClientRequest.status != "closed").count()
    unpaid_stops = db.query(ServiceStop).filter(ServiceStop.paid_status != "paid").count()
    estimates_sent = db.query(Property).filter(Property.estimate_status == "sent").count()
    estimates_approved = db.query(Property).filter(Property.estimate_status == "approved").count()

    upcoming = (
        db.query(ScheduleItem)
        .options(joinedload(ScheduleItem.property).joinedload(Property.client), joinedload(ScheduleItem.employee))
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


@app.get("/field", response_class=HTMLResponse)
def field_dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    today_string = str(date.today())

    query = (
        db.query(ScheduleItem)
        .options(joinedload(ScheduleItem.property).joinedload(Property.client), joinedload(ScheduleItem.employee))
        .filter(ScheduleItem.date == today_string)
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
        .options(joinedload(ScheduleItem.property).joinedload(Property.client), joinedload(ScheduleItem.employee))
        .filter(ScheduleItem.date == today_string)
    )

    if current_user.role == "field" and current_user.employee_id:
        query = query.filter(ScheduleItem.employee_id == current_user.employee_id)

    today_items = query.order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc()).all()

    return templates.TemplateResponse(
        "today.html",
        {"request": request, "current_user": current_user, "today_items": today_items, "today_string": today_string},
    )


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    clients = db.query(Client).order_by(Client.name.asc()).all()
    return templates.TemplateResponse("clients.html", {"request": request, "current_user": current_user, "clients": clients})


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

        existing = (
            db.query(Client)
            .filter(Client.name == name, Client.phone == phone)
            .first()
        )

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
def properties_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office", "field"])
    properties = (
        db.query(Property)
        .options(joinedload(Property.client))
        .order_by(Property.id.desc())
        .all()
    )
    return templates.TemplateResponse("properties.html", {"request": request, "current_user": current_user, "properties": properties})


@app.get("/properties/new", response_class=HTMLResponse)
def new_property(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    clients = db.query(Client).order_by(Client.name.asc()).all()
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

    return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


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
        )
        .filter(Property.id == property_id)
        .first()
    )

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    return templates.TemplateResponse("property_detail.html", {"request": request, "current_user": current_user, "property": prop})


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


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    schedule_items = (
        db.query(ScheduleItem)
        .options(joinedload(ScheduleItem.property).joinedload(Property.client), joinedload(ScheduleItem.employee))
        .order_by(ScheduleItem.date.asc(), ScheduleItem.start_time.asc(), ScheduleItem.id.asc())
        .all()
    )
    return templates.TemplateResponse("schedule.html", {"request": request, "current_user": current_user, "schedule_items": schedule_items})


@app.get("/schedule/new", response_class=HTMLResponse)
def new_schedule_item(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    properties = db.query(Property).options(joinedload(Property.client)).order_by(Property.address.asc()).all()
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
    db.commit()
    return RedirectResponse(url="/schedule", status_code=303)


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
def requests_page(request: Request, db: Session = Depends(get_db)):
    current_user = require_roles(request, db, ["admin", "office"])
    requests_list = db.query(ClientRequest).order_by(ClientRequest.id.desc()).all()
    return templates.TemplateResponse("requests.html", {"request": request, "current_user": current_user, "requests_list": requests_list})


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
    return RedirectResponse(url="/requests", status_code=303)


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

    admin_user = User(username="mike", password="1234", role="admin", employee_id=employee1.id)
    office_user = User(username="office", password="1234", role="office")
    field_user = User(username="jake", password="1234", role="field", employee_id=employee2.id)
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