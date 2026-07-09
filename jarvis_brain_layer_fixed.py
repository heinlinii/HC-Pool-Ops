
# ============================================================
# JARVIS BRAIN LAYER - HEINLIN FIELD OPS
# Safe add-on generated for Mike Heinlin II
# Purpose: Make Jarvis the voice-first command center above the app.
# ============================================================

import os as _jarvis_os
import re as _jarvis_re
import json as _jarvis_json
from datetime import datetime as _jarvis_datetime, date as _jarvis_date, timedelta as _jarvis_timedelta
from fastapi.responses import RedirectResponse as _JarvisRedirectResponse, HTMLResponse as _JarvisHTMLResponse, JSONResponse as _JarvisJSONResponse
from fastapi import Request, Form

JARVIS_BRAIN_ENABLED = _jarvis_os.environ.get("JARVIS_BRAIN_ENABLED", "true").lower() in ("1", "true", "yes", "on")
JARVIS_BRAIN_TAKES_OVER = _jarvis_os.environ.get("JARVIS_BRAIN_TAKES_OVER", "true").lower() in ("1", "true", "yes", "on")
JARVIS_BRAIN_VERSION = "2026.07.03-complete-working-safe-addon"


def _jnow():
    return _jarvis_datetime.now().isoformat(timespec="seconds")


def _jtoday():
    return _jarvis_date.today().isoformat()


def _jtry(func, default=None):
    try:
        return func()
    except Exception as exc:
        print(f"JARVIS BRAIN soft error: {exc}")
        return default


def _juser(request):
    try:
        current_user_func = globals().get("current_user")
        if callable(current_user_func):
            return current_user_func(request)
    except Exception:
        pass
    if hasattr(request, "session"):
        return request.session.get("user")
    return getattr(request, "user", None)


def _jrole(user):
    role = str((user or {}).get("role") or "").lower().strip()
    if role == "employee":
        role = "crew"
    return role or "guest"


def _jis_admin(user):
    try:
        is_admin_func = globals().get("is_admin")
        if callable(is_admin_func):
            return bool(is_admin_func(user))
    except Exception:
        pass
    return _jrole(user) == "admin"


def _jis_client(user):
    try:
        is_client_func = globals().get("is_client")
        if callable(is_client_func):
            return bool(is_client_func(user))
    except Exception:
        pass
    return _jrole(user) == "client"


def _jis_employee(user):
    try:
        is_employee_func = globals().get("is_employee")
        if callable(is_employee_func):
            return bool(is_employee_func(user))
    except Exception:
        pass
    return _jrole(user) in ("crew", "employee")


def _jlogin_redirect():
    try:
        login_redirect_func = globals().get("login_redirect")
        if callable(login_redirect_func):
            return login_redirect_func()
    except Exception:
        pass
    return _JarvisRedirectResponse("/login", status_code=303)


def _jadmin_redirect(user=None):
    try:
        admin_redirect_func = globals().get("admin_redirect")
        if callable(admin_redirect_func):
            return admin_redirect_func(user)
    except Exception:
        pass
    role = _jrole(user)
    if role == "client":
        return _JarvisRedirectResponse("/client-portal", status_code=303)
    if role == "crew":
        return _JarvisRedirectResponse("/employee", status_code=303)
    return _JarvisRedirectResponse("/jarvis-brain", status_code=303)


def _jctx(request, **kw):
    try:
        ctx_func = globals().get("ctx")
        if callable(ctx_func):
            return ctx_func(request, **kw)
    except Exception:
        pass
    return {"request": request, "user": _juser(request), **kw}


def _jrows(sql, params=()):
    try:
        rows_func = globals().get("rows")
        if callable(rows_func):
            return rows_func(sql, params)
    except Exception as exc:
        print(f"JARVIS BRAIN rows failed: {exc}\nSQL: {sql}")
    return []


def _jone(sql, params=()):
    try:
        one_func = globals().get("one")
        if callable(one_func):
            return one_func(sql, params)
    except Exception as exc:
        print(f"JARVIS BRAIN one failed: {exc}\nSQL: {sql}")
    return None


def _jexec(sql, params=()):
    try:
        exec_func = globals().get("exec_sql") or globals().get("exec")
        if callable(exec_func):
            return exec_func(sql, params)
    except Exception as exc:
        print(f"JARVIS BRAIN exec failed: {exc}\nSQL: {sql}")
    return None


def _jtable_columns(table):
    try:
        tc_func = globals().get("table_columns")
        if callable(tc_func):
            return tc_func(table)
    except Exception:
        pass
    return []


def _jadd_col(table, col, spec):
    try:
        if col not in _jtable_columns(table):
            _jexec(f"ALTER TABLE {table} ADD COLUMN {col} {spec}")
    except Exception:
        pass


def _juses_postgres():
    try:
        if "USE_POSTGRES" in globals():
            return bool(globals().get("USE_POSTGRES"))
    except Exception:
        pass
    return bool(_jarvis_os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")))


def _jlike():
    # Postgres handles LIKE case sensitively; we normalize enough in app-side matching.
    return "LIKE"


def _jbool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on", "active", "in")


def _jfirst_existing_table(candidates):
    for table in candidates:
        cols = _jtable_columns(table)
        if cols:
            return table
    return ""


def ensure_jarvis_brain_schema():
    if _juses_postgres():
        _jexec("""
            CREATE TABLE IF NOT EXISTS jarvis_memory (
                id SERIAL PRIMARY KEY,
                source TEXT DEFAULT 'Jarvis Brain',
                memory_type TEXT DEFAULT 'General',
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                client TEXT DEFAULT '',
                property TEXT DEFAULT '',
                job_id INTEGER,
                assigned_to TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                priority TEXT DEFAULT 'Normal',
                status TEXT DEFAULT 'Open',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT ''
            )
        """)
        _jexec("""
            CREATE TABLE IF NOT EXISTS jarvis_command_log (
                id SERIAL PRIMARY KEY,
                user_name TEXT DEFAULT '',
                user_role TEXT DEFAULT '',
                command_text TEXT DEFAULT '',
                intent TEXT DEFAULT '',
                response_text TEXT DEFAULT '',
                action_taken TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
                created_at TEXT DEFAULT ''
            )
        """)
    else:
        _jexec("""
            CREATE TABLE IF NOT EXISTS jarvis_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT DEFAULT 'Jarvis Brain',
                memory_type TEXT DEFAULT 'General',
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                client TEXT DEFAULT '',
                property TEXT DEFAULT '',
                job_id INTEGER,
                assigned_to TEXT DEFAULT '',
                due_date TEXT DEFAULT '',
                priority TEXT DEFAULT 'Normal',
                status TEXT DEFAULT 'Open',
                created_by TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT ''
            )
        """)
        _jexec("""
            CREATE TABLE IF NOT EXISTS jarvis_command_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT DEFAULT '',
                user_role TEXT DEFAULT '',
                command_text TEXT DEFAULT '',
                intent TEXT DEFAULT '',
                response_text TEXT DEFAULT '',
                action_taken TEXT DEFAULT '',
                latitude REAL,
                longitude REAL,
                created_at TEXT DEFAULT ''
            )
        """)

    # Strengthen current Invisible Office table without breaking older builds.
    if _jtable_columns("invisible_office_items"):
        for col, spec in [
            ("source", "TEXT DEFAULT 'Jarvis Brain'"),
            ("category", "TEXT DEFAULT 'General Note'"),
            ("title", "TEXT DEFAULT ''"),
            ("body", "TEXT DEFAULT ''"),
            ("client", "TEXT DEFAULT ''"),
            ("property", "TEXT DEFAULT ''"),
            ("job_id", "INTEGER"),
            ("assigned_to", "TEXT DEFAULT ''"),
            ("due_date", "TEXT DEFAULT ''"),
            ("priority", "TEXT DEFAULT 'Normal'"),
            ("status", "TEXT DEFAULT 'Open'"),
            ("created_by", "TEXT DEFAULT ''"),
            ("created_at", "TEXT DEFAULT ''"),
            ("completed_at", "TEXT DEFAULT ''"),
        ]:
            _jadd_col("invisible_office_items", col, spec)


def _jname(user):
    return str((user or {}).get("name") or (user or {}).get("username") or "Mike").strip() or "Mike"


def _jgreeting(user):
    h = _jarvis_datetime.now().hour
    part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    name = _jname(user).split()[0]
    role = _jrole(user)
    if role == "client":
        return f"Good {part}. I can show your project updates, photos, schedule notes, and service requests."
    if role == "crew":
        return f"Good {part}, {name}. I’ll keep you on the rails: clock, photos, notes, jobs, and what to do next."
    return f"Good {part}, {name}. I’ve got you. Tell me what needs handled and I’ll file it, prompt it, or turn it into work."


def _jschedule_date(job):
    try:
        sd_func = globals().get("schedule_date")
        if callable(sd_func):
            return sd_func(job)
    except Exception:
        pass

    val = (job or {}).get("scheduled_start") or (job or {}).get("date") or ""
    if isinstance(val, _jarvis_datetime):
        return val.date().isoformat()
    if isinstance(val, _jarvis_date):
        return val.isoformat()
    return str(val or "")[:10]


def _jjobs_for_user(user):
    try:
        jfu = globals().get("jobs_for_user")
        if callable(jfu):
            return jfu(user)
    except Exception:
        if _jis_admin(user):
            return _jrows("SELECT * FROM poolops2_jobs ORDER BY id DESC")
        if _jis_client(user):
            cname = _jname(user)
            return _jrows("SELECT * FROM poolops2_jobs WHERE client=? ORDER BY id DESC", (cname,))
        if _jis_employee(user):
            name = _jname(user)
            return _jrows("SELECT * FROM poolops2_jobs WHERE crew LIKE ? OR crew='' OR crew='Unassigned' OR crew IS NULL ORDER BY id DESC", (f"%{name}%",))
        return []


def _jproperties_for_user(user):
    try:
        prop_func = globals().get("properties_for_user")
        if callable(prop_func):
            return prop_func(user)
    except Exception:
        if _jis_admin(user) or _jis_employee(user):
            return _jrows("SELECT * FROM poolops2_properties ORDER BY client,address")
        if _jis_client(user):
            cname = _jname(user)
            return _jrows("SELECT * FROM poolops2_properties WHERE client=? OR client_id=? ORDER BY address", (cname, (user or {}).get("id")))
        return []


def _jphotos_for_user(user):
    try:
        return photos_for_user(user)
    except Exception:
        if _jis_admin(user) or _jis_employee(user):
            return _jrows("SELECT * FROM poolops2_photo_logs ORDER BY id DESC LIMIT 60")
        if _jis_client(user):
            cname = _jname(user)
            return _jrows("SELECT * FROM poolops2_photo_logs WHERE client=? ORDER BY id DESC LIMIT 60", (cname,))
        return []


def _jopen_memory(limit=12, user=None):
    ensure_jarvis_brain_schema()
    if _jis_admin(user):
        return _jrows("SELECT * FROM jarvis_memory WHERE coalesce(status,'Open') <> 'Done' ORDER BY id DESC LIMIT ?", (limit,))
    if _jis_employee(user):
        name = _jname(user)
        return _jrows("SELECT * FROM jarvis_memory WHERE (assigned_to=? OR assigned_to='' OR assigned_to IS NULL) AND coalesce(status,'Open') <> 'Done' ORDER BY id DESC LIMIT ?", (name, limit))
    if _jis_client(user):
        cname = _jname(user)
        return _jrows("SELECT * FROM jarvis_memory WHERE client=? AND coalesce(status,'Open') <> 'Done' ORDER BY id DESC LIMIT ?", (cname, limit))
    return []


def _jclassify_text(text):
    raw = (text or "").strip()
    low = raw.lower()
    memory_type = "General Note"
    priority = "Normal"
    intent = "remember"

    if any(x in low for x in ["clock in", "clock me in", "start gps", "start my day"]):
        intent = "clock_in"
        memory_type = "Time Clock"
    elif any(x in low for x in ["clock out", "clock me out", "end my day"]):
        intent = "clock_out"
        memory_type = "Time Clock"
    elif any(x in low for x in ["what next", "what's next", "what do i do", "what am i forgetting", "start briefing", "morning briefing"]):
        intent = "briefing"
        memory_type = "Briefing"
    elif any(x in low for x in ["bill", "invoice", "charge", "billing", "paid", "payment"]):
        intent = "billing_note"
        memory_type = "Billing Note"
    elif any(x in low for x in ["estimate", "quote", "bid"]):
        intent = "estimate_note"
        memory_type = "Estimate / Quote"
    elif any(x in low for x in ["material", "materials", "need", "buy", "pickup", "pick up", "order", "pipe", "fitting", "union", "cement", "rebar", "concrete", "salt", "check valve"]):
        intent = "materials"
        memory_type = "Material Needed"
    elif any(x in low for x in ["call", "text", "email", "follow up", "follow-up", "reach out", "remind me"]):
        intent = "follow_up"
        memory_type = "Follow-Up"
    elif any(x in low for x in ["problem", "issue", "broken", "leak", "leaking", "error", "failed", "bad", "cracked", "not working", "buzz", "buzzing"]):
        intent = "problem"
        memory_type = "Problem Found"
    elif any(x in low for x in ["field log", "work completed", "we did", "we got", "installed", "replaced", "cleaned", "poured", "formed"]):
        intent = "field_log"
        memory_type = "Field Log"

    if any(x in low for x in ["urgent", "asap", "emergency", "today", "right now", "critical", "danger", "gas", "electrical"]):
        priority = "High"

    title = raw[:80].strip() or "Jarvis Note"
    if len(raw) > 80:
        title += "..."

    return {"intent": intent, "memory_type": memory_type, "priority": priority, "title": title, "body": raw}


def _jextract_client_property_job(text, user=None):
    # Best-effort context resolver. It never blocks the command.
    text = text or ""
    low = text.lower()
    jobs = _jjobs_for_user(user)
    props = _jproperties_for_user(user)
    hit_job = None
    hit_prop = None

    for job in jobs[:300]:
        hay = " ".join([
            str(job.get("client") or ""),
            str(job.get("property") or ""),
            str(job.get("address") or ""),
            str(job.get("job_type") or ""),
        ]).lower()
        tokens = [str(job.get("client") or "").lower(), str(job.get("property") or "").lower(), str(job.get("address") or "").lower()]
        tokens = [t for t in tokens if t and len(t) > 2]
        if any(t in low for t in tokens) or (hay and hay in low):
            hit_job = job
            break

    for prop in props[:300]:
        tokens = [str(prop.get("client") or "").lower(), str(prop.get("property_name") or "").lower(), str(prop.get("address") or "").lower()]
        tokens = [t for t in tokens if t and len(t) > 2]
        if any(t in low for t in tokens):
            hit_prop = prop
            break

    client = (hit_job or hit_prop or {}).get("client") or (_jname(user) if _jis_client(user) else "")
    prop_name = (hit_job or {}).get("property") or (hit_prop or {}).get("property_name") or (hit_prop or {}).get("address") or ""
    job_id = (hit_job or {}).get("id")
    return client, prop_name, job_id, hit_job, hit_prop


def _jsave_memory(request, text, memory_type="", title="", client="", property="", job_id=None, assigned_to="", due_date="", priority="", source="Jarvis Brain"):
    ensure_jarvis_brain_schema()
    user = _juser(request) or {}
    classified = _jclassify_text(text)
    final_type = (memory_type or classified["memory_type"]).strip() or "General Note"
    final_title = (title or classified["title"]).strip() or "Jarvis Note"
    final_priority = (priority or classified["priority"]).strip() or "Normal"
    created_by = _jname(user)

    memory_id = _jexec(
        """
        INSERT INTO jarvis_memory
        (source, memory_type, title, body, client, property, job_id, assigned_to, due_date, priority, status, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (source, final_type, final_title, (text or "").strip(), client or "", property or "", job_id, assigned_to or "", due_date or "", final_priority, "Open", created_by, _jnow()),
    )

    if _jtable_columns("invisible_office_items"):
        _jexec(
            """
            INSERT INTO invisible_office_items
            (source, category, title, body, client, property, job_id, assigned_to, due_date, priority, status, created_by, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (source, final_type, final_title, (text or "").strip(), client or "", property or "", job_id, assigned_to or "", due_date or "", final_priority, "Open", created_by, _jnow()),
        )
    return memory_id


def _jsave_command_log(user, command_text, intent, response_text, action_taken="", lat=None, lng=None):
    ensure_jarvis_brain_schema()
    _jexec(
        """
        INSERT INTO jarvis_command_log
        (user_name, user_role, command_text, intent, response_text, action_taken, latitude, longitude, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (_jname(user), _jrole(user), command_text or "", intent or "", response_text or "", action_taken or "", lat, lng, _jnow()),
    )


def _jclock_employee(user, action, lat=None, lng=None):
    if not _jis_employee(user):
        return False, "Clock commands are crew-only from crew login. Admin can manage employees from the crew page."
    cols = _jtable_columns("poolops2_employees")
    if not cols:
        return False, "I could not find the employee table yet."
    now_minutes = _jarvis_datetime.now().isoformat(timespec="minutes")
    active = action == "in"
    emp_id = (user or {}).get("id")
    if not emp_id:
        return False, "I could not identify the employee record."

    updates = []
    vals = []
    for col, val in [
        ("clocked_in", active),
        ("clock_lat", float(lat) if lat not in (None, "") else None),
        ("clock_lng", float(lng) if lng not in (None, "") else None),
        ("clocked_in_at", now_minutes if active else ""),
        ("last_seen_at", now_minutes),
    ]:
        if col in cols:
            updates.append(f"{col}=?")
            vals.append(val)
    if not updates:
        return False, "The employee table does not have clock columns yet."
    vals.append(emp_id)
    _jexec(f"UPDATE poolops2_employees SET {', '.join(updates)} WHERE id=?", tuple(vals))
    return True, "You are clocked in." if active else "You are clocked out."


def _jmake_field_log_if_requested(request, user, text, client="", property="", lat=None, lng=None):
    if not _jtable_columns("field_logs"):
        return None
    classified = _jclassify_text(text)
    if classified["intent"] != "field_log":
        return None
    emp_name = _jname(user)
    return _jexec(
        """
        INSERT INTO field_logs
        (employee_name, client, property, address, date, total_hours, tools_used, materials_used, equipment_used, work_completed, issues, next_steps, weather, latitude, longitude, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (emp_name, client or "", property or "", "", _jtoday(), 0, "", "", "", text.strip(), "", "", "", float(lat) if lat not in (None, "") else None, float(lng) if lng not in (None, "") else None, _jnow()),
    )


def _jbriefing(user):
    today = _jtoday()
    jobs = _jjobs_for_user(user)
    today_jobs = [j for j in jobs if _jschedule_date(j) == today]
    overdue_jobs = []
    for j in jobs:
        ds = _jschedule_date(j)
        status = str(j.get("status") or "").lower()
        if ds and ds < today and status not in ("complete", "completed", "done", "closed"):
            overdue_jobs.append(j)

    memory = _jopen_memory(10, user)
    photos_today = []
    if not _jis_client(user):
        photos_today = [p for p in _jphotos_for_user(user) if str(p.get("date") or p.get("created_at") or "")[:10] == today]

    clocked_in = []
    if _jis_admin(user) and _jtable_columns("poolops2_employees"):
        clocked_in = _jrows("SELECT * FROM poolops2_employees WHERE clocked_in=? ORDER BY name", (True if _juses_postgres() else 1,))

    stats = {
        "today_jobs": len(today_jobs),
        "overdue_jobs": len(overdue_jobs),
        "open_memory": len(memory),
        "photos_today": len(photos_today),
        "clocked_in": len(clocked_in),
        "total_jobs_visible": len(jobs),
    }

    actions = []
    if _jis_client(user):
        actions = [
            "View your project photos.",
            "Send Mike a service request or project question.",
            "Check your current job status and schedule notes.",
        ]
    elif _jis_employee(user):
        if today_jobs:
            actions.append(f"You have {len(today_jobs)} job(s) showing for today. Open My Day and follow the first card.")
        else:
            actions.append("No assigned job is showing for today. Ask Mike or check the schedule before starting work.")
        actions.extend([
            "Clock in when you arrive.",
            "Take arrival photos before work starts.",
            "Tell Jarvis what you did before leaving so the field log is saved.",
        ])
    else:
        if overdue_jobs:
            actions.append(f"You have {len(overdue_jobs)} overdue job(s) that need status, schedule, or follow-up cleaned up.")
        if today_jobs:
            actions.append(f"You have {len(today_jobs)} job(s) scheduled today.")
        if memory:
            actions.append(f"You have {len(memory)} open Jarvis memory item(s) waiting in the Invisible Office.")
        if not photos_today:
            actions.append("No photos are logged for today yet. Arrival/progress/completion photos protect you.")
        actions.extend([
            "Say: ‘Jarvis, log what I just said’ to turn rough talk into office memory.",
            "Say: ‘Jarvis, add this to billing’ when something should become money.",
        ])

    if not actions:
        actions.append("Everything looks quiet from the data I can see. Tell me what needs handled first.")

    return {
        "today": today,
        "stats": stats,
        "today_jobs": today_jobs[:8],
        "overdue_jobs": overdue_jobs[:8],
        "memory": memory[:8],
        "actions": actions[:8],
    }


def _jquick_actions(user):
    role = _jrole(user)
    if role == "client":
        return [
            {"label": "Project Update", "command": "Jarvis, show my project update."},
            {"label": "Service Request", "command": "Jarvis, I need to send Mike a service request."},
            {"label": "Photos", "href": "/client-portal"},
        ]
    if role == "crew":
        return [
            {"label": "Clock In", "command": "Jarvis, clock me in."},
            {"label": "Clock Out", "command": "Jarvis, clock me out."},
            {"label": "What Next?", "command": "Jarvis, what should I do next?"},
            {"label": "Save Field Log", "command": "Jarvis, field log: "},
            {"label": "Upload Photos", "href": "/photos"},
            {"label": "My Day", "href": "/crew/my-day"},
        ]
    return [
        {"label": "Morning Briefing", "command": "Jarvis, what matters today?"},
        {"label": "What Am I Forgetting?", "command": "Jarvis, what am I forgetting?"},
        {"label": "Billing Note", "command": "Jarvis, add this to billing: "},
        {"label": "Material Needed", "command": "Jarvis, material needed: "},
        {"label": "Follow Up", "command": "Jarvis, remind me to follow up with "},
        {"label": "Invisible Office", "href": "/invisible-office"},
        {"label": "Organize My Day", "href": "/organize-my-day"},
        {"label": "Crew", "href": "/crew"},
    ]


def _janswer_search(user, text):
    q = (text or "").strip()
    q = _jarvis_re.sub(r"^(jarvis[, ]*)?(find|search|look up|show me)\s+", "", q, flags=_jarvis_re.I).strip()
    if not q:
        return None
    like = f"%{q}%"
    results = []
    if _jis_client(user):
        cname = _jname(user)
        for table, url, kind in [("poolops2_jobs", "/client-portal", "Job"), ("poolops2_photo_logs", "/client-portal", "Photo")]:
            if _jtable_columns(table):
                for r in _jrows(f"SELECT * FROM {table} WHERE client=? AND CAST(client AS TEXT) LIKE ? LIMIT 8", (cname, like)):
                    results.append({"kind": kind, "title": r.get("property") or r.get("title") or r.get("client") or kind, "url": url})
    else:
        for table, url, kind, cols in [
            ("poolops2_clients", "/clients", "Client", ["name", "contact_name", "phone", "email", "notes"]),
            ("poolops2_properties", "/properties", "Property", ["client", "property_name", "address", "notes", "equipment_notes"]),
            ("poolops2_jobs", "/jobs", "Job", ["client", "property", "address", "job_type", "notes"]),
            ("jarvis_memory", "/jarvis-brain", "Jarvis Memory", ["title", "body", "client", "property"]),
        ]:
            have = [c for c in cols if c in _jtable_columns(table)]
            if not have:
                continue
            where = " OR ".join([f"CAST({c} AS TEXT) LIKE ?" for c in have])
            for r in _jrows(f"SELECT * FROM {table} WHERE {where} ORDER BY id DESC LIMIT 8", tuple([like] * len(have))):
                title = r.get("name") or r.get("property_name") or r.get("property") or r.get("title") or r.get("client") or kind
                rid = r.get("id")
                link = f"{url}/{rid}" if rid and url in ("/clients", "/properties", "/jobs") else url
                results.append({"kind": kind, "title": title, "url": link})
    if results:
        return results[:10]
    return []


@app.middleware("http")
async def jarvis_brain_front_door_middleware(request, call_next):
    # Makes Jarvis Brain the front door without deleting your existing /jarvis route.
    if JARVIS_BRAIN_ENABLED and JARVIS_BRAIN_TAKES_OVER and request.url.path == "/jarvis":
        return _JarvisRedirectResponse("/jarvis-brain", status_code=303)
    return await call_next(request)


@app.get("/jarvis-brain", response_class=_JarvisHTMLResponse)
def jarvis_brain_page(request: Request):
    if not JARVIS_BRAIN_ENABLED:
        return _JarvisRedirectResponse("/jarvis", status_code=303)
    user = _juser(request)
    if not user:
        return _jlogin_redirect()
    ensure_jarvis_brain_schema()
    briefing = _jbriefing(user)
    recent_commands = _jrows("SELECT * FROM jarvis_command_log ORDER BY id DESC LIMIT 10") if _jis_admin(user) else _jrows("SELECT * FROM jarvis_command_log WHERE user_name=? ORDER BY id DESC LIMIT 10", (_jname(user),))
    return templates.TemplateResponse(
        "jarvis_brain.html",
        _jctx(
            request,
            jarvis_version=JARVIS_BRAIN_VERSION,
            greeting=_jgreeting(user),
            role=_jrole(user),
            briefing=briefing,
            quick_actions=_jquick_actions(user),
            recent_commands=recent_commands,
            today=_jtoday(),
        ),
    )


@app.get("/jarvis/brain", response_class=_JarvisHTMLResponse)
def jarvis_brain_alias(request: Request):
    user = _juser(request)
    if not user:
        return _jlogin_redirect()
    return _JarvisRedirectResponse("/jarvis-brain", status_code=303)


@app.get("/jarvis-brain/install-check")
def jarvis_brain_install_check(request: Request):
    user = _juser(request)
    if not user:
        return _jlogin_redirect()
    ensure_jarvis_brain_schema()
    return _JarvisJSONResponse({
        "ok": True,
        "version": JARVIS_BRAIN_VERSION,
        "takes_over_jarvis": JARVIS_BRAIN_TAKES_OVER,
        "role": _jrole(user),
        "tables": {
            "jarvis_memory": bool(_jtable_columns("jarvis_memory")),
            "jarvis_command_log": bool(_jtable_columns("jarvis_command_log")),
            "invisible_office_items": bool(_jtable_columns("invisible_office_items")),
            "field_logs": bool(_jtable_columns("field_logs")),
            "jobs": bool(_jtable_columns("poolops2_jobs")),
            "employees": bool(_jtable_columns("poolops2_employees")),
        }
    })


@app.get("/jarvis-brain/briefing.json")
def jarvis_brain_briefing_json(request: Request):
    user = _juser(request)
    if not user:
        return _JarvisJSONResponse({"ok": False, "error": "Login required"}, status_code=401)
    return _JarvisJSONResponse({"ok": True, "briefing": _jbriefing(user), "greeting": _jgreeting(user)})


@app.post("/jarvis-brain/command")
async def jarvis_brain_command(request: Request):
    user = _juser(request)
    if not user:
        return _JarvisJSONResponse({"ok": False, "reply": "Login required."}, status_code=401)
    ensure_jarvis_brain_schema()

    payload = {}
    try:
        payload = await request.json()
    except Exception:
        try:
            form = await request.form()
            payload = dict(form)
        except Exception:
            payload = {}

    text = str(payload.get("text") or payload.get("message") or "").strip()
    lat = payload.get("lat") or payload.get("latitude") or ""
    lng = payload.get("lng") or payload.get("longitude") or ""

    if not text:
        return _JarvisJSONResponse({"ok": False, "reply": "Tell me what needs handled."})

    classified = _jclassify_text(text)
    intent = classified["intent"]
    reply = "I saved it to Jarvis memory and the Invisible Office."
    action_taken = "memory_saved"
    links = []
    cards = []

    low = text.lower()

    if intent == "clock_in":
        ok, msg = _jclock_employee(user, "in", lat, lng)
        reply = msg
        action_taken = "clock_in" if ok else "clock_in_failed"
    elif intent == "clock_out":
        ok, msg = _jclock_employee(user, "out", lat, lng)
        reply = msg
        action_taken = "clock_out" if ok else "clock_out_failed"
    elif intent == "briefing":
        b = _jbriefing(user)
        reply = "Here’s what matters: " + " ".join(b.get("actions", [])[:4])
        action_taken = "briefing_returned"
        cards = [{"title": "Today", "value": b["stats"]["today_jobs"], "detail": "jobs today"}, {"title": "Open Memory", "value": b["stats"]["open_memory"], "detail": "items"}, {"title": "Overdue", "value": b["stats"]["overdue_jobs"], "detail": "jobs"}]
    elif _jarvis_re.search(r"\b(find|search|look up|show me)\b", low):
        found = _janswer_search(user, text)
        if found:
            reply = f"I found {len(found)} possible match(es)."
            links = found
        else:
            reply = "I searched the clients, properties, jobs, and Jarvis memory I can access, but I did not find a solid match."
        action_taken = "search"
    else:
        client, prop, job_id, hit_job, hit_prop = _jextract_client_property_job(text, user)
        _jsave_memory(request, text, memory_type=classified["memory_type"], title=classified["title"], client=client, property=prop, job_id=job_id, priority=classified["priority"])
        field_log_id = _jmake_field_log_if_requested(request, user, text, client=client, property=prop, lat=lat, lng=lng)
        if field_log_id:
            reply = "I saved that as a field log and also filed it in Jarvis memory."
            action_taken = "field_log_saved"
            links.append({"kind": "Field Logs", "title": "Open Field Logs", "url": "/field-logs"})
        elif classified["intent"] == "billing_note":
            reply = "I saved that as a billing note. It is waiting in the Invisible Office so you can turn it into money instead of forgetting it."
            links.append({"kind": "Billing", "title": "Open Invisible Office", "url": "/invisible-office"})
        elif classified["intent"] == "materials":
            reply = "I saved that as a material-needed item."
        elif classified["intent"] == "follow_up":
            reply = "I saved that as a follow-up/reminder."
        elif classified["intent"] == "problem":
            reply = "I saved that as a problem found. That protects the job history and gives you something to follow up on."
        else:
            reply = "I saved that to Jarvis memory and filed it where the office can see it."

    _jsave_command_log(user, text, intent, reply, action_taken, float(lat) if str(lat).strip() else None, float(lng) if str(lng).strip() else None)
    return _JarvisJSONResponse({
        "ok": True,
        "reply": reply,
        "intent": intent,
        "action_taken": action_taken,
        "links": links,
        "cards": cards,
        "briefing": _jbriefing(user),
    })


@app.post("/jarvis-brain/memory")
def jarvis_brain_memory_save(request: Request, note: str = Form(""), memory_type: str = Form("General Note"), priority: str = Form("Normal"), client: str = Form(""), property: str = Form(""), due_date: str = Form("")):
    user = _juser(request)
    if not user:
        return _jlogin_redirect()
    if not note.strip():
        return _JarvisRedirectResponse("/jarvis-brain", status_code=303)
    _jsave_memory(request, note.strip(), memory_type=memory_type, priority=priority, client=client, property=property, due_date=due_date, source="Jarvis Brain Manual")
    return _JarvisRedirectResponse("/jarvis-brain", status_code=303)


@app.post("/jarvis-brain/memory/{memory_id}/done")
def jarvis_brain_memory_done(request: Request, memory_id: int):
    user = _juser(request)
    if not user:
        return _jlogin_redirect()
    if not _jis_admin(user) and not _jis_employee(user):
        return _jadmin_redirect(user)
    _jexec("UPDATE jarvis_memory SET status=?, completed_at=? WHERE id=?", ("Done", _jnow(), memory_id))
    return _JarvisRedirectResponse("/jarvis-brain", status_code=303)


@app.get("/jarvis-brain/export.json")
def jarvis_brain_export(request: Request):
    user = _juser(request)
    if not user:
        return _jlogin_redirect()
    if not _jis_admin(user):
        return _jadmin_redirect(user)
    ensure_jarvis_brain_schema()
    return _JarvisJSONResponse({
        "version": JARVIS_BRAIN_VERSION,
        "memory": _jrows("SELECT * FROM jarvis_memory ORDER BY id DESC LIMIT 500"),
        "commands": _jrows("SELECT * FROM jarvis_command_log ORDER BY id DESC LIMIT 500"),
    })


# Legacy names Mike already uses in conversation.
@app.get("/brain", response_class=_JarvisHTMLResponse)
def brain_alias(request: Request):
    return _JarvisRedirectResponse("/jarvis-brain", status_code=303)

@app.get("/mike-brain", response_class=_JarvisHTMLResponse)
def mike_brain_alias(request: Request):
    return _JarvisRedirectResponse("/jarvis-brain", status_code=303)

# ============================================================
# END JARVIS BRAIN LAYER
# ============================================================
