from datetime import date
from pathlib import Path
import json

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.database import SessionLocal


ROOT = Path(__file__).resolve().parent.parent.parent
DESIGN_FILE = ROOT / "app" / "design_studio.json"

router = APIRouter()
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))


def login_redirect():
    return RedirectResponse("/login", status_code=303)


def require_login(request: Request):
    return request.session.get("user")


def is_admin(user):
    return user and user.get("role") == "admin"


def is_client(user):
    return user and user.get("role") == "client"


def is_employee(user):
    return user and str(user.get("role", "")).lower() in ("employee", "crew")


def design_settings():
    if not DESIGN_FILE.exists():
        return {}

    try:
        return json.loads(DESIGN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ctx(request: Request, **kwargs):
    user = require_login(request)
    data = {
        "request": request,
        "user": user,
        "theme": {},
        "design": design_settings(),
        "is_admin": is_admin(user),
        "is_client": is_client(user),
        "is_employee": is_employee(user),
    }
    data.update(kwargs)
    return data


def to_int_or_none(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except Exception:
        return None


def db_rows(db, sql, params=None):
    result = db.execute(text(sql), params or {})
    return [dict(row._mapping) for row in result]


def db_one(db, sql, params=None):
    result = db.execute(text(sql), params or {})
    row = result.first()
    return dict(row._mapping) if row else None


def ensure_pool_monitoring_schema(db):
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    dialect = getattr(dialect, "name", "")

    if dialect == "postgresql":
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS pool_monitoring (
                    id SERIAL PRIMARY KEY,
                    client_id INTEGER,
                    property_id INTEGER,
                    system_brand TEXT DEFAULT 'Pentair',
                    system_type TEXT DEFAULT '',
                    pentair_account_email TEXT DEFAULT '',
                    pentair_system_name TEXT DEFAULT '',
                    pentair_dashboard_url TEXT DEFAULT '',
                    monitoring_status TEXT DEFAULT 'Not Started',
                    last_checked TEXT DEFAULT '',
                    current_alert TEXT DEFAULT '',
                    next_action TEXT DEFAULT '',
                    equipment_notes TEXT DEFAULT '',
                    service_notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT ''
                )
                """
            )
        )
    else:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS pool_monitoring (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER,
                    property_id INTEGER,
                    system_brand TEXT DEFAULT 'Pentair',
                    system_type TEXT DEFAULT '',
                    pentair_account_email TEXT DEFAULT '',
                    pentair_system_name TEXT DEFAULT '',
                    pentair_dashboard_url TEXT DEFAULT '',
                    monitoring_status TEXT DEFAULT 'Not Started',
                    last_checked TEXT DEFAULT '',
                    current_alert TEXT DEFAULT '',
                    next_action TEXT DEFAULT '',
                    equipment_notes TEXT DEFAULT '',
                    service_notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT ''
                )
                """
            )
        )

    db.commit()

    needed_columns = [
        ("client_id", "INTEGER"),
        ("property_id", "INTEGER"),
        ("system_brand", "TEXT DEFAULT 'Pentair'"),
        ("system_type", "TEXT DEFAULT ''"),
        ("pentair_account_email", "TEXT DEFAULT ''"),
        ("pentair_system_name", "TEXT DEFAULT ''"),
        ("pentair_dashboard_url", "TEXT DEFAULT ''"),
        ("monitoring_status", "TEXT DEFAULT 'Not Started'"),
        ("last_checked", "TEXT DEFAULT ''"),
        ("current_alert", "TEXT DEFAULT ''"),
        ("next_action", "TEXT DEFAULT ''"),
        ("equipment_notes", "TEXT DEFAULT ''"),
        ("service_notes", "TEXT DEFAULT ''"),
        ("created_at", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''"),
    ]

    for column_name, column_type in needed_columns:
        try:
            db.execute(text(f"ALTER TABLE pool_monitoring ADD COLUMN {column_name} {column_type}"))
            db.commit()
        except Exception:
            db.rollback()


@router.get("/pool-monitoring", response_class=HTMLResponse)
def pool_monitoring_page(request: Request):
    user = require_login(request)
    if not user:
        return login_redirect()

    db = SessionLocal()
    try:
        ensure_pool_monitoring_schema(db)

        clients = db_rows(
            db,
            """
            SELECT *
            FROM poolops2_clients
            ORDER BY name ASC
            """
        )

        properties = db_rows(
            db,
            """
            SELECT *
            FROM poolops2_properties
            ORDER BY id DESC
            """
        )

        records = db_rows(
            db,
            """
            SELECT
                pm.*,
                c.name AS client_name,
                p.property_name AS property_name,
                p.address AS address
            FROM pool_monitoring pm
            LEFT JOIN poolops2_clients c ON c.id = pm.client_id
            LEFT JOIN poolops2_properties p ON p.id = pm.property_id
            ORDER BY pm.id DESC
            """
        )

        return templates.TemplateResponse(
            "pool_monitoring.html",
            ctx(
                request,
                records=records,
                clients=clients,
                properties=properties,
            ),
        )

    finally:
        db.close()


@router.post("/pool-monitoring/add")
def add_pool_monitoring(
    request: Request,
    client_id: str = Form(""),
    property_id: str = Form(""),
    system_brand: str = Form("Pentair"),
    system_type: str = Form(""),
    pentair_account_email: str = Form(""),
    pentair_system_name: str = Form(""),
    pentair_dashboard_url: str = Form(""),
    monitoring_status: str = Form("Needs Check"),
    current_alert: str = Form(""),
    next_action: str = Form(""),
    equipment_notes: str = Form(""),
    service_notes: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()

    now = date.today().isoformat()

    db = SessionLocal()
    try:
        ensure_pool_monitoring_schema(db)

        db.execute(
            text(
                """
                INSERT INTO pool_monitoring
                (
                    client_id,
                    property_id,
                    system_brand,
                    system_type,
                    pentair_account_email,
                    pentair_system_name,
                    pentair_dashboard_url,
                    monitoring_status,
                    last_checked,
                    current_alert,
                    next_action,
                    equipment_notes,
                    service_notes,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    :client_id,
                    :property_id,
                    :system_brand,
                    :system_type,
                    :pentair_account_email,
                    :pentair_system_name,
                    :pentair_dashboard_url,
                    :monitoring_status,
                    :last_checked,
                    :current_alert,
                    :next_action,
                    :equipment_notes,
                    :service_notes,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "client_id": to_int_or_none(client_id),
                "property_id": to_int_or_none(property_id),
                "system_brand": system_brand or "Pentair",
                "system_type": system_type,
                "pentair_account_email": pentair_account_email,
                "pentair_system_name": pentair_system_name,
                "pentair_dashboard_url": pentair_dashboard_url,
                "monitoring_status": monitoring_status or "Needs Check",
                "last_checked": "",
                "current_alert": current_alert,
                "next_action": next_action,
                "equipment_notes": equipment_notes,
                "service_notes": service_notes,
                "created_at": now,
                "updated_at": now,
            },
        )

        db.commit()
        return RedirectResponse("/pool-monitoring", status_code=303)

    finally:
        db.close()


@router.post("/pool-monitoring/{record_id}/update")
def update_pool_monitoring(
    request: Request,
    record_id: int,
    system_brand: str = Form("Pentair"),
    system_type: str = Form(""),
    pentair_account_email: str = Form(""),
    pentair_system_name: str = Form(""),
    pentair_dashboard_url: str = Form(""),
    monitoring_status: str = Form("Needs Check"),
    current_alert: str = Form(""),
    next_action: str = Form(""),
    equipment_notes: str = Form(""),
    service_notes: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()

    db = SessionLocal()
    try:
        ensure_pool_monitoring_schema(db)

        existing = db_one(
            db,
            """
            SELECT id
            FROM pool_monitoring
            WHERE id = :record_id
            """,
            {"record_id": record_id},
        )

        if existing:
            db.execute(
                text(
                    """
                    UPDATE pool_monitoring
                    SET
                        system_brand = :system_brand,
                        system_type = :system_type,
                        pentair_account_email = :pentair_account_email,
                        pentair_system_name = :pentair_system_name,
                        pentair_dashboard_url = :pentair_dashboard_url,
                        monitoring_status = :monitoring_status,
                        current_alert = :current_alert,
                        next_action = :next_action,
                        equipment_notes = :equipment_notes,
                        service_notes = :service_notes,
                        updated_at = :updated_at
                    WHERE id = :record_id
                    """
                ),
                {
                    "record_id": record_id,
                    "system_brand": system_brand or "Pentair",
                    "system_type": system_type,
                    "pentair_account_email": pentair_account_email,
                    "pentair_system_name": pentair_system_name,
                    "pentair_dashboard_url": pentair_dashboard_url,
                    "monitoring_status": monitoring_status or "Needs Check",
                    "current_alert": current_alert,
                    "next_action": next_action,
                    "equipment_notes": equipment_notes,
                    "service_notes": service_notes,
                    "updated_at": date.today().isoformat(),
                },
            )

            db.commit()

        return RedirectResponse("/pool-monitoring", status_code=303)

    finally:
        db.close()


@router.post("/pool-monitoring/{record_id}/checked")
def mark_pool_monitoring_checked(request: Request, record_id: int):
    user = require_login(request)
    if not user:
        return login_redirect()

    db = SessionLocal()
    try:
        ensure_pool_monitoring_schema(db)

        today = date.today().isoformat()

        db.execute(
            text(
                """
                UPDATE pool_monitoring
                SET
                    last_checked = :last_checked,
                    monitoring_status = :monitoring_status,
                    updated_at = :updated_at
                WHERE id = :record_id
                """
            ),
            {
                "record_id": record_id,
                "last_checked": today,
                "monitoring_status": "Checked",
                "updated_at": today,
            },
        )

        db.commit()
        return RedirectResponse("/pool-monitoring", status_code=303)

    finally:
        db.close()


@router.post("/pool-monitoring/{record_id}/delete")
def delete_pool_monitoring(request: Request, record_id: int):
    user = require_login(request)
    if not user:
        return login_redirect()

    if not is_admin(user):
        return RedirectResponse("/pool-monitoring", status_code=303)

    db = SessionLocal()
    try:
        ensure_pool_monitoring_schema(db)

        db.execute(
            text(
                """
                DELETE FROM pool_monitoring
                WHERE id = :record_id
                """
            ),
            {"record_id": record_id},
        )

        db.commit()
        return RedirectResponse("/pool-monitoring", status_code=303)

    finally:
        db.close()