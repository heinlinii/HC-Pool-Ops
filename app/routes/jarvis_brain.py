from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter()


def _helpers():
    from app.app import (
        templates,
        ctx,
        require_login,
        login_redirect,
        save_invisible_office_item,
        classify_invisible_office_item,
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
        "save_invisible_office_item": save_invisible_office_item,
        "classify_invisible_office_item": classify_invisible_office_item,
        "rows": rows,
        "one": one,
        "exec_sql": exec_sql,
        "USE_POSTGRES": USE_POSTGRES,
    }


def clean(text):
    return " ".join((text or "").lower().replace("’", "'").split())


def role_for_user(user):
    role = clean(user.get("role") if user else "")

    if role in ["admin", "owner"]:
        return "admin"

    if role in ["office", "manager"]:
        return "office"

    if role in ["crew", "employee", "worker"]:
        return "crew"

    if role in ["client", "customer"]:
        return "client"

    return role or "guest"


def get_or_create_employee_for_user(user):
    h = _helpers()

    employee_name = user.get("name") or user.get("username") or "Mike"
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

    role = "Admin" if role_for_user(user) == "admin" else "Crew"

    h["exec_sql"](
        """
        INSERT INTO poolops2_employees
        (name, role, phone, email, username, password, active)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            employee_name,
            role,
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


def clock_user(user, action):
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


DESTINATIONS = [
    {
        "name": "Field Clock + GPS",
        "href": "/gps",
        "roles": ["admin", "crew", "employee"],
        "keywords": [
            "gps",
            "start gps",
            "start tracking",
            "track me",
            "field clock",
            "where am i",
        ],
    },
    {
        "name": "GPS Stops",
        "href": "/gps/stops",
        "roles": ["admin", "crew", "employee"],
        "keywords": [
            "gps stops",
            "my stops",
            "where did i go",
            "where was i",
            "time spent",
            "stops",
        ],
    },
    {
        "name": "GPS Day Log",
        "href": "/gps/day",
        "roles": ["admin", "crew", "employee"],
        "keywords": [
            "gps day",
            "gps log",
            "day log",
            "raw gps",
            "location points",
        ],
    },
    {
        "name": "Invisible Office",
        "href": "/invisible-office",
        "roles": ["admin", "office"],
        "keywords": [
            "invisible office",
            "office memory",
            "reminders",
            "notes",
            "follow ups",
            "follow-ups",
            "what did i save",
        ],
    },
    {
        "name": "Find Anything",
        "href": "/invisible-office/search",
        "roles": ["admin", "office"],
        "keywords": [
            "search",
            "find",
            "find anything",
            "look up",
            "search office",
        ],
    },
    {
        "name": "Today’s Work",
        "href": "/organize-my-day",
        "roles": ["admin", "office", "crew", "employee"],
        "keywords": [
            "today",
            "today's work",
            "todays work",
            "my day",
            "organize my day",
            "today's mission",
            "mission",
        ],
    },
    {
        "name": "Schedule",
        "href": "/schedule/year",
        "roles": ["admin", "office", "crew", "employee", "client"],
        "keywords": [
            "schedule",
            "calendar",
            "year calendar",
            "appointments",
            "visits",
        ],
    },
    {
        "name": "Daily Schedule",
        "href": "/schedule/day",
        "roles": ["admin", "office", "crew", "employee"],
        "keywords": [
            "daily schedule",
            "today schedule",
            "today's schedule",
            "schedule today",
        ],
    },
    {
        "name": "Jobs",
        "href": "/jobs",
        "roles": ["admin", "office", "crew", "employee"],
        "keywords": [
            "jobs",
            "job list",
            "work orders",
            "work order",
            "projects",
        ],
    },
    {
        "name": "Clients",
        "href": "/clients",
        "roles": ["admin", "office"],
        "keywords": [
            "clients",
            "customers",
            "customer list",
            "client list",
        ],
    },
    {
        "name": "Properties",
        "href": "/properties",
        "roles": ["admin", "office", "crew", "employee"],
        "keywords": [
            "properties",
            "property",
            "addresses",
            "address list",
            "pools",
        ],
    },
    {
        "name": "Photos",
        "href": "/photos",
        "roles": ["admin", "office", "crew", "employee", "client"],
        "keywords": [
            "photos",
            "pictures",
            "photo log",
            "upload photos",
            "job photos",
        ],
    },
    {
        "name": "Field Logs",
        "href": "/field-logs",
        "roles": ["admin", "office", "crew", "employee"],
        "keywords": [
            "field logs",
            "field log",
            "work done",
            "daily log",
            "job notes",
        ],
    },
    {
        "name": "Billing",
        "href": "/billing",
        "roles": ["admin", "office"],
        "keywords": [
            "billing",
            "bill",
            "invoice",
            "invoices",
            "money",
            "charge",
        ],
    },
    {
        "name": "Estimates",
        "href": "/estimates",
        "roles": ["admin", "office"],
        "keywords": [
            "estimates",
            "estimate",
            "quote",
            "quotes",
        ],
    },
    {
        "name": "Crew",
        "href": "/crew",
        "roles": ["admin", "office"],
        "keywords": [
            "crew",
            "employees",
            "employee list",
            "workers",
        ],
    },
    {
        "name": "Employee Portal",
        "href": "/employee",
        "roles": ["admin", "crew", "employee"],
        "keywords": [
            "employee portal",
            "crew portal",
            "old clock page",
            "time clock",
        ],
    },
    {
        "name": "Map",
        "href": "/map",
        "roles": ["admin", "office", "crew", "employee"],
        "keywords": [
            "map",
            "field map",
            "locations",
            "pins",
            "where are jobs",
        ],
    },
    {
        "name": "Weather",
        "href": "/weather",
        "roles": ["admin", "office", "crew", "employee", "client"],
        "keywords": [
            "weather",
            "rain",
            "forecast",
            "freeze",
            "temperature",
        ],
    },
    {
        "name": "Pool Monitoring",
        "href": "/pool-monitoring",
        "roles": ["admin", "office"],
        "keywords": [
            "pool monitoring",
            "monitoring",
            "pentair",
            "pool alerts",
        ],
    },
    {
        "name": "Login Manager",
        "href": "/accounts",
        "roles": ["admin"],
        "keywords": [
            "accounts",
            "login manager",
            "create login",
            "edit login",
            "passwords",
            "users",
        ],
    },
    {
        "name": "Client Portal",
        "href": "/client",
        "roles": ["client"],
        "keywords": [
            "my project",
            "my pool",
            "client portal",
            "request service",
            "service request",
            "send message",
        ],
    },
]

def mike_brain_classify(text):
    lower = clean(text)

    category = "General Note"
    priority = "Normal"
    title = "Office Note"

    if any(word in lower for word in ["urgent", "asap", "right now", "today", "before i forget", "important"]):
        priority = "High"

    if any(word in lower for word in ["remind", "remember", "don't forget", "dont forget", "call", "text", "email", "follow up", "follow-up"]):
        category = "Reminder"
        title = "Reminder"

    if any(word in lower for word in ["finished", "complete", "completed", "done", "work done", "wrapped up"]):
        category = "Work Done"
        title = "Work Done"

    if any(word in lower for word in ["look at", "check", "inspect", "go look", "needs looked at", "take a look"]):
        category = "Work To Look At"
        title = "Work To Look At"

    if any(word in lower for word in ["bill", "billing", "invoice", "charge", "collect", "payment", "paid"]):
        category = "Billing Note"
        title = "Billing Note"

    if any(word in lower for word in ["material", "materials", "need", "order", "buy", "pick up", "check valve", "pipe", "fitting", "salt", "sand", "liner", "pump", "filter"]):
        if category == "General Note":
            category = "Material Needed"
            title = "Material Needed"

    if any(word in lower for word in ["problem", "issue", "leak", "broken", "not working", "error", "loud", "noise", "tripping", "won't", "wont"]):
        category = "Problem Found"
        title = "Problem Found"

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

SAVE_WORDS = [
    "remind",
    "remember",
    "note",
    "save",
    "file",
    "log",
    "work done",
    "finished",
    "complete",
    "completed",
    "need to",
    "needs",
    "call",
    "text",
    "email",
    "follow up",
    "follow-up",
    "bill",
    "invoice",
    "material",
    "materials",
    "look at",
    "check",
    "problem",
    "issue",
    "leak",
    "broken",
    "customer said",
    "client said",
    "todo",
    "to do",
]


NAV_WORDS = [
    "open",
    "show",
    "take me",
    "take me to",
    "go to",
    "pull up",
    "bring up",
    "where is",
    "get me to",
]


def allowed_destinations(role):
    if role == "employee":
        role = "crew"

    return [
        d for d in DESTINATIONS
        if role in d["roles"]
    ]


def best_destination(command, role):
    lower = clean(command)
    destinations = allowed_destinations(role)

    best = None
    best_score = 0

    for destination in destinations:
        score = 0

        for keyword in destination["keywords"]:
            key = clean(keyword)

            if key and key in lower:
                score += len(key)

        if score > best_score:
            best_score = score
            best = destination

    return best if best_score > 0 else None


def looks_like_save(command):
    lower = clean(command)
    return any(word in lower for word in SAVE_WORDS)


def looks_like_nav(command):
    lower = clean(command)
    return any(word in lower for word in NAV_WORDS)


def wants_clock_in(command):
    lower = clean(command)

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


def wants_clock_out(command):
    lower = clean(command)

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


@router.post("/jarvis/ask", response_class=HTMLResponse)
def jarvis_ask(
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

    text = (command or "").strip()

    if not text:
        return RedirectResponse("/jarvis", status_code=303)

    role = role_for_user(user)

    if role in ["admin", "crew", "employee"] and wants_clock_in(text):
        employee, timestamp = clock_user(user, "in")

        return h["templates"].TemplateResponse(
            "jarvis_action_done.html",
            h["ctx"](
                request,
                title="You’re Clocked In",
                message=f"{employee.get('name') or 'You'} are clocked in at {timestamp}.",
                primary_label="Start GPS Tracking",
                primary_href="/gps?autostart=1",
                secondary_label="Back to Jarvis",
                secondary_href="/jarvis",
            ),
        )

    if role in ["admin", "crew", "employee"] and wants_clock_out(text):
        employee, timestamp = clock_user(user, "out")

        return h["templates"].TemplateResponse(
            "jarvis_action_done.html",
            h["ctx"](
                request,
                title="You’re Clocked Out",
                message=f"{employee.get('name') or 'You'} are clocked out at {timestamp}.",
                primary_label="View GPS Stops",
                primary_href="/gps/stops",
                secondary_label="Back to Jarvis",
                secondary_href="/jarvis",
            ),
        )
    lower_text = clean(text)

    if role in ["admin", "crew", "employee"] and any(
        phrase in lower_text
        for phrase in [
            "start tracking",
            "start gps",
            "track me",
            "start tracking me",
            "gps me",
        ]
    ):
        return RedirectResponse("/gps?autostart=1", status_code=303)
    
    destination = best_destination(text, role)

    if destination and (looks_like_nav(text) or not looks_like_save(text)):
        href = destination["href"]

        if href == "/invisible-office/search":
            return RedirectResponse("/invisible-office/search?q=", status_code=303)

        return RedirectResponse(href, status_code=303)

    preview = mike_brain_classify(text)

    if priority.strip():
        preview["priority"] = priority.strip()

    return h["templates"].TemplateResponse(
        "jarvis_brain_preview.html",
        h["ctx"](
            request,
            raw_message=text,
            preview=preview,
            client=client,
            property=property,
            due_date=due_date,
            role=role,
        ),
    )


@router.post("/jarvis/file")
def jarvis_file(
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

    text = (body or "").strip()

    if text:
        h["save_invisible_office_item"](
            request=request,
            body=text,
            source="Jarvis Brain",
            category=category,
            title=title,
            client=client,
            property=property,
            due_date=due_date,
            priority=priority,
        )

    return RedirectResponse("/invisible-office", status_code=303)