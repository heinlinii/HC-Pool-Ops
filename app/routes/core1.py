from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.database import SessionLocal
from app.core1.security import is_admin, is_client, is_employee
from app.core1.storage_r2 import build_photo_key, get_r2_settings, upload_fileobj

router = APIRouter()


def db_session():
    return SessionLocal()


def templates_response(request: Request, template: str, context: dict):
    # app.app owns the Jinja2Templates instance in current PoolOps builds.
    from app.app import templates
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template, context)


def require_user(request: Request):
    from app.app import require_login
    return require_login(request)


def require_admin_user(request: Request):
    from app.app import require_admin
    return require_admin(request)


@router.get("/core", response_class=HTMLResponse)
async def core_home(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    return templates_response(request, "core1/core_home.html", {"user": user})


@router.get("/calendar/year", response_class=HTMLResponse)
async def yearly_calendar(request: Request, year: Optional[int] = None):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    year = year or date.today().year
    db = db_session()
    try:
        jobs = db.execute(text("""
            SELECT id, client, address, job_type, status, date
            FROM poolops2_jobs
            WHERE date IS NOT NULL
            ORDER BY date ASC, id ASC
        """)).mappings().all()
    finally:
        db.close()
    months = []
    for month in range(1, 13):
        first = date(year, month, 1)
        months.append({"month": month, "name": first.strftime("%B"), "first_weekday": first.weekday()})
    return templates_response(request, "core1/yearly_calendar.html", {"user": user, "year": year, "months": months, "jobs": jobs})


@router.get("/portal/client", response_class=HTMLResponse)
async def client_portal(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if not (is_admin(user) or is_client(user)):
        return RedirectResponse(url="/dashboard", status_code=303)
    client_id = getattr(user, "client_id", None) or getattr(user, "linked_client_id", None)
    db = db_session()
    try:
        params = {"client_id": client_id}
        where = "WHERE c.id = :client_id" if client_id and not is_admin(user) else ""
        client_rows = db.execute(text(f"""
            SELECT c.* FROM poolops2_clients c {where} ORDER BY c.name ASC LIMIT 50
        """), params).mappings().all()
        schedule_rows = db.execute(text("""
            SELECT id, client, address, job_type, status, date
            FROM poolops2_jobs
            WHERE date IS NOT NULL
            ORDER BY date ASC LIMIT 100
        """)).mappings().all()
    finally:
        db.close()
    return templates_response(request, "core1/client_portal.html", {"user": user, "clients": client_rows, "schedule": schedule_rows})


@router.post("/portal/client/request-service")
async def request_service(request: Request, preferred_date: str = Form(""), notes: str = Form("")):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS poolops2_service_requests (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                requester VARCHAR DEFAULT '',
                preferred_date VARCHAR DEFAULT '',
                notes TEXT DEFAULT '',
                status VARCHAR DEFAULT 'new'
            )
        """))
        db.execute(text("""
            INSERT INTO poolops2_service_requests (requester, preferred_date, notes)
            VALUES (:requester, :preferred_date, :notes)
        """), {"requester": getattr(user, "username", "unknown"), "preferred_date": preferred_date, "notes": notes})
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/portal/client", status_code=303)


@router.get("/portal/employee", response_class=HTMLResponse)
async def employee_portal(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    if not (is_admin(user) or is_employee(user)):
        return RedirectResponse(url="/dashboard", status_code=303)
    db = db_session()
    try:
        jobs = db.execute(text("""
            SELECT id, client, address, job_type, status, date, check_in_time, check_out_time
            FROM poolops2_jobs
            ORDER BY COALESCE(date, CURRENT_DATE) ASC, id DESC LIMIT 100
        """)).mappings().all()
    finally:
        db.close()
    return templates_response(request, "core1/employee_portal.html", {"user": user, "jobs": jobs})


@router.post("/portal/employee/clock")
async def employee_clock(request: Request, action: str = Form(...), lat: str = Form(""), lng: str = Form("")):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS poolops2_time_clock (
                id SERIAL PRIMARY KEY,
                username VARCHAR DEFAULT '',
                action VARCHAR DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                latitude VARCHAR DEFAULT '',
                longitude VARCHAR DEFAULT ''
            )
        """))
        db.execute(text("""
            INSERT INTO poolops2_time_clock (username, action, latitude, longitude)
            VALUES (:username, :action, :lat, :lng)
        """), {"username": getattr(user, "username", "unknown"), "action": action, "lat": lat, "lng": lng})
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/portal/employee", status_code=303)


@router.get("/weather-live", response_class=HTMLResponse)
async def weather_live(request: Request, lat: float = 37.9716, lng: float = -87.5711):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    weather = None
    error = None
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lng, "current": "temperature_2m,precipitation,wind_speed_10m", "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": "America/Chicago"},
            timeout=12,
        )
        weather = r.json()
    except Exception as exc:
        error = str(exc)
    return templates_response(request, "core1/weather_live.html", {"user": user, "weather": weather, "error": error})


@router.get("/photos/permanent", response_class=HTMLResponse)
async def permanent_photos(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    db = db_session()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS poolops2_r2_photos (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by VARCHAR DEFAULT '',
                client_id INTEGER,
                property_id INTEGER,
                original_filename VARCHAR DEFAULT '',
                content_type VARCHAR DEFAULT '',
                r2_bucket VARCHAR DEFAULT '',
                r2_key TEXT DEFAULT '',
                public_url TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            )
        """))
        photos = db.execute(text("SELECT * FROM poolops2_r2_photos ORDER BY id DESC LIMIT 200")).mappings().all()
        db.commit()
    finally:
        db.close()
    return templates_response(request, "core1/permanent_photos.html", {"user": user, "photos": photos, "r2_ready": get_r2_settings() is not None})


@router.post("/photos/permanent/upload")
async def upload_permanent_photo(request: Request, photo: UploadFile = File(...), client_id: str = Form(""), property_id: str = Form(""), notes: str = Form("")):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    cid = int(client_id) if client_id.isdigit() else None
    pid = int(property_id) if property_id.isdigit() else None
    key = build_photo_key(photo.filename or "field-photo.jpg", cid, pid)
    result = upload_fileobj(photo.file, key=key, content_type=photo.content_type or "application/octet-stream")
    db = db_session()
    try:
        db.execute(text("""
            INSERT INTO poolops2_r2_photos (uploaded_by, client_id, property_id, original_filename, content_type, r2_bucket, r2_key, public_url, notes)
            VALUES (:uploaded_by, :client_id, :property_id, :original_filename, :content_type, :r2_bucket, :r2_key, :public_url, :notes)
        """), {"uploaded_by": getattr(user, "username", "unknown"), "client_id": cid, "property_id": pid, "original_filename": photo.filename or "", "content_type": photo.content_type or "", "r2_bucket": result["bucket"], "r2_key": result["key"], "public_url": result["public_url"] or "", "notes": notes})
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/photos/permanent", status_code=303)
