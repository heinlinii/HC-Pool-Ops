from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# demo in-memory data for now
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

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    return RedirectResponse("/dashboard", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

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

@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return HTMLResponse("""
    <html><head><title>Jobs</title><link rel="stylesheet" href="/static/style.css"></head>
    <body class="app-shell"><div class="page-wrap">
    <h1>Jobs</h1><p>Jobs page coming next.</p><p><a href="/dashboard">← Back to Dashboard</a></p>
    </div></body></html>
    """)

@app.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request):
    return HTMLResponse("""
    <html><head><title>Employees</title><link rel="stylesheet" href="/static/style.css"></head>
    <body class="app-shell"><div class="page-wrap">
    <h1>Employees</h1><p>Employees page coming next.</p><p><a href="/dashboard">← Back to Dashboard</a></p>
    </div></body></html>
    """)