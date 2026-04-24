import os
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from functools import wraps
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
    inspect,
)
from sqlalchemy.orm import declarative_base, joinedload, relationship, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(BASE_DIR)

app = FastAPI(title="HC Pool Ops")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "change-this-secret"),
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
    assigned_jobs = relationship("Job", back_populates="crew_user")
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
    properties = relationship("Property", back_populates="client", cascade="all, delete-orphan")
    schedule_requests = relationship("ScheduleSlot", back_populates="booked_by_client")


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String(200), nullable=False)
    address = Column(String(200), default="")
    city = Column(String(100), default="")

    client = relationship("Client", back_populates="properties")
    jobs = relationship("Job", back_populates="property", cascade="all, delete-orphan")
    schedule_slots = relationship("ScheduleSlot", back_populates="property")


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
    crew_user = relationship("User", back_populates="assigned_jobs")


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


def schema_is_valid() -> bool:
    inspector = inspect(engine)

    required = {
        "users": {"id", "username", "password", "full_name", "role", "is_active"},
        "clients": {"id", "name", "phone", "email", "qb_customer_id", "portal_user_id"},
        "properties": {"id", "client_id", "name", "address", "city"},
        "jobs": {"id", "property_id", "title", "status", "scheduled_for", "crew_user_id", "notes"},
        "schedule_slots": {
            "id",
            "property_id",
            "slot_date",
            "start_time",
            "end_time",
            "status",
            "notes",
            "booked_by_client_id",
        },
        "clock_entries": {"id", "user_id", "clock_in_at", "clock_out_at", "entry_date", "notes"},
    }

    existing_tables = set(inspector.get_table_names())

    for table_name, required_columns in required.items():
        if table_name not in existing_tables:
            return False

        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        if not required_columns.issubset(existing_columns):
            return False

    return True


def initialize_database():
    if not schema_is_valid():
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    else:
        Base.metadata.create_all(bind=engine)

    db = db_session()
    try:
        existing_admin = db.query(User).filter(User.username == "mike").first()
        if existing_admin:
            return

        admin = User(
            username="mike",
            password="1234",
            full_name="Mike Heinlin",
            role=ROLE_ADMIN,
            is_active=True,
        )

        crew = User(
            username="jake",
            password="1234",
            full_name="Jake Crew",
            role=ROLE_CREW,
            is_active=True,
        )

        client_user = User(
            username="smith",
            password="1234",
            full_name="Smith Family",
            role=ROLE_CLIENT,
            is_active=True,
        )

        db.add_all([admin, crew, client_user])
        db.commit()

        client_user = db.query(User).filter(User.username == "smith").first()
        crew = db.query(User).filter(User.username == "jake").first()

        client = Client(
            name="Smith Family",
            phone="812-555-0101",
            email="smith@example.com",
            qb_customer_id="QB-DEMO-1001",
            portal_user_id=client_user.id,
        )
        db.add(client)
        db.commit()

        client = db.query(Client).filter(Client.name == "Smith Family").first()

        prop = Property(
            client_id=client.id,
            name="Backyard Pool",
            address="123 Main St",
            city="Evansville",
        )
        db.add(prop)
        db.commit()

        prop = db.query(Property).filter(Property.name == "Backyard Pool").first()

        job = Job(
            property_id=prop.id,
            title="Spring Opening",
            status="Scheduled",
            scheduled_for=date.today(),
            crew_user_id=crew.id,
            notes="Demo seeded job",
        )

        slot = ScheduleSlot(
            property_id=None,
            slot_date=date.today(),
            start_time="08:00 AM",
            end_time="10:00 AM",
            status="Open",
            notes="Client self-book slot",
            booked_by_client_id=None,
        )

        db.add_all([job, slot])
        db.commit()
    finally:
        db.close()


initialize_database()


def current_user(request: Request, db):
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    return (
        db.query(User)
        .filter(User.id == user_id, User.is_active == True)
        .first()
    )


def context_base(request: Request, db, title: str):
    return {
        "request": request,
        "title": title,
        "user": current_user(request, db),
        "ROLE_ADMIN": ROLE_ADMIN,
        "ROLE_CREW": ROLE_CREW,
        "ROLE_CLIENT": ROLE_CLIENT,
    }


def redirect_if_not_logged_in(request: Request, db):
    if not current_user(request, db):
        return RedirectResponse(url="/login", status_code=303)
    return None


def redirect_if_not_role(request: Request, db, allowed_roles):
    user = current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if user.role not in allowed_roles:
        return RedirectResponse(url="/dashboard", status_code=303)
    return None


def render(request: Request, template_name: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=status_code,
    )

    def role_required(*allowed_roles):
    def decorator(route_func):
        @wraps(route_func)
        def wrapper(request: Request, *args, **kwargs):
            db = db_session()
            try:
                user = get_user(request, db)
                if not user:
                    return RedirectResponse(url="/login", status_code=303)

                if user.role not in allowed_roles:
                    return RedirectResponse(url="/dashboard", status_code=303)
            finally:
                db.close()

            return route_func(request, *args, **kwargs)

        return wrapper

    return decorator

def role_required(*allowed_roles):
    def decorator(route_func):
        @wraps(route_func)
        def wrapper(request: Request, *args, **kwargs):
            db = db_session()
            try:
                user = get_user(request, db)
                if not user:
                    return RedirectResponse(url="/login", status_code=303)

                if user.role not in allowed_roles:
                    return RedirectResponse(url="/dashboard", status_code=303)

            finally:
                db.close()

            return route_func(request, *args, **kwargs)

        return wrapper

    return decorator

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    db = db_session()
    try:
        if current_user(request, db):
            return RedirectResponse(url="/dashboard", status_code=303)
        return RedirectResponse(url="/login", status_code=303)
    finally:
        db.close()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    db = db_session()
    try:
        if current_user(request, db):
            return RedirectResponse(url="/dashboard", status_code=303)

        context = context_base(request, db, "Login")
        context["error"] = None

        return render(request, "login.html", context)
    finally:
        db.close()


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
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
            context = context_base(request, db, "Login")
            context["error"] = "Invalid username or password."
            return render(request, "login.html", context, 400)

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
        auth = redirect_if_not_logged_in(request, db)
        if auth:
            return auth

        user = current_user(request, db)
        context = context_base(request, db, "Dashboard")

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
                .order_by(Job.scheduled_for.asc(), Job.id.asc())
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
            client = db.query(Client).options(joinedload(Client.properties)).filter(Client.portal_user_id == user.id).first()
            context["client"] = client
            context["properties"] = client.properties if client else []
            context["open_slots"] = (
                db.query(ScheduleSlot)
                .filter(ScheduleSlot.status == "Open")
                .order_by(ScheduleSlot.slot_date.asc(), ScheduleSlot.start_time.asc())
                .all()
            )

        return render(request, "dashboard.html", context)
    finally:
        db.close()


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        context = context_base(request, db, "Users")
        context["users"] = db.query(User).order_by(User.role.asc(), User.full_name.asc()).all()
        context["error"] = None

        return render(request, "users.html", context)
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        clean_username = username.strip().lower()
        clean_password = password.strip()
        clean_full_name = full_name.strip()
        clean_role = role.strip()

        if clean_role not in [ROLE_ADMIN, ROLE_CREW, ROLE_CLIENT]:
            context = context_base(request, db, "Users")
            context["users"] = db.query(User).order_by(User.role.asc(), User.full_name.asc()).all()
            context["error"] = "Invalid role."
            return render(request, "users.html", context, 400)

        if db.query(User).filter(User.username == clean_username).first():
            context = context_base(request, db, "Users")
            context["users"] = db.query(User).order_by(User.role.asc(), User.full_name.asc()).all()
            context["error"] = "Username already exists."
            return render(request, "users.html", context, 400)

        db.add(
            User(
                username=clean_username,
                password=clean_password,
                full_name=clean_full_name,
                role=clean_role,
                is_active=True,
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        user = current_user(request, db)
        item = db.query(User).filter(User.id == id).first()

        if item and user and item.id != user.id:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/users", status_code=303)
    finally:
        db.close()


@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        context = context_base(request, db, "Clients")
        context["clients"] = (
            db.query(Client)
            .options(joinedload(Client.portal_user))
            .order_by(Client.name.asc())
            .all()
        )
        context["client_users"] = (
            db.query(User)
            .filter(User.role == ROLE_CLIENT)
            .order_by(User.full_name.asc())
            .all()
        )
        context["error"] = None

        return render(request, "clients.html", context)
    finally:
        db.close()


@app.post("/clients")
def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    qb_customer_id: str = Form(""),
    portal_user_id: str = Form(""),
):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        parsed_portal_user_id = int(portal_user_id) if portal_user_id.strip() else None

        db.add(
            Client(
                name=name.strip(),
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        item = db.query(Client).filter(Client.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/clients", status_code=303)
    finally:
        db.close()


@app.get("/properties", response_class=HTMLResponse)
def properties_page(request: Request):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        context = context_base(request, db, "Properties")
        context["clients"] = db.query(Client).order_by(Client.name.asc()).all()
        context["properties"] = (
            db.query(Property)
            .options(joinedload(Property.client))
            .order_by(Property.name.asc())
            .all()
        )
        context["error"] = None

        return render(request, "properties.html", context)
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        item = db.query(Property).filter(Property.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/properties", status_code=303)
    finally:
        db.close()


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        context = context_base(request, db, "Jobs")
        context["properties"] = db.query(Property).order_by(Property.name.asc()).all()
        context["crew_users"] = (
            db.query(User)
            .filter(User.role == ROLE_CREW)
            .order_by(User.full_name.asc())
            .all()
        )
        context["jobs"] = (
            db.query(Job)
            .options(joinedload(Job.property), joinedload(Job.crew_user))
            .order_by(Job.id.desc())
            .all()
        )
        context["statuses"] = JOB_STATUSES
        context["error"] = None

        return render(request, "jobs.html", context)
    finally:
        db.close()


@app.post("/jobs")
def add_job(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    status: str = Form(...),
    scheduled_for: str = Form(""),
    crew_user_id: str = Form(""),
    notes: str = Form(""),
):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        parsed_date = datetime.strptime(scheduled_for, "%Y-%m-%d").date() if scheduled_for.strip() else None
        parsed_crew_user_id = int(crew_user_id) if crew_user_id.strip() else None

        db.add(
            Job(
                property_id=property_id,
                title=title.strip(),
                status=status.strip(),
                scheduled_for=parsed_date,
                crew_user_id=parsed_crew_user_id,
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        item = db.query(Job).filter(Job.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/status")
def update_job_status(
    request: Request,
    id: int = Form(...),
    status: str = Form(...),
):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN, ROLE_CREW])
        if auth:
            return auth

        user = current_user(request, db)
        item = db.query(Job).filter(Job.id == id).first()

        if item and status in JOB_STATUSES:
            if user.role == ROLE_ADMIN or item.crew_user_id == user.id:
                item.status = status
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        context = context_base(request, db, "Schedule")
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

        return render(request, "schedule.html", context)
    finally:
        db.close()


@app.post("/schedule")
def add_schedule_slot(
    request: Request,
    slot_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    status: str = Form(...),
    property_id: str = Form(""),
    notes: str = Form(""),
):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        parsed_date = datetime.strptime(slot_date, "%Y-%m-%d").date()
        parsed_property_id = int(property_id) if property_id.strip() else None

        db.add(
            ScheduleSlot(
                property_id=parsed_property_id,
                slot_date=parsed_date,
                start_time=start_time.strip(),
                end_time=end_time.strip(),
                status=status.strip(),
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
        auth = redirect_if_not_role(request, db, [ROLE_ADMIN])
        if auth:
            return auth

        item = db.query(ScheduleSlot).filter(ScheduleSlot.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/schedule", status_code=303)
    finally:
        db.close()


@app.post("/schedule/book")
@role_required(ROLE_CLIENT)
def book_schedule_slot(
    request: Request,
    id: int = Form(...),
    property_id: int = Form(...),
):
    db = db_session()
    try:
        user = get_user(request, db)
        client = db.query(Client).filter(Client.portal_user_id == user.id).first()
        slot = db.query(ScheduleSlot).filter(ScheduleSlot.id == id).first()

        if client and slot and slot.status == "Open":
            # Book the slot
            slot.status = "Booked"
            slot.booked_by_client_id = client.id
            slot.property_id = property_id

            # 🔥 CREATE JOB AUTOMATICALLY
            job_title = f"{slot.job_type or 'Service'} - {client.name}"

            db.add(
                Job(
                    property_id=property_id,
                    title=job_title,
                    status="Scheduled",
                    scheduled_for=slot.slot_date,
                    crew_user_id=None,
                    notes=f"Booked via client portal | {slot.start_time}-{slot.end_time} | {slot.notes or ''}",
                )
            )

            db.commit()

        return RedirectResponse(url="/client-portal", status_code=303)
    finally:
        db.close()


@app.get("/my-day", response_class=HTMLResponse)
def my_day_page(request: Request):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_CREW])
        if auth:
            return auth

        user = current_user(request, db)

        context = context_base(request, db, "My Day")
        context["jobs"] = (
            db.query(Job)
            .options(joinedload(Job.property))
            .filter(Job.crew_user_id == user.id)
            .order_by(Job.scheduled_for.asc(), Job.id.asc())
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

        return render(request, "my_day.html", context)
    finally:
        db.close()


@app.post("/clock/in")
def clock_in(request: Request, notes: str = Form("")):
    db = db_session()
    try:
        auth = redirect_if_not_role(request, db, [ROLE_CREW])
        if auth:
            return auth

        user = current_user(request, db)

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
        auth = redirect_if_not_role(request, db, [ROLE_CREW])
        if auth:
            return auth

        user = current_user(request, db)

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
        auth = redirect_if_not_role(request, db, [ROLE_CLIENT])
        if auth:
            return auth

        user = current_user(request, db)
        client = (
            db.query(Client)
            .options(joinedload(Client.properties))
            .filter(Client.portal_user_id == user.id)
            .first()
        )

        context = context_base(request, db, "Client Portal")
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
            .options(joinedload(ScheduleSlot.property))
            .filter(ScheduleSlot.booked_by_client_id == client.id)
            .order_by(ScheduleSlot.slot_date.asc(), ScheduleSlot.start_time.asc())
            .all()
            if client
            else []
        )

        return render(request, "client_portal.html", context)
    finally:
        db.close()