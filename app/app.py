from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import csv
import io

app = FastAPI(title="PoolOps2")

app.add_middleware(
    SessionMiddleware,
    secret_key="poolops2-phase-2-secret",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


USERS = {
    "mike": {"password": "5500", "role": "admin", "name": "Mike"},
    "randy": {"password": "0318", "role": "crew", "name": "Randy"},
}


EMPLOYEES = [
    {"id": 1, "name": "Mike", "role": "Admin", "phone": "", "email": "", "active": True},
    {"id": 2, "name": "Randy", "role": "Crew", "phone": "", "email": "", "active": True},
]


CLIENTS = [
    {"id": 1, "name": "Smith Residence", "phone": "", "email": "", "notes": "Sample client."},
    {"id": 2, "name": "Johnson Backyard", "phone": "", "email": "", "notes": "Sample remodel client."},
]


PROPERTIES = [
    {
        "id": 1,
        "client_id": 1,
        "client": "Smith Residence",
        "address": "Evansville, IN",
        "pool_type": "Concrete Pool",
        "notes": "20x40 rectangle pool.",
    },
    {
        "id": 2,
        "client_id": 2,
        "client": "Johnson Backyard",
        "address": "Newburgh, IN",
        "pool_type": "Pool Remodel",
        "notes": "Tile and coping replacement.",
    },
]


JOBS = [
    {
        "id": 1,
        "client": "Smith Residence",
        "property": "Evansville, IN",
        "address": "Evansville, IN",
        "job_type": "Concrete Pool",
        "status": "Scheduled",
        "crew": "Randy",
        "date": "Today",
        "priority": "Normal",
        "notes": "20x40 rectangle pool.",
    },
    {
        "id": 2,
        "client": "Johnson Backyard",
        "property": "Newburgh, IN",
        "address": "Newburgh, IN",
        "job_type": "Pool Remodel",
        "status": "Pending",
        "crew": "Unassigned",
        "date": "Tomorrow",
        "priority": "High",
        "notes": "Tile and coping replacement.",
    },
]


INVOICES = [
    {
        "id": 1,
        "job_id": 1,
        "client": "Smith Residence",
        "description": "Deposit invoice",
        "amount": 5000.00,
        "status": "Draft",
        "date": "Today",
        "notes": "Sample billing record.",
    }
]


JOB_COSTS = [
    {
        "id": 1,
        "job_id": 1,
        "client": "Smith Residence",
        "labor": 1200.00,
        "materials": 2500.00,
        "subs": 0.00,
        "equipment": 350.00,
        "fuel": 125.00,
        "other": 0.00,
        "invoice_amount": 5000.00,
        "notes": "Sample job cost record.",
    }
]


TIME_CLOCK = {
    "randy": {"clocked_in": False, "current_job": None}
}


def get_current_user(request: Request):
    username = request.session.get("username")
    if not username:
        return None

    user = USERS.get(username)
    if not user:
        return None

    return {
        "username": username,
        "name": user["name"],
        "role": user["role"],
    }


def require_login(request: Request):
    return get_current_user(request)


def require_admin(request: Request):
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        return None
    return user


def next_id(items):
    return max([item["id"] for item in items], default=0) + 1


def find_by_id(items, item_id: int):
    for item in items:
        if item["id"] == item_id:
            return item
    return None


def job_options():
    return [
        {
            "id": job["id"],
            "label": f'#{job["id"]} - {job["client"]} - {job["job_type"]}',
            "client": job["client"],
        }
        for job in JOBS
    ]


def cost_totals(cost):
    total_cost = (
        float(cost["labor"])
        + float(cost["materials"])
        + float(cost["subs"])
        + float(cost["equipment"])
        + float(cost["fuel"])
        + float(cost["other"])
    )

    invoice_amount = float(cost["invoice_amount"])
    profit = invoice_amount - total_cost
    margin = 0

    if invoice_amount > 0:
        margin = round((profit / invoice_amount) * 100, 2)

    return {
        "total_cost": round(total_cost, 2),
        "profit": round(profit, 2),
        "margin": margin,
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

    user = USERS.get(username)

    if not user or user["password"] != password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password."},
            status_code=401,
        )

    request.session["username"] = username

    if user["role"] == "crew":
        return RedirectResponse(url="/crew", status_code=303)

    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "PoolOps2",
        "phase": "2",
    }


@app.get("/dashboard")
async def dashboard(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if user["role"] != "admin":
        return RedirectResponse(url="/crew", status_code=303)

    total_invoice_amount = round(sum(float(invoice["amount"]) for invoice in INVOICES), 2)

    total_cost = 0
    total_revenue = 0

    for cost in JOB_COSTS:
        totals = cost_totals(cost)
        total_cost += totals["total_cost"]
        total_revenue += float(cost["invoice_amount"])

    total_profit = round(total_revenue - total_cost, 2)

    stats = {
        "total_jobs": len(JOBS),
        "scheduled": len([job for job in JOBS if job["status"] == "Scheduled"]),
        "pending": len([job for job in JOBS if job["status"] == "Pending"]),
        "in_progress": len([job for job in JOBS if job["status"] == "In Progress"]),
        "completed": len([job for job in JOBS if job["status"] == "Completed"]),
        "clients": len(CLIENTS),
        "properties": len(PROPERTIES),
        "employees": len(EMPLOYEES),
        "invoices": len(INVOICES),
        "invoice_total": total_invoice_amount,
        "tracked_profit": total_profit,
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "jobs": JOBS,
            "clients": CLIENTS,
            "properties": PROPERTIES,
            "employees": EMPLOYEES,
            "stats": stats,
        },
    )


@app.get("/jobs")
async def jobs_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "user": user,
            "jobs": JOBS,
            "clients": CLIENTS,
            "properties": PROPERTIES,
            "employees": EMPLOYEES,
        },
    )


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

    clean_address = address.strip()

    JOBS.append(
        {
            "id": next_id(JOBS),
            "client": client.strip(),
            "property": clean_address,
            "address": clean_address,
            "job_type": job_type.strip(),
            "status": status.strip(),
            "crew": crew.strip() or "Unassigned",
            "date": date.strip(),
            "priority": priority.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/jobs", status_code=303)


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

    job = find_by_id(JOBS, job_id)

    if job:
        job["client"] = client.strip()
        job["property"] = address.strip()
        job["address"] = address.strip()
        job["job_type"] = job_type.strip()
        job["date"] = date.strip()
        job["crew"] = crew.strip()
        job["status"] = status.strip()
        job["priority"] = priority.strip()
        job["notes"] = notes.strip()

    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/delete/{job_id}")
async def delete_job(request: Request, job_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    global JOBS
    JOBS = [job for job in JOBS if job["id"] != job_id]

    return RedirectResponse(url="/jobs", status_code=303)


@app.get("/schedule")
async def schedule_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(request, "schedule.html", {"user": user, "jobs": JOBS})


@app.post("/schedule/status/{job_id}")
async def update_schedule_status(request: Request, job_id: int, status: str = Form(...)):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)
    if job:
        job["status"] = status.strip()

    return RedirectResponse(url="/schedule", status_code=303)


@app.get("/crew")
async def crew_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    crew_jobs = [
        job
        for job in JOBS
        if job["crew"].lower() in [user["name"].lower(), user["username"].lower()]
        or job["crew"].lower() == "unassigned"
        or user["role"] == "admin"
    ]

    clock = TIME_CLOCK.get(user["username"], {"clocked_in": False, "current_job": None})

    return templates.TemplateResponse(
        request,
        "crew.html",
        {"user": user, "jobs": crew_jobs, "clock": clock},
    )


@app.post("/crew/clock-in")
async def clock_in(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    old_clock = TIME_CLOCK.get(user["username"], {"clocked_in": False, "current_job": None})

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

    TIME_CLOCK[user["username"]] = {"clocked_in": False, "current_job": None}

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/start-job/{job_id}")
async def start_job(request: Request, job_id: int):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)

    if job:
        job["status"] = "In Progress"
        TIME_CLOCK[user["username"]] = {"clocked_in": True, "current_job": job_id}

    return RedirectResponse(url="/crew", status_code=303)


@app.post("/crew/complete-job/{job_id}")
async def complete_job(request: Request, job_id: int):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    job = find_by_id(JOBS, job_id)

    if job:
        job["status"] = "Completed"

        if TIME_CLOCK.get(user["username"], {}).get("current_job") == job_id:
            TIME_CLOCK[user["username"]]["current_job"] = None

    return RedirectResponse(url="/crew", status_code=303)


@app.get("/clients")
async def clients_page(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(request, "clients.html", {"user": user, "clients": CLIENTS})


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

    CLIENTS.append(
        {
            "id": next_id(CLIENTS),
            "name": name.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/clients", status_code=303)


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

    client = find_by_id(CLIENTS, client_id)

    if client:
        old_name = client["name"]
        client["name"] = name.strip()
        client["phone"] = phone.strip()
        client["email"] = email.strip()
        client["notes"] = notes.strip()

        for prop in PROPERTIES:
            if prop["client"] == old_name:
                prop["client"] = client["name"]

        for job in JOBS:
            if job["client"] == old_name:
                job["client"] = client["name"]

    return RedirectResponse(url="/clients", status_code=303)


@app.post("/clients/delete/{client_id}")
async def delete_client(request: Request, client_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    global CLIENTS
    CLIENTS = [client for client in CLIENTS if client["id"] != client_id]

    return RedirectResponse(url="/clients", status_code=303)


@app.get("/properties")
async def properties_page(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "properties.html",
        {"user": user, "clients": CLIENTS, "properties": PROPERTIES},
    )


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

    selected_client = None

    for c in CLIENTS:
        if c["name"] == client:
            selected_client = c
            break

    PROPERTIES.append(
        {
            "id": next_id(PROPERTIES),
            "client_id": selected_client["id"] if selected_client else None,
            "client": client.strip(),
            "address": address.strip(),
            "pool_type": pool_type.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/properties", status_code=303)


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

    prop = find_by_id(PROPERTIES, property_id)

    if prop:
        old_address = prop["address"]

        selected_client = None
        for c in CLIENTS:
            if c["name"] == client:
                selected_client = c
                break

        prop["client_id"] = selected_client["id"] if selected_client else None
        prop["client"] = client.strip()
        prop["address"] = address.strip()
        prop["pool_type"] = pool_type.strip()
        prop["notes"] = notes.strip()

        for job in JOBS:
            if job["address"] == old_address:
                job["property"] = prop["address"]
                job["address"] = prop["address"]
                job["client"] = prop["client"]

    return RedirectResponse(url="/properties", status_code=303)


@app.post("/properties/delete/{property_id}")
async def delete_property(request: Request, property_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    global PROPERTIES
    PROPERTIES = [prop for prop in PROPERTIES if prop["id"] != property_id]

    return RedirectResponse(url="/properties", status_code=303)


@app.get("/employees")
async def employees_page(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "employees.html",
        {"user": user, "employees": EMPLOYEES},
    )


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

    EMPLOYEES.append(
        {
            "id": next_id(EMPLOYEES),
            "name": name.strip(),
            "role": role.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
            "active": active == "true",
        }
    )

    return RedirectResponse(url="/employees", status_code=303)


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

    employee = find_by_id(EMPLOYEES, employee_id)

    if employee:
        old_name = employee["name"]
        employee["name"] = name.strip()
        employee["role"] = role.strip()
        employee["phone"] = phone.strip()
        employee["email"] = email.strip()
        employee["active"] = active == "true"

        for job in JOBS:
            if job["crew"] == old_name:
                job["crew"] = employee["name"]

    return RedirectResponse(url="/employees", status_code=303)


@app.post("/employees/delete/{employee_id}")
async def delete_employee(request: Request, employee_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    global EMPLOYEES
    EMPLOYEES = [employee for employee in EMPLOYEES if employee["id"] != employee_id]

    return RedirectResponse(url="/employees", status_code=303)


@app.get("/billing")
async def billing_page(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    total_billed = round(sum(float(invoice["amount"]) for invoice in INVOICES), 2)
    paid_total = round(
        sum(float(invoice["amount"]) for invoice in INVOICES if invoice["status"] == "Paid"),
        2,
    )
    open_total = round(total_billed - paid_total, 2)

    return templates.TemplateResponse(
        request,
        "billing.html",
        {
            "user": user,
            "invoices": INVOICES,
            "jobs": job_options(),
            "total_billed": total_billed,
            "paid_total": paid_total,
            "open_total": open_total,
        },
    )


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

    job = find_by_id(JOBS, job_id)
    client_name = job["client"] if job else "Unknown Client"

    INVOICES.append(
        {
            "id": next_id(INVOICES),
            "job_id": job_id,
            "client": client_name,
            "description": description.strip(),
            "amount": round(float(amount), 2),
            "status": status.strip(),
            "date": date.strip(),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/billing", status_code=303)


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

    invoice = find_by_id(INVOICES, invoice_id)

    if invoice:
        invoice["description"] = description.strip()
        invoice["amount"] = round(float(amount), 2)
        invoice["status"] = status.strip()
        invoice["date"] = date.strip()
        invoice["notes"] = notes.strip()

    return RedirectResponse(url="/billing", status_code=303)


@app.post("/billing/delete/{invoice_id}")
async def delete_invoice(request: Request, invoice_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    global INVOICES
    INVOICES = [invoice for invoice in INVOICES if invoice["id"] != invoice_id]

    return RedirectResponse(url="/billing", status_code=303)


@app.get("/billing/export")
async def export_invoices(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Invoice ID", "Job ID", "Client", "Description", "Amount", "Status", "Date", "Notes"])

    for invoice in INVOICES:
        writer.writerow(
            [
                invoice["id"],
                invoice["job_id"],
                invoice["client"],
                invoice["description"],
                invoice["amount"],
                invoice["status"],
                invoice["date"],
                invoice["notes"],
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poolops2_invoices.csv"},
    )


@app.get("/job-costing")
async def job_costing_page(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    enriched_costs = []

    for cost in JOB_COSTS:
        totals = cost_totals(cost)
        enriched = dict(cost)
        enriched["total_cost"] = totals["total_cost"]
        enriched["profit"] = totals["profit"]
        enriched["margin"] = totals["margin"]
        enriched_costs.append(enriched)

    total_revenue = round(sum(float(cost["invoice_amount"]) for cost in JOB_COSTS), 2)
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
            "jobs": job_options(),
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "total_profit": total_profit,
            "overall_margin": overall_margin,
        },
    )


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

    job = find_by_id(JOBS, job_id)
    client_name = job["client"] if job else "Unknown Client"

    JOB_COSTS.append(
        {
            "id": next_id(JOB_COSTS),
            "job_id": job_id,
            "client": client_name,
            "labor": round(float(labor), 2),
            "materials": round(float(materials), 2),
            "subs": round(float(subs), 2),
            "equipment": round(float(equipment), 2),
            "fuel": round(float(fuel), 2),
            "other": round(float(other), 2),
            "invoice_amount": round(float(invoice_amount), 2),
            "notes": notes.strip(),
        }
    )

    return RedirectResponse(url="/job-costing", status_code=303)


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

    cost = find_by_id(JOB_COSTS, cost_id)

    if cost:
        cost["labor"] = round(float(labor), 2)
        cost["materials"] = round(float(materials), 2)
        cost["subs"] = round(float(subs), 2)
        cost["equipment"] = round(float(equipment), 2)
        cost["fuel"] = round(float(fuel), 2)
        cost["other"] = round(float(other), 2)
        cost["invoice_amount"] = round(float(invoice_amount), 2)
        cost["notes"] = notes.strip()

    return RedirectResponse(url="/job-costing", status_code=303)


@app.post("/job-costing/delete/{cost_id}")
async def delete_job_cost(request: Request, cost_id: int):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    global JOB_COSTS
    JOB_COSTS = [cost for cost in JOB_COSTS if cost["id"] != cost_id]

    return RedirectResponse(url="/job-costing", status_code=303)


@app.get("/job-costing/export")
async def export_job_costing(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

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

    for cost in JOB_COSTS:
        totals = cost_totals(cost)
        writer.writerow(
            [
                cost["id"],
                cost["job_id"],
                cost["client"],
                cost["labor"],
                cost["materials"],
                cost["subs"],
                cost["equipment"],
                cost["fuel"],
                cost["other"],
                totals["total_cost"],
                cost["invoice_amount"],
                totals["profit"],
                totals["margin"],
                cost["notes"],
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poolops2_job_costing.csv"},
    )