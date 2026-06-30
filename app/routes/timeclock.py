from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime, date
import html
import json
import math

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
        "raw_id": user_id,
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


def _float_or_none(value):
    try:
        if value in ("", None):
            return None
        return float(value)
    except Exception:
        return None


def _save_employee_gps_point(user, lat, lng, accuracy="", speed="", heading="", source="time_clock", note=""):
    rows, exec_sql = _app_helpers()

    latitude = _float_or_none(lat)
    longitude = _float_or_none(lng)

    if latitude is None or longitude is None:
        return

    now = datetime.now().isoformat(timespec="seconds")

    exec_sql(
        """
        INSERT INTO employee_location_points
        (employee_id, employee_name, latitude, longitude, accuracy, speed, heading, source, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            user.get("id"),
            user.get("name") or user.get("username") or "",
            latitude,
            longitude,
            _float_or_none(accuracy),
            _float_or_none(speed),
            _float_or_none(heading),
            source,
            note,
            now,
        )
    )

    try:
        exec_sql(
            "UPDATE poolops2_employees SET clock_lat=?, clock_lng=?, last_seen_at=? WHERE id=?",
            (latitude, longitude, now, user.get("id"))
        )
    except Exception:
        pass


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
            <a class="btn" href="/gps-replay">GPS Replay</a>
          </div>
        </div>

        <div class="card">
          <div class="status {status_class}">{status_text}</div>
          <div class="muted">This page uses your browser GPS when available. Keep it open while clocked in.</div>
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

        function sendTrackingPoint() {{
          if (!navigator.geolocation) return;
          navigator.geolocation.getCurrentPosition(function(pos) {{
            const formData = new FormData();
            formData.append("lat", pos.coords.latitude || "");
            formData.append("lng", pos.coords.longitude || "");
            formData.append("accuracy", pos.coords.accuracy || "");
            formData.append("speed", pos.coords.speed || "");
            formData.append("heading", pos.coords.heading || "");
            formData.append("source", "time_clock");
            formData.append("note", "auto_tracking");

            fetch("/time-clock/location", {{ method: "POST", body: formData }}).catch(function(){{}});
            fetch("/gps/ping", {{ method: "POST", body: formData }}).catch(function(){{}});
          }});
        }}

        document.querySelectorAll('form').forEach(fillGeo);

        const isClockedIn = {str(bool(open_session)).lower()};
        if (isClockedIn) {{
          sendTrackingPoint();
          setInterval(sendTrackingPoint, 60000);
        }}
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

    _save_employee_gps_point(u, form.get("lat", ""), form.get("lng", ""), form.get("accuracy", ""), source="time_clock", note="Clock in")

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

    _save_employee_gps_point(u, form.get("lat", ""), form.get("lng", ""), form.get("accuracy", ""), source="time_clock", note="Clock out")

    if is_employee(u):
        try:
            exec_sql(
                "UPDATE poolops2_employees SET clocked_in=?, clock_lat=?, clock_lng=?, last_seen_at=?, clocked_in_at=? WHERE id=?",
                (False, _float_or_none(form.get("lat", "")), _float_or_none(form.get("lng", "")), now, "", u.get("id"))
            )
        except Exception:
            pass

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

    _save_employee_gps_point(
        u,
        form.get("lat", ""),
        form.get("lng", ""),
        form.get("accuracy", ""),
        form.get("speed", ""),
        form.get("heading", ""),
        source="time_clock",
        note="auto_tracking",
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


def _parse_dt(value):
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _haversine_miles(lat1, lng1, lat2, lng2):
    r = 3958.7613
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _format_minutes(minutes):
    try:
        minutes = int(round(minutes))
    except Exception:
        minutes = 0
    h = minutes // 60
    m = minutes % 60
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _detect_stops(points, radius_miles=0.05, min_minutes=5):
    stops = []
    if not points:
        return stops

    cluster = []
    center_lat = None
    center_lng = None

    def flush_cluster():
        if len(cluster) < 2:
            return
        start = _parse_dt(cluster[0].get("created_at"))
        end = _parse_dt(cluster[-1].get("created_at"))
        if not start or not end:
            return
        mins = (end - start).total_seconds() / 60
        if mins >= min_minutes:
            avg_lat = sum(float(p.get("latitude")) for p in cluster) / len(cluster)
            avg_lng = sum(float(p.get("longitude")) for p in cluster) / len(cluster)
            stops.append({
                "lat": avg_lat,
                "lng": avg_lng,
                "arrival": cluster[0].get("created_at", ""),
                "departure": cluster[-1].get("created_at", ""),
                "minutes": int(round(mins)),
                "duration": _format_minutes(mins),
                "points": len(cluster),
            })

    for p in points:
        lat = _float_or_none(p.get("latitude"))
        lng = _float_or_none(p.get("longitude"))
        if lat is None or lng is None:
            continue

        if not cluster:
            cluster = [p]
            center_lat = lat
            center_lng = lng
            continue

        dist = _haversine_miles(center_lat, center_lng, lat, lng)

        if dist <= radius_miles:
            cluster.append(p)
            center_lat = sum(float(x.get("latitude")) for x in cluster) / len(cluster)
            center_lng = sum(float(x.get("longitude")) for x in cluster) / len(cluster)
        else:
            flush_cluster()
            cluster = [p]
            center_lat = lat
            center_lng = lng

    flush_cluster()
    return stops


def _gps_replay_html(request: Request, title="GPS Route Replay"):
    u = require_login(request)
    if not u:
        return login_redirect()

    rows, exec_sql = _app_helpers()

    selected_day = request.query_params.get("date") or date.today().isoformat()
    selected_employee = request.query_params.get("employee_id") or ""

    employees = []
    if is_admin(u):
        employees = rows("SELECT id, name, username FROM poolops2_employees WHERE coalesce(name,'') <> '' ORDER BY name")
    else:
        selected_employee = str(u.get("id") or "")

    params = [f"{selected_day}%"]
    where = "created_at LIKE ?"

    if is_admin(u) and selected_employee:
        where += " AND CAST(employee_id AS TEXT)=?"
        params.append(str(selected_employee))
    elif not is_admin(u):
        where += " AND CAST(employee_id AS TEXT)=?"
        params.append(str(u.get("id")))

    points = rows(
        f"""
        SELECT *
        FROM employee_location_points
        WHERE {where}
        ORDER BY created_at ASC, id ASC
        """,
        tuple(params)
    )

    clean_points = []
    total_miles = 0.0
    previous = None

    for p in points:
        lat = _float_or_none(p.get("latitude"))
        lng = _float_or_none(p.get("longitude"))
        if lat is None or lng is None:
            continue

        item = dict(p)
        item["latitude"] = lat
        item["longitude"] = lng
        clean_points.append(item)

        if previous:
            total_miles += _haversine_miles(previous["latitude"], previous["longitude"], lat, lng)
        previous = item

    stops = _detect_stops(clean_points)
    route_points = [[p["latitude"], p["longitude"]] for p in clean_points]

    first_time = clean_points[0].get("created_at") if clean_points else ""
    last_time = clean_points[-1].get("created_at") if clean_points else ""

    point_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(str(p.get('created_at') or ''))}</td>
          <td>{html.escape(str(p.get('employee_name') or ''))}</td>
          <td>{p.get('latitude')}</td>
          <td>{p.get('longitude')}</td>
          <td>{html.escape(str(p.get('source') or ''))}</td>
          <td>{html.escape(str(p.get('note') or ''))}</td>
        </tr>
        """
        for p in reversed(clean_points[-200:])
    ) or '<tr><td colspan="6">No GPS points for this date.</td></tr>'

    stop_rows = "".join(
        f"""
        <tr>
          <td>{i}</td>
          <td>{html.escape(str(s.get('arrival') or ''))}</td>
          <td>{html.escape(str(s.get('departure') or ''))}</td>
          <td>{html.escape(str(s.get('duration') or ''))}</td>
          <td>{round(s.get('lat'), 6)}, {round(s.get('lng'), 6)}</td>
        </tr>
        """
        for i, s in enumerate(stops, start=1)
    ) or '<tr><td colspan="5">No stops detected yet. Stops require multiple points near the same location for at least 5 minutes.</td></tr>'

    employee_options = ""
    if is_admin(u):
        employee_options = '<option value="">All Employees</option>'
        for e in employees:
            selected = "selected" if str(e.get("id")) == str(selected_employee) else ""
            label = html.escape(str(e.get("name") or e.get("username") or e.get("id")))
            employee_options += f'<option value="{e.get("id")}" {selected}>{label}</option>'

    employee_filter = f"""
      <label>Employee</label>
      <select name="employee_id">{employee_options}</select>
    """ if is_admin(u) else ""

    route_json = json.dumps(route_points)
    stops_json = json.dumps(stops)

    body = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{html.escape(title)}</title>
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
      <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
      <style>
        body {{ margin:0; font-family:Arial, sans-serif; background:#05090d; color:#f7eedf; }}
        .wrap {{ max-width:1320px; margin:0 auto; padding:32px 18px 70px; }}
        .top {{ display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }}
        h1 {{ margin:0; color:#d6b36a; font-size:clamp(34px, 6vw, 76px); text-transform:uppercase; letter-spacing:.04em; }}
        h2 {{ color:#d6b36a; margin-top:0; }}
        .btn, button {{ display:inline-block; border:1px solid rgba(214,179,106,.55); border-radius:12px; padding:12px 18px; background:rgba(0,0,0,.45); color:#d6b36a; text-decoration:none; font-weight:800; cursor:pointer; }}
        button.primary {{ background:#d6b36a; color:#05090d; }}
        .card {{ border:1px solid rgba(214,179,106,.38); border-radius:18px; padding:18px; background:rgba(255,255,255,.045); margin:18px 0; box-shadow:0 18px 38px rgba(0,0,0,.35); }}
        .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:16px; }}
        .metric {{ font-size:34px; font-weight:900; color:#fff; }}
        .muted {{ color:#bfb6a8; }}
        input, select {{ width:100%; box-sizing:border-box; border:1px solid rgba(214,179,106,.35); border-radius:12px; background:#0b1117; color:#fff; padding:12px; margin:6px 0 12px; }}
        table {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:14px; }}
        th, td {{ border-bottom:1px solid rgba(255,255,255,.1); padding:10px; text-align:left; vertical-align:top; }}
        th {{ color:#d6b36a; }}
        #gpsMap {{ height:560px; border-radius:18px; overflow:hidden; border:1px solid rgba(214,179,106,.35); background:#0b1117; }}
        .leaflet-popup-content-wrapper, .leaflet-popup-tip {{ background:#071017; color:#fff; }}
        @media(max-width:760px) {{ #gpsMap {{ height:430px; }} table {{ font-size:12px; }} }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="top">
          <div>
            <h1>{html.escape(title)}</h1>
            <div class="muted">Routes, stops, time at stops, mileage, and raw GPS points.</div>
          </div>
          <div>
            <a class="btn" href="/jarvis">Dashboard</a>
            <a class="btn" href="/time-clock">Time Clock</a>
            <a class="btn" href="/map">Live Map</a>
          </div>
        </div>

        <form class="card" method="get" action="/gps-replay">
          <div class="grid">
            <div>
              <label>Date</label>
              <input type="date" name="date" value="{html.escape(selected_day)}">
            </div>
            <div>
              {employee_filter}
            </div>
            <div style="display:flex; align-items:end;">
              <button class="primary" type="submit">Load Day</button>
            </div>
          </div>
        </form>

        <section class="grid">
          <div class="card"><div class="metric">{len(clean_points)}</div><div class="muted">GPS Points</div></div>
          <div class="card"><div class="metric">{len(stops)}</div><div class="muted">Stops Detected</div></div>
          <div class="card"><div class="metric">{round(total_miles, 2)}</div><div class="muted">Approx. Miles</div></div>
          <div class="card"><div class="metric">{html.escape(str(first_time)[11:16])} → {html.escape(str(last_time)[11:16])}</div><div class="muted">First → Last Point</div></div>
        </section>

        <section class="card">
          <h2>Route Map</h2>
          <div id="gpsMap"></div>
        </section>

        <section class="card">
          <h2>Stops</h2>
          <table><thead><tr><th>#</th><th>Arrival</th><th>Departure</th><th>Time There</th><th>Location</th></tr></thead><tbody>{stop_rows}</tbody></table>
        </section>

        <section class="card">
          <h2>Raw GPS Points</h2>
          <table><thead><tr><th>Time</th><th>Employee</th><th>Lat</th><th>Lng</th><th>Source</th><th>Note</th></tr></thead><tbody>{point_rows}</tbody></table>
        </section>
      </div>

      <script>
        const routePoints = {route_json};
        const stops = {stops_json};

        const map = L.map("gpsMap");
        L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
          maxZoom: 19,
          attribution: "&copy; OpenStreetMap"
        }}).addTo(map);

        if (routePoints.length) {{
          const line = L.polyline(routePoints, {{ weight: 5 }}).addTo(map);
          map.fitBounds(line.getBounds(), {{ padding: [30, 30] }});

          L.marker(routePoints[0]).addTo(map).bindPopup("Start");
          L.marker(routePoints[routePoints.length - 1]).addTo(map).bindPopup("End");

          stops.forEach(function(stop, idx) {{
            L.circleMarker([stop.lat, stop.lng], {{
              radius: 10,
              weight: 3,
              fillOpacity: 0.55
            }}).addTo(map).bindPopup(
              "<b>Stop " + (idx + 1) + "</b><br>" +
              "Arrived: " + stop.arrival + "<br>" +
              "Left: " + stop.departure + "<br>" +
              "Time: " + stop.duration
            );
          }});
        }} else {{
          map.setView([38.0, -87.57], 11);
        }}
      </script>
    </body>
    </html>
    """

    return HTMLResponse(body)


@router.get("/gps-replay", response_class=HTMLResponse)
def gps_replay(request: Request):
    return _gps_replay_html(request, "GPS Route Replay")


@router.get("/gps/day", response_class=HTMLResponse)
def gps_day(request: Request):
    return _gps_replay_html(request, "GPS Day Log")


@router.get("/gps/stops", response_class=HTMLResponse)
def gps_stops(request: Request):
    return _gps_replay_html(request, "GPS Stops")
