import os
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, joinedload
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

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./poolops.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

ROLE_ADMIN = "admin"
ROLE_CREW = "crew"
ROLE_CLIENT = "client"

JOB_STATUSES = ["Scheduled", "In Progress", "Complete"]
BILLING_STATUSES = ["Pending", "Ready to Bill", "Billed", "Paid"]
SLOT_STATUSES = ["Open", "Booked", "Blocked"]
JOB_TYPES = [
    "Opening",
    "Closing",
    "Service",
    "Repair",
    "Estimate",
    "Cover Service",
    "Leak Check",
    "Tile/Coping",
    "Other",
]


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
    billing = relationship("JobBilling", back_populates="job", uselist=False, cascade="all, delete")


class JobBilling(Base):
    __tablename__ = "job_billing"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    price = Column(Numeric(10, 2), default=0)
    billing_status = Column(String(50), default="Pending")
    invoice_number = Column(String(100), default="")
    notes = Column(Text, default="")
    ready_to_bill_at = Column(DateTime, nullable=True)
    billed_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    job = relationship("Job", back_populates="billing")


class ScheduleSlot(Base):
    __tablename__ = "schedule_slots"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    slot_date = Column(Date, nullable=False)
    start_time = Column(String(20), nullable=False)
    end_time = Column(String(20), nullable=False)
    job_type = Column(String(100), default="Service")
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


Base.metadata.create_all(bind=engine)


def db_session():
    return SessionLocal()


def ensure_billing_for_job(db, job: Job):
    if job and not job.billing:
        billing = JobBilling(job_id=job.id, price=0, billing_status="Pending")
        db.add(billing)
        db.commit()
        db.refresh(job)


def ensure_billing_for_all_jobs(db):
    jobs = db.query(Job).options(joinedload(Job.billing)).all()
    for job in jobs:
        if not job.billing:
            db.add(JobBilling(job_id=job.id, price=0, billing_status="Pending"))
    db.commit()


def seed_database():
    db = db_session()
    try:
        if db.query(User).count() == 0:
            admin = User(username="mike", password="1234", full_name="Mike Heinlin", role=ROLE_ADMIN)
            crew = User(username="jake", password="1234", full_name="Jake Crew", role=ROLE_CREW)
            client_user = User(username="smith", password="1234", full_name="Smith Family", role=ROLE_CLIENT)
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
            db.add(job)
            db.commit()

            job = db.query(Job).filter(Job.title == "Spring Opening").first()
            db.add(JobBilling(job_id=job.id, price=450, billing_status="Pending"))

            db.add(
                ScheduleSlot(
                    property_id=prop.id,
                    slot_date=date.today(),
                    start_time="8am",
                    end_time="9am",
                    job_type="Opening",
                    status="Open",
                    notes="Demo open schedule slot",
                )
            )

            db.commit()
        else:
            ensure_billing_for_all_jobs(db)
    finally:
        db.close()


seed_database()


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


def render(request: Request, template_name: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=status_code,
    )


def login_required(route_func):
    @wraps(route_func)
    def wrapper(request: Request, *args, **kwargs):
        db = db_session()
        try:
            user = get_user(request, db)
            if not user:
                return RedirectResponse(url="/login", status_code=303)
        finally:
            db.close()

        return route_func(request, *args, **kwargs)

    return wrapper


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


def money(value):
    if value is None:
        return 0
    return float(value)


def billing_total(db, status: str):
    records = db.query(JobBilling).filter(JobBilling.billing_status == status).all()
    return sum(money(record.price) for record in records)


def billing_total_for_week(db):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    jobs = (
        db.query(Job)
        .options(joinedload(Job.billing))
        .filter(Job.scheduled_for >= week_start, Job.scheduled_for <= week_end)
        .all()
    )

    total = 0
    for job in jobs:
        if job.billing:
            total += money(job.billing.price)
    return total


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    db = db_session()
    try:
        if get_user(request, db):
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
            context = base_context(request, db, "Login")
            context["error"] = "Invalid username or password."
            return render(request, "login.html", context, status_code=400)

        request.session["user_id"] = user.id
        return RedirectResponse(url="/dashboard", status_code=303)
    finally:
        db.close()


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
@login_required
def dashboard(request: Request):
    db = db_session()
    try:
        user = get_user(request, db)
        context = base_context(request, db, "Dashboard")

        if user.role == ROLE_ADMIN:
            ensure_billing_for_all_jobs(db)

            context["client_count"] = db.query(Client).count()
            context["property_count"] = db.query(Property).count()
            context["job_count"] = db.query(Job).count()
            context["open_slot_count"] = db.query(ScheduleSlot).filter(ScheduleSlot.status == "Open").count()
            context["billing_pending_total"] = billing_total(db, "Pending")
            context["ready_to_bill_total"] = billing_total(db, "Ready to Bill")
            context["billed_total"] = billing_total(db, "Billed")
            context["paid_total"] = billing_total(db, "Paid")
            context["week_total"] = billing_total_for_week(db)
            context["recent_jobs"] = (
                db.query(Job)
                .options(joinedload(Job.property), joinedload(Job.crew_user), joinedload(Job.billing))
                .order_by(Job.id.desc())
                .limit(10)
                .all()
            )

        elif user.role == ROLE_CREW:
            context["today_jobs"] = (
                db.query(Job)
                .options(joinedload(Job.property))
                .filter(Job.crew_user_id == user.id)
                .order_by(Job.scheduled_for.asc().nulls_last(), Job.id.asc())
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

        return render(request, "dashboard.html", context)
    finally:
        db.close()


@app.get("/users", response_class=HTMLResponse)
@role_required(ROLE_ADMIN)
def users_page(request: Request):
    db = db_session()
    try:
        context = base_context(request, db, "Users")
        context["users"] = db.query(User).order_by(User.role.asc(), User.full_name.asc()).all()
        context["error"] = None
        return render(request, "users.html", context)
    finally:
        db.close()


@app.post("/users")
@role_required(ROLE_ADMIN)
def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
):
    db = db_session()
    try:
        clean_username = username.strip().lower()
        clean_role = role.strip()

        if clean_role not in [ROLE_ADMIN, ROLE_CREW, ROLE_CLIENT]:
            return RedirectResponse(url="/users", status_code=303)

        existing = db.query(User).filter(User.username == clean_username).first()
        if existing:
            return RedirectResponse(url="/users", status_code=303)

        db.add(
            User(
                username=clean_username,
                password=password.strip(),
                full_name=full_name.strip(),
                role=clean_role,
            )
        )
        db.commit()
        return RedirectResponse(url="/users", status_code=303)
    finally:
        db.close()


@app.post("/users/delete")
@role_required(ROLE_ADMIN)
def delete_user(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        current_user = get_user(request, db)
        user = db.query(User).filter(User.id == id).first()

        if user and current_user and user.id != current_user.id:
            db.delete(user)
            db.commit()

        return RedirectResponse(url="/users", status_code=303)
    finally:
        db.close()


@app.get("/clients", response_class=HTMLResponse)
@role_required(ROLE_ADMIN)
def clients_page(request: Request):
    db = db_session()
    try:
        context = base_context(request, db, "Clients")
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
@role_required(ROLE_ADMIN)
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
        parsed_portal_user_id = int(portal_user_id) if str(portal_user_id).strip() else None

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
@role_required(ROLE_ADMIN)
def delete_client(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        item = db.query(Client).filter(Client.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/clients", status_code=303)
    finally:
        db.close()


@app.get("/properties", response_class=HTMLResponse)
@role_required(ROLE_ADMIN)
def properties_page(request: Request):
    db = db_session()
    try:
        context = base_context(request, db, "Properties")
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
@role_required(ROLE_ADMIN)
def add_property(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
):
    db = db_session()
    try:
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
@role_required(ROLE_ADMIN)
def delete_property(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        item = db.query(Property).filter(Property.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/properties", status_code=303)
    finally:
        db.close()


@app.get("/jobs", response_class=HTMLResponse)
@role_required(ROLE_ADMIN)
def jobs_page(request: Request):
    db = db_session()
    try:
        ensure_billing_for_all_jobs(db)

        context = base_context(request, db, "Jobs")
        context["properties"] = db.query(Property).order_by(Property.name.asc()).all()
        context["crew_users"] = (
            db.query(User)
            .filter(User.role == ROLE_CREW)
            .order_by(User.full_name.asc())
            .all()
        )
        context["jobs"] = (
            db.query(Job)
            .options(joinedload(Job.property), joinedload(Job.crew_user), joinedload(Job.billing))
            .order_by(Job.id.desc())
            .all()
        )
        context["statuses"] = JOB_STATUSES
        context["billing_statuses"] = BILLING_STATUSES
        context["error"] = None
        return render(request, "jobs.html", context)
    finally:
        db.close()


@app.post("/jobs")
@role_required(ROLE_ADMIN)
def add_job(
    request: Request,
    property_id: int = Form(...),
    title: str = Form(...),
    status: str = Form(...),
    scheduled_for: str = Form(""),
    crew_user_id: Optional[str] = Form(""),
    notes: str = Form(""),
    price: str = Form("0"),
):
    db = db_session()
    try:
        parsed_date = datetime.strptime(scheduled_for, "%Y-%m-%d").date() if scheduled_for.strip() else None
        parsed_crew_id = int(crew_user_id) if str(crew_user_id).strip() else None

        job = Job(
            property_id=property_id,
            title=title.strip(),
            status=status.strip(),
            scheduled_for=parsed_date,
            crew_user_id=parsed_crew_id,
            notes=notes.strip(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        clean_price = float(price) if str(price).strip() else 0
        db.add(JobBilling(job_id=job.id, price=clean_price, billing_status="Pending"))
        db.commit()

        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/delete")
@role_required(ROLE_ADMIN)
def delete_job(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        item = db.query(Job).filter(Job.id == id).first()
        if item:
            db.delete(item)
            db.commit()

        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/status")
@role_required(ROLE_ADMIN, ROLE_CREW)
def update_job_status(request: Request, id: int = Form(...), status: str = Form(...)):
    db = db_session()
    try:
        user = get_user(request, db)
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


@app.post("/jobs/billing")
@role_required(ROLE_ADMIN)
def update_job_billing(
    request: Request,
    id: int = Form(...),
    price: str = Form("0"),
    billing_status: str = Form("Pending"),
    invoice_number: str = Form(""),
    billing_notes: str = Form(""),
):
    db = db_session()
    try:
        job = db.query(Job).options(joinedload(Job.billing)).filter(Job.id == id).first()

        if job:
            ensure_billing_for_job(db, job)
            billing = db.query(JobBilling).filter(JobBilling.job_id == job.id).first()

            clean_price = float(price) if str(price).strip() else 0
            clean_status = billing_status if billing_status in BILLING_STATUSES else "Pending"

            billing.price = clean_price
            billing.billing_status = clean_status
            billing.invoice_number = invoice_number.strip()
            billing.notes = billing_notes.strip()

            now = datetime.now()
            if clean_status == "Ready to Bill" and not billing.ready_to_bill_at:
                billing.ready_to_bill_at = now
            if clean_status == "Billed" and not billing.billed_at:
                billing.billed_at = now
            if clean_status == "Paid" and not billing.paid_at:
                billing.paid_at = now

            db.commit()

        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/ready-to-bill")
@role_required(ROLE_ADMIN, ROLE_CREW)
def mark_ready_to_bill(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user = get_user(request, db)
        job = db.query(Job).options(joinedload(Job.billing)).filter(Job.id == id).first()

        if job:
            if user.role == ROLE_ADMIN or job.crew_user_id == user.id:
                ensure_billing_for_job(db, job)
                billing = db.query(JobBilling).filter(JobBilling.job_id == job.id).first()
                billing.billing_status = "Ready to Bill"
                billing.ready_to_bill_at = datetime.now()
                db.commit()

        if user.role == ROLE_CREW:
            return RedirectResponse(url="/my-day", status_code=303)

        return RedirectResponse(url="/jobs", status_code=303)
    finally:
        db.close()


@app.post("/jobs/start")
@role_required(ROLE_CREW)
def start_job(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user = get_user(request, db)
        job = db.query(Job).filter(Job.id == id, Job.crew_user_id == user.id).first()

        if job:
            job.status = "In Progress"

            open_clock = (
                db.query(ClockEntry)
                .filter(
                    ClockEntry.user_id == user.id,
                    ClockEntry.entry_date == date.today(),
                    ClockEntry.clock_out_at == None,
                )
                .first()
            )

            if not open_clock:
                db.add(
                    ClockEntry(
                        user_id=user.id,
                        clock_in_at=datetime.now(),
                        entry_date=date.today(),
                        notes=f"Auto clock-in: started {job.title}",
                    )
                )

            db.commit()

        return RedirectResponse(url="/my-day", status_code=303)
    finally:
        db.close()


@app.post("/jobs/complete")
@role_required(ROLE_CREW)
def complete_job(request: Request, id: int = Form(...)):
    db = db_session()
    try:
        user = get_user(request, db)
        job = db.query(Job).filter(Job.id == id, Job.crew_user_id == user.id).first()

        if job:
            job.status = "Complete"
            ensure_billing_for_job(db, job)
            billing = db.query(JobBilling).filter(JobBilling.job_id == job.id).first()
            billing.billing_status = "Ready to Bill"
            billing.ready_to_bill_at = datetime.now()
            db.commit()

        return RedirectResponse(url="/my-day", status_code=303)
    finally:
        db.close()


@app.get("/schedule", response_class=HTMLResponse)
@role_required(ROLE_ADMIN)
def schedule_page(request: Request):
    db = db_session()
    try:
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
        context["job_types"] = JOB_TYPES
        context["error"] = None
        return render(request, "schedule.html", context)
    finally:
        db.close()


@app.post("/schedule")
@role_required(ROLE_ADMIN)
def add_schedule_slot(
    request: Request,
    slot_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    job_type: str = Form("Service"),
    status: str = Form("Open"),
    property_id: Optional[str] = Form(""),
    notes: str = Form(""),
):
    db = db_session()
    try:
        parsed_date = datetime.strptime(slot_date, "%Y-%m-%d").date()
        parsed_property_id = int(property_id) if str(property_id).strip() else None

        db.add(
            ScheduleSlot(
                property_id=parsed_property_id,
                slot_date=parsed_date,
                start_time=start_time.strip(),
                end_time=end_time.strip(),
                job_type=job_type.strip() or "Service",
                status=status.strip() or "Open",
                notes=notes.strip(),
            )
        )
        db.commit()

        return RedirectResponse(url="/schedule", status_code=303)
    finally:
        db.close()


@app.post("/schedule/delete")
@role_required(ROLE_ADMIN)
def delete_schedule_slot(request: Request, id: int = Form(...)):
    db = db_session()
    try:
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
            slot.status = "Booked"
            slot.booked_by_client_id = client.id
            slot.property_id = property_id
            db.commit()

        return RedirectResponse(url="/client-portal", status_code=303)
    finally:
        db.close()


@app.get("/my-day", response_class=HTMLResponse)
@role_required(ROLE_CREW)
def my_day_page(request: Request):
    db = db_session()
    try:
        user = get_user(request, db)
        context = base_context(request, db, "My Day")
        context["jobs"] = (
            db.query(Job)
            .options(joinedload(Job.property), joinedload(Job.billing))
            .filter(Job.crew_user_id == user.id)
            .order_by(Job.scheduled_for.asc().nulls_last(), Job.id.asc())
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
@role_required(ROLE_CREW)
def clock_in(request: Request, notes: str = Form("")):
    db = db_session()
    try:
        user = get_user(request, db)
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
@role_required(ROLE_CREW)
def clock_out(request: Request):
    db = db_session()
    try:
        user = get_user(request, db)
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
@role_required(ROLE_CLIENT)
def client_portal_page(request: Request):
    db = db_session()
    try:
        user = get_user(request, db)
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

        return render(request, "client_portal.html", context)
    finally:
        db.close()
