from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

app = FastAPI()

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Temporary in-memory client data
CLIENTS = [
    {
        "id": 1,
        "name": "John Smith",
        "phone": "(812) 555-0101",
        "email": "john@example.com",
        "address": "123 Main St, Evansville, IN",
        "notes": "Needs spring opening and weekly service.",
    },
    {
        "id": 2,
        "name": "Sarah Johnson",
        "phone": "(812) 555-0102",
        "email": "sarah@example.com",
        "address": "456 Oak Ave, Newburgh, IN",
        "notes": "Automatic cover issue last season.",
    },
]

# -------------------------
# AUTH / ENTRY
# -------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
def login(
    username: str = Form(...),
    password: str = Form(...),
):
    # TEMP login: lets us move through app while building structure
    # We can replace this with real auth/database users next
    if username.strip() and password.strip():
        return RedirectResponse("/dashboard", status_code=302)

    return RedirectResponse("/login", status_code=302)

# -------------------------
# DASHBOARD
# -------------------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

# -------------------------
# CLIENTS
# -------------------------

@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "clients": CLIENTS,
        },
    )


@app.get("/clients/new", response_class=HTMLResponse)
def new_client_page(request: Request):
    return templates.TemplateResponse("client_new.html", {"request": request})


@app.post("/clients/new")
def create_client(
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
):
    next_id = max([c["id"] for c in CLIENTS], default=0) + 1

    CLIENTS.append(
        {
            "id": next_id,
            "name": name,
            "phone": phone,
            "email": email,
            "address": address,
            "notes": notes,
        }
    )

    return RedirectResponse("/clients", status_code=302)

# -------------------------
# PLACEHOLDER PAGES
# -------------------------

@app.get("/jobs", response_class=HTMLResponse)
def jobs_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Jobs | HC Pool Ops</title>
        <link rel="stylesheet" href="/static/style.css" />
    </head>
    <body>
        <div class="page-wrap">
            <div class="page-head">
                <div>
                    <h1>Jobs</h1>
                    <p>Jobs page coming next.</p>
                </div>
                <div class="head-actions">
                    <a class="btn" href="/dashboard">Back to Dashboard</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """)


@app.get("/employees", response_class=HTMLResponse)
def employees_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Employees | HC Pool Ops</title>
        <link rel="stylesheet" href="/static/style.css" />
    </head>
    <body>
        <div class="page-wrap">
            <div class="page-head">
                <div>
                    <h1>Employees</h1>
                    <p>Employees page coming next.</p>
                </div>
                <div class="head-actions">
                    <a class="btn" href="/dashboard">Back to Dashboard</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """)