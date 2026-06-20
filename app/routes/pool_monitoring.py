from datetime import date
from pathlib import Path
from typing import Optional
import json

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PoolMonitoring, Client, Property


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


@router.get("/pool-monitoring")
def pool_monitoring_page(request: Request):
    user = require_login(request)
    if not user:
        return login_redirect()

    db: Session = SessionLocal()
    try:
        records = (
            db.query(PoolMonitoring)
            .order_by(PoolMonitoring.updated_at.desc())
            .all()
        )

        clients = db.query(Client).order_by(Client.name.asc()).all()
        properties = db.query(Property).order_by(Property.id.desc()).all()

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

    db: Session = SessionLocal()
    try:
        record = PoolMonitoring(
            client_id=client_id,
            property_id=property_id,
            system_brand="Pentair",
            system_type=system_type,
            pentair_account_email=pentair_account_email,
            monitoring_status=monitoring_status,
            last_checked=date.today(),
            current_alert=current_alert,
            equipment_notes=equipment_notes,
            service_notes=service_notes,
        )

        db.add(record)
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

    db: Session = SessionLocal()
    try:
        record = db.query(PoolMonitoring).filter(PoolMonitoring.id == record_id).first()

        if record:
            record.monitoring_status = monitoring_status
            record.current_alert = current_alert
            record.equipment_notes = equipment_notes
            record.service_notes = service_notes
            record.last_checked = date.today()

            db.commit()

        return RedirectResponse("/pool-monitoring", status_code=303)
    finally:
        db.close()


@router.post("/pool-monitoring/{record_id}/delete")
def delete_pool_monitoring(request: Request, record_id: int):
    user = require_login(request)
    if not user:
        return login_redirect()

    db: Session = SessionLocal()
    try:
        record = db.query(PoolMonitoring).filter(PoolMonitoring.id == record_id).first()

        if record:
            db.delete(record)
            db.commit()

        return RedirectResponse("/pool-monitoring", status_code=303)
    finally:
        db.close()
