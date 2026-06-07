from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi import Form
from fastapi.responses import RedirectResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from openai import OpenAI
import os

from sqlalchemy import text, inspect
from typing import List
from uuid import uuid4
import importlib
active_sessions = {}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

try:
    requests = importlib.import_module("requests")
except ImportError:
    # Minimal shim for environments without 'requests' installed.
    # Provides get/post with a Response-like object used in this app.
    import urllib.request as _ur
    import urllib.parse as _up
    import json as _json

    class _ResponseShim:
        def __init__(self, status_code, content, headers=None):
            self.status_code = status_code
            self.content = content
            self.headers = headers or {}

        @property
        def text(self):
            try:
                return self.content.decode('utf-8')
            except Exception:
                return str(self.content)

        def json(self):
            return _json.loads(self.text)

    def _build_request(url, method='GET', params=None, data=None, json_data=None, headers=None):
        if params:
            query = _up.urlencode(params)
            url = f"{url}?{query}"
        body = None
        hdrs = headers.copy() if headers else {}
        if json_data is not None:
            body = _json.dumps(json_data).encode('utf-8')
            hdrs.setdefault('Content-Type', 'application/json')
        elif data is not None:
            if isinstance(data, dict):
                body = _up.urlencode(data).encode('utf-8')
                hdrs.setdefault('Content-Type', 'application/x-www-form-urlencoded')
            elif isinstance(data, str):
                body = data.encode('utf-8')
            else:
                body = data
        req = _ur.Request(url, data=body, method=method, headers=hdrs)
        return req

    def _do_request(req, timeout=None):
        try:
            with _ur.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                return _ResponseShim(resp.getcode(), content, dict(resp.getheaders()))
        except Exception as e:
            # Attempt to extract code from HTTPError
            if hasattr(e, 'code') and hasattr(e, 'read'):
                return _ResponseShim(e.code, e.read())
            raise

    def requests_get(url, params=None, headers=None, timeout=None):
        req = _build_request(url, 'GET', params=params, headers=headers)
        return _do_request(req, timeout=timeout)

    def requests_post(url, params=None, data=None, json=None, headers=None, timeout=None):
        req = _build_request(url, 'POST', params=params, data=data, json_data=json, headers=headers)
        return _do_request(req, timeout=timeout)

    # Expose a 'requests' namespace with get/post
    class _RequestsModule:
        get = staticmethod(requests_get)
        post = staticmethod(requests_post)

    requests = _RequestsModule()
import base64
import csv
import io
import os
import shutil
import json
import urllib.request
import calendar
import math

from datetime import datetime, date, timedelta
from app.database import Base, engine, SessionLocal
from app.models import User, Employee, Client, Property, Job, Invoice, JobCost, PhotoLog, FieldLog
from app.routes.imports import router as imports_router

app = FastAPI(title="PoolOps2")
app.include_router(imports_router)
app.add_middleware(
    SessionMiddleware,
    secret_key="poolops2-phase-5-secret",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def sync_database_schema():
    """Create missing tables/columns and seed default users. Safe for fresh Render DBs."""
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    dialect = engine.dialect

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                table.create(bind=engine, checkfirst=True)
                continue

            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                column_type = column.type.compile(dialect=dialect)
                nullable = "" if column.nullable or column.primary_key else " NOT NULL"
                default = ""
                if column.default is not None and column.default.is_scalar:
                    value = column.default.arg
                    if isinstance(value, str):
                        default = " DEFAULT '" + value.replace("'", "''") + "'"
                    elif isinstance(value, bool):
                        default = " DEFAULT " + ("TRUE" if value else "FALSE")
                    elif value is not None:
                        default = f" DEFAULT {value}"

                sql = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {column_type}{default}{nullable}'
                conn.execute(text(sql))

    db = SessionLocal()
    try:
        defaults = [
            ("mike", "mike", "admin", "Mike"),
            ("randy", "randy", "crew", "Randy"),
            ("marty", "marty", "crew", "Marty"),
        ]
        for username, password, role, name in defaults:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                db.add(User(username=username, password=password, role=role, name=name))
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def startup():
    sync_database_schema()
    print("POOL OPS DATABASE READY")

property_gps_columns = [
    ("latitude", "FLOAT"),
    ("longitude", "FLOAT"),
]

gps_columns = [
    ("latitude", "FLOAT"),
    ("longitude", "FLOAT"),
    ("check_in_time", "TIMESTAMP"),
    ("check_in_lat", "FLOAT"),
    ("check_in_lng", "FLOAT"),
    ("check_out_time", "TIMESTAMP"),
    ("check_out_lat", "FLOAT"),
    ("check_out_lng", "FLOAT"),
]


extra_schema_columns = {
    "poolops2_clients": [
        ("portal_username", "VARCHAR DEFAULT ''"),
        ("portal_password", "VARCHAR DEFAULT ''"),
        ("card_image", "VARCHAR DEFAULT ''"),
    ],
    "poolops2_properties": [
        ("card_image", "VARCHAR DEFAULT ''"),
    ],
    "poolops2_employees": [
        ("card_image", "VARCHAR DEFAULT ''"),
    ],
    "poolops2_photo_logs": [
        ("property_id", "INTEGER NULL"),
        ("latitude", "FLOAT NULL"),
        ("longitude", "FLOAT NULL"),
    ],
}

with engine.begin() as conn:
    for column_name, column_type in property_gps_columns:
        try:
            conn.execute(text(f"ALTER TABLE poolops2_properties ADD COLUMN {column_name} {column_type}"))
        except Exception:
            pass

    for column_name, column_type in gps_columns:
        try:
            conn.execute(text(f"ALTER TABLE poolops2_jobs ADD COLUMN {column_name} {column_type}"))
        except Exception:
            pass

    for table_name, columns in extra_schema_columns.items():
        for column_name, column_type in columns:
            try:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
            except Exception:
                pass
with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS poolops2_memories (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            username VARCHAR DEFAULT '',
            raw_text TEXT DEFAULT '',
            organized_text TEXT DEFAULT '',
            source VARCHAR DEFAULT 'capture'
        )
    """))
db = SessionLocal()

try:
    seed_users = [
        ("mike", "5500", "admin", "Mike"),
        ("randy", "0318", "crew", "Randy"),
        ("marty", "0318", "crew", "Marty"),
    ]

    for username, password, role, name in seed_users:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            existing.role = existing.role or role
            existing.name = existing.name or name
        else:
            db.add(User(username=username, password=password, role=role, name=name))

    for employee_name in ["Mike", "Randy", "Marty"]:
        existing_employee = db.query(Employee).filter(Employee.name == employee_name).first()
        if not existing_employee:
            db.add(Employee(name=employee_name, role="Admin" if employee_name == "Mike" else "Crew"))

    db.commit()

finally:
    db.close()

@app.get("/capture")
async def capture_page(request: Request):
    if "current" not in active_sessions:
        active_sessions["current"] = []

    active_sessions["current"].append("")

    return templates.TemplateResponse(
        request,
        "capture.html",
        {
            "raw_text": "",
            "result": None
        }
    )

def find_matching_client_and_property(db, raw_text):
    text_lower = (raw_text or "").lower()

    matched_client = None
    matched_property = None

    clients = db.query(Client).all()
    properties = db.query(Property).all()

    # Match by saved client name
    for client_obj in clients:
        name = (client_obj.name or "").strip()
        if name and name.lower() in text_lower:
            matched_client = client_obj
            break

    # Match by saved property address
    for prop in properties:
        address = (prop.address or "").strip()
        if address and address.lower() in text_lower:
            matched_property = prop
            break

    # If property matched but client did not, try to match the property client too
    if matched_property and not matched_client:
        prop_client = (getattr(matched_property, "client", "") or "").strip()
        if prop_client:
            matched_client = (
                db.query(Client)
                .filter(Client.name == prop_client)
                .first()
            )

    return matched_client, matched_property

@app.get("/where-am-i")
async def where_am_i(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "where_am_i.html",
        {
            "request": request,
            "user": user,
        }
    )

@app.post("/capture")
async def capture_submit(request: Request, raw_text: str = Form(...)):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    if "current" not in active_sessions:
        active_sessions["current"] = []

    active_sessions["current"].append(raw_text)

    result = ""
    saved = False
    clients_for_filing = []
    properties_for_filing = []
    memory_id = None

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
You are Invisible Office AI for PoolOps2.

Your job is to take rough spoken field notes from a contractor and turn them into useful office records.

Extract and organize:
- Client/property mentioned
- Location clues
- Arrival/departure/time worked if mentioned
- Work performed
- Materials used
- Equipment involved
- Problems found
- Follow-up needed
- Billable items
- Invoice draft
- Customer-facing summary
- Internal office notes
- Knowledge worth preserving
- Missing information needed

Rules:
- Do not invent facts.
- If unknown, say Unknown.
- Be practical, direct, and contractor-ready.
- Separate billable items from internal notes.
- Preserve important field wisdom.
"""
                },
                {
                    "role": "user",
                    "content": raw_text
                }
            ]
        )

        result = response.choices[0].message.content

    except Exception as e:
        result = f"AI error: {str(e)}"

    db = db_session()

    try:
        insert_result = db.execute(
            text("""
                INSERT INTO poolops2_memories
                (username, raw_text, organized_text, source)
                VALUES
                (:username, :raw_text, :organized_text, :source)
                RETURNING id
            """),
            {
                "username": user.get("username", ""),
                "raw_text": raw_text,
                "organized_text": result,
                "source": "capture",
            }
        )

        try:
            memory_id = insert_result.scalar()
        except Exception:
            memory_id = None

        clients = db.query(Client).order_by(Client.name.asc()).all()
        properties = db.query(Property).order_by(Property.address.asc()).all()

        # Convert ORM rows into simple dictionaries before closing the database session.
        # This prevents detached-session template errors.
        clients_for_filing = [
            {
                "id": c.id,
                "name": c.name or "Unnamed Client",
            }
            for c in clients
        ]

        properties_for_filing = [
            {
                "id": p.id,
                "client": p.client or "",
                "address": p.address or "No address listed",
            }
            for p in properties
        ]

        db.commit()
        saved = True

    except Exception as e:
        db.rollback()
        result = result + f"\n\nSAVE ERROR: {str(e)}"
        saved = False

    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "capture.html",
        {
            "raw_text": raw_text,
            "result": result,
            "saved": saved,
            "memory_id": memory_id,
            "matched_client": None,
            "matched_property": None,
            "clients": clients_for_filing,
            "properties": properties_for_filing,
        }
    )


@app.post("/memory/file")
async def file_memory(
    request: Request,
    raw_text: str = Form(""),
    organized_text: str = Form(""),
    file_option: str = Form("general"),
    existing_client_id: int = Form(0),
    existing_property_id: int = Form(0),
    new_client_name: str = Form(""),
    new_property_address: str = Form("")
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        memory_note = (
            "\n\n--- JARVIS MEMORY FILED ---\n"
            + f"Date: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n"
            + f"User: {user.get('username', '')}\n\n"
            + "RAW TRANSCRIPT:\n"
            + raw_text.strip()
            + "\n\nORGANIZED RECORD:\n"
            + organized_text.strip()
            + "\n"
        )

        selected_client = None
        selected_property = None

        if file_option == "existing":
            if existing_client_id:
                selected_client = db.query(Client).filter(Client.id == existing_client_id).first()

            if existing_property_id:
                selected_property = db.query(Property).filter(Property.id == existing_property_id).first()

            if selected_client:
                selected_client.notes = (selected_client.notes or "") + memory_note

            if selected_property:
                selected_property.notes = (selected_property.notes or "") + memory_note

        elif file_option == "existing_client_new_property":
            if existing_client_id:
                selected_client = db.query(Client).filter(Client.id == existing_client_id).first()

            if selected_client:
                selected_client.notes = (selected_client.notes or "") + memory_note

                selected_property = Property(
                    client_id=selected_client.id,
                    client=selected_client.name,
                    address=new_property_address.strip(),
                    notes=memory_note
                )
                db.add(selected_property)

        elif file_option == "new":
            selected_client = Client(
                name=new_client_name.strip() or "Unknown Client",
                notes=memory_note
            )
            db.add(selected_client)
            db.flush()

            selected_property = Property(
                client_id=selected_client.id,
                client=selected_client.name,
                address=new_property_address.strip(),
                notes=memory_note
            )
            db.add(selected_property)

        else:
            # General memory only: the capture is already saved in poolops2_memories.
            pass

        db.commit()

        return RedirectResponse(url="/capture", status_code=303)

    except Exception as e:
        db.rollback()
        return HTMLResponse(f"Memory filing error: {str(e)}", status_code=500)

    finally:
        db.close()


@app.get("/ai-test")
async def ai_test():
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "user",
                    "content": "Say: PoolOps2 AI is online."
                }
            ]
        )

        return {
            "success": True,
            "message": response.choices[0].message.content
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        } 

@app.get("/talk-to-jarvis")
async def talk_to_jarvis_choice(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "talk_to_jarvis.html",
        {
            "request": request,
            "user": user,
        }
    )     
    
@app.get("/ai")
async def ai_page(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse("/capture", status_code=303)

    return templates.TemplateResponse("ai.html", {
        "request": request,
        "user": user,
        "answer": None,
        "question": ""
    })


@app.post("/ai")
async def ai_ask(request: Request, question: str = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    
                        "content": """
You are PoolOps2 AI, an elite pool construction and service operations assistant for professional contractors.

You specialize in:
- pool heater diagnostics
- plumbing troubleshooting
- automation systems
- chemistry
- pumps
- filters
- leak detection
- construction sequencing
- job costing
- service operations
- estimates
- concrete pool construction
- ecoFINISH
- Pentair
- Hayward
- Jandy systems

Your responses should:
- sound like an experienced pool technician
- prioritize the most likely causes first
- give practical field-ready diagnostics
- avoid generic filler
- explain WHY something may be happening
- minimize unnecessary parts swapping
- provide troubleshooting order
- focus on real-world contractor workflows

When discussing repairs:
- start with the most common failure points
- explain likely causes
- recommend testing steps in order
- mention safety concerns when relevant
- help avoid wasted labor and parts

Keep answers concise but useful.
"""
                },
                {
                    "role": "user",
                    "content": question
                }
            ]
        )

        answer = response.choices[0].message.content

    except Exception as e:
        answer = f"AI error: {str(e)}"

    return templates.TemplateResponse("ai.html", {
        "request": request,
        "user": user,
        "answer": answer,
        "question": question
    }) 

@app.post("/location-context")
async def location_context(
    request: Request,
    lat: float = Form(...),
    lng: float = Form(...)
):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db = db_session()

    try:
        properties = db.query(Property).all()

        nearest = None
        nearest_distance = None

        for prop in properties:
            if prop.latitude is None or prop.longitude is None:
                continue

            try:
                prop_lat = float(prop.latitude)
                prop_lng = float(prop.longitude)
            except (TypeError, ValueError):
                continue

            distance = (
                ((prop_lat - lat) ** 2)
                + ((prop_lng - lng) ** 2)
            )

            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest = prop

        return templates.TemplateResponse(
            "location_context.html",
            {
                "request": request,
                "user": user,
                "nearest": nearest,
                "nearest_distance": nearest_distance,
                "properties": properties,
            }
        )

    except Exception as e:
        return templates.TemplateResponse(
            "location_context.html",
            {
                "request": request,
                "user": user,
                "error": str(e),
            }
        )
    finally:
        db.close()

@app.get("/ai-import")
async def ai_import_page(request: Request):
    return templates.TemplateResponse(
        request,
        "ai_import.html",
        {
            "raw_text": "",
            "result": None
        }
    )


@app.post("/ai-import")
async def ai_import_clean(request: Request, raw_text: str = Form(...)):
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
You are PoolOps2 AI Intake Assistant.

Your job is to clean messy customer, client, and property information for a pool/concrete contractor.

Extract and organize:
- Client name
- Spouse/secondary contact if mentioned
- Phone numbers
- Email addresses
- Property address
- Billing address if different
- Gate code
- Pets/dog warnings
- Pool type
- Equipment notes
- Service notes
- Missing information
- Possible duplicate warning

Return a clean contractor-ready summary.

Do not invent missing information.
If unsure, mark it as "Unknown".
"""
                },
                {
                    "role": "user",
                    "content": raw_text
                }
            ]
        )

        result = response.choices[0].message.content

    except Exception as e:
        result = f"AI error: {str(e)}"

    return templates.TemplateResponse(
        request,
        "ai_import.html",
        {
            "raw_text": raw_text,
            "result": result
        }
    ) 

@app.get("/guided-intake")
async def guided_intake_page(request: Request):
    return templates.TemplateResponse(
        request,
        "guided_intake.html",
        {"answer": None}
    )

@app.get("/session/start")
async def start_session(request: Request):

    active_sessions["current"] = []

    return RedirectResponse("/capture", status_code=303)


@app.get("/session/end")
async def end_session(request: Request):

    notes = "\n".join(active_sessions.get("current", []))

    return templates.TemplateResponse(
        request,
        "session_summary.html",
        {
            "notes": notes
        }
    )

@app.get("/admin/seed-users")
async def seed_users(request: Request):
    db = db_session()

    users = [
        ("mike", "5500", "admin", "Mike"),
        ("randy", "0318", "crew", "Randy"),
        ("marty", "0712", "crew", "Marty"),
        ("jamie", "1105", "admin", "Jamie"),
    ]

    for username, password, role, name in users:
        existing = db.query(User).filter(User.username == username).first()

        if existing:
            existing.password = password
            existing.role = role
            existing.name = name
        else:
            db.add(User(username=username, password=password, role=role, name=name))

    db.commit()
    db.close()

    return {"status": "users seeded"}

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


def full_address_parts(address="", city="", state="", zip_code=""):
    return " ".join([part.strip() for part in [address or "", city or "", state or "", zip_code or ""] if part and part.strip()])

def client_display_address(client):
    return full_address_parts(
        getattr(client, "billing_address", ""),
        getattr(client, "city", ""),
        getattr(client, "state", ""),
        getattr(client, "zip_code", ""),
    )

def parse_schedule_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    value = str(value).strip()
    for fmt in ["%Y-%m-%dT%H:%M", "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"]:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed
        except Exception:
            pass
    return None

def job_day_key(job):
    dt = parse_schedule_date(getattr(job, "scheduled_start", None)) or parse_schedule_date(getattr(job, "date", ""))
    if not dt:
        return "unscheduled"
    return dt.strftime("%Y-%m-%d")

def build_calendar(month_value, day_value, jobs):
    today = date.today()
    if month_value:
        try:
            current = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
        except Exception:
            current = today.replace(day=1)
    else:
        current = today.replace(day=1)

    if day_value:
        try:
            selected = datetime.strptime(day_value, "%Y-%m-%d").date()
        except Exception:
            selected = today
    else:
        selected = today if today.month == current.month and today.year == current.year else current

    jobs_by_day = {}
    for job in jobs:
        jobs_by_day.setdefault(job_day_key(job), []).append(job)

    weeks = []
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(current.year, current.month):
        week_cells = []
        for d in week:
            key = d.strftime("%Y-%m-%d")
            week_cells.append({
                "date": d,
                "key": key,
                "in_month": d.month == current.month,
                "is_today": d == today,
                "is_selected": d == selected,
                "jobs": jobs_by_day.get(key, []),
            })
        weeks.append(week_cells)

    prev_month = (current.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)

    return {
        "current": current,
        "selected": selected,
        "weeks": weeks,
        "selected_jobs": jobs_by_day.get(selected.strftime("%Y-%m-%d"), []),
        "unscheduled_jobs": jobs_by_day.get("unscheduled", []),
        "prev_month": prev_month.strftime("%Y-%m"),
        "next_month": next_month.strftime("%Y-%m"),
    }

def distance_miles(lat1, lng1, lat2, lng2):
    if None in [lat1, lng1, lat2, lng2]:
        return None
    try:
        lat1, lng1, lat2, lng2 = map(float, [lat1, lng1, lat2, lng2])
    except Exception:
        return None
    r = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1-a))

def nearest_property(db, lat, lng, client_name=""):
    if not lat or not lng:
        return None
    properties = db.query(Property).all()
    best = None
    best_distance = None
    for prop in properties:
        p_lat = getattr(prop, "latitude", None)
        p_lng = getattr(prop, "longitude", None)
        if p_lat is None or p_lng is None:
            continue
        if client_name and prop.client and prop.client != client_name:
            continue
        dist = distance_miles(lat, lng, p_lat, p_lng)
        if dist is not None and (best_distance is None or dist < best_distance):
            best = prop
            best_distance = dist
    if best and best_distance is not None and best_distance <= 0.25:
        return best
    return None

def attach_photo_to_property(db, photo, explicit_property_id=None, lat=None, lng=None):
    prop = None
    if explicit_property_id:
        prop = db.query(Property).filter(Property.id == explicit_property_id).first()
    if not prop:
        prop = nearest_property(db, lat, lng, getattr(photo, "client", ""))
    if prop:
        photo.property_id = prop.id
        if not getattr(prop, "card_image", ""):
            prop.card_image = photo.photo_url
    if lat:
        photo.latitude = float(lat)
    if lng:
        photo.longitude = float(lng)
    return prop


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


def openai_ready():
    return client is not None


def missing_openai_message():
    return "OpenAI API key is not set. Add OPENAI_API_KEY in Render environment variables or your local .env file to use Jarvis AI features."

def require_login(request: Request):
    return get_current_user(request)


def require_admin(request: Request):
    user = get_current_user(request)

    if not user:
        return None

    if user["role"] != "admin":
        return None

    return user

def require_mike(request: Request):
    # Historical name kept so old delete routes do not break.
    # Rule now matches the app policy: only admins can delete anything.
    return require_admin(request)

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

def dashboard_work_groups(jobs):
    today_jobs = []
    high_priority = []
    followups = []
    waiting = []
    openings = []
    closings = []

    for job in jobs:
        status = (job.status or "").lower()
        priority = (job.priority or "").lower()
        job_type = (job.job_type or "").lower()
        date_label = (job.date or "").lower()

        if "today" in date_label:
            today_jobs.append(job)

        if priority in ["high", "urgent"]:
            high_priority.append(job)

        if "follow" in status:
            followups.append(job)

        if "waiting" in status or "parts" in status:
            waiting.append(job)

        if "opening" in job_type:
            openings.append(job)

        if "closing" in job_type:
            closings.append(job)

    return {
        "today_jobs": today_jobs,
        "high_priority": high_priority,
        "followups": followups,
        "waiting": waiting,
        "openings": openings,
        "closings": closings,
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

@app.get("/brain-dump")
async def brain_dump_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "brain_dump.html",
        {
            "user": user,
        },
    )


@app.post("/brain-dump")
async def save_brain_dump(
    request: Request,
    client: str = Form(...),
    address: str = Form(""),
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        existing_client = (
            db.query(Client)
            .filter(Client.name == client.strip())
            .first()
        )

        if existing_client:
            old_notes = existing_client.notes or ""

            existing_client.notes = (
                old_notes
                + "\n\n--- FIELD BRAIN DUMP ---\n\n"
                + notes.strip()
            )

        else:
            db.add(
                Client(
                    name=client.strip(),
                    address=address.strip(),
                    notes=notes.strip(),
                )
            )

        db.commit()

        return RedirectResponse(
            url="/clients",
            status_code=303
        )

    finally:
        db.close()

@app.get("/estimates", response_class=HTMLResponse)
async def estimates_page(request: Request):
    return templates.TemplateResponse("estimates.html", {"request": request})

@app.get("/estimate/new", response_class=HTMLResponse)
async def estimate_new_page(request: Request, type: str = "general"):

    db = db_session()

    try:

        labels = {
            "pool_build": "Custom Pool Build",
            "remodel": "Pool Remodel",
            "repair": "Repair Estimate",
            "service": "Service / Maintenance",
            "automation": "Automation / Equipment",
            "general": "General Estimate",
        }

        estimate_type_label = labels.get(type, "General Estimate")

        clients = db.query(Client).order_by(Client.name.asc()).all()

        properties = db.query(Property).order_by(Property.address.asc()).all()

        return templates.TemplateResponse(
            "estimate_new.html",
            {
                "request": request,
                "estimate_type": type,
                "estimate_type_label": estimate_type_label,
                "clients": clients,
                "properties": properties,
            },
        )

    finally:
        db.close()

@app.post("/estimate/new/save")
async def estimate_new_save(
    request: Request,
    estimate_type: str = Form("general"),
    client_name: str = Form(""),
    property_address: str = Form(""),
    title: str = Form(""),
    scope_notes: str = Form(""),
    material_cost: float = Form(0),
    labor_cost: float = Form(0),
    markup_percent: float = Form(35),
):
    return RedirectResponse(
        url="/estimates",
        status_code=303
    )

@app.get("/ai/field-help")
async def ai_field_help(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ai_tool.html",
        {
            "user": user,
            "title": "Field Help",
            "description": "Troubleshoot field problems and equipment issues.",
            "placeholder": "Example: Hayward heater SF code as soon as power turns on...",
        },
    )


@app.get("/ai/estimate-helper")
async def ai_estimate_helper(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ai_tool.html",
        {
            "user": user,
            "title": "Estimate Helper",
            "description": "Build estimate scopes, material notes, labor assumptions, and customer-facing wording.",
            "placeholder": "Example: Estimate a 400k BTU heater install with gas check, bypass, check valve, and startup...",
        },
    )


@app.get("/ai/job-costing-helper")
async def ai_job_costing_helper(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ai_tool.html",
        {
            "user": user,
            "title": "Job Costing Helper",
            "description": "Review labor, materials, equipment, subcontractors, and profit notes.",
            "placeholder": "Example: Labor 14 hours, materials $1,850, charged $4,900. How did we do?",
        },
    )


@app.get("/ai/billing-helper")
async def ai_billing_helper(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ai_tool.html",
        {
            "user": user,
            "title": "Billing Helper",
            "description": "Draft invoice descriptions, payment notes, and billing summaries.",
            "placeholder": "Example: Write an invoice description for replacing a leaking multiport valve and re-plumbing filter connections...",
        },
    )


@app.get("/ai/quickbooks-helper")
async def ai_quickbooks_helper(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ai_tool.html",
        {
            "user": user,
            "title": "QuickBooks Helper",
            "description": "Prepare QuickBooks notes, categories, export reminders, and cleanup guidance.",
            "placeholder": "Example: Help me categorize this pool opening income and chemical expense...",
        },
    )      

@app.get("/assistant-interview-live")
async def assistant_interview_live_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()

        return templates.TemplateResponse(
            request,
            "assistant_interview_live.html",
            {
                "user": user,
                "clients": clients,
                "next_questions": [],
            },
        )

    finally:
        db.close()

@app.get("/ai")
async def ai_command_center(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ai.html",
        {
            "user": user,
        },
    )

@app.post("/assistant-interview-live")
async def assistant_interview_live(
    request: Request,
    client: str = Form(""),
    new_client: str = Form(""),
    notes: str = Form(...),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    if new_client.strip():
        client = new_client.strip()

    try:
        client_name = client.strip() or new_client.strip()

        if not client_name:
            return RedirectResponse(url="/assistant-interview-live", status_code=303)

        existing_client = (
            db.query(Client)
            .filter(Client.name == client_name)
            .first()
        )

        if existing_client:
            old_notes = existing_client.notes or ""
            existing_client.notes = (
                old_notes
                + "\n\n--- ASSISTANT INTERVIEW LIVE NOTES ---\n\n"
                + notes.strip()
            )
        else:
            db.add(
                Client(
                    name=client_name,
                    notes=notes.strip(),
                )
            )

        db.commit()

        return RedirectResponse(url="/clients", status_code=303)

    finally:
        db.close()

@app.get("/assistant-interview")
async def assistant_interview_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "assistant_interview.html",
        {
            "user": user,
        },
    )


@app.post("/assistant-interview")
async def save_assistant_interview(
    request: Request,
    record_type: str = Form(...),
    record_id: int = Form(...),
    notes: str = Form(...),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        header = "\n\n--- ASSISTANT INTERVIEW NOTES ---\n\n"

        if record_type == "client":
            record = db.query(Client).filter(Client.id == record_id).first()

            if record:
                record.notes = (record.notes or "") + header + notes.strip()
                db.commit()
                return RedirectResponse(url=f"/clients/{record.id}", status_code=303)

        if record_type == "property":
            record = db.query(Property).filter(Property.id == record_id).first()

            if record:
                record.notes = (record.notes or "") + header + notes.strip()
                db.commit()
                return RedirectResponse(url=f"/properties/{record.id}", status_code=303)

        if record_type == "job":
            record = db.query(Job).filter(Job.id == record_id).first()

            if record:
                record.notes = (record.notes or "") + header + notes.strip()
                db.commit()
                return RedirectResponse(url=f"/jobs/{record.id}", status_code=303)

        return RedirectResponse(url="/capture", status_code=303)

    finally:
        db.close()       

@app.get("/assistant-action")
async def assistant_action_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "assistant_action.html",
        {
            "user": user,
            "command": "",
            "preview": None,
        },
    )


@app.post("/assistant-action")
async def prepare_assistant_action(
    request: Request,
    command: str = Form(...),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    text = command.strip()
    lower = text.lower()

    action = "add_job"
    job_type = "Service"
    status = "Requested"
    priority = "Normal"

    if "opening" in lower or "open " in lower:
        job_type = "Opening"

    if "closing" in lower or "close " in lower:
        job_type = "Closing"

    if "urgent" in lower or "asap" in lower:
        priority = "Urgent"

    if "repair" in lower:
        job_type = "Repair"

    client = ""
    address = ""

    if " for " in lower:
        client = text.split(" for ", 1)[1].split(" at ")[0].strip()

    if " at " in lower:
        address = text.split(" at ", 1)[1].split(".")[0].strip()

    preview = {
        "action": action,
        "client": client,
        "address": address,
        "job_type": job_type,
        "status": status,
        "priority": priority,
        "notes": text,
    }

    return templates.TemplateResponse(
        request,
        "assistant_action.html",
        {
            "user": user,
            "command": command,
            "preview": preview,
        },
    )


@app.post("/assistant-action/confirm")
async def confirm_assistant_action(
    request: Request,
    action: str = Form(...),
    client: str = Form(""),
    address: str = Form(""),
    job_type: str = Form("Service"),
    status: str = Form("Requested"),
    priority: str = Form("Normal"),
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        if action == "add_job":
            db.add(
                Job(
                    client=client.strip() or "Unknown Client",
                    address=address.strip(),
                    property=address.strip(),
                    job_type=job_type.strip(),
                    status=status.strip(),
                    priority=priority.strip(),
                    crew="Unassigned",
                    date="",
                    notes=notes.strip(),
                )
            )

        db.commit()

        return RedirectResponse(url="/jobs", status_code=303)

    finally:
        db.close()

@app.get("/client-interview")
async def client_interview_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()

        return templates.TemplateResponse(
            request,
            "client_interview.html",
            {
                "user": user,
                "clients": clients,
            },
        )

    finally:
        db.close()


@app.post("/client-interview")
async def save_client_interview(
    request: Request,
    client_id: int = Form(...),
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        client = db.query(Client).filter(Client.id == client_id).first()

        if client:
            old_notes = client.notes or ""

            client.notes = (
                old_notes
                + "\n\n--- CLIENT INTERVIEW NOTES ---\n\n"
                + notes.strip()
            )

            db.commit()

            return RedirectResponse(
                url=f"/clients/{client.id}",
                status_code=303
            )

        return RedirectResponse(url="/clients", status_code=303)

    finally:
        db.close()       

@app.get("/brain-dump")
async def brain_dump_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "brain_dump.html",
        {
            "user": user,
        },
    )


@app.post("/brain-dump")
async def save_brain_dump(
    request: Request,
    client: str = Form(...),
    address: str = Form(""),
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:

        existing_client = (
            db.query(Client)
            .filter(Client.name == client.strip())
            .first()
        )

        if existing_client:

            old_notes = existing_client.notes or ""

            existing_client.notes = (
                old_notes
                + "\n\n--- FIELD BRAIN DUMP ---\n\n"
                + notes.strip()
            )

        else:

            db.add(
                Client(
                    name=client.strip(),
                    address=address.strip(),
                    notes=notes.strip(),
                )
            )

        db.commit()

        return RedirectResponse(
            url="/clients",
            status_code=303
        )

    finally:
        db.close()       

@app.get("/admin/job-addresses-real")
async def job_addresses_real(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).all()

        output = []

        for job in jobs:
            if job.address:
                output.append({
                    "id": job.id,
                    "client": job.client,
                    "address": job.address,
                    "job_type": job.job_type,
                    "status": job.status,
                })

        return {
            "count": len(output),
            "jobs": output[:50],
        }

    finally:
        db.close()

@app.get("/admin/geocode-properties")
async def geocode_properties(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        properties = db.query(Property).all()
        updated = 0
        skipped = 0

        for prop in properties:
            if not prop.address:
                skipped += 1
                continue

            if prop.latitude and prop.longitude:
                skipped += 1
                continue

            address_parts = [
                prop.address or "",
                prop.city or "",
                prop.state or "",
                prop.zip_code or "",
            ]

            query = ", ".join([part for part in address_parts if part]).strip()

            if not query:
                skipped += 1
                continue

            url = "https://nominatim.openstreetmap.org/search"

            try:
                response = requests.get(
                    url,
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={
                        "User-Agent": "PoolOps2-HeinlinConcrete/1.0"
                    },
                    timeout=10,
                )

                data = response.json()

                if data:
                    prop.latitude = float(data[0]["lat"])
                    prop.longitude = float(data[0]["lon"])
                    updated += 1
                else:
                    skipped += 1

            except Exception:
                skipped += 1

        db.commit()

        return {
            "status": "geocode complete",
            "updated": updated,
            "skipped": skipped,
        }

    finally:
        db.close()

@app.get("/map")
async def map_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).order_by(Job.id.desc()).all()

        map_jobs = []

        for job in jobs:

            if job.check_in_lat and job.check_in_lng:

                map_jobs.append({
                    "id": job.id,
                    "client": job.client,
                    "address": job.address,
                    "job_type": job.job_type,
                    "status": job.status,
                    "lat": job.check_in_lat,
                    "lng": job.check_in_lng,
                    "check_type": "checkin",
                })

            if job.check_out_lat and job.check_out_lng:

                map_jobs.append({
                    "id": job.id,
                    "client": job.client,
                    "address": job.address,
                    "job_type": job.job_type,
                    "status": job.status,
                    "lat": job.check_out_lat,
                    "lng": job.check_out_lng,
                    "check_type": "checkout",
                })

        return templates.TemplateResponse(
            request,
            "map.html",
            {
                "user": user,
                "jobs": jobs,
                "map_jobs": map_jobs,
            },
        )

    finally:
        db.close()

@app.get("/admin/property-addresses")
async def property_addresses(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        properties = db.query(Property).limit(25).all()

        output = []

        for prop in properties:
            output.append({
                "client": prop.client,
                "address": prop.address,
                "city": prop.city,
                "state": prop.state,
                "zip": prop.zip_code,
            })

        return output

    finally:
        db.close()


@app.get("/admin/geocode-jobs")
async def geocode_jobs(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = db.query(Job).all()

        updated = 0
        skipped = 0

        for job in jobs:

            if not job.address:
                skipped += 1
                continue

            if job.latitude and job.longitude:
                skipped += 1
                continue

            address_parts = [
                job.address or "",
                "Evansville",
                "IN",
            ]

            query = ", ".join([part for part in address_parts if part]).strip()

            try:
                response = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={
                        "User-Agent": "PoolOps2-HeinlinConcrete/1.0"
                    },
                    timeout=10,
                )

                data = response.json()

                if data:
                    job.latitude = float(data[0]["lat"])
                    job.longitude = float(data[0]["lon"])
                    updated += 1
                else:
                    skipped += 1

            except Exception:
                skipped += 1

        db.commit()

        return {
            "status": "job geocode complete",
            "updated": updated,
            "skipped": skipped,
        }

    finally:
        db.close()

@app.get("/admin/geocode-properties")
async def geocode_properties(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        properties = db.query(Property).all()
        updated = 0
        skipped = 0

        for prop in properties:
            if prop.latitude and prop.longitude:
                skipped += 1
                continue

            address_parts = [
                prop.address or "",
                prop.city or "Evansvlle",
                prop.state or "IN",
                prop.zip_code or "",
            ]

            query = ", ".join([part for part in address_parts if part]).strip()

            if not query:
                skipped += 1
                continue

            try:
                response = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={
                        "User-Agent": "PoolOps2-HeinlinConcrete/1.0"
                    },
                    timeout=10,
                )

                data = response.json()

                if data:
                    prop.latitude = float(data[0]["lat"])
                    prop.longitude = float(data[0]["lon"])
                    updated += 1
                else:
                    skipped += 1

            except Exception:
                skipped += 1

        db.commit()

        return {
            "status": "geocode complete",
            "updated": updated,
            "skipped": skipped,
        }

    finally:
        db.close()

@app.post("/jobs/{job_id}/check-in")
async def job_check_in(
    request: Request,
    job_id: int,
    lat: float = Form(...),
    lng: float = Form(...),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.check_in_time = datetime.now()
            job.check_in_lat = lat
            job.check_in_lng = lng
            db.commit()

        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    finally:
        db.close()


@app.post("/jobs/{job_id}/check-out")
async def job_check_out(
    request: Request,
    job_id: int,
    lat: float = Form(...),
    lng: float = Form(...),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            job.check_out_time = datetime.now()
            job.check_out_lat = lat
            job.check_out_lng = lng
            db.commit()

        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    finally:
        db.close()

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

@app.get("/")
async def login_page(request: Request):
    user = get_current_user(request)

    if user:
        if user["role"] == "crew":
            return RedirectResponse(url="/crew", status_code=303)

        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(request, "login.html", {"error": None})

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {}
    )

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

@app.get("/admin/upgrade-job-schedule")
async def upgrade_job_schedule(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    columns = {
        "scheduled_start": "TIMESTAMP NULL",
        "scheduled_end": "TIMESTAMP NULL",
    }

    added = []
    skipped = []

    try:
        for column_name, column_type in columns.items():
            try:
                db.execute(
                    text(
                        f"ALTER TABLE poolops2_jobs "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )
                added.append(column_name)

            except Exception:
                db.rollback()
                skipped.append(column_name)

        db.commit()

        return {
            "status": "Job schedule upgrade complete",
            "added": added,
            "already_existed_or_skipped": skipped,
        }

    finally:
        db.close()

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
        theme = get_dashboard_theme()

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

        work_groups = dashboard_work_groups(jobs)

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
                "theme": theme,
                "work_groups": work_groups,
            },
        )

    finally:
        db.close()

@app.get("/jobs/new/{property_id}")
async def new_job_from_property(request: Request, property_id: int):

    user = require_login(request)

    if not user:
            return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
            property_obj = (
                db.query(Property)
                .filter(Property.id == property_id)
                .first()
            )

            if not property_obj:
                return RedirectResponse(url="/projects", status_code=303)

            employees = db.query(Employee).all()

            return templates.TemplateResponse(
                request,
                "job_new.html",
                {
                    "user": user,
                    "property": property_obj,
                    "employees": employees,
                },
            )

    finally:
            db.close()

@app.get("/projects")
async def projects_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        projects = db.query(Property).order_by(Property.client.asc()).all()

        return templates.TemplateResponse(
            "projects.html",
            {
                "request": request,
                "user": user,
                "projects": projects,
            },
        )

    finally:
        db.close()
DASHBOARD_THEME_FILE = "app/dashboard_theme.json"


def get_dashboard_theme():
    default_theme = {
        "title": "Heinlin Operations",
        "subtitle": " Dashboard for jobs, projects, schedules, photos, weather, billing, and field work.",
        "hero_title": "Jarvis (Mike's Brain)",
        "hero_subtitle": "We fix the unfixable & everything the other guys say they fix!",
        "accent": "#22d3ee",
        "hero_image": "",
        "background_image": "",
    }

    try:
        if os.path.exists(DASHBOARD_THEME_FILE):
            with open(DASHBOARD_THEME_FILE, "r") as f:
                saved = json.load(f)
                default_theme.update(saved)
    except Exception:
        pass

    return default_theme


@app.get("/dashboard/theme")
async def dashboard_theme_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    theme = get_dashboard_theme()

    return templates.TemplateResponse(
        request,
        "dashboard_theme.html",
        {
            "user": user,
            "theme": theme,
        },
    )


@app.post("/dashboard/theme")
async def save_dashboard_theme(
    request: Request,
    title: str = Form("Command Center"),
    subtitle: str = Form(""),
    hero_title: str = Form("Jarvis for Pool Operations"),
    hero_subtitle: str = Form(""),
    accent: str = Form("#22d3ee"),
    hero_image: UploadFile = File(None),
    background_image: UploadFile = File(None),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    os.makedirs("app/static/uploads", exist_ok=True)

    theme = get_dashboard_theme()

    theme["title"] = title.strip()
    theme["subtitle"] = subtitle.strip()
    theme["hero_title"] = hero_title.strip()
    theme["hero_subtitle"] = hero_subtitle.strip()
    theme["accent"] = accent.strip() or "#22d3ee"

    if hero_image and hero_image.filename:
        hero_path = f"app/static/uploads/dashboard_hero_{hero_image.filename}"
        with open(hero_path, "wb") as buffer:
            shutil.copyfileobj(hero_image.file, buffer)
        theme["hero_image"] = "/" + hero_path.replace("app/", "")

    if background_image and background_image.filename:
        bg_path = f"app/static/uploads/dashboard_bg_{background_image.filename}"
        with open(bg_path, "wb") as buffer:
            shutil.copyfileobj(background_image.file, buffer)
        theme["background_image"] = "/" + bg_path.replace("app/", "")

    with open(DASHBOARD_THEME_FILE, "w") as f:
        json.dump(theme, f, indent=2)

    return RedirectResponse(url="/dashboard/theme", status_code=303)


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

@app.post("/clients/{client_id}/delete")
async def delete_client(client_id: int, request: Request):

    user = require_mike(request)

    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)

    db = db_session()

    try:

        client = (
            db.query(Client)
            .filter(Client.id == client_id)
            .first()
        )

        if client:

            existing_notes = client.notes or ""

            if "[ARCHIVED_CLIENT]" not in existing_notes:

                client.notes = (
                    existing_notes
                    + "\n[ARCHIVED_CLIENT]"
                )

                db.commit()

        return RedirectResponse(
            url="/clients",
            status_code=303
        )

    except Exception as e:

        db.rollback()

        print("CLIENT DELETE ERROR:", e)

        return RedirectResponse(
            url="/clients",
            status_code=303
        )

    finally:
        db.close()

@app.post("/jobs/{job_id}/delete")
async def delete_job(job_id: int, request: Request):
    user = require_mike(request)

    if not user:
        return RedirectResponse(url="/dashboard", status_code=303) 
    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job:
            db.delete(job)
            db.commit()

        return RedirectResponse(url="/jobs", status_code=303)

    finally:
        db.close()

@app.post("/jobs/{job_id}/status")
async def update_job_detail_status(
    request: Request,
    job_id: int,
    status: str = Form(...),
):
    user = require_login(request)

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
    date: str = Form(""),
    scheduled_start: str = Form(""),
    scheduled_end: str = Form(""),
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

        start_dt = None
        end_dt = None

        if scheduled_start:
            start_dt = datetime.fromisoformat(scheduled_start)

        if scheduled_end:
            end_dt = datetime.fromisoformat(scheduled_end)

        db.add(
            Job(
                client=client.strip(),
                property=clean_address,
                address=clean_address,
                job_type=job_type.strip(),
                status=status.strip(),
                crew=crew.strip() or "Unassigned",
                date=date.strip(),
                scheduled_start=start_dt,
                scheduled_end=end_dt,
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
    user = require_mike(request)

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
async def schedule_page(request: Request, month: str = "", day: str = ""):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = (
            db.query(Job)
            .order_by(Job.scheduled_start.asc().nullslast(), Job.id.desc())
            .all()
        )
        calendar_data = build_calendar(month, day, jobs)

        return templates.TemplateResponse(
            request,
            "schedule.html",
            {
                "user": user,
                "jobs": jobs,
                "calendar_data": calendar_data,
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

# =========================================
# CLIENTS + PROPERTIES — CLIENT-FIRST SYSTEM
# =========================================

@app.get("/clients")
async def clients_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(Client.name.asc()).all()
        properties = db.query(Property).all()

        property_counts = {}

        for prop in properties:
            key = prop.client_id or prop.client
            property_counts[key] = property_counts.get(key, 0) + 1

        return templates.TemplateResponse(
            "clients.html",
            {
                "request": request,
                "user": user,
                "clients": clients,
                "properties": properties,
                "property_counts": property_counts,
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
        {
            "request": request,
            "user": user,
        },
    )


@app.post("/clients/add")
async def add_client(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    mobile: str = Form(""),
    email: str = Form(""),
    billing_address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        existing = db.query(Client).filter(
            Client.name == name.strip()
        ).first()

        if not existing:
            new_client = Client(
                name=name.strip(),
                phone=phone.strip(),
                mobile=mobile.strip(),
                email=email.strip(),
                billing_address=billing_address.strip(),
                city=city.strip(),
                state=state.strip(),
                zip_code=zip_code.strip(),
                notes=notes.strip(),
            )

            db.add(new_client)
            db.commit()

        return RedirectResponse(
            url="/clients",
            status_code=303
        )

    finally:
        db.close()


@app.get("/clients/{client_id}")
async def client_detail_page(
    request: Request,
    client_id: int
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        client_obj = db.query(Client).filter(
            Client.id == client_id
        ).first()

        if not client_obj:
            return RedirectResponse(
                url="/clients",
                status_code=303
            )

        properties = db.query(Property).filter(
            (Property.client_id == client_obj.id)
            |
            (Property.client == client_obj.name)
        ).order_by(
            Property.id.desc()
        ).all()

        jobs = db.query(Job).filter(
            Job.client == client_obj.name
        ).order_by(
            Job.id.desc()
        ).all()

        photos = db.query(PhotoLog).filter(
            PhotoLog.client == client_obj.name
        ).order_by(
            PhotoLog.id.desc()
        ).all()

        return templates.TemplateResponse(
            "client_detail.html",
            {
                "request": request,
                "user": user,
                "client": client_obj,
                "properties": properties,
                "jobs": jobs,
                "photos": photos,
            }
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
        properties = db.query(Property).order_by(
    Property.address.asc()
).all()

        properties = sorted(
    properties,
    key=lambda p: (
        1 if not (p.address or "").strip() else 0,
        (p.client or "").lower(),
        (p.property_name or "").lower(),
        (p.address or "").lower(),
    )
)   
        return templates.TemplateResponse(

            "properties.html",
            {
                "request": request,
                "user": user,
                "properties": properties,
            }
        )

    finally:
      db.close()


@app.get("/properties/new", response_class=HTMLResponse)
async def new_property_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        clients = db.query(Client).order_by(
            Client.name.asc()
        ).all()

        return templates.TemplateResponse(
            "property_new.html",
            {
                "request": request,
                "user": user,
                "clients": clients,
            }
        )

    finally:
        db.close()


@app.post("/properties/new")
async def save_property(
    request: Request,
    client_id: int = Form(...),
    property_name: str = Form(""),
    address: str = Form(...),
    city: str = Form(""),
    state: str = Form("IN"),
    zip_code: str = Form(""),
    pool_type: str = Form(""),
    pool_size: str = Form(""),
    pool_depth: str = Form(""),
    cover_type: str = Form(""),
    finish_type: str = Form(""),
    pump_model: str = Form(""),
    filter_model: str = Form(""),
    heater_model: str = Form(""),
    sanitizer: str = Form(""),
    automation_system: str = Form(""),
    gate_code: str = Form(""),
    service_plan: str = Form(""),
    notes: str = Form(""),
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        client_obj = db.query(Client).filter(
            Client.id == client_id
        ).first()

        if not client_obj:
            return RedirectResponse(
                url="/properties/new",
                status_code=303
            )

        new_property = Property(
            client_id=client_obj.id,
            client=client_obj.name,
            property_name=property_name.strip(),
            address=address.strip(),
            city=city.strip(),
            state=state.strip(),
            zip_code=zip_code.strip(),
            pool_type=pool_type.strip(),
            pool_size=pool_size.strip(),
            pool_depth=pool_depth.strip(),
            cover_type=cover_type.strip(),
            finish_type=finish_type.strip(),
            pump_model=pump_model.strip(),
            filter_model=filter_model.strip(),
            heater_model=heater_model.strip(),
            sanitizer=sanitizer.strip(),
            automation_system=automation_system.strip(),
            gate_code=gate_code.strip(),
            service_plan=service_plan.strip(),
            notes=notes.strip(),
        )

        db.add(new_property)
        db.commit()

        return RedirectResponse(
            url=f"/clients/{client_obj.id}",
            status_code=303
        )

    except Exception as e:
        db.rollback()

        print("SAVE PROPERTY ERROR:", e)

        return RedirectResponse(
            url="/properties/new",
            status_code=303
        )

    finally:
        db.close()


@app.get("/properties/{property_id}")
async def property_detail_page(
    request: Request,
    property_id: int
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        prop = db.query(Property).filter(
            Property.id == property_id
        ).first()

        if not prop:
            return RedirectResponse(
                url="/properties",
                status_code=303
            )

        jobs = db.query(Job).filter(
            Job.address == prop.address
        ).order_by(
            Job.id.desc()
        ).all()

        return templates.TemplateResponse(
            "property_detail.html",
            {
                "request": request,
                "user": user,
                "property": prop,
                "jobs": jobs,
            }
        )

    finally:
        db.close()

@app.post("/crew/profile")
async def update_crew_profile(
    request: Request,
    phone: str = Form(""),
    email: str = Form(""),
    card_image: str = Form(""),
):
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()
    try:
        employee = db.query(Employee).filter(Employee.name == user["name"]).first()
        if not employee:
            employee = Employee(name=user["name"], role=user["role"].title())
            db.add(employee)
            db.flush()
        employee.phone = phone.strip()
        employee.email = email.strip()
        employee.card_image = card_image.strip()
        db.commit()
        return RedirectResponse(url="/crew", status_code=303)
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
    user = require_mike(request)

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

@app.get("/quick-add")
async def quick_add_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "quick_add.html",
        {
            "user": user,
        },
    )

@app.post("/quick-add")
async def quick_add_job(
    request: Request,
    client: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    job_type: str = Form("Service"),
    status: str = Form("Requested"),
    priority: str = Form("Normal"),
    date: str = Form(""),
    notes: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:

        existing_client = (
            db.query(Client)
            .filter(Client.name == client.strip())
            .first()
        )

        if not existing_client:

            db.add(
                Client(
                    name=client.strip(),
                    phone=phone.strip(),
                    notes=notes.strip(),
                )
            )

        db.add(
            Job(
                client=client.strip(),
                address=address.strip(),
                property=address.strip(),
                job_type=job_type.strip(),
                status=status.strip(),
                priority=priority.strip(),
                date=date.strip(),
                notes=notes.strip(),
            )
        )

        db.commit()

        return RedirectResponse(
            url="/jobs",
            status_code=303
        )

    finally:
        db.close()

@app.get("/openings")
async def openings_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = (
            db.query(Job)
            .filter(Job.job_type.ilike("%opening%"))
            .order_by(Job.scheduled_start.asc().nullslast(), Job.id.desc())
            .all()
        )

        return templates.TemplateResponse(
            request,
            "seasonal_queue.html",
            {
                "user": user,
                "jobs": jobs,
                "queue_title": "Pool Openings",
                "queue_subtitle": "Opening season command board.",
                "queue_type": "Opening",
            },
        )

    finally:
        db.close()


@app.get("/closings")
async def closings_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        jobs = (
            db.query(Job)
            .filter(Job.job_type.ilike("%closing%"))
            .order_by(Job.scheduled_start.asc().nullslast(), Job.id.desc())
            .all()
        )

        return templates.TemplateResponse(
            request,
            "seasonal_queue.html",
            {
                "user": user,
                "jobs": jobs,
                "queue_title": "Pool Closings",
                "queue_subtitle": "Closing season command board.",
                "queue_type": "Closing",
            },
        )

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
    user = require_mike(request)

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
    user = require_mike(request)

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
                "properties": db.query(Property).order_by(Property.client.asc(), Property.address.asc()).all(),
            },
        )

    finally:
        db.close()


@app.post("/photos/add")
async def add_photo_log(
    request: Request,
    job_id: int = Form(...),
    photo_type: str = Form(...),
    title: str = Form(""),
    photo_files: List[UploadFile] = File(None),
    date: str = Form("Today"),
    notes: str = Form(""),
    property_id: int = Form(0),
    latitude: str = Form(""),
    longitude: str = Form(""),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        client_name = job.client if job else "Unknown Client"

        if not photo_files:
            return RedirectResponse(url="/photos", status_code=303)

        for index, photo_file in enumerate(photo_files):

            if not photo_file or not photo_file.filename:
                continue

            file_bytes = await photo_file.read()
            encoded = base64.b64encode(file_bytes).decode("utf-8")

            content_type = photo_file.content_type or "image/jpeg"
            photo_url = f"data:{content_type};base64,{encoded}"

            photo_title = title.strip() or "Job Photo"

            if len(photo_files) > 1:
                photo_title = f"{photo_title} {index + 1}"

            photo_log = PhotoLog(
                job_id=job_id,
                client=client_name,
                photo_type=photo_type.strip(),
                title=photo_title,
                photo_url=photo_url,
                date=date.strip(),
                notes=notes.strip(),
            )
            attach_photo_to_property(db, photo_log, property_id or None, latitude or None, longitude or None)
            db.add(photo_log)

        db.commit()

        return RedirectResponse(url="/photos", status_code=303)

    finally:
        db.close()


from typing import List
import os
import shutil
from uuid import uuid4


@app.post("/jobs/{job_id}/upload-photos")
async def upload_job_photos(
    request: Request,
    job_id: int,
    photo_type: str = Form(...),
    title: str = Form(""),
    date: str = Form(""),
    notes: str = Form(""),
    property_id: int = Form(0),
    latitude: str = Form(""),
    longitude: str = Form(""),
    photo_files: List[UploadFile] = File(...)
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if not job:
            return RedirectResponse(url="/jobs", status_code=303)

        upload_dir = "app/static/uploads"

        os.makedirs(upload_dir, exist_ok=True)

        for index, photo_file in enumerate(photo_files):

            if not photo_file.filename:
                continue

            ext = photo_file.filename.split(".")[-1]

            filename = f"{uuid4()}.{ext}"

            filepath = os.path.join(upload_dir, filename)

            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(photo_file.file, buffer)

            photo_url = f"/static/uploads/{filename}"

            photo_log = PhotoLog(
                job_id=job.id,
                client=job.client,
                photo_type=photo_type,
                title=f"{title} {index + 1}".strip(),
                photo_url=photo_url,
                date=date,
                notes=notes,
            )
            attach_photo_to_property(db, photo_log, property_id or None, latitude or None, longitude or None)
            db.add(photo_log)

        db.commit()

        return RedirectResponse(
            url=f"/jobs/{job.id}",
            status_code=303
        )

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
    user = require_mike(request)

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

@app.get("/contact-matcher")
async def contact_matcher_page(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "contact_matcher.html",
        {
            "user": user,
            "matches": None,
            "new_contacts": None,
        },
    )

@app.post("/contact-matcher")
async def contact_matcher_upload(
    request: Request,
    csv_file: UploadFile = File(...)
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    contents = await csv_file.read()
    decoded = contents.decode("utf-8").splitlines()

    import csv

    reader = csv.DictReader(decoded)

    imported_contacts = []

    for row in reader:
        imported_contacts.append({
            "name": row.get("Name", ""),
            "phone": row.get("Phone", ""),
            "email": row.get("E-mail 1 - Value", "")
        })

    db = db_session()

    try:
        clients = db.query(Client).all()

        matches = []
        new_contacts = []

        for contact in imported_contacts:
            found = False

            contact_name = (contact["name"] or "").lower().strip()
            contact_email = (contact["email"] or "").lower().strip()

            contact_phone = (
                (contact["phone"] or "")
                .replace("-", "")
                .replace("(", "")
                .replace(")", "")
                .replace(" ", "")
                .replace(".", "")
            )

            for client in clients:
                client_name = (client.name or "").lower().strip()
                client_email = (client.email or "").lower().strip()

                client_phone = (
                    (client.phone or "")
                    .replace("-", "")
                    .replace("(", "")
                    .replace(")", "")
                    .replace(" ", "")
                    .replace(".", "")
                )

                matched = False

                if client_phone and contact_phone and client_phone[-7:] == contact_phone[-7:]:
                    matched = True

                elif client_email and contact_email and client_email == contact_email:
                    matched = True

                elif client_name and contact_name and client_name == contact_name:
                    matched = True

                if matched:
                    matches.append({
                        "contact": contact,
                        "client": client
                    })

                    found = True
                    break

            if not found:
                new_contacts.append(contact)

        return templates.TemplateResponse(
            request,
            "contact_matcher.html",
            {
                "user": user,
                "matches": matches,
                "new_contacts": new_contacts,
            },
        )

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
    user = require_mike(request)

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
    email_or_name: str = Form(...),
    password: str = Form("")
):

    db = db_session()

    try:
        login_value = email_or_name.strip().lower()
        client = db.query(Client).filter(Client.portal_username == login_value).first()

        if not client:
            client = db.query(Client).filter(Client.email == login_value).first()

        if not client:
            client = db.query(Client).filter(Client.name == email_or_name.strip()).first()

        saved_password = (getattr(client, "portal_password", "") if client else "") or ""
        if not client or (saved_password and saved_password != password.strip()):
            return templates.TemplateResponse(
                "client_login.html",
                {
                    "request": request,
                    "error": "Client login not found or password is incorrect."
                }
            )

        request.session["client_id"] = client.id

        return RedirectResponse(
            "/client-dashboard",
            status_code=303
        )

    finally:
        db.close()

@app.post("/clients/{client_id}/edit")
async def update_client(
    request: Request,
    client_id: int,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    notes: str = Form("")
):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        client = db.query(Client).filter(Client.id == client_id).first()

        if not client:
            return HTMLResponse("Client not found", status_code=404)

        client.name = name.strip()
        client.phone = phone.strip()
        client.email = email.strip()
        client.billing_address = address.strip()
        client.notes = notes.strip()

        db.commit()

        return RedirectResponse(url="/clients", status_code=303)

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

        property_ids = [p.id for p in properties]
        photos = []
        if property_ids:
            photos = db.query(PhotoLog).filter(PhotoLog.property_id.in_(property_ids)).order_by(PhotoLog.id.desc()).all()
        if not photos:
            photos = db.query(PhotoLog).filter(PhotoLog.client == client.name).order_by(PhotoLog.id.desc()).all()

        public_schedule = db.query(Job).all()
        calendar_data = build_calendar("", "", public_schedule)

        return templates.TemplateResponse(
            "client_dashboard.html",
            {
                "request": request,
                "client": client,
                "jobs": jobs,
                "properties": properties,
                "photos": photos,
                "public_schedule": public_schedule,
                "calendar_data": calendar_data,
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
            notes=message,
     
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

    return {
        "current": {
            "temperature_2m": 72,
            "precipitation": 0,
            "wind_speed_10m": 8,
        },
        "daily": {
            "time": [
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
            ],
            "temperature_2m_max": [74, 78, 80, 76, 73],
            "temperature_2m_min": [58, 60, 62, 59, 57],
            "precipitation_probability_max": [10, 20, 50, 30, 15],
            "precipitation_sum": [0.1, 0.3, 0.5, 0.2, 0.1],
            "wind_speed_10m_max": [8, 10, 14, 12, 9],
        }
    }

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



@app.post("/clients/{client_id}/portal-login")
async def create_client_portal_login(
    request: Request,
    client_id: int,
    portal_username: str = Form(""),
    portal_password: str = Form(""),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            username_value = (portal_username or client.email or client.name).strip().lower().replace(" ", "")
            password_value = (portal_password or str(client.id).zfill(4)).strip()
            client.portal_username = username_value
            client.portal_password = password_value
            db.commit()
        return RedirectResponse(url=f"/clients/{client_id}", status_code=303)
    finally:
        db.close()

@app.post("/clients/{client_id}/card-image")
async def update_client_card_image(request: Request, client_id: int, card_image: str = Form("")):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            client.card_image = card_image.strip()
            db.commit()
        return RedirectResponse(url=f"/clients/{client_id}", status_code=303)
    finally:
        db.close()

@app.post("/properties/{property_id}/card-image")
async def update_property_card_image(request: Request, property_id: int, card_image: str = Form("")):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        prop = db.query(Property).filter(Property.id == property_id).first()
        if prop:
            prop.card_image = card_image.strip()
            db.commit()
        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)
    finally:
        db.close()

@app.post("/admin/clients-to-properties")
async def convert_client_addresses_to_properties(request: Request):
    user = require_admin(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()
    try:
        clients = db.query(Client).all()
        created = 0
        for client in clients:
            address = (client.billing_address or client.shipping_address or "").strip()
            if not address:
                continue
            existing = db.query(Property).filter(
                Property.client_id == client.id,
                Property.address == address
            ).first()
            if existing:
                continue
            db.add(Property(
                client_id=client.id,
                client=client.name,
                property_name=f"{client.name} Pool",
                address=address,
                city=client.city or "",
                state=client.state or "",
                zip_code=client.zip_code or "",
                notes="Created automatically from the QuickBooks client address import.",
            ))
            created += 1
        db.commit()
        return RedirectResponse(url=f"/properties?created={created}", status_code=303)
    finally:
        db.close()

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

@app.get("/weather-test")
async def weather_test():
    weather = get_evansville_weather()

    if not weather:
        return {"status": "failed", "weather": None}

    return {
        "status": "ok",
        "current": weather.get("current", {}),
        "daily_keys": list(weather.get("daily", {}).keys()),
    }

@app.get("/weather")
async def weather_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    current = {}
    daily = {}
    alerts = []

    try:
        weather = get_evansville_weather()

        if weather:
            current = weather.get("current", {})
            daily = weather.get("daily", {})
            alerts = build_weather_alerts(weather)

    except Exception as e:
        print("WEATHER ERROR:", e)

    return templates.TemplateResponse(
        request,
        "weather.html",
        {
            "user": user,
            "weather": weather if "weather" in locals() else None,
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

@app.get("/assistant")
async def assistant_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request,
        "assistant.html",
        {
            "user": user,
            "question": "",
            "answer": "",
        },
    )


@app.post("/assistant")
async def assistant_answer(
    request: Request,
    question: str = Form(...),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    db = db_session()

    try:
        q = question.lower().strip()

        clients = db.query(Client).all()
        jobs = db.query(Job).all()

        results = []

        for client in clients:
            searchable = " ".join([
                client.name or "",
                getattr(client, "phone", "") or "",
                getattr(client, "email", "") or "",
                getattr(client, "address", "") or "",
                client.notes or "",
            ]).lower()

            if any(word in searchable for word in q.split()):
                results.append(
                    f"<div class='result-card'>"
                    f"<h3>Client: {client.name}</h3>"
                    f"<p><strong>Phone:</strong> {getattr(client, 'phone', '') or '—'}</p>"
                    f"<p><strong>Email:</strong> {getattr(client, 'email', '') or '—'}</p>"
                    f"<p><strong>Notes:</strong> {client.notes or '—'}</p>"
                    f"<a class='btn' href='/clients/{client.id}'>Open Client</a>"
                    f"</div>"
                )

        for job in jobs:
            searchable = " ".join([
                job.client or "",
                job.address or "",
                job.job_type or "",
                job.status or "",
                getattr(job, "notes", "") or "",
            ]).lower()

            if any(word in searchable for word in q.split()):
                results.append(
                    f"<div class='result-card'>"
                    f"<h3>Job: {job.client}</h3>"
                    f"<p><strong>Type:</strong> {job.job_type or '—'}</p>"
                    f"<p><strong>Status:</strong> {job.status or '—'}</p>"
                    f"<p><strong>Address:</strong> {job.address or '—'}</p>"
                    f"<a class='btn' href='/jobs/{job.id}'>Open Job</a>"
                    f"</div>"
                )

        if not results:
            answer = (
                "<p>I did not find a strong match yet. Try using a client name, "
                "address, job type, status, or equipment keyword.</p>"
            )
        else:
            answer = "".join(results[:20])

        return templates.TemplateResponse(
            request,
            "assistant.html",
            {
                "user": user,
                "question": question,
                "answer": answer,
            },
        )

    finally:
        db.close()

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
    
TEMP_ESTIMATE_FILE = "app/temp_estimates.json"


def load_temp_estimates():
    if not os.path.exists(TEMP_ESTIMATE_FILE):
        return []

    try:
        with open(TEMP_ESTIMATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_temp_estimates(estimates):
    with open(TEMP_ESTIMATE_FILE, "w") as f:
        json.dump(estimates, f, indent=2)


@app.get("/estimate-capture")
async def estimate_capture_page(request: Request):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    estimates = load_temp_estimates()

    return templates.TemplateResponse(
        request,
        "estimate_capture.html",
        {
            "user": user,
            "estimates": estimates,
            "message": None,
        },
    )


@app.post("/estimate-capture/save")
async def save_estimate_capture(
    request: Request,
    client: str = Form(...),
    property_address: str = Form(...),
    estimate_type: str = Form(...),
    captured_text: str = Form(""),
    total: str = Form("0"),
    notes: str = Form(""),
    estimate_image: UploadFile = File(None),
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    image_url = ""

    if estimate_image and estimate_image.filename:
        clean_name = estimate_image.filename.replace(" ", "_")

        image_path = os.path.join(
            UPLOAD_DIR,
            f"estimate_{clean_name}"
        )

        with open(image_path, "wb") as buffer:
            shutil.copyfileobj(estimate_image.file, buffer)

        image_url = "/" + image_path.replace("app/", "")

    estimates = load_temp_estimates()

    new_estimate = {
        "client": client.strip(),
        "property_address": property_address.strip(),
        "estimate_type": estimate_type.strip(),
        "captured_text": captured_text.strip(),
        "total": total.strip(),
        "notes": notes.strip(),
        "image_url": image_url,
    }

    estimates.insert(0, new_estimate)
    save_temp_estimates(estimates)

    return templates.TemplateResponse(
        request,
        "estimate_capture.html",
        {
            "user": user,
            "estimates": estimates,
            "message": "Estimate saved successfully.",
        },
    )     

@app.post("/estimate-to-job/{estimate_index}")
async def estimate_to_job(
    request: Request,
    estimate_index: int,
):
    user = require_login(request)

    if not user:
        return RedirectResponse(url="/", status_code=303)

    estimates = load_temp_estimates()

    if estimate_index < 0 or estimate_index >= len(estimates):
        return RedirectResponse(url="/estimate-capture", status_code=303)

    estimate = estimates[estimate_index]

    db = db_session()

    try:
        client_name = estimate.get("client", "").strip() or "Unknown Client"
        property_address = estimate.get("property_address", "").strip() or "No address listed"
        estimate_type = estimate.get("estimate_type", "").strip() or "Captured Estimate"
        captured_text = estimate.get("captured_text", "").strip()
        total = estimate.get("total", "").strip()
        notes = estimate.get("notes", "").strip()

        existing_client = db.query(Client).filter(Client.name == client_name).first()

        if not existing_client:
            existing_client = Client(
                name=client_name,
                phone="",
                email="",
                notes="Created from estimate capture."
            )
            db.add(existing_client)
            db.commit()
            db.refresh(existing_client)

        existing_property = db.query(Property).filter(
            Property.client == client_name,
            Property.address == property_address,
        ).first()

        if not existing_property:
            existing_property = Property(
                client_id=existing_client.id,
                client=client_name,
                address=property_address,
                pool_type="",
                notes="Created from estimate capture."
            )
            db.add(existing_property)
            db.commit()

        job_notes = f"""
Created from Estimate Capture.

Estimate Type:
{estimate_type}

Estimate Total:
${total}

Captured Estimate Text:
{captured_text}

Notes:
{notes}
""".strip()

        new_job = Job(
            client=client_name,
            property=property_address,
            address=property_address,
            job_type=estimate_type,
            status="Pending",
            crew="Unassigned",
            date="Unscheduled",
            priority="Normal",
            notes=job_notes,
        )

        db.add(new_job)
        db.commit()

    finally:
        db.close()

    return RedirectResponse(url="/jobs", status_code=303)