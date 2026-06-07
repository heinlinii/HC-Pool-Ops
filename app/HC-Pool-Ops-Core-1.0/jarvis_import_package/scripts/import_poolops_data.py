#!/usr/bin/env python3
"""
Jarvis PoolOps organized data importer.

Use from repo root:
    python jarvis_import_package/scripts/import_poolops_data.py

Optional:
    python jarvis_import_package/scripts/import_poolops_data.py --database-url postgresql://...

This script imports app-ready sheets only.
It intentionally does NOT import Contacts Master.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text


BASE_DIR = Path(__file__).resolve().parents[1]
IMPORT_DIR = BASE_DIR / "imports"
SCHEMA_FILE = BASE_DIR / "scripts" / "schema_poolops_foundation.sql"


def clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() in {"none", "null", "nan"}:
        return None
    return s


def parse_bool(value: Any) -> bool:
    s = (clean(value) or "").lower()
    return s in {"1", "true", "yes", "y", "active"}


def parse_amount(value: Any) -> Optional[Decimal]:
    s = clean(value)
    if not s:
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(value: Any) -> tuple[Optional[date], Optional[str]]:
    raw = clean(value)
    if not raw:
        return None, None

    low = raw.lower()
    today = date.today()
    if low == "today":
        return today, raw
    if low == "tomorrow":
        return today + timedelta(days=1), raw

    # Handles 5/4/26, 05/04/2026, etc.
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date(), raw
        except ValueError:
            pass

    # Handles compact bad entry like 04102026
    if re.fullmatch(r"\d{8}", raw):
        try:
            return datetime.strptime(raw, "%m%d%Y").date(), raw
        except ValueError:
            pass

    return None, raw


def read_csv(name: str) -> list[dict[str, str]]:
    path = IMPORT_DIR / name
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def execute_schema(conn) -> None:
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    raw = conn.connection
    raw.executescript(schema)


def upsert_client(conn, row):
    conn.execute(
        text("""
        INSERT INTO clients (
            external_id, client_name, contact_name, phone, email, source, notes,
            portal_username, portal_password, card_image
        )
        VALUES (
            :external_id, :client_name, :contact_name, :phone, :email, :source, :notes,
            :portal_username, :portal_password, :card_image
        )
        
        """),
        {
            "external_id": clean(row.get("client_id")),
            "client_name": clean(row.get("client_name")) or "Unnamed Client",
            "contact_name": clean(row.get("contact_name")),
            "phone": clean(row.get("phone")),
            "email": clean(row.get("email")),
            "source": clean(row.get("source")),
            "notes": clean(row.get("notes")),
            "portal_username": clean(row.get("portal_username")),
            "portal_password": clean(row.get("portal_password")),
            "card_image": clean(row.get("card_image")),
        },
    )


def upsert_property(conn, row):
    client_external_id = clean(row.get("client_id"))
    client_id = conn.execute(
        text("SELECT id FROM clients WHERE external_id = :external_id"),
        {"external_id": client_external_id},
    ).scalar()

    conn.execute(
        text("""
        INSERT INTO properties (
            external_id, client_id, client_external_id, client_name, property_name,
            street, city, state, zip_code, full_address, google_maps_url, raw_address,
            card_image, needs_review, source
        )
        VALUES (
            :external_id, :client_id, :client_external_id, :client_name, :property_name,
            :street, :city, :state, :zip_code, :full_address, :google_maps_url, :raw_address,
            :card_image, :needs_review, :source
        )
        """),
        {
            "external_id": clean(row.get("property_id")),
            "client_id": client_id,
            "client_external_id": client_external_id,
            "client_name": clean(row.get("client_name")),
            "property_name": clean(row.get("property_name")) or clean(row.get("client_name")) or "Unnamed Property",
            "street": clean(row.get("street")),
            "city": clean(row.get("city")),
            "state": clean(row.get("state")),
            "zip_code": clean(row.get("zip_code")),
            "full_address": clean(row.get("full_address")),
            "google_maps_url": clean(row.get("google_maps_url")),
            "raw_address": clean(row.get("raw_address")),
            "card_image": clean(row.get("card_image")),
            "needs_review": parse_bool(row.get("needs_review")),
            "source": clean(row.get("source")),
        },
    )


def upsert_employee(conn, row):
    conn.execute(
        text("""
        INSERT INTO employees (external_id, name, phone, role, username, password, card_image, active)
        VALUES (:external_id, :name, :phone, :role, :username, :password, :card_image, :active)
        """),
        {
            "external_id": clean(row.get("employee_id")),
            "name": clean(row.get("name")) or "Unnamed Employee",
            "phone": clean(row.get("phone")),
            "role": clean(row.get("role")),
            "username": clean(row.get("username")),
            "password": clean(row.get("password")),
            "card_image": clean(row.get("card_image")),
            "active": parse_bool(row.get("active")),
        },
    )


def find_property_id(conn, client_external_id, property_name, address):
    if client_external_id:
        pid = conn.execute(
            text("SELECT id FROM properties WHERE client_external_id = :cid ORDER BY id LIMIT 1"),
            {"cid": client_external_id},
        ).scalar()
        if pid:
            return pid

    if property_name:
        pid = conn.execute(
            text("""
            SELECT id FROM properties
            WHERE lower(property_name) = lower(:property_name)
               OR lower(client_name) = lower(:property_name)
            ORDER BY id LIMIT 1
            """),
            {"property_name": property_name},
        ).scalar()
        if pid:
            return pid

    if address:
        pid = conn.execute(
            text("""
            SELECT id FROM properties
            WHERE lower(full_address) LIKE lower(:needle)
               OR lower(raw_address) LIKE lower(:needle)
            ORDER BY id LIMIT 1
            """),
            {"needle": f"%{address}%"},
        ).scalar()
        if pid:
            return pid

    return None


def upsert_job(conn, row):
    scheduled_date, raw_date = parse_date(row.get("date"))
    client_external_id = clean(row.get("client_id"))
    client_id = conn.execute(
        text("SELECT id FROM clients WHERE external_id = :external_id"),
        {"external_id": client_external_id},
    ).scalar() if client_external_id else None

    property_id = find_property_id(
        conn,
        client_external_id,
        clean(row.get("property_name")),
        clean(row.get("address")),
    )

    conn.execute(
        text("""
        INSERT INTO jobs (
            external_id, client_id, property_id, client_external_id, client_name,
            property_name, address, job_type, status, crew, scheduled_date,
            raw_date, priority, notes, card_image
        )
        VALUES (
            :external_id, :client_id, :property_id, :client_external_id, :client_name,
            :property_name, :address, :job_type, :status, :crew, :scheduled_date,
            :raw_date, :priority, :notes, :card_image
        )
        """),
        {
            "external_id": clean(row.get("job_id")),
            "client_id": client_id,
            "property_id": property_id,
            "client_external_id": client_external_id,
            "client_name": clean(row.get("client_name")),
            "property_name": clean(row.get("property_name")),
            "address": clean(row.get("address")),
            "job_type": clean(row.get("job_type")),
            "status": clean(row.get("status")) or "Requested",
            "crew": clean(row.get("crew")),
            "scheduled_date": scheduled_date,
            "raw_date": raw_date,
            "priority": clean(row.get("priority")) or "Normal",
            "notes": clean(row.get("notes")),
            "card_image": clean(row.get("card_image")),
        },
    )


def upsert_invoice(conn, row):
    invoice_date, raw_date = parse_date(row.get("date"))
    client_name = clean(row.get("client_name"))
    client_id = conn.execute(
        text("SELECT id FROM clients WHERE lower(client_name) = lower(:client_name) ORDER BY id LIMIT 1"),
        {"client_name": client_name or ""},
    ).scalar()

    conn.execute(
        text("""
        INSERT INTO invoices (external_id, client_id, client_name, description, amount, status, invoice_date, raw_date)
        VALUES (:external_id, :client_id, :client_name, :description, :amount, :status, :invoice_date, :raw_date)
        """),
        {
            "external_id": clean(row.get("invoice_id")),
            "client_id": client_id,
            "client_name": client_name,
            "description": clean(row.get("description")),
            "amount": float(clean(row.get("amount")) or 0), 
            "status": clean(row.get("status")) or "Draft",
            "invoice_date": invoice_date,
            "raw_date": raw_date,
        },
    )


def upsert_photo_log(conn, row):
    photo_date, raw_date = parse_date(row.get("date"))
    job_external_id = clean(row.get("job_id"))
    job_id = conn.execute(
        text("SELECT id FROM jobs WHERE external_id = :external_id"),
        {"external_id": job_external_id},
    ).scalar() if job_external_id else None

    property_external_id = clean(row.get("property_id"))
    property_id = conn.execute(
        text("SELECT id FROM properties WHERE external_id = :external_id"),
        {"external_id": property_external_id},
    ).scalar() if property_external_id else None

    if not property_id and job_id:
        property_id = conn.execute(
            text("SELECT property_id FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        ).scalar()

    conn.execute(
        text("""
        INSERT INTO photo_logs (
            external_id, job_id, property_id, client_name, photo_type, title,
            photo_url, photo_date, raw_date, notes, latitude, longitude
        )
        VALUES (
            :external_id, :job_id, :property_id, :client_name, :photo_type, :title,
            :photo_url, :photo_date, :raw_date, :notes, :latitude, :longitude
        )
        """),
        {
            "external_id": clean(row.get("photo_id")),
            "job_id": job_id,
            "property_id": property_id,
            "client_name": clean(row.get("client_name")),
            "photo_type": clean(row.get("photo_type")),
            "title": clean(row.get("title")),
            "photo_url": clean(row.get("photo_url")),
            "photo_date": photo_date,
            "raw_date": raw_date,
            "notes": clean(row.get("notes")),
            "latitude": clean(row.get("latitude")),
            "longitude": clean(row.get("longitude")),
        },
    )


def upsert_card_image(conn, row):
    conn.execute(
        text("""
        INSERT INTO property_card_images (filename, app_path, recommended_use, assigned_client, assigned_property)
        VALUES (:filename, :app_path, :recommended_use, :assigned_client, :assigned_property)
        ON CONFLICT (filename) DO UPDATE SET
            app_path = EXCLUDED.app_path,
            recommended_use = EXCLUDED.recommended_use,
            assigned_client = EXCLUDED.assigned_client,
            assigned_property = EXCLUDED.assigned_property
        """),
        {
            "filename": clean(row.get("filename")),
            "app_path": clean(row.get("app_path")),
            "recommended_use": clean(row.get("recommended_use")),
            "assigned_client": clean(row.get("assigned_client")),
            "assigned_property": clean(row.get("assigned_property")),
        },
    )


def print_counts(conn) -> None:
    for table in [
        "clients", "properties", "employees", "jobs",
        "invoices", "photo_logs", "property_card_images"
    ]:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        print(f"{table}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--skip-schema", action="store_true")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit(
            "DATABASE_URL is missing. Add it to .env or pass --database-url."
        )

    engine = create_engine(args.database_url, future=True)

    with engine.begin() as conn:
        if not args.skip_schema:
            execute_schema(conn)

        for row in read_csv("clients_import.csv"):
            upsert_client(conn, row)

        for row in read_csv("properties_import.csv"):
            upsert_property(conn, row)

        for row in read_csv("employees_import.csv"):
            upsert_employee(conn, row)

        for row in read_csv("jobs_import.csv"):
            upsert_job(conn, row)

        for row in read_csv("invoices_import.csv"):
            upsert_invoice(conn, row)

        for row in read_csv("photo_logs_import.csv"):
            upsert_photo_log(conn, row)

        for row in read_csv("card_images.csv"):
            upsert_card_image(conn, row)

        print("\nImport complete.")
        print_counts(conn)

        review_count = len(read_csv("review_needed.csv"))
        print(f"\nManual review list kept separate: {review_count} rows")
        print("Contacts Master was intentionally excluded.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

