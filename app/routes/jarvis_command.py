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
    )

    return {
        "templates": templates,
        "ctx": ctx,
        "require_login": require_login,
        "login_redirect": login_redirect,
        "save_invisible_office_item": save_invisible_office_item,
        "classify_invisible_office_item": classify_invisible_office_item,
    }


DESTINATIONS = [
    {
        "name": "Mike Mode",
        "href": "/jarvis",
        "keywords": ["dashboard", "mike mode", "home", "cockpit", "command center"],
    },
    {
        "name": "Talk to Jarvis",
        "href": "/assistant-interview-live",
        "keywords": ["talk to jarvis", "jarvis", "assistant", "send it"],
    },
    {
        "name": "Invisible Office",
        "href": "/invisible-office",
        "keywords": ["invisible office", "office", "reminders", "notes", "follow ups", "follow-ups"],
    },
    {
        "name": "Find Anything",
        "href": "/invisible-office/search",
        "keywords": ["search", "find", "find anything", "look up"],
    },
    {
        "name": "Today’s Work",
        "href": "/organize-my-day",
        "keywords": ["today", "today's work", "todays work", "organize my day", "my day", "mission"],
    },
    {
        "name": "Daily Schedule",
        "href": "/schedule/day",
        "keywords": ["daily schedule", "today schedule", "today's schedule", "schedule today"],
    },
    {
        "name": "Schedule",
        "href": "/schedule/year",
        "keywords": ["schedule", "calendar", "year calendar", "full calendar"],
    },
    {
        "name": "Jobs",
        "href": "/jobs",
        "keywords": ["jobs", "job list", "work orders", "work order"],
    },
    {
        "name": "Clients",
        "href": "/clients",
        "keywords": ["clients", "customers", "customer list", "client list"],
    },
    {
        "name": "Properties",
        "href": "/properties",
        "keywords": ["properties", "property", "addresses", "address list", "pools"],
    },
    {
        "name": "Photos",
        "href": "/photos",
        "keywords": ["photos", "pictures", "photo log", "upload photos"],
    },
    {
        "name": "Field Logs",
        "href": "/field-logs",
        "keywords": ["field logs", "field log", "work done", "daily log", "job notes"],
    },
    {
        "name": "Billing",
        "href": "/billing",
        "keywords": ["billing", "bill", "invoice", "invoices", "money"],
    },
    {
        "name": "Estimates",
        "href": "/estimates",
        "keywords": ["estimates", "estimate", "quote", "quotes"],
    },
    {
        "name": "QuickBooks",
        "href": "/quickbooks",
        "keywords": ["quickbooks", "quick books", "qb"],
    },
    {
        "name": "Job Costing",
        "href": "/job-costing",
        "keywords": ["job costing", "costing", "profit", "costs"],
    },
    {
        "name": "Crew",
        "href": "/crew",
        "keywords": ["crew", "employees", "employee", "workers", "randy", "marty"],
    },
    {
        "name": "Crew Portal",
        "href": "/employee",
        "keywords": ["clock in", "clock out", "crew portal", "employee portal", "time clock"],
    },
    {
        "name": "GPS Tracker",
        "href": "/gps",
        "keywords": ["gps", "track me", "tracking", "tracker", "location"],
    },
    {
        "name": "GPS Day Log",
        "href": "/gps/day",
        "keywords": ["gps day", "gps log", "day log", "raw gps"],
    },
    {
        "name": "GPS Stops",
        "href": "/gps/stops",
        "keywords": ["gps stops", "stops", "time spent", "where was i", "where did i go"],
    },
    {
        "name": "Map",
        "href": "/map",
        "keywords": ["map", "field map", "locations", "pins"],
    },
    {
        "name": "Weather",
        "href": "/weather",
        "keywords": ["weather", "rain", "forecast", "freeze", "temperature"],
    },
    {
        "name": "Pool Monitoring",
        "href": "/pool-monitoring",
        "keywords": ["pool monitoring", "monitoring", "pentair", "pool alerts"],
    },
    {
        "name": "Login Manager",
        "href": "/accounts",
        "keywords": ["accounts", "login manager", "create login", "edit login", "passwords"],
    },
    {
        "name": "Design Studio",
        "href": "/design-studio",
        "keywords": ["design studio", "edit dashboard", "change look", "theme"],
    },
    {
        "name": "AI Systems",
        "href": "/ai-systems",
        "keywords": ["ai systems", "ai tools", "jarvis tools"],
    },
]


SAVE_WORDS = [
    "remind",
    "remember",
    "note",
    "add note",
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


def normalize(text):
    return " ".join((text or "").lower().replace("’", "'").split())


def best_destination(command):
    lower = normalize(command)

    best = None
    best_score = 0

    for destination in DESTINATIONS:
        score = 0

        for keyword in destination["keywords"]:
            key = normalize(keyword)

            if key in lower:
                score += len(key)

        if score > best_score:
            best_score = score
            best = destination

    return best if best_score > 0 else None


def looks_like_save(command):
    lower = normalize(command)
    return any(word in lower for word in SAVE_WORDS)


def looks_like_nav(command):
    lower = normalize(command)
    return any(word in lower for word in NAV_WORDS)


@router.post("/jarvis-command", response_class=HTMLResponse)
def jarvis_command(
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
        return RedirectResponse("/assistant-interview-live", status_code=303)

    destination = best_destination(text)

    if destination and (looks_like_nav(text) or not looks_like_save(text)):
        href = destination["href"]

        if href == "/invisible-office/search":
            return RedirectResponse("/invisible-office/search?q=", status_code=303)

        return RedirectResponse(href, status_code=303)

    preview = h["classify_invisible_office_item"](text)

    if priority.strip():
        preview["priority"] = priority.strip()

    return h["templates"].TemplateResponse(
        "jarvis_command_preview.html",
        h["ctx"](
            request,
            raw_message=text,
            preview=preview,
            client=client,
            property=property,
            due_date=due_date,
            destinations=DESTINATIONS,
        ),
    )


@router.post("/jarvis-command/save")
def jarvis_command_save(
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
            source="Jarvis Command",
            category=category,
            title=title,
            client=client,
            property=property,
            due_date=due_date,
            priority=priority,
        )

    return RedirectResponse("/invisible-office", status_code=303)


@router.get("/jarvis-destinations", response_class=HTMLResponse)
def jarvis_destinations(request: Request):
    h = _helpers()
    user = h["require_login"](request)

    if not user:
        return h["login_redirect"]()

    return h["templates"].TemplateResponse(
        "jarvis_destinations.html",
        h["ctx"](
            request,
            destinations=DESTINATIONS,
        ),
    )