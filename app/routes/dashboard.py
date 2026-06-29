from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import date
import json

router = APIRouter()

from app.app import (
    templates,
    ctx,
    rows,
    jobs_for_user,
    schedule_date,
    ensure_legacy_schema,
    design_settings,
    save_design_settings,
    normalize_dashboard_cards,
    require_login,
    login_redirect,
    admin_redirect,
    is_admin,
    is_client,
    is_employee,
    USE_POSTGRES,
)

@router.get("/jarvis/search")
def jarvis_search(request: Request, q: str = ""):
    u = require_login(request)
    if not u:
        return login_redirect()

    text = (q or "").strip().lower()

    if not text:
        return RedirectResponse("/organize-my-day", status_code=303)

    if "today" in text or "day" in text or "work" in text or "handle" in text:
        return RedirectResponse("/organize-my-day", status_code=303)

    if "my day" in text or "clock" in text or "clock in" in text or "employee" in text:
        return RedirectResponse("/employee", status_code=303)

    if "talk" in text or "jarvis" in text or "assistant" in text:
        return RedirectResponse("/assistant-interview-live", status_code=303)

    if "job" in text:
        return RedirectResponse("/jobs", status_code=303)

    if "client" in text:
        return RedirectResponse("/clients", status_code=303)

    if "property" in text or "pool" in text:
        return RedirectResponse("/properties", status_code=303)

    if "photo" in text or "picture" in text:
        return RedirectResponse("/photos", status_code=303)

    if "field log" in text or "log" in text:
        return RedirectResponse("/field-logs", status_code=303)

    if "map" in text or "crew" in text:
        return RedirectResponse("/map", status_code=303)

    if "weather" in text:
        return RedirectResponse("/weather", status_code=303)

    return RedirectResponse("/organize-my-day", status_code=303)

@router.get("/jarvis", response_class=HTMLResponse)
def jarvis_landing(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    if is_employee(u):
        return RedirectResponse("/crew-dashboard", status_code=303)

    if is_client(u):
        return RedirectResponse("/client-dashboard", status_code=303)

    ensure_legacy_schema()
    design = design_settings()
    command_center = command_center_settings(design)
    attention = command_center_attention(u)

    return templates.TemplateResponse(
        "legacy_command_center.html",
        ctx(
            request,
            command_center=command_center,
            attention=attention,
        )
    )
# ============================================================
# HEINLIN FIELD OPS - ORGANIZED DASHBOARD SECTIONS
# ============================================================

DASHBOARD_SECTIONS = {
    "accounts": {
        "title": "Accounts",
        "subtitle": "Clients, properties, jobs, billing, photos, estimates, and invoices.",
        "description": "Everything tied to a customer account, property, job, invoice, estimate, or photo record.",
        "items": [
            {
                "title": "Clients",
                "subtitle": "Customer list, contact info, notes, and account history.",
                "url": "/clients",
                "button": "Open Clients",
            },
            {
                "title": "Properties",
                "subtitle": "Addresses, pool details, equipment, photos, and property notes.",
                "url": "/properties",
                "button": "Open Properties",
            },
            {
                "title": "Jobs",
                "subtitle": "Active jobs, service work, repairs, installs, and project records.",
                "url": "/jobs",
                "button": "Open Jobs",
            },
            {
                "title": "Billing",
                "subtitle": "Invoices, QuickBooks imports, balances, and money tracking.",
                "url": "/billing",
                "button": "Open Billing",
            },
            {
                "title": "Photos",
                "subtitle": "Job photos, property photos, equipment photos, and uploads.",
                "url": "/photos",
                "button": "Open Photos",
            },
            {
                "title": "Estimates",
                "subtitle": "Estimate work, pricing, proposals, and customer quote records.",
                "url": "/estimates",
                "button": "Open Estimates",
            },
        ],
    },

    "today": {
        "title": "Today",
        "subtitle": "Daily work, schedule, weather, map, and crew planning.",
        "description": "The first place to go every morning before the day starts.",
        "items": [
            {
                "title": "My Day",
                "subtitle": "Daily work view, today's work, notes, and field workflow.",
                "url": "/my-day",
                "button": "Open My Day",
            },
            {
                "title": "Schedule",
                "subtitle": "Schedule and calendar views for jobs, crew, and planning.",
                "url": "/schedule",
                "button": "Open Schedule",
            },
            {
                "title": "Weather",
                "subtitle": "Weather, freeze watch, weather watch, alerts, forecast, and radar.",
                "url": "/weather",
                "button": "Open Weather",
            },
            {
                "title": "Map",
                "subtitle": "Customer locations, jobsite map, and route planning.",
                "url": "/map",
                "button": "Open Map",
            },
        ],
    },

    "field-operations": {
        "title": "Field Operations",
        "subtitle": "Crew tools, employee dashboard, field logs, GPS, and photos.",
        "description": "The working side of the app for the people actually doing the work.",
        "items": [
            {
                "title": "Employee Dashboard",
                "subtitle": "Crew portal, daily tools, profile, and clock in/out.",
                "url": "/employee",
                "button": "Open Employee Dashboard",
            },
            {
    "title": "Time Clock",
    "subtitle": "Clock in/out and GPS tracking for admins, employees, and crew.",
    "url": "/time-clock",
    "button": "Open Time Clock",
},
            {
                "title": "Crew List",
                "subtitle": "Crew records, employees, and field users.",
                "url": "/crew",
                "button": "Open Crew",
            },
            {
                "title": "Field Logs",
                "subtitle": "Job notes, labor, materials, problems, and jobsite updates.",
                "url": "/field-logs",
                "button": "Open Field Logs",
            },
            {
                "title": "GPS Day Log",
                "subtitle": "GPS activity, stops, and day movement records.",
                "url": "/gps-day-log",
                "button": "Open GPS Day",
            },
            {
                "title": "Photos",
                "subtitle": "Upload and review jobsite photos.",
                "url": "/photos",
                "button": "Open Photos",
            },
        ],
    },

    "pool-systems": {
        "title": "Pool Systems",
        "subtitle": "Pool monitoring, Pentair access, weather protection, and equipment notes.",
        "description": "Everything related to monitored pools, pool equipment, heaters, pumps, filters, freeze risk, and service history.",
        "items": [
            {
                "title": "Pool Monitoring",
                "subtitle": "Open Pentair Pro links, track alerts, notes, and next actions.",
                "url": "/pool-monitoring",
                "button": "Open Pool Monitoring",
            },
            {
                "title": "Weather Protection",
                "subtitle": "Freeze watch, weather watch, forecast, radar, and pool protection planning.",
                "url": "/weather",
                "button": "Open Weather Protection",
            },
            {
                "title": "Photos",
                "subtitle": "Pool equipment photos, pad photos, repairs, and job documentation.",
                "url": "/photos",
                "button": "Open Photos",
            },
        ],
    },

    "business": {
        "title": "Business",
        "subtitle": "Employees, QuickBooks, invoice import, design studio, and office tools.",
        "description": "Company-side tools for running the business instead of working the jobsite.",
        "items": [
            {
                "title": "Employees",
                "subtitle": "Employee list, roles, crew access, and staff records.",
                "url": "/employees",
                "button": "Open Employees",
            },
            {
                "title": "QuickBooks",
                "subtitle": "QuickBooks invoice area and imported invoice records.",
                "url": "/quickbooks",
                "button": "Open QuickBooks",
            },
            {
                "title": "Invoice Import",
                "subtitle": "Import QuickBooks invoice CSV records.",
                "url": "/quickbooks/invoices/import",
                "button": "Open Import",
            },
            {
                "title": "Design Studio",
                "subtitle": "Change the app look, dashboard cards, images, and layout.",
                "url": "/design-studio",
                "button": "Open Design Studio",
            },
            {
                "title": "Invisible Office",
                "subtitle": "Internal notes, admin search, and office tools.",
                "url": "/invisible-office",
                "button": "Open Invisible Office",
            },
        ],
    },

    "jarvis-tools": {
        "title": "Jarvis",
        "subtitle": "AI system tools.",
        "description": "The Jarvis section is now cleaned up to show only the AI Systems card.",
        "items": [
            {
                "title": "Legacy Library",
                "subtitle": "Lessons learned, standards, fixes, and Heinlin know-how from completed jobs.",
                "url": "/legacy",
                "button": "Open Legacy",
            },
            {
                "title": "AI Systems",
                "subtitle": "Assistant and AI system tools.",
                "url": "/ai-systems",
                "button": "Open AI Systems",
            },
        ],
    },
}

@router.get("/accounts", response_class=HTMLResponse)
def accounts_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["accounts"]),
    )


@router.get("/today-dashboard", response_class=HTMLResponse)
def today_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["today"]),
    )


@router.get("/field-operations", response_class=HTMLResponse)
def field_operations_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["field-operations"]),
    )


@router.get("/pool-systems", response_class=HTMLResponse)
def pool_systems_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["pool-systems"]),
    )


@router.get("/business", response_class=HTMLResponse)
def business_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["business"]),
    )


@router.get("/jarvis-tools", response_class=HTMLResponse)
def jarvis_tools_dashboard(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()

    return templates.TemplateResponse(
        "dashboard_section.html",
        ctx(request, section=DASHBOARD_SECTIONS["jarvis-tools"]),
    )

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, y: int = None, m: int = None):
    u = require_login(request)
    if not u:
        return login_redirect()
    return RedirectResponse("/jarvis", status_code=303)



# ============================================================
# HEINLIN LEGACY COMMAND CENTER - EDITABLE DASHBOARD
# ============================================================

COMMAND_CENTER_DEFAULT = {
    "crest_image": "/static/heinlin-wide-crest.png",
    "background_image": "",
    "award_image": "",
    "award_title": "Indiana Historical Society",
    "award_subtitle": "CENTENNIAL BUSINESS AWARD",
    "weather_location": "Evansville, IN",
    "motto": "Built by the hands that perfected the term “work hard play harder.”",
    "cards": [
        {"key": "clients", "title": "Clients", "subtitle": "Client list and contact records.", "href": "/clients", "button": "View all", "icon": "👥", "image": "", "enabled": True, "order": 10},
        {"key": "properties", "title": "Properties", "subtitle": "Property records and pool history.", "href": "/properties", "button": "View all", "icon": "🏠", "image": "", "enabled": True, "order": 20},
        {"key": "jobs", "title": "Jobs", "subtitle": "Active jobs and job details.", "href": "/jobs", "button": "View all", "icon": "💼", "image": "", "enabled": True, "order": 30},
        {"key": "schedule", "title": "Schedule", "subtitle": "Calendar and bookings.", "href": "/schedule/year", "button": "Calendar", "icon": "🗓", "image": "", "enabled": True, "order": 40},
        {"key": "photos", "title": "Photos", "subtitle": "Jobsite photos and documentation.", "href": "/photos", "button": "Jobsite photos", "icon": "🖼", "image": "", "enabled": True, "order": 50},
        {"key": "crew", "title": "Crew", "subtitle": "Employees and crew management.", "href": "/crew", "button": "Manage crew", "icon": "👥", "image": "", "enabled": True, "order": 60},
        {"key": "time_clock", "title": "Time Clock", "subtitle": "Clock in/out and GPS tracking.", "href": "/time-clock", "button": "Clock / GPS", "icon": "⏱", "image": "", "enabled": True, "order": 70},
        {"key": "field_logs", "title": "Field Logs", "subtitle": "Logs and notes from the field.", "href": "/field-logs", "button": "Logs & notes", "icon": "📋", "image": "", "enabled": True, "order": 80},
        {"key": "estimates", "title": "Estimates", "subtitle": "Create and manage estimates.", "href": "/estimates", "button": "Create & manage", "icon": "📄", "image": "", "enabled": True, "order": 90},
        {"key": "job_costing", "title": "Job Costing", "subtitle": "Costs and reports.", "href": "/job-costing", "button": "Costs & reports", "icon": "💲", "image": "", "enabled": True, "order": 100},
        {"key": "quickbooks", "title": "QuickBooks", "subtitle": "Sync and manage QuickBooks.", "href": "/quickbooks", "button": "Sync & manage", "icon": "qb", "image": "", "enabled": True, "order": 110},
        {"key": "weather", "title": "Weather", "subtitle": "Forecast and alerts.", "href": "/weather", "button": "Forecast & alerts", "icon": "☁", "image": "", "enabled": True, "order": 120},
        {"key": "map", "title": "Map", "subtitle": "Jobs and locations.", "href": "/map", "button": "Jobs & locations", "icon": "📍", "image": "", "enabled": True, "order": 130},
        {"key": "legacy", "title": "Legacy", "subtitle": "Lessons learned and Heinlin standards.", "href": "/legacy", "button": "Legacy Library", "icon": "📖", "image": "", "enabled": True, "order": 140},
        {"key": "jarvis", "title": "Jarvis", "subtitle": "AI assistant and daily organization.", "href": "/ai-systems", "button": "AI Assistant", "icon": "🤖", "image": "", "enabled": True, "order": 150},
    ],
}

def command_center_settings(design=None):
    design = design or design_settings()
    data = json.loads(json.dumps(COMMAND_CENTER_DEFAULT))
    saved = design.get("command_center", {}) if isinstance(design, dict) else {}

    for key in ["crest_image", "background_image", "award_image", "award_title", "award_subtitle", "weather_location", "motto"]:
        if str(saved.get(key, "")).strip():
            data[key] = str(saved.get(key)).strip()

    # Pull old card-image settings forward so your existing Dashboard Card Images page still matters.
    old_cards = normalize_dashboard_cards(design) if isinstance(design, dict) else {}

    saved_cards = saved.get("cards", [])
    saved_by_key = {}
    if isinstance(saved_cards, list):
        for card in saved_cards:
            if isinstance(card, dict) and card.get("key"):
                saved_by_key[str(card.get("key"))] = card

    final_cards = []
    for default_card in data["cards"]:
        card = default_card.copy()
        key = card["key"]

        if key in old_cards and old_cards[key].get("image"):
            card["image"] = old_cards[key].get("image")

        if key in saved_by_key:
            for field in ["title", "subtitle", "href", "button", "icon", "image"]:
                if str(saved_by_key[key].get(field, "")).strip():
                    card[field] = str(saved_by_key[key].get(field)).strip()
            card["enabled"] = str(saved_by_key[key].get("enabled", card.get("enabled", True))).lower() not in ("0", "false", "off", "no")
            try:
                card["order"] = int(saved_by_key[key].get("order", card.get("order", 100)))
            except Exception:
                card["order"] = default_card.get("order", 100)

        final_cards.append(card)

    data["cards"] = sorted([c for c in final_cards if c.get("enabled", True)], key=lambda c: c.get("order", 100))
    data["all_cards"] = sorted(final_cards, key=lambda c: c.get("order", 100))
    return data


def command_center_attention(user):
    today = date.today().isoformat()
    attention = {
        "today_jobs": 0,
        "active_crew": 0,
        "pool_alerts": 0,
        "open_invoices": 0,
        "legacy_lessons": 0,
        "recent_lessons": [],
    }

    try:
        attention["today_jobs"] = len([j for j in jobs_for_user(user) if schedule_date(j) == today])
    except Exception:
        pass

    try:
        if is_admin(user):
            attention["active_crew"] = len(rows("SELECT id FROM poolops2_employees WHERE clocked_in=?", (True if USE_POSTGRES else 1,)))
    except Exception:
        pass

    try:
        attention["pool_alerts"] = len(rows("SELECT id FROM pool_monitoring WHERE coalesce(current_alert,'')<>''"))
    except Exception:
        pass

    try:
        if is_admin(user):
            attention["open_invoices"] = len(rows("SELECT id FROM poolops2_invoices WHERE lower(coalesce(status,'')) NOT IN ('paid','closed')"))
    except Exception:
        pass

    try:
        attention["legacy_lessons"] = len(rows("SELECT id FROM hfo_legacy_lessons"))
        attention["recent_lessons"] = rows("SELECT * FROM hfo_legacy_lessons ORDER BY id DESC LIMIT 3")
    except Exception:
        pass

    try:
        attention["clients"] = len(rows("SELECT id FROM poolops2_clients"))
    except Exception:
        attention["clients"] = 0

    try:
        attention["properties"] = len(rows("SELECT id FROM poolops2_properties"))
    except Exception:
        attention["properties"] = 0

    try:
        attention["jobs"] = len(rows("SELECT id FROM poolops2_jobs"))
    except Exception:
        attention["jobs"] = 0

    try:
        attention["employees"] = len(rows("""
            SELECT id
            FROM poolops2_employees
            WHERE coalesce(name,'') <> ''
              AND lower(coalesce(role,'')) IN ('crew','employee','admin')
        """))
    except Exception:
        attention["employees"] = 0

    return attention


@router.get("/command-center-design", response_class=HTMLResponse)
def command_center_design_page(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    design = design_settings()
    command_center = command_center_settings(design)

    return templates.TemplateResponse(
        "command_center_design.html",
        ctx(request, command_center=command_center)
    )


@router.post("/command-center-design")
async def command_center_design_save(request: Request):
    u = require_login(request)
    if not u:
        return login_redirect()
    if not is_admin(u):
        return admin_redirect(u)

    form = await request.form()
    design = design_settings()
    current = command_center_settings(design)

    saved = {
        "crest_image": str(form.get("crest_image", current.get("crest_image", ""))).strip(),
        "background_image": str(form.get("background_image", current.get("background_image", ""))).strip(),
        "award_image": str(form.get("award_image", current.get("award_image", ""))).strip(),
        "award_title": str(form.get("award_title", current.get("award_title", ""))).strip(),
        "award_subtitle": str(form.get("award_subtitle", current.get("award_subtitle", ""))).strip(),
        "weather_location": str(form.get("weather_location", current.get("weather_location", ""))).strip(),
        "motto": str(form.get("motto", current.get("motto", ""))).strip(),
        "cards": [],
    }

    for card in current.get("all_cards", current.get("cards", [])):
        key = card.get("key")
        saved["cards"].append({
            "key": key,
            "title": str(form.get(f"{key}_title", card.get("title", ""))).strip(),
            "subtitle": str(form.get(f"{key}_subtitle", card.get("subtitle", ""))).strip(),
            "href": str(form.get(f"{key}_href", card.get("href", ""))).strip(),
            "button": str(form.get(f"{key}_button", card.get("button", ""))).strip(),
            "icon": str(form.get(f"{key}_icon", card.get("icon", ""))).strip(),
            "image": str(form.get(f"{key}_image", card.get("image", ""))).strip(),
            "order": str(form.get(f"{key}_order", card.get("order", 100))).strip(),
            "enabled": str(form.get(f"{key}_enabled", "")).lower() in ("1", "true", "on", "yes"),
        })

    design["command_center"] = saved
    save_design_settings(design)

    return RedirectResponse("/command-center-design", status_code=303)


