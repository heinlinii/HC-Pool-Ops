from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime
import html

from app.routes.auth import (
    require_login,
    login_redirect,
    is_admin,
    is_employee,
)

router = APIRouter()


def _app_helpers():
    # Imported lazily to avoid circular imports while app.app is loading.
    from app.app import rows, exec_sql
    return rows, exec_sql


def current_user_identity(request: Request):
    user = require_login(request)

    if not user:
        return {
            "id": "",
            "name": "Unknown",
            "role": "",
            "email": "",
        }

    user_id = (
        user.get("id")
        or user.get("user_id")
        or user.get("employee_id")
        or user.get("email")
        or user.get("username")
        or "unknown"
    )

    user_name = (
        user.get("name")
        or user.get("full_name")
        or user.get("username")
        or user.get("email")
        or "Unknown User"
    )

    user_role = str(user.get("role", "")).lower()
    user_email = user.get("email", "")

    return {
        "id": f"{user_role}:{user_id}",
        "name": str(user_name),
        "role": str(user_role),
        "email": str(user_email),
    }


def ensure_time_clock_schema():
    rows, exec_sql = _app_helpers()

    try:
        exec_sql(
            """
            CREATE TABLE IF NOT EXISTS hfo_time_clock_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_name TEXT,
                user_role TEXT,
                user_email TEXT,
                clock_in_at TEXT,
                clock_out_at TEXT,
                clock_in_lat TEXT,
                clock_in_lng TEXT,
                clock_out_lat TEXT,
                clock_out_lng TEXT,
                status TEXT DEFAULT 'clocked_in',
                notes TEXT DEFAULT ''
            )
            """
        )
    except Exception:
        exec_sql(
            """
            CREATE TABLE IF NOT EXISTS hfo_time_clock_sessions (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                user_name TEXT,
                user_role TEXT,
                user_email TEXT,
                clock_in_at TEXT,
                clock_out_at TEXT,
                clock_in_lat TEXT,
                clock_in_lng TEXT,
                clock_out_lat TEXT,
                clock_out_lng TEXT,
                status TEXT DEFAULT 'clocked_in',
                notes TEXT DEFAULT ''
            )
            """
        )

    try:
        exec_sql(
            """
            CREATE TABLE IF NOT EXISTS hfo_location_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                user_id TEXT,
                user_name TEXT,
                user_role TEXT,
                lat TEXT,
                lng TEXT,
                accuracy TEXT,
                captured_at TEXT
            )
            """
        )
    except Exception:
        exec_sql(
            """
            CREATE TABLE IF NOT EXISTS hfo_location_points (
                id SERIAL PRIMARY KEY,
                session_id INTEGER,
                user_id TEXT,
                user_name TEXT,
                user_role TEXT,
                lat TEXT,
                lng TEXT,
                accuracy TEXT,
                captured_at TEXT
            )
            """
        )


def open_clock_session_for_user(user_id):
    rows, exec_sql = _app_helpers()
    ensure_time_clock_schema()

    result = rows(
        """
        SELECT *
        FROM hfo_time_clock_sessions
        WHERE user_id = ?
          AND status = 'clocked_in'
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(user_id),),
    )

    return result[0] if result else None


@router.get("/time-clock", response_class=HTMLResponse)
def time_clock_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    rows, exec_sql = _app_helpers()
    ensure_time_clock_schema()

    identity = current_user_identity(request)
    open_session = open_clock_session_for_user(identity["id"])

    recent_sessions = rows(
        """
        SELECT *
        FROM hfo_time_clock_sessions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (identity["id"],),
    )

    recent_points = []
    if open_session:
        recent_points = rows(
            """
            SELECT *
            FROM hfo_location_points
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (open_session["id"],),
        )

    def esc(value):
        return html.escape(str(value or ""))

    status_text = "Clocked In" if open_session else "Clocked Out"
    status_class = "in" if open_session else "out"

    sessions_html = "".join(
        f"""
        <tr>
          <td>{esc(s.get('clock_in_at'))}</td>
          <td>{esc(s.get('clock_out_at'))}</td>
          <td>{esc(s.get('status'))}</td>
          <td>{esc(s.get('notes'))}</td>
        </tr>
        """
        for s in recent_sessions
    ) or '<tr><td colspan="4">No time clock sessions yet.</td></tr>'

    points_html = "".join(
        f"""
        <tr>
          <td>{esc(p.get('captured_at'))}</td>
          <td>{esc(p.get('lat'))}</td>
          <td>{esc(p.get('lng'))}</td>
          <td>{esc(p.get('accuracy'))}</td>
        </tr>
        """
        for p in recent_points
    ) or '<tr><td colspan="4">No GPS points for the current session yet.</td></tr>'

    html_body = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Heinlin Time Clock</title>
      <style>
        body {{ margin:0; font-family:Arial, sans-serif; background:#05090d; color:#f7eedf; }}
        .wrap {{ max-width:1100px; margin:0 auto; padding:32px 18px 70px; }}
        .top {{ display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }}
        h1 {{ margin:0; color:#d6b36a; font-size:clamp(38px, 7vw, 78px); text-transform:uppercase; letter-spacing:.04em; }}
        .btn, button {{ display:inline-block; border:1px solid rgba(214,179,106,.55); border-radius:12px; padding:12px 18px; background:rgba(0,0,0,.45); color:#d6b36a; text-decoration:none; font-weight:800; cursor:pointer; }}
        button.primary {{ background:#d6b36a; color:#05090d; }}
        .card {{ border:1px solid rgba(214,179,106,.38); border-radius:18px; padding:18px; background:rgba(255,255,255,.045); margin:18px 0; box-shadow:0 18px 38px rgba(0,0,0,.35); }}
        .status {{ font-size:28px; font-weight:900; }}
        .status.in {{ color:#72ff9d; }}
        .status.out {{ color:#ffcf72; }}
        input, textarea {{ width:100%; box-sizing:border-box; border:1px solid rgba(214,179,106,.35); border-radius:12px; background:#0b1117; color:#fff; padding:12px; margin:8px 0 12px; }}
        table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
        th, td {{ border-bottom:1px solid rgba(255,255,255,.1); padding:10px; text-align:left; vertical-align:top; }}
        th {{ color:#d6b36a; }}
        .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }}
        .muted {{ color:#bfb6a8; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="top">
          <div>
            <h1>Time Clock</h1>
            <div class="muted">{esc(identity.get('name'))} • {esc(identity.get('role'))}</div>
          </div>
          <div>
            <a class="btn" href="/jarvis">Dashboard</a>
            <a class="btn" href="/employee">Crew Portal</a>
            <a class="btn" href="/map">Map</a>
          </div>
        </div>

        <div class="card">
          <div class="status {status_class}">{status_text}</div>
          <div class="muted">This page uses your browser GPS when available.</div>
        </div>

        <div class="grid">
          <form class="card" method="post" action="/time-clock/in" id="clockInForm">
            <h2>Clock In</h2>
            <textarea name="notes" placeholder="Notes, job, property, or reason"></textarea>
            <input type="hidden" name="lat"><input type="hidden" name="lng"><input type="hidden" name="accuracy">
            <button class="primary" type="submit">Clock In</button>
          </form>

          <form class="card" method="post" action="/time-clock/out" id="clockOutForm">
            <h2>Clock Out</h2>
            <input type="hidden" name="lat"><input type="hidden" name="lng"><input type="hidden" name="accuracy">
            <button type="submit">Clock Out</button>
          </form>
        </div>

        <div class="card">
          <h2>Recent Time Clock Sessions</h2>
          <table><thead><tr><th>Clock In</th><th>Clock Out</th><th>Status</th><th>Notes</th></tr></thead><tbody>{sessions_html}</tbody></table>
        </div>

        <div class="card">
          <h2>Current Session GPS Points</h2>
          <table><thead><tr><th>Captured</th><th>Lat</th><th>Lng</th><th>Accuracy</th></tr></thead><tbody>{points_html}</tbody></table>
        </div>
      </div>
      <script>
        function fillGeo(form) {{
          if (!navigator.geolocation) return;
          navigator.geolocation.getCurrentPosition(function(pos) {{
            form.querySelector('[name="lat"]').value = pos.coords.latitude || '';
            form.querySelector('[name="lng"]').value = pos.coords.longitude || '';
            form.querySelector('[name="accuracy"]').value = pos.coords.accuracy || '';
          }});
        }}
        document.querySelectorAll('form').forEach(fillGeo);
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html_body)


@router.post("/time-clock/in")
async def time_clock_in(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    rows, exec_sql = _app_helpers()
    ensure_time_clock_schema()

    form = await request.form()
    identity = current_user_identity(request)

    existing = open_clock_session_for_user(identity["id"])
    if existing:
        return RedirectResponse("/time-clock", status_code=303)

    now = datetime.now().isoformat(timespec="seconds")

    exec_sql(
        """
        INSERT INTO hfo_time_clock_sessions
        (user_id, user_name, user_role, user_email, clock_in_at, clock_in_lat, clock_in_lng, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'clocked_in', ?)
        """,
        (
            identity["id"],
            identity["name"],
            identity["role"],
            identity["email"],
            now,
            str(form.get("lat", "")),
            str(form.get("lng", "")),
            str(form.get("notes", "")),
        ),
    )

    open_session = open_clock_session_for_user(identity["id"])

    if open_session:
        exec_sql(
            """
            INSERT INTO hfo_location_points
            (session_id, user_id, user_name, user_role, lat, lng, accuracy, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                open_session["id"],
                identity["id"],
                identity["name"],
                identity["role"],
                str(form.get("lat", "")),
                str(form.get("lng", "")),
                str(form.get("accuracy", "")),
                now,
            ),
        )

    return RedirectResponse("/time-clock", status_code=303)


@router.post("/time-clock/out")
async def time_clock_out(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    rows, exec_sql = _app_helpers()
    ensure_time_clock_schema()

    form = await request.form()
    identity = current_user_identity(request)
    open_session = open_clock_session_for_user(identity["id"])

    if not open_session:
        return RedirectResponse("/time-clock", status_code=303)

    now = datetime.now().isoformat(timespec="seconds")

    exec_sql(
        """
        UPDATE hfo_time_clock_sessions
        SET clock_out_at = ?, clock_out_lat = ?, clock_out_lng = ?, status = 'clocked_out'
        WHERE id = ?
        """,
        (
            now,
            str(form.get("lat", "")),
            str(form.get("lng", "")),
            open_session["id"],
        ),
    )

    exec_sql(
        """
        INSERT INTO hfo_location_points
        (session_id, user_id, user_name, user_role, lat, lng, accuracy, captured_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            open_session["id"],
            identity["id"],
            identity["name"],
            identity["role"],
            str(form.get("lat", "")),
            str(form.get("lng", "")),
            str(form.get("accuracy", "")),
            now,
        ),
    )

    return RedirectResponse("/time-clock", status_code=303)


@router.post("/time-clock/location")
async def time_clock_location(request: Request):
    u = require_login(request)
    if not u:
        return {"ok": False, "error": "not_logged_in"}

    rows, exec_sql = _app_helpers()
    ensure_time_clock_schema()

    form = await request.form()
    identity = current_user_identity(request)
    open_session = open_clock_session_for_user(identity["id"])

    if not open_session:
        return {"ok": False, "error": "not_clocked_in"}

    now = datetime.now().isoformat(timespec="seconds")

    exec_sql(
        """
        INSERT INTO hfo_location_points
        (session_id, user_id, user_name, user_role, lat, lng, accuracy, captured_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            open_session["id"],
            identity["id"],
            identity["name"],
            identity["role"],
            str(form.get("lat", "")),
            str(form.get("lng", "")),
            str(form.get("accuracy", "")),
            now,
        ),
    )

    return {"ok": True, "captured_at": now}


@router.post("/gps/ping")
def gps_ping(
    request: Request,
    lat: str = Form(""),
    lng: str = Form(""),
    accuracy: str = Form(""),
    speed: str = Form(""),
    heading: str = Form(""),
    source: str = Form("employee_portal"),
    note: str = Form(""),
):
    u = require_login(request)
    if not u:
        return {"ok": False, "error": "not_logged_in"}

    if not (is_employee(u) or is_admin(u)):
        return {"ok": False, "error": "not_allowed"}

    rows, exec_sql = _app_helpers()

    try:
        latitude = float(lat)
        longitude = float(lng)
    except Exception:
        return {"ok": False, "error": "bad_location"}

    def clean_float(value):
        try:
            return float(value) if value not in ("", None) else None
        except Exception:
            return None

    now = datetime.now().isoformat(timespec="seconds")

    exec_sql(
        """
        INSERT INTO employee_location_points
        (employee_id, employee_name, latitude, longitude, accuracy, speed, heading, source, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            u.get("id"),
            u.get("name") or u.get("username") or "",
            latitude,
            longitude,
            clean_float(accuracy),
            clean_float(speed),
            clean_float(heading),
            source,
            note,
            now,
        )
    )

    if is_employee(u):
        try:
            exec_sql(
                "UPDATE poolops2_employees SET clock_lat=?, clock_lng=?, last_seen_at=? WHERE id=?",
                (latitude, longitude, now, u.get("id"))
            )
        except Exception:
            pass

    return {"ok": True}


@router.get("/gps/day", response_class=HTMLResponse)
def gps_day(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/time-clock", status_code=303)


@router.get("/gps/stops", response_class=HTMLResponse)
def gps_stops(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/time-clock", status_code=303)
