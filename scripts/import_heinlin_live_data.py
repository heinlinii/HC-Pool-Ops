
import json
from pathlib import Path
from sqlalchemy import text
from app.database import engine, SessionLocal, Base
from app import models

DATA_FILE = Path(__file__).with_name("heinlin_live_data_export.json")

MODEL_BY_TABLE = {
    "poolops2_employees": models.Employee,
    "poolops2_clients": models.Client,
    "poolops2_properties": models.Property,
    "poolops2_jobs": models.Job,
    "poolops2_invoices": models.Invoice,
    "poolops2_job_costs": models.JobCost,
    "poolops2_photo_logs": models.PhotoLog,
    "field_logs": models.FieldLog,
}

# Optional models that may or may not exist in the current code.
for optional_name, table_name in [
    ("CalendarDayImage", "poolops2_calendar_day_images"),
    ("Equipment", "poolops2_equipment"),
    ("Estimate", "poolops2_estimates"),
    ("OfficeNote", "poolops2_office_notes"),
]:
    if hasattr(models, optional_name):
        MODEL_BY_TABLE[table_name] = getattr(models, optional_name)


def clean_row(model, row):
    allowed = {c.name for c in model.__table__.columns}
    return {k: v for k, v in row.items() if k in allowed}


def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    # Make sure tables exist in live Postgres.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Import in dependency order. Delete only app operational records, not login users.
        order = [
            "field_logs",
            "poolops2_photo_logs",
            "poolops2_job_costs",
            "poolops2_invoices",
            "poolops2_jobs",
            "poolops2_properties",
            "poolops2_clients",
            "poolops2_employees",
            "poolops2_calendar_day_images",
            "poolops2_equipment",
            "poolops2_estimates",
            "poolops2_office_notes",
        ]

        for table in order:
            model = MODEL_BY_TABLE.get(table)
            if model is None:
                print(f"SKIP {table}: model not present in this app.py/models.py")
                continue
            count = len(data.get(table, []))
            if count == 0:
                print(f"SKIP {table}: 0 rows")
                continue

            print(f"CLEAR {table}")
            db.execute(text(f'DELETE FROM {model.__tablename__}'))
            db.commit()

            print(f"IMPORT {table}: {count} rows")
            objects = []
            for row in data[table]:
                cleaned = clean_row(model, row)
                objects.append(model(**cleaned))
            db.add_all(objects)
            db.commit()

            # Reset Postgres sequence so new records continue after imported IDs.
            if hasattr(model, "id"):
                try:
                    db.execute(text(f"SELECT setval(pg_get_serial_sequence('{model.__tablename__}', 'id'), COALESCE((SELECT MAX(id) FROM {model.__tablename__}), 1), true)"))
                    db.commit()
                except Exception as e:
                    db.rollback()
                    print(f"Sequence reset skipped for {table}: {e}")

        print("DONE: Heinlin live data import complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
