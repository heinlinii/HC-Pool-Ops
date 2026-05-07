from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import csv
import io
import os
import shutil
import json
import urllib.request

from app.database import Base, engine, SessionLocal
from app.models import User, Employee, Client, Property, Job, Invoice, JobCost, PhotoLog, FieldLog


app = FastAPI(title="PoolOps2")

app.add_middleware(
    SessionMiddleware,
    secret_key="poolops2-phase-5-secret",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        if db.query(User).count() == 0:
            db.add(User(username="mike", password="5500", role="admin", name="Mike"))
            db.add(User(username="randy", password="0318", role="crew", name="Randy"))
            db.add(User(username="marty", password="0712", role="crew", name="Marty"))
            db.add(User(username="carrie", password="0127", role="office", name="Carrie"))


        if db.query(Employee).count() == 0:
            db.add(Employee(name="Mike", role="Admin", phone="", email="", active=True))
            db.add(Employee(name="Randy", role="Foreman", phone="", email="", active=True))
            db.add(Employee(name="Marty", role="Crew", phone="", email="", active=True))
            db.add(Employee(name="Carrie", role="Office", phone="", email="", active=True)) 

        db.commit()

    finally:
        db.close()


TIME_CLOCK = {
    "randy": {"clocked_in": False, "current_job": None}
}


def db_session():
    return SessionLocal()


def save_uploaded_photo(upload: UploadFile):
    if not upload or not upload.filename:
        return "/static/logo.png"

    clean_name = upload.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, clean_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)

    return f"/static/uploads/{clean_name}"


def read_csv_upload(upload: UploadFile):
    raw = upload.file.read().decode("utf-8-sig")
    stream = io.StringIO(raw)
    return list(csv.DictReader(stream))


def pick(row, *keys):
    for key in keys:
        for actual_key, value in row.items():
            if actual_key and actual_key.strip().lower() == key.lower():
                return (value or "").strip()
    return ""


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
        "phase": "9",
        "database": "connected",
        "feature": "database backups",
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
        clients = db.query(Client).order_by(Client.name.asc()).all()
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
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()

        return templates.TemplateResponse(
            "clients.html",
            {
                "request": request,
                "user": user,
                "clients": clients
            }
        )

    finally:
        db.close()

@app.get("/clients/{client_id}")
async def client_detail_page(request: Request, client_id: int):

    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:

        client = db.query(Client).filter(Client.id == client_id).first()

        if not client:
            return RedirectResponse(url="/clients", status_code=303)

        properties = db.query(Property).filter(
            Property.client == client.name
        ).all()

        jobs = db.query(Job).filter(
            Job.client == client.name
        ).all()

        photos = db.query(PhotoLog).filter(
            PhotoLog.client == client.name
        ).all()

        return templates.TemplateResponse(
            "client_detail.html",
            {
                "request": request,
                "user": user,
                "client": client,
                "properties": properties,
                "jobs": jobs,
                "photos": photos,
            }
        )

    finally:
        db.close()

@app.get("/clients/new")
async def new_client_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "client_new.html",
        {"user": user},
    )


@app.post("/admin/wipe-clients")
async def wipe_clients(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        db.query(Client).delete()
        db.commit()

    finally:
        db.close()

    return RedirectResponse(url="/clients", status_code=303)


@app.get("/properties/new")
async def new_property_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()

        return templates.TemplateResponse(
            request,
            "property_new.html",
            {
                "user": user,
                "clients": clients,
            },
        )

    finally:
        db.close()


@app.get("/properties")
async def properties_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        properties = db.query(Property).order_by(Property.id.desc()).all()

        return templates.TemplateResponse(
            "properties.html",
            {
                "request": request,
                "user": user,
                "properties": properties
            }
        )

    finally:
        db.close()


@app.get("/properties/{property_id}")
async def property_detail_page(request: Request, property_id: int):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        prop = db.query(Property).filter(Property.id == property_id).first()

        if not prop:
            return RedirectResponse(url="/properties", status_code=303)

        jobs = db.query(Job).filter(Job.address == prop.address).order_by(Job.id.desc()).all()

        return templates.TemplateResponse(
            request,
            "property_detail.html",
            {
                "user": user,
                "property": prop,
                "jobs": jobs,
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

        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)

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
    photo_file: UploadFile = File(None),
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

        photo_url = save_uploaded_photo(photo_file)

        db.add(
            PhotoLog(
                job_id=job_id,
                client=client_name,
                photo_type=photo_type.strip(),
                title=title.strip(),
                photo_url=photo_url,
                date=date.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url="/photos", status_code=303)

    finally:
        db.close()


@app.post("/jobs/{job_id}/upload-photo")
async def upload_job_photo(
    request: Request,
    job_id: int,
    photo_type: str = Form(...),
    title: str = Form(...),
    photo_file: UploadFile = File(None),
    date: str = Form("Today"),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if not job:
            return RedirectResponse(url="/jobs", status_code=303)

        photo_url = save_uploaded_photo(photo_file)

        db.add(
            PhotoLog(
                job_id=job.id,
                client=job.client,
                photo_type=photo_type.strip(),
                title=title.strip(),
                photo_url=photo_url,
                date=date.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

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


@app.get("/imports")
async def imports_page(request: Request, message: str = ""):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "user": user,
            "message": message,
        },
    )


@app.post("/imports/clients")
async def import_clients(request: Request, csv_file: UploadFile = File(...)):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    rows = read_csv_upload(csv_file)

    db = db_session()

    imported = 0
    skipped = 0

    try:
        for row in rows:
            name = pick(row, "name", "customer", "client", "display name", "company")

            if not name:
                skipped += 1
                continue

            existing = db.query(Client).filter(Client.name == name).first()

            if existing:
                skipped += 1
                continue

            db.add(
                Client(
                    name=name,
                    phone=pick(row, "phone", "phone number", "mobile", "main phone"),
                    email=pick(row, "email", "email address", "main email"),
                    notes=pick(row, "notes", "memo", "description"),
                )
            )

            imported += 1

        db.commit()

    finally:
        db.close()

    return RedirectResponse(
        url=f"/imports?message=Imported {imported} clients. Skipped {skipped}.",
        status_code=303,
    )

@app.post("/imports/properties")
async def import_properties(request: Request, file: UploadFile = File(...)):

    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        contents = await file.read()
        text = contents.decode("utf-8")

        import csv
        reader = csv.DictReader(text.splitlines())

        for row in reader:
            print("IMPORT ROW:", row)  # <-- DEBUG (shows in Render logs)

            new_property = Property(
                client = row.get("client") or row.get("Client") or "",
                address = row.get("address") or row.get("Address") or "",
                pool_type = row.get("pool_type") or row.get("Type") or "",
                notes = row.get("notes") or row.get("Notes") or "",
            )

            db.add(new_property)

        db.commit()

        return RedirectResponse(url="/properties", status_code=303)

    finally:
        db.close()

@app.post("/properties/delete/{property_id}")
async def delete_property_post(property_id: int, request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    property_obj = db.query(Property).filter(Property.id == property_id).first()

    if property_obj:
        db.delete(property_obj)
        db.commit()

    return RedirectResponse(url="/properties", status_code=303)

# =========================
# PHASE 6 SCHEDULE ROUTES
# =========================

@app.get("/schedule/day", response_class=HTMLResponse)
async def schedule_day(request: Request):

    user = require_login(request)

    if not user:
        return RedirectResponse("/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).all()

        return templates.TemplateResponse(
            "schedule_day.html",
            {
                "request": request,
                "user": user,
                "jobs": jobs,
                "view_title": "Daily Schedule",
                "view_subtitle": "Today's scheduled work"
            }
        )

    finally:
        db.close()


@app.get("/schedule/week", response_class=HTMLResponse)
async def schedule_week(request: Request):

    user = require_login(request)

    if not user:
        return RedirectResponse("/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).all()

        return templates.TemplateResponse(
            "schedule_week.html",
            {
                "request": request,
                "user": user,
                "jobs": jobs,
                "view_title": "Weekly Schedule",
                "view_subtitle": "Weekly production planning"
            }
        )

    finally:
        db.close()


@app.get("/schedule/month", response_class=HTMLResponse)
async def schedule_month(request: Request):

    user = require_login(request)

    if not user:
        return RedirectResponse("/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).all()

        return templates.TemplateResponse(
            "schedule_month.html",
            {
                "request": request,
                "user": user,
                "jobs": jobs,
                "view_title": "Monthly Schedule",
                "view_subtitle": "Long-range scheduling"
            }
        )

    finally:
        db.close()


# =========================
# CLIENT PORTAL
# =========================

@app.get("/client-login", response_class=HTMLResponse)
async def client_login_page(request: Request):

    return templates.TemplateResponse(
        "client_login.html",
        {
            "request": request,
            "error": None
        }
    )


@app.post("/client-login", response_class=HTMLResponse)
async def client_login(
    request: Request,
    email_or_name: str = Form(...)
):

    db = db_session()

    try:

        client = db.query(Client).filter(
            Client.name == email_or_name
        ).first()

        if not client:

            return templates.TemplateResponse(
                "client_login.html",
                {
                    "request": request,
                    "error": "Client not found"
                }
            )

        request.session["client_id"] = client.id

        return RedirectResponse(
            "/client-dashboard",
            status_code=303
        )

    finally:
        db.close()


@app.get("/client-dashboard", response_class=HTMLResponse)
async def client_dashboard(request: Request):

    client_id = request.session.get("client_id")

    if not client_id:
        return RedirectResponse("/client-login", status_code=303)

    db = db_session()

    try:

        client = db.query(Client).filter(
            Client.id == client_id
        ).first()

        jobs = db.query(Job).filter(
            Job.client == client.name
        ).all()

        properties = db.query(Property).filter(
            Property.client == client.name
        ).all()

        public_schedule = db.query(Job).all()

        return templates.TemplateResponse(
            "client_dashboard.html",
            {
                "request": request,
                "client": client,
                "jobs": jobs,
                "properties": properties,
                "public_schedule": public_schedule
            }
        )

    finally:
        db.close()


@app.get("/client-request", response_class=HTMLResponse)
async def client_request_page(request: Request):

    client_id = request.session.get("client_id")

    if not client_id:
        return RedirectResponse("/client-login", status_code=303)

    db = db_session()

    try:

        client = db.query(Client).filter(
            Client.id == client_id
        ).first()

        properties = db.query(Property).filter(
            Property.client == client.name
        ).all()

        return templates.TemplateResponse(
            "client_requests.html",
            {
                "request": request,
                "client": client,
                "properties": properties,
                "message": None
            }
        )

    finally:
        db.close()


@app.post("/client-request", response_class=HTMLResponse)
async def submit_client_request(
    request: Request,
    request_type: str = Form(...),
    address: str = Form(""),
    requested_date: str = Form(""),
    message: str = Form("")
):

    client_id = request.session.get("client_id")

    if not client_id:
        return RedirectResponse("/client-login", status_code=303)

    db = db_session()

    try:

        client = db.query(Client).filter(
            Client.id == client_id
        ).first()

        properties = db.query(Property).filter(
            Property.client == client.name
        ).all()

        new_job = Job(
            client=client.name,
            address=address,
            job_type=request_type,
            date=requested_date,
            crew="Unassigned",
            status="Requested",
            priority="Medium",
            notes=message
        )

        db.add(new_job)
        db.commit()

        return templates.TemplateResponse(
            "client_requests.html",
            {
                "request": request,
                "client": client,
                "properties": properties,
                "message": "Request submitted successfully."
            }
        )

    finally:
        db.close()


@app.get("/client-logout")
async def client_logout(request: Request):

    request.session.clear()

    return RedirectResponse("/", status_code=303)

# =========================
# PHASE 7 WEATHER
# =========================

def get_evansville_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=37.9716"
        "&longitude=-87.5711"
        "&current=temperature_2m,precipitation,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max"
        "&temperature_unit=fahrenheit"
        "&wind_speed_unit=mph"
        "&precipitation_unit=inch"
        "&timezone=America%2FChicago"
    )

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

        return data

    except Exception:
        return None


def build_weather_alerts(weather):
    alerts = []

    if not weather:
        alerts.append("Weather data is currently unavailable.")
        return alerts

    current = weather.get("current", {})
    daily = weather.get("daily", {})

    temp = current.get("temperature_2m", 0)
    rain_now = current.get("precipitation", 0)
    wind_now = current.get("wind_speed_10m", 0)

    if rain_now and rain_now > 0:
        alerts.append("Rain is currently active. Check open excavation, tile work, EcoFinish prep, and cover work.")

    if wind_now and wind_now >= 20:
        alerts.append("High wind warning. Be careful with forms, covers, liners, tarps, dust, and spraying work.")

    if temp and temp >= 90:
        alerts.append("Heat warning. Watch crew hydration, concrete timing, EcoFinish surface temps, and employee fatigue.")

    if temp and temp <= 35:
        alerts.append("Cold warning. Protect concrete, plumbing, tile materials, and coatings.")

    rain_chances = daily.get("precipitation_probability_max", [])
    dates = daily.get("time", [])

    for index, chance in enumerate(rain_chances[:3]):
        if chance and chance >= 50:
            day = dates[index] if index < len(dates) else "upcoming day"
            alerts.append(f"Rain chance {chance}% on {day}. Consider schedule risk.")

    if not alerts:
        alerts.append("No major weather warnings right now.")

    return alerts

# =========================
# PHASE 16A UNIVERSAL SEARCH API
# =========================

@app.get("/api/search")
async def api_search(request: Request, q: str = ""):

    user = require_login(request)

    if not user:
        return {"results": []}

    q = (q or "").strip().lower()

    if not q:
        return {"results": []}

    db = db_session()

    try:

        results = []

        # JOBS
        jobs = db.query(Job).all()

        for job in jobs:

            search_blob = f"""
            {job.client or ""}
            {job.property or ""}
            {job.address or ""}
            {job.job_type or ""}
            {job.status or ""}
            {job.crew or ""}
            {job.notes or ""}
            """.lower()

            if q in search_blob:

                results.append({
                    "type": "Job",
                    "title": f"{job.client} • {job.job_type}",
                    "subtitle": f"{job.address} • {job.status}",
                    "url": f"/jobs/{job.id}"
                })

        # CLIENTS
        clients = db.query(Client).all()

        for client in clients:

            search_blob = f"""
            {client.name or ""}
            {client.phone or ""}
            {client.email or ""}
            {client.notes or ""}
            """.lower()

            if q in search_blob:

                results.append({
                    "type": "Client",
                    "title": client.name,
                    "subtitle": client.phone or client.email or "",
                    "url": "/clients"
                })

        # PROPERTIES
        properties = db.query(Property).all()

        for prop in properties:

            search_blob = f"""
            {prop.client or ""}
            {prop.address or ""}
            {prop.pool_type or ""}
            {prop.notes or ""}
            """.lower()

            if q in search_blob:

                results.append({
                    "type": "Property",
                    "title": prop.address,
                    "subtitle": f"{prop.client} • {prop.pool_type}",
                    "url": "/properties"
                })

        # FIELD LOGS
        logs = db.query(FieldLog).all()

        for log in logs:

            search_blob = f"""
            {log.employee_name or ""}
            {log.client or ""}
            {log.address or ""}
            {log.work_completed or ""}
            {log.issues or ""}
            {log.next_steps or ""}
            """.lower()

            if q in search_blob:

                results.append({
                    "type": "Field Log",
                    "title": log.client or "Field Log",
                    "subtitle": log.work_completed[:80] if log.work_completed else "",
                    "url": "/field-logs"
                })

        # PHOTOS
        photos = db.query(PhotoLog).all()

        for photo in photos:

            search_blob = f"""
            {photo.client or ""}
            {photo.title or ""}
            {photo.notes or ""}
            {photo.photo_type or ""}
            """.lower()

            if q in search_blob:

                results.append({
                    "type": "Photo",
                    "title": photo.title or "Photo",
                    "subtitle": photo.client or "",
                    "url": "/photos"
                })

        return {
            "results": results[:25]
        }

    finally: 
        db.close()

@app.get("/weather")
async def weather_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    weather = get_evansville_weather()
    alerts = build_weather_alerts(weather)

    current = {}
    daily = {}

    if weather:
        current = weather.get("current", {})
        daily = weather.get("daily", {})

    return templates.TemplateResponse(
        request,
        "weather.html",
        {
            "user": user,
            "weather": weather,
            "current": current,
            "daily": daily,
            "alerts": alerts,
        },
    )
# =========================
# PHASE 7B QUICKBOOKS CENTER
# =========================

@app.get("/quickbooks")
async def quickbooks_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()
        invoices = db.query(Invoice).order_by(Invoice.id.desc()).all()
        jobs = db.query(Job).order_by(Job.id.desc()).all()

        invoice_total = round(sum(float(invoice.amount or 0) for invoice in invoices), 2)

        return templates.TemplateResponse(
            request,
            "quickbooks.html",
            {
                "user": user,
                "clients": clients,
                "invoices": invoices,
                "jobs": jobs,
                "invoice_total": invoice_total,
            },
        )

    finally:
        db.close()


@app.get("/quickbooks/export/customers")
async def quickbooks_export_customers(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Customer",
            "Company",
            "Phone",
            "Email",
            "Notes",
        ])

        for client in clients:
            writer.writerow([
                client.name,
                client.name,
                client.phone or "",
                client.email or "",
                client.notes or "",
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=quickbooks_customers.csv"
            },
        )

    finally:
        db.close()


@app.get("/quickbooks/export/invoices")
async def quickbooks_export_invoices(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        invoices = db.query(Invoice).order_by(Invoice.id.asc()).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Customer",
            "Invoice Date",
            "Due Date",
            "Product/Service",
            "Description",
            "Qty",
            "Rate",
            "Amount",
            "Memo",
        ])

        for invoice in invoices:
            writer.writerow([
                invoice.client,
                invoice.date or "",
                "",
                "Pool / Concrete Service",
                invoice.description,
                1,
                invoice.amount or 0,
                invoice.amount or 0,
                invoice.notes or "",
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=quickbooks_invoices.csv"
            },
        )

    finally:
        db.close()
        # =========================
# PHASE 8 LITE COMMUNICATION CENTER
# =========================

@app.get("/communication")
async def communication_center(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()
        employees = db.query(Employee).order_by(Employee.name.asc()).all()
        jobs = db.query(Job).order_by(Job.id.desc()).all()

        client_phones = [client.phone for client in clients if client.phone]
        client_emails = [client.email for client in clients if client.email]
        employee_phones = [employee.phone for employee in employees if employee.phone]

        return templates.TemplateResponse(
            request,
            "communication.html",
            {
                "user": user,
                "clients": clients,
                "employees": employees,
                "jobs": jobs,
                "client_phones": client_phones,
                "client_emails": client_emails,
                "employee_phones": employee_phones,
            },
        )

    finally:
        db.close()
        # =========================
# PHASE 9 DATABASE BACKUPS
# =========================

@app.get("/backups")
async def backups_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "backups.html",
        {
            "user": user,
        },
    )


@app.get("/backup/clients")
async def backup_clients(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID",
            "Name",
            "Phone",
            "Email",
            "Notes",
        ])

        for client in clients:
            writer.writerow([
                client.id,
                client.name,
                client.phone,
                client.email,
                client.notes,
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                "attachment; filename=clients_backup.csv"
            },
        )

    finally:
        db.close()


@app.get("/backup/jobs")
async def backup_jobs(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID",
            "Client",
            "Property",
            "Address",
            "Job Type",
            "Status",
            "Crew",
            "Date",
            "Priority",
            "Notes",
        ])

        for job in jobs:
            writer.writerow([
                job.id,
                job.client,
                job.property,
                job.address,
                job.job_type,
                job.status,
                job.crew,
                job.date,
                job.priority,
                job.notes,
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=jobs_backup.csv"
            },
        )

    finally:
        db.close()


@app.get("/backup/employees")
async def backup_employees(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        employees = db.query(Employee).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID",
            "Name",
            "Phone",
            "Role",
        ])

        for employee in employees:
            writer.writerow([
                employee.id,
                employee.name,
                employee.phone,
                employee.role,
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                "attachment; filename=employees_backup.csv"
            },
        )

    finally:
        db.close()


@app.get("/backup/invoices")
async def backup_invoices(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        invoices = db.query(Invoice).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID",
            "Client",
            "Description",
            "Amount",
            "Status",
            "Date",
        ])

        for invoice in invoices:
            writer.writerow([
                invoice.id,
                invoice.client,
                invoice.description,
                invoice.amount,
                invoice.status,
                invoice.date,
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                "attachment; filename=invoices_backup.csv"
            },
        )

    finally:
        db.close()


@app.get("/backup/photos")
async def backup_photos(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        photos = db.query(PhotoLog).all()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID",
            "Job ID",
            "Client",
            "Photo Type",
            "Title",
            "Photo URL",
            "Date",
            "Notes",
        ])

        for photo in photos:
            writer.writerow([
                photo.id,
                photo.job_id,
                photo.client,
                photo.photo_type,
                photo.title,
                photo.photo_url,
                photo.date,
                photo.notes,
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=photos_backup.csv"
            },
        )

    finally:
        db.close()
        # =========================================
# PHASE 11 — DAILY FIELD LOGS
# =========================================

@app.get("/field-logs")
async def field_logs_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        logs = db.query(FieldLog).order_by(
            FieldLog.id.desc()
        ).all()

        total_hours = round(
            sum(log.total_hours or 0 for log in logs),
            2
        )

        total_fuel = round(
            sum(log.fuel_cost or 0 for log in logs),
            2
        )

        return templates.TemplateResponse(
            request,
            "field_log.html",
            {
                "user": user,
                "logs": logs,
                "total_hours": total_hours,
                "total_fuel": total_fuel,
            },
        )

    finally:
        db.close()


@app.post("/field-logs/add")
async def add_field_log(
    request: Request,

    employee_name: str = Form(...),
    crew: str = Form(""),

    client: str = Form(""),
    property: str = Form(""),
    address: str = Form(""),

    date: str = Form(""),

    arrival_time: str = Form(""),
    departure_time: str = Form(""),

    total_hours: float = Form(0),

    truck: str = Form(""),
    trailer: str = Form(""),

    tools_used: str = Form(""),
    materials_used: str = Form(""),
    equipment_used: str = Form(""),

    fuel_cost: float = Form(0),

    work_completed: str = Form(""),
    issues: str = Form(""),
    next_steps: str = Form(""),

    weather: str = Form(""),

    photo_count: int = Form(0),
):

    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:

        new_log = FieldLog(
            employee_name=employee_name,
            crew=crew,

            client=client,
            property=property,
            address=address,

            date=date,

            arrival_time=arrival_time,
            departure_time=departure_time,

            total_hours=total_hours,

            truck=truck,
            trailer=trailer,

            tools_used=tools_used,
            materials_used=materials_used,
            equipment_used=equipment_used,

            fuel_cost=fuel_cost,

            work_completed=work_completed,
            issues=issues,
            next_steps=next_steps,

            weather=weather,

            photo_count=photo_count,
        )

        db.add(new_log)
        db.commit()

        return RedirectResponse(
            url="/field-logs",
            status_code=303
        )

    finally:
        db.close()