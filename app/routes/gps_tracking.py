from datetime import datetime, date
from math import radians, sin, cos, sqrt, atan2

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

router = APIRouter()


def _helpers():
    from app.app import (
        templates,
        ctx,
        require_login,
        login_redirect,
        admin_redirect,
        is_admin,
        is_employee,
        rows,
        one,
        exec_sql,
        USE_POSTGRES,
    )

    return {
        "templates": templates,
        "ctx": ctx,
        "require_login": require_login,
        "login_redirect": login_redirect,
        "admin_redirect": admin_redirect,
        "is_admin": is_admin,
        "is_employee": is_employee,
        "rows": rows,
        "one": one,
        "exec_sql": exec_sql,
        "USE_POSTGRES": USE_POSTGRES,
    }


def _safe_exec(sql, params=()):
    h = _helpers()
    try:
        return h["exec_sql"](sql, params)
    except Exception:
        return None


def ensure_gps_schema():
    h = _helpers()

    if h["USE_POSTGRES"]:
        _safe_exec(
            """
            CREATE TABLE IF NOT EXISTS employee_location_points (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER,
                employee_name TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
                accuracy REAL,
                speed REAL,
                heading REAL,
                source TEXT DEFAULT 'employee_portal',
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        _safe_exec(
            """
            CREATE TABLE IF NOT EXISTS employee_location_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                employee_name TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
                accuracy REAL,
                speed REAL,
                heading REAL,
                source TEXT DEFAULT 'employee_portal',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
            """
        )


def current_tracker_identity(user):
    """
    Admins can track as themselves. Crew tracks as their employee record.
    If an admin does not have an employee row, we still save points under their user id/name.
    """
    if not user:
        return 0, "Unknown"

    employee_id = user.get("id") or 0
    employee_name = user.get("name") or user.get("username") or "User"

    return employee_id, employee_name


def miles_between(lat1, lng1, lat2, lng2):
    try:
        lat1 = float(lat1)
        lng1 = float(lng1)
        lat2 = float(lat2)
        lng2 = float(lng2)
    except Exception:
        return 0

    radius = 3958.8
    p1 = radians(lat1)
    p2 = radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)

    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * radius * atan2(sqrt(a), sqrt(1 - a))


def parse_dt(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    value = str(value).replace("Z", "").strip()

    for fmt in [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]:
        try:
            return datetime.strptime(value[:19], fmt)
        except Exception:
            pass

    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def today_string_from_request(request: Request):
    return request.query_params.get("date") or date.today().isoformat()


def points_for_day(day):
    h = _helpers()
    ensure_gps_schema()

    return h["rows"](
        """
        SELECT *
        FROM employee_location_points
        WHERE CAST(created_at AS TEXT) LIKE ?
        ORDER BY employee_name, created_at, id
        """,
        (f"{day}%",),
    )


def build_stops(points, stop_radius_miles=0.10, min_minutes=3):
    """
    Groups GPS points into stops.
    A new stop begins when movement jumps outside the radius or time gap gets large.
    """
    grouped = {}

    for p in points:
        name = p.get("employee_name") or "Employee"
        grouped.setdefault(name, []).append(p)

    stops = []

    for employee_name, employee_points in grouped.items():
        current = []

        for p in employee_points:
            lat = p.get("latitude")
            lng = p.get("longitude")

            if lat is None or lng is None:
                continue

            if not current:
                current = [p]
                continue

            avg_lat = sum(float(x.get("latitude") or 0) for x in current) / len(current)
            avg_lng = sum(float(x.get("longitude") or 0) for x in current) / len(current)
            distance = miles_between(avg_lat, avg_lng, lat, lng)

            last_dt = parse_dt(current[-1].get("created_at"))
            this_dt = parse_dt(p.get("created_at"))
            gap_minutes = 0

            if last_dt and this_dt:
                gap_minutes = (this_dt - last_dt).total_seconds() / 60

            if distance > stop_radius_miles or gap_minutes > 45:
                stop = summarize_stop(employee_name, current)

                if stop and stop["minutes"] >= min_minutes:
                    stops.append(stop)

                current = [p]
            else:
                current.append(p)

        stop = summarize_stop(employee_name, current)

        if stop and stop["minutes"] >= min_minutes:
            stops.append(stop)

    return stops


def summarize_stop(employee_name, point_group):
    if not point_group:
        return None

    times = [parse_dt(p.get("created_at")) for p in point_group]
    times = [t for t in times if t]

    if not times:
        return None

    start = min(times)
    end = max(times)
    minutes = round((end - start).total_seconds() / 60, 1)

    avg_lat = sum(float(p.get("latitude") or 0) for p in point_group) / len(point_group)
    avg_lng = sum(float(p.get("longitude") or 0) for p in point_group) / len(point_group)

    return {
        "employee_name": employee_name,
        "start": start,
        "end": end,
        "minutes": minutes,
        "hours": round(minutes / 60, 2),
        "latitude": avg_lat,
        "longitude": avg_lng,
        "point_count": len(point_group),
        "maps_url": f"https://www.google.com/maps?q={avg_lat},{avg_lng}",
    }


@router.get("/gps", response_class=HTMLResponse)
@router.get("/gps/tracker", response_class=HTMLResponse)
def gps_tracker(request: Request):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not (h["is_admin"](user) or h["is_employee"](user)):
        return h["admin_redirect"](user)

    ensure_gps_schema()

    employee_id, employee_name = current_tracker_identity(user)

    return h["templates"].TemplateResponse(
        "gps_tracker.html",
        h["ctx"](
            request,
            employee_id=employee_id,
            employee_name=employee_name,
        ),
    )


@router.post("/gps/ping")
def gps_ping(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(0),
    speed: float = Form(0),
    heading: float = Form(0),
    source: str = Form("gps_tracker"),
    note: str = Form(""),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return JSONResponse({"ok": False, "error": "Not logged in"}, status_code=401)

    if not (h["is_admin"](user) or h["is_employee"](user)):
        return JSONResponse({"ok": False, "error": "Not allowed"}, status_code=403)

    ensure_gps_schema()

    employee_id, employee_name = current_tracker_identity(user)

    _safe_exec(
        """
        INSERT INTO employee_location_points
        (employee_id, employee_name, latitude, longitude, accuracy, speed, heading, source, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee_name,
            latitude,
            longitude,
            accuracy,
            speed,
            heading,
            source,
            note,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    return JSONResponse(
        {
            "ok": True,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "latitude": latitude,
            "longitude": longitude,
        }
    )


@router.get("/gps/day", response_class=HTMLResponse)
def gps_day(request: Request):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not (h["is_admin"](user) or h["is_employee"](user)):
        return h["admin_redirect"](user)

    selected_day = today_string_from_request(request)
    points = points_for_day(selected_day)

    if h["is_employee"](user) and not h["is_admin"](user):
        name = str(user.get("name") or "").strip().lower()
        points = [
            p for p in points
            if str(p.get("employee_name") or "").strip().lower() == name
        ]

    return h["templates"].TemplateResponse(
        "gps_day.html",
        h["ctx"](
            request,
            selected_day=selected_day,
            points=points,
        ),
    )


@router.get("/gps/stops", response_class=HTMLResponse)
def gps_stops(request: Request):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not (h["is_admin"](user) or h["is_employee"](user)):
        return h["admin_redirect"](user)

    selected_day = today_string_from_request(request)
    points = points_for_day(selected_day)

    if h["is_employee"](user) and not h["is_admin"](user):
        name = str(user.get("name") or "").strip().lower()
        points = [
            p for p in points
            if str(p.get("employee_name") or "").strip().lower() == name
        ]

    stops = build_stops(points)

    return h["templates"].TemplateResponse(
        "gps_stops.html",
        h["ctx"](
            request,
            selected_day=selected_day,
            points=points,
            stops=stops,
        ),
    )