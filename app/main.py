from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from .database import SessionLocal, engine, Base
from .models import Client, Property, ServiceStop, ScheduleItem, Employee, ClientRequest

app = FastAPI(title="PoolOps Pro")

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def money(value):
    return f"${float(value or 0):,.2f}"


templates.env.filters["money"] = money


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    properties = db.query(Property).count()
    clients = db.query(Client).count()
    employees = db.query(Employee).count()
    open_requests = db.query(ClientRequest).filter(ClientRequest.status != "closed").count()
    unpaid_stops = db.query(ServiceStop).filter(ServiceStop.paid_status != "paid").count()

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

    recent_properties = (
        db.query(Property)
        .options(joinedload(Property.client))
        .order_by(Property.id.desc())
        .limit(8)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": {
                "properties": properties,
                "clients": clients,
                "employees": employees,
                "open_requests": open_requests,
                "unpaid_stops": unpaid_stops,
            },
            "upcoming": upcoming,
            "recent_stops": recent_stops,
            "recent_properties": recent_properties,
        },
    )


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).order_by(Client.name.asc()).all()
    return templates.TemplateResponse("clients.html", {"request": request, "clients": clients})


@app.get("/clients/new", response_class=HTMLResponse)
def client_new_form(request: Request):
    return templates.TemplateResponse("client_new.html", {"request": request})


@app.post("/clients/new")
def client_create(
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    billing_address: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
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


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request, db: Session = Depends(get_db)):
    properties = (
        db.query(Property)
        .options(joinedload(Property.client))
        .order_by(Property.id.desc())
        .all()
    )
    return templates.TemplateResponse("properties.html", {"request": request, "properties": properties})


@app.get("/properties/new", response_class=HTMLResponse)
def new_property(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).order_by(Client.name.asc()).all()
    return templates.TemplateResponse("property_new.html", {"request": request, "clients": clients})


@app.post("/properties/new")
def create_property(
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
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
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
        notes=notes.strip(),
        client_id=selected_client.id,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)

    return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


@app.get("/properties/{property_id}", response_class=HTMLResponse)
def property_detail(request: Request, property_id: int, db: Session = Depends(get_db)):
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

    return templates.TemplateResponse("property_detail.html", {"request": request, "property": prop})


@app.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request, db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.name.asc()).all()
    return templates.TemplateResponse("employees.html", {"request": request, "employees": employees})


@app.get("/employees/new", response_class=HTMLResponse)
def employee_new_form(request: Request):
    return templates.TemplateResponse("employee_new.html", {"request": request})


@app.post("/employees/new")
def employee_create(
    name: str = Form(""),
    role: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    status: str = Form("active"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
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
    schedule_items = (
        db.query(ScheduleItem)
        .options(joinedload(ScheduleItem.property).joinedload(Property.client), joinedload(ScheduleItem.employee))
        .order_by(ScheduleItem.date.asc(), ScheduleItem.start_time.asc(), ScheduleItem.id.asc())
        .all()
    )
    return templates.TemplateResponse("schedule.html", {"request": request, "schedule_items": schedule_items})


@app.get("/schedule/new", response_class=HTMLResponse)
def new_schedule_item(request: Request, db: Session = Depends(get_db)):
    properties = db.query(Property).options(joinedload(Property.client)).order_by(Property.address.asc()).all()
    employees = db.query(Employee).order_by(Employee.name.asc()).all()
    return templates.TemplateResponse(
        "schedule_new.html",
        {"request": request, "properties": properties, "employees": employees},
    )


@app.post("/schedule/new")
def create_schedule_item(
    property_id: int = Form(...),
    employee_id: str = Form(""),
    date: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    assigned_to: str = Form(""),
    job_type: str = Form(""),
    status: str = Form("scheduled"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
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
        notes=notes.strip(),
    )
    db.add(item)
    db.commit()
    return RedirectResponse(url="/schedule", status_code=303)


@app.get("/properties/{property_id}/service-stop/new", response_class=HTMLResponse)
def new_service_stop(request: Request, property_id: int, db: Session = Depends(get_db)):
    prop = db.query(Property).options(joinedload(Property.client)).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return templates.TemplateResponse("service_stop_new.html", {"request": request, "property": prop})


@app.post("/properties/{property_id}/service-stop/new")
def create_service_stop(
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
    db: Session = Depends(get_db),
):
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

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
        property_id=prop.id,
    )
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return RedirectResponse(url=f"/service-stops/{stop.id}", status_code=303)


@app.get("/service-stops/{stop_id}", response_class=HTMLResponse)
def service_stop_detail(request: Request, stop_id: int, db: Session = Depends(get_db)):
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
            "service_stop": stop,
            "labor_total": labor_total,
            "invoice_total": invoice_total,
        },
    )


@app.get("/requests", response_class=HTMLResponse)
def requests_page(request: Request, db: Session = Depends(get_db)):
    requests_list = db.query(ClientRequest).order_by(ClientRequest.id.desc()).all()
    return templates.TemplateResponse("requests.html", {"request": request, "requests_list": requests_list})


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
    )
    db.add(stop)

    schedule1 = ScheduleItem(
        property_id=property1.id,
        employee_id=employee1.id,
        date="2026-04-18",
        start_time="08:00",
        end_time="10:30",
        assigned_to="Mike Heinlin",
        job_type="Service Call",
        status="scheduled",
        notes="Inspect automatic cover and test key switch.",
    )
    schedule2 = ScheduleItem(
        property_id=property2.id,
        employee_id=employee2.id,
        date="2026-04-19",
        start_time="09:00",
        end_time="12:00",
        assigned_to="Jake Turner",
        job_type="Opening / Cleaning",
        status="scheduled",
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
    db.add(request1)
    db.commit()

    return {"status": "seeded"}
