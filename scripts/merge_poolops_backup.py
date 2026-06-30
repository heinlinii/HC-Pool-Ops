"""
Merge a PoolOps JSON backup into the active Heinlin Field Ops database.

Usage from project root:
    python scripts/merge_poolops_backup.py backup_2026_06_24_07_01_10.json

This uses app.app database helpers, so it works with:
- local SQLite when DATABASE_URL is not set
- Render/Postgres when DATABASE_URL is set in the environment
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.app import ensure_schema, exec_sql, rows, table_columns


SECTION_TO_TABLE = {
    "clients": "poolops2_clients",
    "properties": "poolops2_properties",
    "jobs": "poolops2_jobs",
    "employees": "poolops2_employees",
    "field_logs": "poolops2_field_logs",
}


def clean_value(value: Any) -> Any:
    """Keep JSON values database-friendly."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def count_table(table: str) -> str:
    try:
        return str(len(rows(f"SELECT * FROM {table}")))
    except Exception as exc:
        return f"ERROR: {exc}"


def upsert_record(table: str, record: dict[str, Any], available_cols: set[str]) -> str:
    """Insert or update one record by id when possible."""
    clean = {
        key: clean_value(value)
        for key, value in record.items()
        if key in available_cols
    }

    if not clean:
        return "skipped"

    record_id = clean.get("id")

    if "id" in clean and record_id is not None:
        existing = rows(f"SELECT id FROM {table} WHERE id=?", (record_id,))

        if existing:
            update_cols = [col for col in clean.keys() if col != "id"]
            if not update_cols:
                return "skipped"

            assignments = ", ".join([f"{col}=?" for col in update_cols])
            params = [clean[col] for col in update_cols] + [record_id]
            exec_sql(f"UPDATE {table} SET {assignments} WHERE id=?", params)
            return "updated"

        insert_cols = list(clean.keys())
        placeholders = ", ".join(["?"] * len(insert_cols))
        col_sql = ", ".join(insert_cols)
        params = [clean[col] for col in insert_cols]
        exec_sql(f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})", params)
        return "inserted"

    insert_cols = list(clean.keys())
    placeholders = ", ".join(["?"] * len(insert_cols))
    col_sql = ", ".join(insert_cols)
    params = [clean[col] for col in insert_cols]
    exec_sql(f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})", params)
    return "inserted"


def run_merge(backup_path: Path) -> None:
    if not backup_path.exists():
        raise SystemExit(f"Backup file not found: {backup_path}")

    backup = json.loads(backup_path.read_text(encoding="utf-8"))

    print("\nPOOL OPS BACKUP MERGE")
    print("=====================")
    print(f"Backup file: {backup_path}")
    print(f"Backup timestamp: {backup.get('timestamp', 'unknown')}")

    ensure_schema()

    print("\nBEFORE")
    print("------")
    for table in SECTION_TO_TABLE.values():
        print(f"{table}: {count_table(table)}")

    print("\nMERGING")
    print("-------")

    for section, table in SECTION_TO_TABLE.items():
        records = backup.get(section, [])
        if not isinstance(records, list):
            print(f"{section}: skipped, not a list")
            continue

        try:
            available_cols = set(table_columns(table))
        except Exception as exc:
            print(f"{section} -> {table}: skipped, table problem: {exc}")
            continue

        if not available_cols:
            print(f"{section} -> {table}: skipped, no columns found")
            continue

        totals = {"inserted": 0, "updated": 0, "skipped": 0}
        skipped_fields: set[str] = set()

        for record in records:
            if not isinstance(record, dict):
                totals["skipped"] += 1
                continue

            skipped_fields.update(set(record.keys()) - available_cols)
            result = upsert_record(table, record, available_cols)
            totals[result] = totals.get(result, 0) + 1

        print(
            f"{section} -> {table}: "
            f"{totals.get('inserted', 0)} inserted, "
            f"{totals.get('updated', 0)} updated, "
            f"{totals.get('skipped', 0)} skipped"
        )

        if skipped_fields:
            print(f"  skipped fields not in table: {', '.join(sorted(skipped_fields))}")

    print("\nAFTER")
    print("-----")
    for table in SECTION_TO_TABLE.values():
        print(f"{table}: {count_table(table)}")

    print("\nDone. Now restart the app and check Clients, Properties, Jobs, and Field Logs.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python scripts/merge_poolops_backup.py backup_2026_06_24_07_01_10.json"
        )

    run_merge(Path(sys.argv[1]))
