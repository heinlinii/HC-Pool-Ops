import os
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, joinedload, relationship, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(BASE_DIR)

app = FastAPI(title="HC Pool Ops Phase 1")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "super-secret-key-change-me"),
)

app.mount("/static", StaticFiles(directory=os.path.join(APP_ROOT, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

raw_database_url = os.getenv("DATABASE_URL", "sqlite:///./poolops.db")
if raw_database_url.startswith("postgres://"):
    raw_database_url = raw_database_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if raw_database_url.startswith("sqlite") else {}
engine = create_engine(raw_database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

ROLE_ADMIN = "admin"
ROLE_CREW = "crew"
ROLE_CLIENT = "client"

JOB_STATUSES = ["Scheduled", "In Progress", "Complete"]
SLOT_STATUSES = ["Open", "Booked", "Blocked"]


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password = Column(String(100), nullable=False)
    full_name = Column(String(200), nullable=False)
    role = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)

    client_profile = relationship("Client", back_populates="portal_user", uselist=False)
    assigned_jobs = relationship("Job", back_populates="crew_user", foreign_keys="Job.crew_user_id")
    clock_entries = relationship("ClockEntry", back_populates="user")


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(100), default="")
    email = Column(String(200), default="")
    qb_customer_id = Column(String(100), default="")
    portal_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    portal_user = relationship("User", back_populates="client_profile")
    properties = relationship("Property", back_populates="client", cascade="all, delete")
    schedule_requests = relationship("ScheduleSlot", back_populates="booked_by_client")


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String(200), nullable=False)
    address = Column(String(200), default="")
    city = Column(String(100), default="")

    client = relationship("Client", back_populates="properties")
    jobs = relationship("Job", back_populates="property", cascade="all, delete")
    schedule_slots = relationship("ScheduleSlot", back_populates="property", cascade="all, delete")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(String(50), default="Scheduled")
    scheduled_for = Column(Date, nullable=True)
    crew_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")

    property = relationship("Property", back_populates="jobs")
    crew_user = relationship("User", back_populates="assigned_jobs", foreign_keys=[crew_user_id])


class ScheduleSlot(Base):
    __tablename__ = "schedule_slots"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    slot_date = Column(Date, nullable=False)
    start_time = Column(String(20), nullable=False)
    end_time = Column(String(20), nullable=False)
    status = Column(String(20), default="Open")
    notes = Column(Text, default="")
    booked_by_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)

    property = relationship("Property", back_populates="schedule_slots")
    booked_by_client = relationship("Client", back_populates="schedule_requests")


class ClockEntry(Base):
    __tablename__ = "clock_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    clock_in_at = Column(DateTime, nullable=False)
    clock_out_at = Column(DateTime, nullable=True)
    entry_date = Column(Date, nullable=False)
    notes = Column(Text, default="")

    user = relationship("User", back_populates="clock_entries")


def db_session():
    return SessionLocal()


def ensure_seed_data():
    db = db_session()
    try:
        mike = db.query(User).filter(User.username == "mike").first()
        if not mike:
            mike = User(username="mike", password="1234", full_name="Mike Heinlin", role=ROLE_ADMIN)
            db.add(mike)

        jake = db.query(User).filter(User.username == "jake").first()
        if not jake:
            jake = User(username="jake", password="1234", full_name="Jake Crew", role=ROLE_CREW)
            db.add(jake)

        smith_user = db.query(User).filter(User.username == "smith").first()
        if not smith_user:
            smith_user = User(username="smith", password="1234", full_name="Smith Family", role=ROLE_CLIENT)
            db.add(smith_user)

        db.commit()

        smith_user = db.query(User).filter(User.username == "smith").first()
        smith_client = db.query(Client).filter(Client.name == "Smith Family").first()

        if not smith_client:
            smith_client = Client(
                name="Smith Family",
                phone="812-555-0101",
                email="smith@example.com",
                qb_customer_id="QB-DEMO-1001",
                portal_user_id=smith_user.id if smith_user else None,
            )
            db.add(smith_client)
            db.commit()
        else:
            if smith_user and not smith_client.portal_user_id:
                smith_client.portal_user_id = smith_user.id
                db.commit()

        smith_client = db.query(Client).filter(Client.name == "Smith Family").first()
        prop = db.query(Property).filter(Property.name == "Backyard Pool").first()

        if smith_client and not prop:
            prop = Property(
                client_id=smith_client.id,
                name="Backyard Pool",
                address="123 Main St",
                city="Evansville",
            )
            db.add(prop)
            db.commit()

        prop = db.query(Property).filter(Property.name == "Backyard Pool").first()
        jake = db.query(User).filter(User.username == "jake").first()

        if prop and jake and db.query(Job).count() == 0:
            db.add(
                Job(
                    property_id=prop.id,
                    title="Spring Opening",
                    status="Scheduled",
                    scheduled_for=date.today(),
                    crew_user_id=jake.id,
                    notes="Demo seeded job",
                )
            )
            db.commit()

        if db.query(ScheduleSlot).count() == 0:
            db.add(
                ScheduleSlot(
                    property_id=None,
                    slot_date=date.today(),
                    start_time="08:00 AM",
                    end_time="10:00 AM",
                    status="Open",
                    notes="Client self-book slot",
                )
            )
            db.commit()
    finally:
        db.close()


Base.metadata.create_all(bind=engine)
ensure_seed_data()


def get_user(request: Request, db):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def base_context(request: Request, db, title: str):
    return {
        "request": request,
        "title": title,
        "user": get_user(request, db),
        "ROLE_ADMIN": ROLE_ADMIN,
        "ROLE_CREW": ROLE_CREW,
        "ROLE_CLIENT": ROLE_CLIENT,
    }


def require_role(request: Request, db, allowed_roles):
    user = get_user(request, db)
    if not user:
        return None, RedirectResponse(url="/login", status_code=303)
    if user.role not in allowed_roles:
        return user, RedirectResponse(url="/dashboard", status_code=303)
    return user, None


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    db = db_session()
    try:
        user = get_user(request, db)
        if user:
            return RedirectResponse(url="/dashboard", status_code=303)
        return RedirectResponse(url="/login", status_code=303)
    finally:
        db.close()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    db = db_session()
    try:
        if get_user(request, db):
            return RedirectResponse(url="/dashboard", status_code=303)

        context = base_context(request, db, "Login")
        context["error"] = None
        return templates.TemplateResponse(request=request, name="login.html", context=context)
    finally:
        db.close()


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    db = db_session()
    try:
        user = (
            db.query(User)
            .filter(
                User.username == username.strip().lower(),
                User.password == password.strip(),
                User.is_active == True,
            )
            .first()
        )

        if not user:
            context = base_context(request, db, "Login")
            context["error"] = "Invalid username or password."
            return templates.TemplateResponse(request=request, name="login.html", context=context, status_code=400)

        request.session["user_id"] = user.id
        return RedirectResponse(url="/dashboard", status_code=303)
    finally:
        db.close()


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN, ROLE_CREW, ROLE_CLIENT])
        if redirect:
            return redirect

        context = base_context(request, db, "Dashboard")

        if user.role == ROLE_ADMIN:
            context["client_count"] = db.query(Client).count()
            context["property_count"] = db.query(Property).count()
            context["job_count"] = db.query(Job).count()
            context["open_slot_count"] = db.query(ScheduleSlot).filter(ScheduleSlot.status == "Open").count()
            context["recent_jobs"] = (
                db.query(Job)
                .options(joinedload(Job.property), joinedload(Job.crew_user))
                .order_by(Job.id.desc())
                .limit(10)
                .all()
            )

        elif user.role == ROLE_CREW:
            context["today_jobs"] = (
                db.query(Job)
                .options(joinedload(Job.property))
                .filter(Job.crew_user_id == user.id)
                .order_by(Job.id.asc())
                .all()
            )
            context["open_clock"] = (
                db.query(ClockEntry)
                .filter(
                    ClockEntry.user_id == user.id,
                    ClockEntry.entry_date == date.today(),
                    ClockEntry.clock_out_at == None,
                )
                .first()
            )

        elif user.role == ROLE_CLIENT:
            client = db.query(Client).filter(Client.portal_user_id == user.id).first()
            context["client"] = client
            context["properties"] = client.properties if client else []
            context["open_slots"] = (
                db.query(ScheduleSlot)
                .filter(ScheduleSlot.status == "Open")
                .order_by(ScheduleSlot.slot_date.asc(), ScheduleSlot.start_time.asc())
                .all()
            )

        return templates.TemplateResponse(request=request, name="dashboard.html", context=context)
    finally:
        db.close()


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        context = base_context(request, db, "Users")
        context["users"] = db.query(User).order_by(User.role.asc(), User.full_name.asc()).all()
        context["error"] = None
        return templates.TemplateResponse(request=request, name="users.html", context=context)
    finally:
        db.close()


@app.post("/users")
def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        context = base_context(request, db, "Users")
        context["users"] = db.query(User).order_by(User.role.asc(), User.full_name.asc()).all()

        clean_username = username.strip().lower()
        clean_password = password.strip()
        clean_full_name = full_name.strip()
        clean_role = role.strip()

        if clean_role not in [ROLE_ADMIN, ROLE_CREW, ROLE_CLIENT]:
            context["error"] = "Please choose a valid role."
            return templates.TemplateResponse(request=request, name="users.html", context=context, status_code=400)

        if db.query(User).filter(User.username == clean_username).first():
            context["error"] = "Username already exists."
            return templates.TemplateResponse(request=request, name="users.html", context=context, status_code=400)

        db.add(
            User(
                username=clean_username,
                password=clean_password,
                full_name=clean_full_name,
                role=clean_role,
            )
        )
        db.commit()
        return RedirectResponse(url="/users", status_code=303)
    finally:
        db.close()


@app.post("/users/delete")
def delete_user(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        current_user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        user_to_delete = db.query(User).filter(User.id == id).first()
        if user_to_delete and current_user and user_to_delete.id != current_user.id:
            db.delete(user_to_delete)
            db.commit()

        return RedirectResponse(url="/users", status_code=303)
    finally:
        db.close()


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        context = base_context(request, db, "Clients")
        context["clients"] = (
            db.query(Client)
            .options(joinedload(Client.portal_user))
            .order_by(Client.name.asc())
            .all()
        )
        context["client_users"] = db.query(User).filter(User.role == ROLE_CLIENT).order_by(User.full_name.asc()).all()
        context["error"] = None
        return templates.TemplateResponse(request=request, name="clients.html", context=context)
    finally:
        db.close()


@app.post("/clients")
def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    qb_customer_id: str = Form(""),
    portal_user_id: Optional[str] = Form(""),
):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        clean_name = name.strip()
        parsed_portal_user_id = int(portal_user_id) if str(portal_user_id).strip() else None

        db.add(
            Client(
                name=clean_name,
                phone=phone.strip(),
                email=email.strip(),
                qb_customer_id=qb_customer_id.strip(),
                portal_user_id=parsed_portal_user_id,
            )
        )
        db.commit()
        return RedirectResponse(url="/clients", status_code=303)
    finally:
        db.close()


@app.post("/clients/delete")
def delete_client(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        client = db.query(Client).filter(Client.id == id).first()
        if client:
            db.delete(client)
            db.commit()
        return RedirectResponse(url="/clients", status_code=303)
    finally:
        db.close()


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        context = base_context(request, db, "Properties")
        context["clients"] = db.query(Client).order_by(Client.name.asc()).all()
        context["properties"] = (
            db.query(Property)
            .options(joinedload(Property.client))
            .order_by(Property.name.asc())
            .all()
        )
        context["error"] = None
        return templates.TemplateResponse(request=request, name="properties.html", context=context)
    finally:
        db.close()


@app.post("/properties")
def add_property(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        db.add(
            Property(
                client_id=client_id,
                name=name.strip(),
                address=address.strip(),
                city=city.strip(),
            )
        )
        db.commit()
        return RedirectResponse(url="/properties", status_code=303)
    finally:
        db.close()


@app.post("/properties/delete")
def delete_property(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        prop = db.query(Property).filter(Property.id == id).first()
        if prop:
            db.delete(prop)
            db.commit()
        return RedirectResponse(url="/properties", status_code=303)
    finally:
        db.close()


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        context = base_context(request, db, "Jobs")
        context["properties"] = db.query(Property).order_by(Property.name.asc()).all()
        context["crew_users"] = db.query(User).filter(User.role == ROLE_CREW).order_by(User.full_name.asc()).all()
        context["jobs"] = (
            db.query(Job)
            .options(joinedload(Job.property), joinedload(Job.crew_user))
            .order_by(Job.id.desc())
            .all()
        )
        context["statuses"] = JOB_STATUSES
        context["error"] = None
        return templates.TemplateResponse(request=request, name="jobs.html", context=context)
    finally:
        db.close()


@app.post("/jobs")
def add_job(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    status: str = Form(...),
    scheduled_for: str = Form(""),
    crew_user_id: Optional[str] = Form(""),
    notes: str = Form(""),
):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        parsed_date = datetime.strptime(scheduled_for, "%Y-%m-%d").date() if scheduled_for.strip() else None
        parsed_crew_id = int(crew_user_id) if str(crew_user_id).strip() else None

        db.add(
            Job(
                property_id=property_id,
                title=title.strip(),
                status=status,
                scheduled_for=parsed_date,
                crew_user_id=parsed_crew_id,
                notes=notes.strip(),
            )
        )
        db.commit()
        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/delete")
def delete_job(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        job = db.query(Job).filter(Job.id == id).first()
        if job:
            db.delete(job)
            db.commit()
        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/status")
def update_job_status(request: Request, id: int = Form(...), status: str = Form(...)):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN, ROLE_CREW])
        if redirect:
            return redirect

        job = db.query(Job).filter(Job.id == id).first()
        if job and status in JOB_STATUSES:
            if user.role == ROLE_ADMIN or job.crew_user_id == user.id:
                job.status = status
                db.commit()

        if user.role == ROLE_CREW:
            return RedirectResponse(url="/my-day", status_code=303)
        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        context = base_context(request, db, "Schedule")
        context["properties"] = (
            db.query(Property)
            .options(joinedload(Property.client))
            .order_by(Property.name.asc())
            .all()
        )
        context["slots"] = (
            db.query(ScheduleSlot)
            .options(joinedload(ScheduleSlot.property), joinedload(ScheduleSlot.booked_by_client))
            .order_by(ScheduleSlot.slot_date.asc(), ScheduleSlot.start_time.asc())
            .all()
        )
        context["slot_statuses"] = SLOT_STATUSES
        context["error"] = None
        return templates.TemplateResponse(request=request, name="schedule.html", context=context)
    finally:
        db.close()


@app.post("/schedule")
def add_schedule_slot(
    request: Request,
    slot_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    status: str = Form(...),
    property_id: Optional[str] = Form(""),
    notes: str = Form(""),
):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        parsed_date = datetime.strptime(slot_date, "%Y-%m-%d").date()
        parsed_property_id = int(property_id) if str(property_id).strip() else None

        db.add(
            ScheduleSlot(
                property_id=parsed_property_id,
                slot_date=parsed_date,
                start_time=start_time.strip(),
                end_time=end_time.strip(),
                status=status,
                notes=notes.strip(),
            )
        )
        db.commit()
        return RedirectResponse(url="/schedule", status_code=303)
    finally:
        db.close()


@app.post("/schedule/delete")
def delete_schedule_slot(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_ADMIN])
        if redirect:
            return redirect

        slot = db.query(ScheduleSlot).filter(ScheduleSlot.id == id).first()
        if slot:
            db.delete(slot)
            db.commit()
        return RedirectResponse(url="/schedule", status_code=303)
    finally:
        db.close()


@app.post("/schedule/book")
def book_schedule_slot(request: Request, id: int = Form(...), property_id: int = Form(...)):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_CLIENT])
        if redirect:
            return redirect

        client = db.query(Client).filter(Client.portal_user_id == user.id).first()
        slot = db.query(ScheduleSlot).filter(ScheduleSlot.id == id).first()

        if client and slot and slot.status == "Open":
            slot.status = "Booked"
            slot.booked_by_client_id = client.id
            slot.property_id = property_id
            db.commit()

        return RedirectResponse(url="/client-portal", status_code=303)
    finally:
        db.close()


@app.get("/my-day", response_class=HTMLResponse)
def my_day_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_CREW])
        if redirect:
            return redirect

        context = base_context(request, db, "My Day")
        context["jobs"] = (
            db.query(Job)
            .options(joinedload(Job.property))
            .filter(Job.crew_user_id == user.id)
            .order_by(Job.id.asc())
            .all()
        )
        context["open_clock"] = (
            db.query(ClockEntry)
            .filter(
                ClockEntry.user_id == user.id,
                ClockEntry.entry_date == date.today(),
                ClockEntry.clock_out_at == None,
            )
            .first()
        )
        context["today_entries"] = (
            db.query(ClockEntry)
            .filter(ClockEntry.user_id == user.id)
            .order_by(ClockEntry.id.desc())
            .limit(10)
            .all()
        )
        return templates.TemplateResponse(request=request, name="my_day.html", context=context)
    finally:
        db.close()


@app.post("/clock/in")
def clock_in(request: Request, notes: str = Form("")):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_CREW])
        if redirect:
            return redirect

        existing = (
            db.query(ClockEntry)
            .filter(
                ClockEntry.user_id == user.id,
                ClockEntry.entry_date == date.today(),
                ClockEntry.clock_out_at == None,
            )
            .first()
        )

        if not existing:
            db.add(
                ClockEntry(
                    user_id=user.id,
                    clock_in_at=datetime.now(),
                    entry_date=date.today(),
                    notes=notes.strip(),
                )
            )
            db.commit()

        return RedirectResponse(url="/my-day", status_code=303)
    finally:
        db.close()


@app.post("/clock/out")
def clock_out(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_CREW])
        if redirect:
            return redirect

        existing = (
            db.query(ClockEntry)
            .filter(
                ClockEntry.user_id == user.id,
                ClockEntry.entry_date == date.today(),
                ClockEntry.clock_out_at == None,
            )
            .first()
        )

        if existing:
            existing.clock_out_at = datetime.now()
            db.commit()

        return RedirectResponse(url="/my-day", status_code=303)
    finally:
        db.close()


@app.get("/client-portal", response_class=HTMLResponse)
def client_portal_page(request: Request):
    db = db_session()
    try:
        user, redirect = require_role(request, db, [ROLE_CLIENT])
        if redirect:
            return redirect

        client = db.query(Client).filter(Client.portal_user_id == user.id).first()

        context = base_context(request, db, "Client Portal")
        context["client"] = client
        context["properties"] = client.properties if client else []
        context["open_slots"] = (
            db.query(ScheduleSlot)
            .filter(ScheduleSlot.status == "Open")
            .order_by(ScheduleSlot.slot_date.asc(), ScheduleSlot.start_time.asc())
            .all()
        )
        context["my_booked_slots"] = (
            db.query(ScheduleSlot)
            .filter(ScheduleSlot.booked_by_client_id == client.id)
            .order_by(ScheduleSlot.slot_date.asc(), ScheduleSlot.start_time.asc())
            .all()
            if client
            else []
        )

        return templates.TemplateResponse(request=request, name="client_portal.html", context=context)
    finally:
        db.close()