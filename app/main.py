from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Configure Jinja2 templates directory
templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Send everyone to the login page by default
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    # Simple demo login check—replace with real auth later
    if username == "admin" and password == "admin":
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    # Render our new dashboard template
    return templates.TemplateResponse("dashboard.html", {"request": request})