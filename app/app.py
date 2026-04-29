from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path

app = FastAPI()

# Sessions
app.add_middleware(
    SessionMiddleware,
    secret_key="poolops-secret-key"
)

# Paths
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Users
users = {
    "mike": {"password": "1234", "role": "admin"},
    "jake": {"password": "1234", "role": "crew"},
    "smith": {"password": "1234", "role": "client"},
}

# Health
@app.get("/health")
def health():
    return {"status": "ok"}

# Home
@app.get("/", response_class=HTMLResponse)
def home():
    return '<h1>PoolOps Pro is LIVE</h1><a href="/login">Go to Login</a>'

# Login page
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

# Login submit
@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.lower()

    if username not in users or users[username]["password"] != password:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid login"},
            status_code=401
        )

    request.session["user"] = username
    request.session["role"] = users[username]["role"]

    return RedirectResponse("/dashboard", status_code=303)

# Dashboard (SAFE VERSION)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse("/login", status_code=303)

    return f"<h1>Welcome {user}</h1><p>Login works.</p>"

# Logout
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)