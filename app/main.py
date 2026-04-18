from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload
import hashlib

from .database import SessionLocal, engine
from .models import Base, User, Employee

from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()

# Sessions (required for login)
app.add_middleware(SessionMiddleware, secret_key="super-secret-key")

# Static + Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Create tables
Base.metadata.create_all(bind=engine)

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# PASSWORD FUNCTIONS
# =========================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


# =========================
# ROUTES
# =========================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# LOGIN PAGE
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


# LOGIN SUBMIT
@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .options(joinedload(User.employee))
        .filter(User.username == username.strip(), User.is_active == True)
        .first()
    )

    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "User not found"},
            status_code=400,
        )

    if not verify_password(password.strip(), user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Wrong password"},
            status_code=400,
        )

    request.session["user_id"] = user.id

    if user.role in ["admin", "office"]:
        return RedirectResponse("/", status_code=303)

    return RedirectResponse("/field", status_code=303)


# =========================
# DEV: RESET USERS
# =========================
@app.get("/dev/reset-users")
def reset_users(db: Session = Depends(get_db)):
    db.query(User).delete()

    employee1 = db.query(Employee).filter(Employee.name == "Mike Heinlin").first()
    employee2 = db.query(Employee).filter(Employee.name == "Jake Turner").first()

    admin_user = User(
        username="mike",
        password_hash=hash_password("1234"),
        role="admin",
        employee_id=employee1.id if employee1 else None,
        is_active=True,
    )

    office_user = User(
        username="office",
        password_hash=hash_password("1234"),
        role="office",
        employee_id=None,
        is_active=True,
    )

    field_user = User(
        username="jake",
        password_hash=hash_password("1234"),
        role="field",
        employee_id=employee2.id if employee2 else None,
        is_active=True,
    )

    db.add_all([admin_user, office_user, field_user])
    db.commit()

    return {
        "status": "users reset",
        "logins": [
            "mike / 1234",
            "office / 1234",
            "jake / 1234",
        ],
    }


# =========================
# FIELD PAGE (example)
# =========================
@app.get("/field", response_class=HTMLResponse)
def field_page(request: Request):
    return templates.TemplateResponse("field.html", {"request": request})