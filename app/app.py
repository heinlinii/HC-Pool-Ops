from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import csv
import io

from app.database import Base, engine, SessionLocal
from app.models import User, Employee, Client, Property, Job, Invoice, JobCost, PhotoLog


app = FastAPI(title="PoolOps2")

app.add_middleware(
    SessionMiddleware,
    secret_key="poolops2-phase-35-secret",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        if db.query(User).count() == 0:
            db.add(User(username="mike", password="5500", role="admin", name="Mike"))
            db.add(User(username="randy", password="0318", role="crew", name="Randy"))

        if db.query(Employee).count() == 0:
            db.add(Employee(name="Mike", role="Admin", phone="", email="", active=True))
            db.add(Employee(name="Randy", role="Crew", phone="", email="", active=True))

        if db.query(Client).count() == 0:
            db.add(Client(name="Smith Residence", phone="", email="", notes="Sample client."))
            db.add(Client(name="Johnson Backyard", phone="", email="", notes="Sample remodel client."))

        if db.query(Property).count() == 0:
            db.add(Property(client_id=1, client="Smith Residence", address="Evansville, IN", pool_type="Concrete Pool", notes="20x40 rectangle pool."))
            db.add(Property(client_id=2, client="Johnson Backyard", address="Newburgh, IN", pool_type="Pool Remodel", notes="Tile and coping replacement."))

        if db.query(Job).count() == 0:
            db.add(Job(client="Smith Residence", property="Evansville, IN", address="Evansville, IN", job_type="Concrete Pool", status="Scheduled", crew="Randy", date="Today", priority="Normal", notes="20x40 rectangle pool."))
            db.add(Job(client="Johnson Backyard", property="Newburgh, IN", address="Newburgh, IN", job_type="Pool Remodel", status="Pending", crew="Unassigned", date="Tomorrow", priority="High", notes="Tile and coping replacement."))

        if db.query(Invoice).count() == 0:
            db.add(Invoice(job_id=1, client="Smith Residence", description="Deposit invoice", amount=5000.00, status="Draft", date="Today", notes="Sample billing record."))

        if db.query(JobCost).count() == 0:
            db.add(JobCost(job_id=1, client="Smith Residence", labor=1200.00, materials=2500.00, subs=0.00, equipment=350.00, fuel=125.00, other=0.00, invoice_amount=5000.00, notes="Sample job cost record."))

        if db.query(PhotoLog).count() == 0:
            db.add(PhotoLog(job_id=1, client="Smith Residence", photo_type="Before", title="Sample before photo", photo_url="/static/logo.png", date="Today", notes="Temporary sample photo."))

        db.commit()

    finally:
        db.close()


TIME_CLOCK = {
    "randy": {"clocked_in": False, "current_job": None}
}


def db_session():
    return SessionLocal()


def get_current_user(request: Request):
    username = request.session.get("username")

    if not username:
        return None

    db = db_session()

    try:
        user = db.query(User).filter(User.username == username).first()

        if not user:
            return None

        return {
            "username": user.username,
            "name": user.name,
            "role": user.role,
        }

    finally:
        db.close()


def require_login(request: Request):
    return get_current_user(request)


def require_admin(request: Request):
    user = get_current_user(request)

    if not user:
        return None

    if user["role"] != "admin":
        return None

    return user


def cost_totals(cost):
    total_cost = (
        float(cost.labor or 0)
        + float(cost.materials or 0)
        + float(cost.subs or 0)
        + float(cost.equipment or 0)
        + float(cost.fuel or 0)
        + float(cost.other or 0)
    )

    invoice_amount = float(cost.invoice_amount or 0)
    profit = invoice_amount - total_cost
    margin = 0

    if invoice_amount > 0:
        margin = round((profit / invoice_amount) * 100, 2)

    return {
        "total_cost": round(total_cost, 2),
        "profit": round(profit, 2),
        "margin": margin,
    }


def profit_status(profit, margin):
    if profit < 0:
        return "danger"

    if margin < 15:
        return "warning"

    return "good"


def job_options(db):
    jobs = db.query(Job).order_by(Job.id.desc()).all()

    return [
        {
            "id": job.id,
            "label": f"#{job.id} - {job.client} - {job.job_type}",
            "client": job.client,
        }
        for job in jobs
    ]


def job_financial_summary(job_id: int, db):
    invoices = db.query(Invoice).filter(Invoice.job_id == job_id).all()
    costs = db.query(JobCost).filter(JobCost.job_id == job_id).all()

    invoice_total = round(sum(float(invoice.amount or 0) for invoice in invoices), 2)

    cost_total = 0
    cost_revenue_total = 0

    for cost in costs:
        totals = cost_totals(cost)
        cost_total += totals["total_cost"]
        cost_revenue_total += float(cost.invoice_amount or 0)

    tracked_profit = round(cost_revenue_total - cost_total, 2)

    tracked_margin = 0
    if cost_revenue_total > 0:
        tracked_margin = round((tracked_profit / cost_revenue_total) * 100, 2)

    return {
        "invoice_total": invoice_total,
        "cost_total": round(cost_total, 2),
        "tracked_revenue": round(cost_revenue_total, 2),
        "tracked_profit": tracked_profit,
        "tracked_margin": tracked_margin,
        "profit_status": profit_status(tracked_profit, tracked_margin),
    }


@app.get("/")
async def login_page(request: Request):
    user = get_current_user(request)

    if user:
        if user["role"] == "crew":
            return RedirectResponse(url="/crew", status_code=303)

        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.lower().strip()
    password = password.strip()

    db = db_session()

    try:
        user = db.query(User).filter(User.username == username).first()

        if not user or user.password != password:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid username or password."},
                status_code=401,
            )

        request.session["username"] = username

        if user.role == "crew":
            return RedirectResponse(url="/crew", status_code=303)

        return RedirectResponse(url="/dashboard", status_code=303)

    finally:
        db.close()


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "PoolOps2",
        "phase": "3.5",
        "database": "connected",
        "feature": "job hub",
    }


@app.get("/dashboard")
async def dashboard(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    if user["role"] != "admin":
        return RedirectResponse(url="/crew", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).order_by(Job.id.desc()).all()
        clients = db.query(Client).order_by(Client.id.desc()).all()
        properties = db.query(Property).order_by(Property.id.desc()).all()
        employees = db.query(Employee).order_by(Employee.id.desc()).all()
        invoices = db.query(Invoice).all()
        costs = db.query(JobCost).all()
        photos = db.query(PhotoLog).all()

        total_invoice_amount = round(sum(float(invoice.amount or 0) for invoice in invoices), 2)

        total_cost = 0
        total_revenue = 0

        for cost in costs:
            totals = cost_totals(cost)
            total_cost += totals["total_cost"]
            total_revenue += float(cost.invoice_amount or 0)

        total_profit = round(total_revenue - total_cost, 2)

        stats = {
            "total_jobs": len(jobs),
            "scheduled": len([job for job in jobs if job.status == "Scheduled"]),
            "pending": len([job for job in jobs if job.status == "Pending"]),
            "in_progress": len([job for job in jobs if job.status == "In Progress"]),
            "completed": len([job for job in jobs if job.status == "Completed"]),
            "clients": len(clients),
            "properties": len(properties),
            "employees": len(employees),
            "invoices": len(invoices),
            "invoice_total": total_invoice_amount,
            "tracked_profit": total_profit,
            "photos": len(photos),
        }

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "user": user,
                "jobs": jobs,
                "clients": clients,
                "properties": properties,
                "employees": employees,
                "stats": stats,
            },
        )

    finally:
        db.close()


@app.get("/jobs")
async def jobs_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        return templates.TemplateResponse(
            request,
            "jobs.html",
            {
                "user": user,
                "jobs": db.query(Job).order_by(Job.id.desc()).all(),
                "clients": db.query(Client).order_by(Client.name.asc()).all(),
                "properties": db.query(Property).order_by(Property.address.asc()).all(),
                "employees": db.query(Employee).order_by(Employee.name.asc()).all(),
            },
        )

    finally:
        db.close()


@app.get("/jobs/{job_id}")
async def job_detail_page(request: Request, job_id: int):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if not job:
            return RedirectResponse(url="/jobs", status_code=303)

        invoices = db.query(Invoice).filter(Invoice.job_id == job_id).order_by(Invoice.id.desc()).all()
        costs = db.query(JobCost).filter(JobCost.job_id == job_id).order_by(JobCost.id.desc()).all()
        photos = db.query(PhotoLog).filter(PhotoLog.job_id == job_id).order_by(PhotoLog.id.desc()).all()

        enriched_costs = []

        for cost in costs:
            totals = cost_totals(cost)

            enriched_costs.append(
                {
                    "id": cost.id,
                    "job_id": cost.job_id,
                    "client": cost.client,
                    "labor": cost.labor,
                    "materials": cost.materials,
                    "subs": cost.subs,
                    "equipment": cost.equipment,
                    "fuel": cost.fuel,
                    "other": cost.other,
                    "invoice_amount": cost.invoice_amount,
                    "notes": cost.notes,
                    "total_cost": totals["total_cost"],
                    "profit": totals["profit"],
                    "margin": totals["margin"],
                    "profit_status": profit_status(totals["profit"], totals["margin"]),
                }
            )

        summary = job_financial_summary(job_id, db)

        return templates.TemplateResponse(
            request,
            "job_detail.html",
            {
                "user": user,
                "job": job,
                "invoices": invoices,
                "costs": enriched_costs,
                "photos": photos,
                "summary": summary,
            },
        )

    finally:
        db.close()


@app.post("/jobs/{job_id}/notes")
async def update_job_notes(
    request: Request,
    job_id: int,
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.notes = notes.strip()
            db.commit()

        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    finally:
        db.close()


@app.post("/jobs/{job_id}/status")
async def update_job_detail_status(
    request: Request,
    job_id: int,
    status: str = Form(...),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.status = status.strip()
            db.commit()

        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    finally:
        db.close()


@app.post("/jobs/add")
async def add_job(
    request: Request,
    client: str = Form(...),
    address: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    crew: str = Form("Unassigned"),
    status: str = Form("Scheduled"),
    priority: str = Form("Normal"),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clean_address = address.strip()

        db.add(
            Job(
                client=client.strip(),
                property=clean_address,
                address=clean_address,
                job_type=job_type.strip(),
                status=status.strip(),
                crew=crew.strip() or "Unassigned",
                date=date.strip(),
                priority=priority.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/jobs", status_code=303)

    finally:
        db.close()


@app.post("/jobs/update/{job_id}")
async def update_job(
    request: Request,
    job_id: int,
    client: str = Form(...),
    address: str = Form(...),
    job_type: str = Form(...),
    date: str = Form(...),
    crew: str = Form(...),
    status: str = Form(...),
    priority: str = Form(...),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.client = client.strip()
            job.property = address.strip()
            job.address = address.strip()
            job.job_type = job_type.strip()
            job.date = date.strip()
            job.crew = crew.strip()
            job.status = status.strip()
            job.priority = priority.strip()
            job.notes = notes.strip()

            db.commit()

        return RedirectResponse(url="/jobs", status_code=303)

    finally:
        db.close()


@app.post("/jobs/delete/{job_id}")
async def delete_job(request: Request, job_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            db.delete(job)
            db.commit()

        return RedirectResponse(url="/jobs", status_code=303)

    finally:
        db.close()


@app.get("/schedule")
async def schedule_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        return templates.TemplateResponse(
            request,
            "schedule.html",
            {
                "user": user,
                "jobs": db.query(Job).order_by(Job.id.desc()).all(),
            },
        )

    finally:
        db.close()


@app.post("/schedule/status/{job_id}")
async def update_schedule_status(request: Request, job_id: int, status: str = Form(...)):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.status = status.strip()
            db.commit()

        return RedirectResponse(url="/schedule", status_code=303)

    finally:
        db.close()


@app.get("/crew")
async def crew_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).order_by(Job.id.desc()).all()

        crew_jobs = [
            job
            for job in jobs
            if job.crew.lower() in [user["name"].lower(), user["username"].lower()]
            or job.crew.lower() == "unassigned"
            or user["role"] == "admin"
        ]

        clock = TIME_CLOCK.get(
            user["username"],
            {"clocked_in": False, "current_job": None},
        )

        return templates.TemplateResponse(
            request,
            "crew.html",
            {
                "user": user,
                "jobs": crew_jobs,
                "clock": clock,
            },
        )

    finally:
        db.close()


@app.post("/crew/clock-in")
async def clock_in(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    old_clock = TIME_CLOCK.get(
        user["username"],
        {"clocked_in": False, "current_job": None},
    )

    TIME_CLOCK[user["username"]] = {
        "clocked_in": True,
        "current_job": old_clock.get("current_job"),
    }

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/clock-out")
async def clock_out(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    TIME_CLOCK[user["username"]] = {
        "clocked_in": False,
        "current_job": None,
    }

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/start-job/{job_id}")
async def start_job(request: Request, job_id: int):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.status = "In Progress"
            db.commit()

            TIME_CLOCK[user["username"]] = {
                "clocked_in": True,
                "current_job": job_id,
            }

        return RedirectResponse(url="/crew", status_code=303)

    finally:
        db.close()


@app.post("/crew/complete-job/{job_id}")
async def complete_job(request: Request, job_id: int):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.status = "Completed"
            db.commit()

            if TIME_CLOCK.get(user["username"], {}).get("current_job") == job_id:
                TIME_CLOCK[user["username"]]["current_job"] = None

        return RedirectResponse(url="/crew", status_code=303)

    finally:
        db.close()


@app.get("/clients")
async def clients_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        return templates.TemplateResponse(
            request,
            "clients.html",
            {
                "user": user,
                "clients": db.query(Client).order_by(Client.id.desc()).all(),
            },
        )

    finally:
        db.close()


@app.post("/clients/add")
async def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        db.add(
            Client(
                name=name.strip(),
                phone=phone.strip(),
                email=email.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/clients", status_code=303)

    finally:
        db.close()


@app.post("/clients/update/{client_id}")
async def update_client(
    request: Request,
    client_id: int,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        client = db.query(Client).filter(Client.id == client_id).first()

        if client:
            old_name = client.name

            client.name = name.strip()
            client.phone = phone.strip()
            client.email = email.strip()
            client.notes = notes.strip()

            properties = db.query(Property).filter(Property.client == old_name).all()
            jobs = db.query(Job).filter(Job.client == old_name).all()

            for prop in properties:
                prop.client = client.name

            for job in jobs:
                job.client = client.name

            db.commit()

        return RedirectResponse(url="/clients", status_code=303)

    finally:
        db.close()


@app.post("/clients/delete/{client_id}")
async def delete_client(request: Request, client_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        client = db.query(Client).filter(Client.id == client_id).first()

        if client:
            db.delete(client)
            db.commit()

        return RedirectResponse(url="/clients", status_code=303)

    finally:
        db.close()


@app.get("/properties")
async def properties_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        return templates.TemplateResponse(
            request,
            "properties.html",
            {
                "user": user,
                "clients": db.query(Client).order_by(Client.name.asc()).all(),
                "properties": db.query(Property).order_by(Property.id.desc()).all(),
            },
        )

    finally:
        db.close()


@app.post("/properties/add")
async def add_property(
    request: Request,
    client: str = Form(...),
    address: str = Form(...),
    pool_type: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        selected_client = db.query(Client).filter(Client.name == client).first()

        db.add(
            Property(
                client_id=selected_client.id if selected_client else None,
                client=client.strip(),
                address=address.strip(),
                pool_type=pool_type.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/properties", status_code=303)

    finally:
        db.close()


@app.post("/properties/update/{property_id}")
async def update_property(
    request: Request,
    property_id: int,
    client: str = Form(...),
    address: str = Form(...),
    pool_type: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        prop = db.query(Property).filter(Property.id == property_id).first()

        if prop:
            old_address = prop.address
            selected_client = db.query(Client).filter(Client.name == client).first()

            prop.client_id = selected_client.id if selected_client else None
            prop.client = client.strip()
            prop.address = address.strip()
            prop.pool_type = pool_type.strip()
            prop.notes = notes.strip()

            jobs = db.query(Job).filter(Job.address == old_address).all()

            for job in jobs:
                job.property = prop.address
                job.address = prop.address
                job.client = prop.client

            db.commit()

        return RedirectResponse(url="/properties", status_code=303)

    finally:
        db.close()


@app.post("/properties/delete/{property_id}")
async def delete_property(request: Request, property_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        prop = db.query(Property).filter(Property.id == property_id).first()

        if prop:
            db.delete(prop)
            db.commit()

        return RedirectResponse(url="/properties", status_code=303)

    finally:
        db.close()


@app.get("/employees")
async def employees_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        return templates.TemplateResponse(
            request,
            "employees.html",
            {
                "user": user,
                "employees": db.query(Employee).order_by(Employee.id.desc()).all(),
            },
        )

    finally:
        db.close()


@app.post("/employees/add")
async def add_employee(
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    active: str = Form("true"),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        db.add(
            Employee(
                name=name.strip(),
                role=role.strip(),
                phone=phone.strip(),
                email=email.strip(),
                active=active == "true",
            )
        )

        db.commit()

        return RedirectResponse(url="/employees", status_code=303)

    finally:
        db.close()


@app.post("/employees/update/{employee_id}")
async def update_employee(
    request: Request,
    employee_id: int,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    active: str = Form("true"),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        employee = db.query(Employee).filter(Employee.id == employee_id).first()

        if employee:
            old_name = employee.name

            employee.name = name.strip()
            employee.role = role.strip()
            employee.phone = phone.strip()
            employee.email = email.strip()
            employee.active = active == "true"

            jobs = db.query(Job).filter(Job.crew == old_name).all()

            for job in jobs:
                job.crew = employee.name

            db.commit()

        return RedirectResponse(url="/employees", status_code=303)

    finally:
        db.close()


@app.post("/employees/delete/{employee_id}")
async def delete_employee(request: Request, employee_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        employee = db.query(Employee).filter(Employee.id == employee_id).first()

        if employee:
            db.delete(employee)
            db.commit()

        return RedirectResponse(url="/employees", status_code=303)

    finally:
        db.close()


@app.get("/billing")
async def billing_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        invoices = db.query(Invoice).order_by(Invoice.id.desc()).all()

        total_billed = round(sum(float(invoice.amount or 0) for invoice in invoices), 2)
        paid_total = round(sum(float(invoice.amount or 0) for invoice in invoices if invoice.status == "Paid"), 2)
        open_total = round(total_billed - paid_total, 2)

        return templates.TemplateResponse(
            request,
            "billing.html",
            {
                "user": user,
                "invoices": invoices,
                "jobs": job_options(db),
                "total_billed": total_billed,
                "paid_total": paid_total,
                "open_total": open_total,
            },
        )

    finally:
        db.close()


@app.post("/billing/add")
async def add_invoice(
    request: Request,
    job_id: int = Form(...),
    description: str = Form(...),
    amount: float = Form(...),
    status: str = Form("Draft"),
    date: str = Form("Today"),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        client_name = job.client if job else "Unknown Client"

        db.add(
            Invoice(
                job_id=job_id,
                client=client_name,
                description=description.strip(),
                amount=round(float(amount), 2),
                status=status.strip(),
                date=date.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/billing", status_code=303)

    finally:
        db.close()


@app.post("/billing/update/{invoice_id}")
async def update_invoice(
    request: Request,
    invoice_id: int,
    description: str = Form(...),
    amount: float = Form(...),
    status: str = Form(...),
    date: str = Form(...),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()

        if invoice:
            invoice.description = description.strip()
            invoice.amount = round(float(amount), 2)
            invoice.status = status.strip()
            invoice.date = date.strip()
            invoice.notes = notes.strip()

            db.commit()

        return RedirectResponse(url="/billing", status_code=303)

    finally:
        db.close()


@app.post("/billing/delete/{invoice_id}")
async def delete_invoice(request: Request, invoice_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()

        if invoice:
            db.delete(invoice)
            db.commit()

        return RedirectResponse(url="/billing", status_code=303)

    finally:
        db.close()


@app.get("/billing/export")
async def export_invoices(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        invoices = db.query(Invoice).order_by(Invoice.id.asc()).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["Invoice ID", "Job ID", "Client", "Description", "Amount", "Status", "Date", "Notes"])

        for invoice in invoices:
            writer.writerow(
                [
                    invoice.id,
                    invoice.job_id,
                    invoice.client,
                    invoice.description,
                    invoice.amount,
                    invoice.status,
                    invoice.date,
                    invoice.notes,
                ]
            )

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=poolops2_invoices.csv"},
        )

    finally:
        db.close()


@app.get("/job-costing")
async def job_costing_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        costs = db.query(JobCost).order_by(JobCost.id.desc()).all()
        enriched_costs = []

        for cost in costs:
            totals = cost_totals(cost)

            enriched_costs.append(
                {
                    "id": cost.id,
                    "job_id": cost.job_id,
                    "client": cost.client,
                    "labor": cost.labor,
                    "materials": cost.materials,
                    "subs": cost.subs,
                    "equipment": cost.equipment,
                    "fuel": cost.fuel,
                    "other": cost.other,
                    "invoice_amount": cost.invoice_amount,
                    "notes": cost.notes,
                    "total_cost": totals["total_cost"],
                    "profit": totals["profit"],
                    "margin": totals["margin"],
                    "profit_status": profit_status(totals["profit"], totals["margin"]),
                }
            )

        total_revenue = round(sum(float(cost.invoice_amount or 0) for cost in costs), 2)
        total_cost = round(sum(float(cost["total_cost"]) for cost in enriched_costs), 2)
        total_profit = round(total_revenue - total_cost, 2)

        overall_margin = 0

        if total_revenue > 0:
            overall_margin = round((total_profit / total_revenue) * 100, 2)

        return templates.TemplateResponse(
            request,
            "job_costing.html",
            {
                "user": user,
                "costs": enriched_costs,
                "jobs": job_options(db),
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "total_profit": total_profit,
                "overall_margin": overall_margin,
            },
        )

    finally:
        db.close()


@app.post("/job-costing/add")
async def add_job_cost(
    request: Request,
    job_id: int = Form(...),
    labor: float = Form(0),
    materials: float = Form(0),
    subs: float = Form(0),
    equipment: float = Form(0),
    fuel: float = Form(0),
    other: float = Form(0),
    invoice_amount: float = Form(0),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        client_name = job.client if job else "Unknown Client"

        db.add(
            JobCost(
                job_id=job_id,
                client=client_name,
                labor=round(float(labor), 2),
                materials=round(float(materials), 2),
                subs=round(float(subs), 2),
                equipment=round(float(equipment), 2),
                fuel=round(float(fuel), 2),
                other=round(float(other), 2),
                invoice_amount=round(float(invoice_amount), 2),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/job-costing", status_code=303)

    finally:
        db.close()


@app.post("/job-costing/update/{cost_id}")
async def update_job_cost(
    request: Request,
    cost_id: int,
    labor: float = Form(0),
    materials: float = Form(0),
    subs: float = Form(0),
    equipment: float = Form(0),
    fuel: float = Form(0),
    other: float = Form(0),
    invoice_amount: float = Form(0),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        cost = db.query(JobCost).filter(JobCost.id == cost_id).first()

        if cost:
            cost.labor = round(float(labor), 2)
            cost.materials = round(float(materials), 2)
            cost.subs = round(float(subs), 2)
            cost.equipment = round(float(equipment), 2)
            cost.fuel = round(float(fuel), 2)
            cost.other = round(float(other), 2)
            cost.invoice_amount = round(float(invoice_amount), 2)
            cost.notes = notes.strip()

            db.commit()

        return RedirectResponse(url="/job-costing", status_code=303)

    finally:
        db.close()


@app.post("/job-costing/delete/{cost_id}")
async def delete_job_cost(request: Request, cost_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        cost = db.query(JobCost).filter(JobCost.id == cost_id).first()

        if cost:
            db.delete(cost)
            db.commit()

        return RedirectResponse(url="/job-costing", status_code=303)

    finally:
        db.close()


@app.get("/job-costing/export")
async def export_job_costing(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        costs = db.query(JobCost).order_by(JobCost.id.asc()).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            [
                "Cost ID",
                "Job ID",
                "Client",
                "Labor",
                "Materials",
                "Subs",
                "Equipment",
                "Fuel",
                "Other",
                "Total Cost",
                "Invoice Amount",
                "Profit",
                "Margin %",
                "Notes",
            ]
        )

        for cost in costs:
            totals = cost_totals(cost)

            writer.writerow(
                [
                    cost.id,
                    cost.job_id,
                    cost.client,
                    cost.labor,
                    cost.materials,
                    cost.subs,
                    cost.equipment,
                    cost.fuel,
                    cost.other,
                    totals["total_cost"],
                    cost.invoice_amount,
                    totals["profit"],
                    totals["margin"],
                    cost.notes,
                ]
            )

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=poolops2_job_costing.csv"},
        )

    finally:
        db.close()


@app.get("/photos")
async def photos_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        return templates.TemplateResponse(
            request,
            "photos.html",
            {
                "user": user,
                "photos": db.query(PhotoLog).order_by(PhotoLog.id.desc()).all(),
                "jobs": job_options(db),
            },
        )

    finally:
        db.close()


@app.post("/photos/add")
async def add_photo_log(
    request: Request,
    job_id: int = Form(...),
    photo_type: str = Form(...),
    title: str = Form(...),
    photo_url: str = Form(""),
    date: str = Form("Today"),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        client_name = job.client if job else "Unknown Client"

        clean_photo_url = photo_url.strip()

        if not clean_photo_url:
            clean_photo_url = "/static/logo.png"

        db.add(
            PhotoLog(
                job_id=job_id,
                client=client_name,
                photo_type=photo_type.strip(),
                title=title.strip(),
                photo_url=clean_photo_url,
                date=date.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/photos", status_code=303)

    finally:
        db.close()


@app.post("/photos/update/{photo_id}")
async def update_photo_log(
    request: Request,
    photo_id: int,
    photo_type: str = Form(...),
    title: str = Form(...),
    photo_url: str = Form(""),
    date: str = Form("Today"),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        photo = db.query(PhotoLog).filter(PhotoLog.id == photo_id).first()

        if photo:
            photo.photo_type = photo_type.strip()
            photo.title = title.strip()
            photo.photo_url = photo_url.strip() or "/static/logo.png"
            photo.date = date.strip()
            photo.notes = notes.strip()

            db.commit()

        return RedirectResponse(url="/photos", status_code=303)

    finally:
        db.close()


@app.post("/photos/delete/{photo_id}")
async def delete_photo_log(request: Request, photo_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        photo = db.query(PhotoLog).filter(PhotoLog.id == photo_id).first()

        if photo:
            db.delete(photo)
            db.commit()

        return RedirectResponse(url="/photos", status_code=303)

    finally:
        db.close()