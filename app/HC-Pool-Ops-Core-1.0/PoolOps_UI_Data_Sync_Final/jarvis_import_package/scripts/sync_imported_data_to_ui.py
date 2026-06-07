import sqlite3
from pathlib import Path

DB = Path('poolops_local.db')


def val(row, key, default=''):
    v = row[key] if key in row.keys() else default
    return default if v is None else v


def main():
    if not DB.exists():
        raise SystemExit('poolops_local.db not found. Run this from the HC-Pool-Ops-FIXED-BY-JARVIS folder.')

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Keep the old UI tables, but fill them from the new imported foundation tables.
    cur.execute('DELETE FROM poolops2_clients')
    cur.execute('DELETE FROM poolops2_properties')
    cur.execute('DELETE FROM poolops2_jobs')

    for r in cur.execute('SELECT * FROM clients ORDER BY client_name'):
        cur.execute('''
            INSERT INTO poolops2_clients
            (id, name, contact_name, phone, mobile, email, billing_address, shipping_address,
             city, state, zip_code, company, notes, portal_username, portal_password, card_image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            val(r, 'id'), val(r, 'client_name'), val(r, 'contact_name'), val(r, 'phone'), '', val(r, 'email'),
            '', '', '', '', '', val(r, 'source'), val(r, 'notes'), val(r, 'portal_username'),
            val(r, 'portal_password'), val(r, 'card_image')
        ))

    for r in cur.execute('SELECT * FROM properties ORDER BY client_name, property_name, full_address'):
        cur.execute('''
            INSERT INTO poolops2_properties
            (id, client_id, client, property_name, address, city, state, zip_code,
             pool_type, pool_size, pool_depth, cover_type, finish_type, pump_model, filter_model,
             heater_model, sanitizer, automation_system, gate_code, service_plan, notes, card_image,
             latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            val(r, 'id'), val(r, 'client_id', None), val(r, 'client_name'), val(r, 'property_name'),
            val(r, 'full_address') or val(r, 'raw_address') or val(r, 'street'), val(r, 'city'), val(r, 'state'), val(r, 'zip_code'),
            '', '', '', '', '', '', '', '', '', '', '', '', val(r, 'source'), val(r, 'card_image'),
            val(r, 'latitude', None), val(r, 'longitude', None)
        ))

    for r in cur.execute('SELECT * FROM jobs ORDER BY id'):
        cur.execute('''
            INSERT INTO poolops2_jobs
            (id, client, property, address, check_in_time, check_in_lat, check_in_lng,
             check_out_time, check_out_lat, check_out_lng, job_type, status, crew, date,
             scheduled_start, scheduled_end, priority, notes, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            val(r, 'id'), val(r, 'client_name'), val(r, 'property_name'), val(r, 'address'),
            None, None, None, None, None, None, val(r, 'job_type'), val(r, 'status') or 'Pending',
            val(r, 'crew') or 'Unassigned', str(val(r, 'scheduled_date') or val(r, 'raw_date')),
            None, None, val(r, 'priority') or 'Normal', val(r, 'notes'), None, None
        ))

    con.commit()

    counts = {
        'poolops2_clients': cur.execute('SELECT COUNT(*) FROM poolops2_clients').fetchone()[0],
        'poolops2_properties': cur.execute('SELECT COUNT(*) FROM poolops2_properties').fetchone()[0],
        'poolops2_jobs': cur.execute('SELECT COUNT(*) FROM poolops2_jobs').fetchone()[0],
    }
    con.close()

    print('UI tables synced')
    for k, v in counts.items():
        print(f'{k}: {v}')


if __name__ == '__main__':
    main()
