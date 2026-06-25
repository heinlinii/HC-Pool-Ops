from datetime import date
from pathlib import Path
from typing import Optional
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


def db_rows(db, sql, params=None):
    result = db.execute(text(sql), params or {})
    return [dict(row._mapping) for row in result]


def db_one(db, sql, params=None):
    result = db.execute(text(sql), params or {})
    row = result.first()
    return dict(row._mapping) if row else None


@router.get("/pool-monitoring", response_class=HTMLResponse)
def pool_monitoring_page(request: Request):
    user = require_login(request)
    if not user:
        return login_redirect()

    db = SessionLocal()
    try:
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
    client_id: Optional[int] = Form(None),
    property_id: Optional[int] = Form(None),
    system_brand: str = Form("Pentair"),
    system_type: str = Form(""),
    pentair_account_email: str = Form(""),
    monitoring_status: str = Form("Not Started"),
    current_alert: str = Form(""),
    equipment_notes: str = Form(""),
    service_notes: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()

    db = SessionLocal()
    try:
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
                    monitoring_status,
                    last_checked,
                    current_alert,
                    equipment_notes,
                    service_notes
                )
                VALUES
                (
                    :client_id,
                    :property_id,
                    :system_brand,
                    :system_type,
                    :pentair_account_email,
                    :monitoring_status,
                    :last_checked,
                    :current_alert,
                    :equipment_notes,
                    :service_notes
                )
                """
            ),
            {
                "client_id": client_id,
                "property_id": property_id,
                "system_brand": system_brand or "Pentair",
                "system_type": system_type,
                "pentair_account_email": pentair_account_email,
                "monitoring_status": monitoring_status or "Not Started",
                "last_checked": date.today().isoformat(),
                "current_alert": current_alert,
                "equipment_notes": equipment_notes,
                "service_notes": service_notes,
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
    monitoring_status: str = Form("Not Started"),
    current_alert: str = Form(""),
    equipment_notes: str = Form(""),
    service_notes: str = Form(""),
):
    user = require_login(request)
    if not user:
        return login_redirect()

    db = SessionLocal()
    try:
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
                        monitoring_status = :monitoring_status,
                        current_alert = :current_alert,
                        equipment_notes = :equipment_notes,
                        service_notes = :service_notes,
                        last_checked = :last_checked
                    WHERE id = :record_id
                    """
                ),
                {
                    "record_id": record_id,
                    "monitoring_status": monitoring_status or "Not Started",
                    "current_alert": current_alert,
                    "equipment_notes": equipment_notes,
                    "service_notes": service_notes,
                    "last_checked": date.today().isoformat(),
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