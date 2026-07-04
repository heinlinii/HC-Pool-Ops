from datetime import datetime, date

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

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
        save_invisible_office_item,
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
        "save_invisible_office_item": save_invisible_office_item,
    }


def clean(text):
    return " ".join((text or "").lower().replace("’", "'").split())


def user_role(user):
    return clean(user.get("role") or "")


def allowed_crew_user(user):
    if not user:
        return False

    role = user_role(user)

    return role in ["admin", "crew", "employee", "worker"]


def get_or_create_employee_for_user(user):
    h = _helpers()

    employee_name = user.get("name") or user.get("username") or "Crew"
    username = user.get("username") or employee_name.lower().replace(" ", ".")

    existing = h["one"](
        """
        SELECT *
        FROM poolops2_employees
        WHERE lower(name)=lower(?) OR lower(username)=lower(?)
        ORDER BY id
        LIMIT 1
        """,
        (employee_name, username),
    )

    if existing:
        return existing

    h["exec_sql"](
        """
        INSERT INTO poolops2_employees
        (name, role, phone, email, username, password, active)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            employee_name,
            "Admin" if user_role(user) == "admin" else "Crew",
            "",
            "",
            username,
            "",
            True if h["USE_POSTGRES"] else 1,
        ),
    )

    return h["one"](
        """
        SELECT *
        FROM poolops2_employees
        WHERE lower(name)=lower(?) OR lower(username)=lower(?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (employee_name, username),
    )


def clock_employee(user, action):
    h = _helpers()

    employee = get_or_create_employee_for_user(user)
    now = datetime.now().isoformat(timespec="minutes")
    clocked = action == "in"

    h["exec_sql"](
        """
        UPDATE poolops2_employees
        SET clocked_in=?,
            clocked_in_at=?,
            last_seen_at=?
        WHERE id=?
        """,
        (
            True if clocked else False,
            now if clocked else "",
            now,
            employee.get("id"),
        ),
    )

    return employee, now


def classify_crew_note(text):
    lower = clean(text)
    category = "General Note"
    priority = "Normal"
    title = "Crew Note"

    if any(word in lower for word in ["urgent", "asap", "right now", "today", "important"]):
        priority = "High"

    if any(word in lower for word in ["finished", "complete", "completed", "done", "work done", "wrapped up"]):
        category = "Work Done"
        title = "Work Done"

    if any(word in lower for word in ["need", "needs", "material", "materials", "order", "buy", "pick up", "check valve", "pipe", "fitting", "salt", "sand"]):
        category = "Material Needed"
        title = "Material Needed"

    if any(word in lower for word in ["problem", "issue", "leak", "broken", "not working", "error", "loud", "noise", "tripping", "won't", "wont"]):
        category = "Problem Found"
        title = "Problem Found"

    if any(word in lower for word in ["look at", "check", "inspect", "needs looked at", "take a look"]):
        category = "Work To Look At"
        title = "Work To Look At"

    if any(word in lower for word in ["photo", "picture", "upload"]):
        category = "Photo Note"
        title = "Photo Note"

    if any(word in lower for word in ["heater", "pump", "filter", "automation", "pentair", "hayward", "jandy", "valve"]):
        if category == "General Note":
            category = "Equipment Note"
            title = "Equipment Note"

    short = (text or "").strip()

    if len(short) <= 80:
        title = short
    else:
        title = short[:77].rstrip() + "..."

    return {
        "category": category,
        "priority": priority,
        "title": title,
        "body": short,
    }


def todays_jobs_for_crew(user, employee):
    h = _helpers()
    today = date.today().isoformat()

    employee_name = employee.get("name") or user.get("name") or user.get("username") or ""

    # This is intentionally forgiving because job/schedule schemas may vary.
    # First try schedule items assigned to this employee by name.
    schedule_items = []

    try:
        schedule_items = h["rows"](
            """
            SELECT *
            FROM schedule_items
            WHERE CAST(start_date AS TEXT) LIKE ?
              AND (
                lower(COALESCE(assigned_to, '')) LIKE lower(?)
                OR lower(COALESCE(crew, '')) LIKE lower(?)
              )
            ORDER BY start_date, start_time, id
            LIMIT 10
            """,
            (f"{today}%", f"%{employee_name}%", f"%{employee_name}%"),
        )
    except Exception:
        schedule_items = []

    if schedule_items:
        return schedule_items

    # Fallback: show today's schedule if assignment column doesn't match/exist.
    try:
        return h["rows"](
            """
            SELECT *
            FROM schedule_items
            WHERE CAST(start_date AS TEXT) LIKE ?
            ORDER BY start_date, start_time, id
            LIMIT 10
            """,
            (f"{today}%",),
        )
    except Exception:
        return []


def wants_clock_in(text):
    lower = clean(text)

    return any(
        phrase in lower
        for phrase in [
            "clock me in",
            "clock in",
            "punch me in",
            "start my day",
            "start work",
        ]
    )


def wants_clock_out(text):
    lower = clean(text)

    return any(
        phrase in lower
        for phrase in [
            "clock me out",
            "clock out",
            "punch me out",
            "end my day",
            "done for the day",
            "stop work",
        ]
    )


def wants_tracking(text):
    lower = clean(text)

    return any(
        phrase in lower
        for phrase in [
            "start gps",
            "start tracking",
            "track me",
            "start tracking me",
            "gps me",
        ]
    )


def wants_nav(text):
    lower = clean(text)

    navs = [
        (["jobs", "my jobs", "today's jobs", "todays jobs", "today work", "work today"], "/crew-home#today-jobs"),
        (["photos", "pictures", "upload photos", "upload pictures"], "/photos"),
        (["map", "directions", "locations"], "/map"),
        (["weather", "forecast", "rain"], "/weather"),
        (["gps stops", "my stops", "where did i go", "where was i"], "/gps/stops"),
        (["gps day", "gps log"], "/gps/day"),
        (["employee portal", "old clock"], "/employee"),
    ]

    for keywords, href in navs:
        if any(k in lower for k in keywords):
            return href

    return None


@router.get("/crew-home", response_class=HTMLResponse)
def crew_home(request: Request):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not allowed_crew_user(user):
        return h["admin_redirect"](user)

    employee = get_or_create_employee_for_user(user)
    jobs = todays_jobs_for_crew(user, employee)
    clocked_in = employee.get("clocked_in")

    def truthy(value):
        return str(value).lower() in ("1", "true", "yes", "on", "t")

    gps_points_today = 0

    try:
        today = date.today().isoformat()
        gps_rows = h["rows"](
            """
            SELECT *
            FROM employee_location_points
            WHERE CAST(created_at AS TEXT) LIKE ?
              AND (
                employee_id=?
                OR lower(COALESCE(employee_name, ''))=lower(?)
              )
            ORDER BY id DESC
            LIMIT 5
            """,
            (
                f"{today}%",
                employee.get("id"),
                employee.get("name") or "",
            ),
        )
        gps_points_today = len(gps_rows or [])
    except Exception:
        gps_points_today = 0

    is_clocked_in = truthy(clocked_in)
    gps_active_today = gps_points_today > 0

    first_job = jobs[0] if jobs else None

    first_job_href = "/schedule/day"

    if first_job:
        if first_job.get("job_id"):
            first_job_href = f"/jobs/{first_job.get('job_id')}"
        elif first_job.get("id"):
            first_job_href = "/schedule/day"

    if not is_clocked_in:
        next_move = {
            "step": "Step 1",
            "title": "Clock In",
            "message": "You are not clocked in yet. Start the day here.",
            "primary_label": "Clock In",
            "primary_command": "Clock me in",
            "secondary_label": "View Today’s Jobs",
            "secondary_href": "#today-jobs",
        }
    elif not gps_active_today:
        next_move = {
            "step": "Step 2",
            "title": "Start GPS Tracking",
            "message": "You are clocked in. Now start GPS so Mike can see stops and time spent.",
            "primary_label": "Start GPS",
            "primary_href": "/gps?autostart=1",
            "secondary_label": "GPS Stops",
            "secondary_href": "/gps/stops",
        }
    elif first_job:
        next_move = {
            "step": "Step 3",
            "title": "Open Today’s First Job",
            "message": "GPS has started. Open the first job and get before photos.",
            "primary_label": "Open First Job",
            "primary_href": first_job_href,
            "secondary_label": "Upload Photos",
            "secondary_href": "/photos",
        }
    else:
        next_move = {
            "step": "Step 3",
            "title": "Tell Jarvis What You’re Doing",
            "message": "No assigned job was found for today. Tell Jarvis what you are working on.",
            "primary_label": "Add Field Note",
            "primary_href": "#talk-to-jarvis",
            "secondary_label": "Open Schedule",
            "secondary_href": "/schedule/day",
        }

    checklist = [
        {
            "label": "Clock in",
            "done": is_clocked_in,
            "hint": "Start the work day.",
        },
        {
            "label": "Start GPS tracking",
            "done": gps_active_today,
            "hint": "Keep the tracker page open while working.",
        },
        {
            "label": "Open today’s first job",
            "done": False,
            "hint": "Review where you are going and what needs done.",
        },
        {
            "label": "Upload before photos",
            "done": False,
            "hint": "Photos protect the company and help Mike remember what happened.",
        },
        {
            "label": "Tell Jarvis what got done",
            "done": False,
            "hint": "Say: Finished plumbing at Johnson.",
        },
        {
            "label": "Report problems or materials",
            "done": False,
            "hint": "Say: Need two check valves. Problem at Smith liner leak.",
        },
        {
            "label": "End-day report + clock out",
            "done": False,
            "hint": "Jarvis will ask what got done before clocking out.",
        },
    ]

    return h["templates"].TemplateResponse(
        "crew_home.html",
        h["ctx"](
            request,
            employee=employee,
            employee_name=employee.get("name") or user.get("name") or user.get("username") or "Crew",
            clocked_in=clocked_in,
            clocked_in_at=employee.get("clocked_in_at"),
            gps_active_today=gps_active_today,
            gps_points_today=gps_points_today,
            next_move=next_move,
            checklist=checklist,
            jobs=jobs,
        ),
    )


@router.post("/crew-home/ask", response_class=HTMLResponse)
def crew_home_ask(
    request: Request,
    command: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    due_date: str = Form(""),
    priority: str = Form(""),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not allowed_crew_user(user):
        return h["admin_redirect"](user)

    text = (command or "").strip()

    if not text:
        return RedirectResponse("/crew-home", status_code=303)

    if wants_clock_in(text):
        employee, timestamp = clock_employee(user, "in")

        return h["templates"].TemplateResponse(
            "crew_action_done.html",
            h["ctx"](
                request,
                title="You’re Clocked In",
                message=f"{employee.get('name') or 'Crew'} is clocked in at {timestamp}.",
                primary_label="Start GPS Tracking",
                primary_href="/gps?autostart=1",
                secondary_label="Back to Crew Home",
                secondary_href="/crew-home",
            ),
        )

    if wants_clock_out(text):
        employee, timestamp = clock_employee(user, "out")

        return h["templates"].TemplateResponse(
            "crew_action_done.html",
            h["ctx"](
                request,
                title="You’re Clocked Out",
                message=f"{employee.get('name') or 'Crew'} is clocked out at {timestamp}.",
                primary_label="View GPS Stops",
                primary_href="/gps/stops",
                secondary_label="Back to Crew Home",
                secondary_href="/crew-home",
            ),
        )

    if wants_tracking(text):
        return RedirectResponse("/gps?autostart=1", status_code=303)

    nav_href = wants_nav(text)

    if nav_href:
        return RedirectResponse(nav_href, status_code=303)

    preview = classify_crew_note(text)

    if priority.strip():
        preview["priority"] = priority.strip()

    return h["templates"].TemplateResponse(
        "crew_note_preview.html",
        h["ctx"](
            request,
            raw_message=text,
            preview=preview,
            client=client,
            property=property,
            due_date=due_date,
        ),
    )


@router.post("/crew-home/file")
def crew_home_file(
    request: Request,
    category: str = Form("General Note"),
    priority: str = Form("Normal"),
    title: str = Form(""),
    body: str = Form(""),
    client: str = Form(""),
    property: str = Form(""),
    due_date: str = Form(""),
):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    if not allowed_crew_user(user):
        return h["admin_redirect"](user)

    text = (body or "").strip()
    employee = get_or_create_employee_for_user(user)
    employee_name = employee.get("name") or user.get("name") or user.get("username") or "Crew"

    if text:
        h["save_invisible_office_item"](
            request=request,
            body=text,
            source=f"Crew Home - {employee_name}",
            category=category,
            title=title,
            client=client,
            property=property,
            due_date=due_date,
            priority=priority,
        )

    return RedirectResponse("/crew-home", status_code=303)