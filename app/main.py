"""AI-assisted Clinical Trial Management System.

Server-rendered routes enforce the approved five-role CTMS scope. AI services create
reviewable findings; only authorised people make eligibility, safety, or governance
outcomes.
"""
from __future__ import annotations

import dataclasses
import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import alerts, audit, auth, ctms, governance, kpi, pv, queues, signals
from .config import settings
from .db import Connection, backend, close_pool, get_db, init
from .models import EscalationRaisedByRole, EscalationType, LeadershipDecisionType, User, UserRole, utcnow
from .security import prepare_csrf, set_csrf_cookie, verify_csrf, verify_csrf_header

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# The `qs` macro in _queue.html rebuilds URLs from the cleaned params echo via
# dict(); Jinja does not expose the builtin on its own.
templates.env.globals["dict"] = dict

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = init(seed=settings.demo_seed_enabled)
    ctms.ensure_schema(conn)
    _migrate_legacy_users(conn)
    conn.close()
    yield
    close_pool()

app = FastAPI(title="AI-Powered CTMS", description="Role-based clinical trial management. Synthetic data only.", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

def _migrate_legacy_users(conn: Connection) -> None:
    """Normalize legacy demo identities to the five approved primary roles."""
    aliases = {
        "principal_investigator": "investigator", "study_coordinator": "investigator", "monitor": "investigator",
        "pharmacovigilance": "safety_officer", "ethics_committee": "leadership",
        "administration": "leadership", "regulator": "leadership",
    }
    for before, after in aliases.items():
        conn.execute("UPDATE users SET role=? WHERE role=?", (after, before))
    # A synthetic participant account makes the approved Volunteer journey demonstrable.
    if not conn.execute("SELECT 1 FROM users WHERE role='volunteer' LIMIT 1").fetchone():
        password_hash, salt = auth.hash_password("CtmsVolunteer#01")
        conn.execute("INSERT INTO users (id,username,password_hash,salt,role,display_name,pi_name,active,created_at) VALUES (?,?,?,?,?,?,?,1,?)", ("USR-VOLUNTEER-DEMO", "volunteer.demo", password_hash, salt, "volunteer", "Participant (Demo)", None, utcnow().isoformat()))
    # The demo volunteer must also be LINKED to a participant record — without a
    # participant_user_access row the Volunteer portal can only ever show its
    # unlinked empty state, and the journey demonstrates nothing.
    vol = conn.execute("SELECT id FROM users WHERE username='volunteer.demo'").fetchone()
    if vol and not conn.execute("SELECT 1 FROM participant_user_access WHERE user_id=?", (vol["id"],)).fetchone():
        participant = conn.execute("SELECT id FROM participants ORDER BY id LIMIT 1").fetchone()
        if participant:
            conn.execute("INSERT INTO participant_user_access (user_id, participant_id) VALUES (?,?)", (vol["id"], participant["id"]))
    conn.commit()

_PUBLIC = {"/", "/about", "/login", "/health", "/robots.txt"}

@app.middleware("http")
async def session_gate(request: Request, call_next):
    if request.url.path.startswith("/static/"):
        return await call_next(request)
    gen = get_db()
    conn = next(gen)
    try:
        user = auth.get_session_user(conn, request.cookies.get(auth.SESSION_COOKIE))
    finally:
        next(gen, None)
    request.state.user = user
    if request.url.path in _PUBLIC:
        return await call_next(request)
    if not user:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required."}, 401)
        return RedirectResponse("/login?next=" + request.url.path, 303)
    return await call_next(request)

def current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not user: raise HTTPException(401, "Authentication required.")
    return user

def audit_session_ref(request: Request) -> str | None:
    return auth.session_reference(request.cookies.get(auth.SESSION_COOKIE))

def require(*roles: UserRole):
    def gate(user: User = Depends(current_user)):
        if user.role not in roles: raise HTTPException(403, "Your role is not authorised for this CTMS action.")
        return user
    return gate

def own_participant(db: Connection, user: User):
    row = db.execute("""SELECT p.* FROM participants p JOIN participant_user_access a ON a.participant_id=p.id
                      WHERE a.user_id=?""", (user.id,)).fetchone()
    return row

def _workspace_name_for(path: str, user: User | None = None) -> str:
    if path.startswith("/portal/"):
        return f"{user.role.value.replace('_', ' ').title()} Dashboard" if user else "CTMS Portal"
    if path.startswith("/escalations"):
        return "Escalations"
    if path.startswith("/trial"):
        return "Trial Workspace"
    if path.startswith("/ae"):
        return "Adverse Events"
    if path == "/alerts":
        return "Operational Alerts"
    if path == "/signals":
        return "Safety Signals"
    if path == "/audit":
        return "Audit Trail"
    if path == "/search":
        return "Global Search"
    if path == "/docs":
        return "Documentation"
    return settings.app_name

def page(request: Request, name: str, db: Connection | None = None, **context):
    token = prepare_csrf(request)
    user = getattr(request.state, "user", None)
    workspace_name = context.pop("workspace_name", None) or _workspace_name_for(request.url.path, user)
    as_of = context.pop("as_of", None) or utcnow()
    response = templates.TemplateResponse(request=request, name=name, context={
        "settings": settings, "csrf_token": token, "current_user": user,
        "workspace_name": workspace_name, "as_of": as_of, **context})
    set_csrf_cookie(response, token)
    return response

def safe_date(value: str) -> str:
    try: return date.fromisoformat(value).isoformat()
    except ValueError: raise HTTPException(400, "Date must use YYYY-MM-DD.")

def label(v: str | None) -> str:
    if not v: return "—"
    return str(v).replace("_", " ").title()

def _fmt_dt(value: str | datetime | None, fmt: str = "%d %b %Y %H:%M") -> str:
    if not value: return "—"
    if isinstance(value, datetime): return value.strftime(fmt)
    try:
        return datetime.fromisoformat(value).strftime(fmt)
    except (ValueError, TypeError):
        return str(value)

templates.env.filters["label"] = label
templates.env.filters["dt"] = lambda v: _fmt_dt(v, "%d %b %Y %H:%M")
templates.env.filters["d"] = lambda v: _fmt_dt(v, "%d %b %Y")
templates.env.filters["fromjson"] = lambda v: json.loads(v or "[]")

# ------------------------------------------------------------------ queue specs
# Phase 4 (prompt.md §10.2): one declared spec per queue surface. Search stays
# scoped to identifiers — never clinical narrative — and a param outside these
# allowlists falls back silently rather than reaching a row comparison. The
# trial filter's options are supplied per request (dynamic_options in the
# toolbar), because the trial set is data, not vocabulary.

def _trial_filter() -> queues.FilterSpec:
    return queues.FilterSpec(param="trial", label="Trial", key="trial_id")

_AE_CLOCK_RANK = {"breached": 0, "due_soon": 1, "on_track": 2, "not_applicable": 3}

AE_SPEC = queues.QueueSpec(
    name="ae",
    search_keys=("id", "participant_code", "coded_term", "trial_id"),
    search_label="Case ID, participant code, coded term or trial ID",
    filters=(
        queues.FilterSpec(param="clock", label="Clock", key="timeline_status", options=(
            ("breached", "Breached"), ("due_soon", "Due soon"),
            ("on_track", "On track"), ("not_applicable", "No statutory clock"))),
        queues.FilterSpec(param="serious", label="Seriousness", key="serious", options=(
            ("1", "Serious"), ("0", "Non-serious"))),
        queues.FilterSpec(param="severity", label="Severity", key="severity", options=(
            ("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe"))),
        queues.FilterSpec(param="coding", label="Coding", options=(
            ("coded", "Coded"), ("uncoded", "Uncoded")),
            match=lambda r, v: (r.get("coded_term") is not None) == (v == "coded")),
        _trial_filter(),
    ),
    sorts=(
        queues.SortSpec(param="urgency", label="Clock urgency", key=lambda r: (
            _AE_CLOCK_RANK.get(r["timeline_status"], 4),
            r["hours_left"] is None, r["hours_left"] or 0.0, r["id"])),
        queues.SortSpec(param="reported", label="Recently reported", desc=True,
                        key=lambda r: (r["reported_at"], r["id"])),
        queues.SortSpec(param="onset", label="Onset date", desc=True,
                        key=lambda r: (r["onset_date"], r["id"])),
        queues.SortSpec(param="participant", label="Participant code",
                        key=lambda r: (r["participant_code"], r["id"])),
    ),
    default_sort="urgency",
)

SIGNAL_SPEC = queues.QueueSpec(
    name="signals",
    search_keys=("trial_id", "coded_term", "coded_code"),
    search_label="Trial ID, coded term or code",
    filters=(
        queues.FilterSpec(param="flagged", label="Threshold", key="flagged", options=(
            ("1", "Meets threshold"), ("0", "Below threshold"))),
        queues.FilterSpec(param="serious", label="Serious cases", options=(
            ("1", "Has serious cases"), ("0", "No serious cases")),
            match=lambda r, v: (r.get("serious", 0) > 0) == (v == "1")),
        _trial_filter(),
    ),
    sorts=(
        queues.SortSpec(param="strength", label="Signal strength", key=lambda r: (
            not r["flagged"], r["prr"] is not None, -(r["prr"] or 0.0),
            -r["cases"], r["coded_term"])),
        queues.SortSpec(param="cases", label="Case count", desc=True,
                        key=lambda r: (r["cases"], r["serious"], r["coded_term"])),
        queues.SortSpec(param="trial", label="Trial",
                        key=lambda r: (r["trial_id"], r["coded_term"])),
        queues.SortSpec(param="term", label="Term A–Z",
                        key=lambda r: (r["coded_term"].lower(), r["trial_id"])),
    ),
    default_sort="strength",
)

_ESC_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

ESCALATION_SPEC = queues.QueueSpec(
    name="escalations",
    search_keys=("id", "trial_id", "raised_by"),
    search_label="Escalation ID, trial ID or raiser",
    filters=(
        queues.FilterSpec(param="status", label="Status", key="status", options=(
            ("open", "Open"), ("company_responded", "Company responded"),
            ("under_leadership_review", "Under leadership review"),
            ("resolved", "Resolved"), ("closed", "Closed"))),
        queues.FilterSpec(param="type", label="Type", key="escalation_type", options=(
            ("protocol_deviation", "Protocol deviation"),
            ("safety_concern", "Safety concern"))),
        queues.FilterSpec(param="severity", label="Severity", key="severity", options=(
            ("critical", "Critical"), ("high", "High"),
            ("medium", "Medium"), ("low", "Low"))),
        _trial_filter(),
    ),
    sorts=(
        # Single-key on purpose: Python's sort is stable, so equal severities
        # keep list_escalations' input order (recently raised first).
        queues.SortSpec(param="urgency", label="Most urgent",
                        key=lambda r: _ESC_SEV_RANK.get(r["severity"], 4)),
        queues.SortSpec(param="raised", label="Recently raised", desc=True,
                        key=lambda r: (r["created_at"], r["id"])),
        queues.SortSpec(param="deadline", label="Response deadline", key=lambda r: (
            r["deadline"] is None, r["deadline"] or "", r["id"])),
        queues.SortSpec(param="status", label="Status",
                        key=lambda r: (r["status"], r["created_at"])),
    ),
    default_sort="urgency",
)

ALERT_SPEC = queues.QueueSpec(
    name="alerts",
    search_keys=("id", "trial_id", "trial_title"),
    search_label="Alert ID or trial",
    filters=(
        queues.FilterSpec(param="severity", label="Severity", key="severity", options=(
            ("critical", "Critical"), ("warning", "Warning"), ("info", "Info"))),
        queues.FilterSpec(param="rule", label="Rule", key="rule", options=(
            ("sae_timeline_breach", "SAE timeline breach"),
            ("enrolment_lag", "Enrolment lag"),
            ("ethics_renewal_due", "Ethics renewal due"),
            ("monitoring_visit_overdue", "Monitoring visit overdue"))),
        _trial_filter(),
    ),
    sorts=(
        queues.SortSpec(param="severity", label="Most severe", key=lambda r: (
            {"critical": 0, "warning": 1, "info": 2}.get(r["severity"], 3),
            r["trial_id"], r["rule"])),
        queues.SortSpec(param="trial", label="Trial",
                        key=lambda r: (r["trial_id"], r["rule"])),
        queues.SortSpec(param="rule", label="Rule",
                        key=lambda r: (r["rule"], r["trial_id"])),
    ),
    default_sort="severity",
)


def _trial_options(rows) -> tuple[tuple[str, str], ...]:
    """(value, label) pairs for a queue's trial filter, from trial table rows."""
    return tuple((t["id"], f"{t['id']} — {t['title']}") for t in rows)


def _milestone_geometry(rows, today: date):
    """Planned vs actual positions for the milestone timeline (§10.3).

    Every percentage is computed from stored dates on one shared scale that
    always includes today — the reference the plan is measured against. A
    milestone with no actual date draws a planned mark only; nothing is
    extrapolated, and no progress curve is fabricated from a single count.
    """
    parsed = []
    for m in rows:
        try:
            planned = date.fromisoformat(m["planned_date"])
        except (TypeError, ValueError):
            continue  # an unparseable plan is skipped, never drawn at a guessed spot
        actual = None
        if m["actual_date"]:
            try:
                actual = date.fromisoformat(m["actual_date"])
            except (TypeError, ValueError):
                actual = None
        parsed.append((m, planned, actual))
    if not parsed:
        return [], None
    lo = min([p for _, p, _ in parsed] + [a for _, _, a in parsed if a] + [today])
    hi = max([p for _, p, _ in parsed] + [a for _, _, a in parsed if a] + [today])
    span = max((hi - lo).days, 1)

    def pct(d: date) -> float:
        return round(100 * (d - lo).days / span, 1)

    items = []
    for m, planned, actual in parsed:
        late = bool(actual and actual > planned)
        items.append({
            "type": m["type"], "status": m["status"],
            "planned": planned.isoformat(), "actual": actual.isoformat() if actual else None,
            "planned_pct": pct(planned),
            "actual_pct": pct(actual) if actual else None,
            "late": late,
            "slip_days": (actual - planned).days if actual else None,
            "slip_from": pct(planned) if late else None,
            "slip_to": pct(actual) if late else None,
        })
    return items, pct(today)

# ------------------------------------------------------------------ public & auth routes
@app.get("/health")
def health():
    return {"status": "ok", "backend": backend(), "time": utcnow().isoformat()}

@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"

@app.get("/about")
def about():
    return RedirectResponse("/#about", 303)

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Connection = Depends(get_db)):
    user = getattr(request.state, "user", None)
    if user:
        return RedirectResponse(f"/portal/{user.role.value}", 303)
    return page(request, "landing.html", db=db)

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", error: str | None = None):
    # `error` arrives as a query param from the POST handler's failure redirect;
    # it must be declared and forwarded or the template's error block never renders.
    return page(request, "login.html", next=next, error=error)

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"), db: Connection = Depends(get_db), _: None = Depends(verify_csrf)):
    user = auth.authenticate(db, username.strip(), password)
    if not user: return RedirectResponse("/login?error=Invalid+username+or+password", 303)
    token = auth.create_session(db, user.id)
    destination = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(destination, 303)
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=settings.session_ttl_hours*3600, httponly=True, secure=not settings.demo_allow_http, samesite="strict", path="/")
    return response

@app.post("/logout")
def logout(request: Request, db: Connection = Depends(get_db), _: None = Depends(verify_csrf)):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token: auth.revoke_session(db, token)
    response = RedirectResponse("/login", 303)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response

# -------------------------------------------------------------------- role dashboards
@app.get("/portal/volunteer", response_class=HTMLResponse)
def volunteer_dashboard(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.VOLUNTEER))):
    participant = own_participant(db, user)
    trial = db.execute("SELECT * FROM trials WHERE id=?", (participant["trial_id"],)).fetchone() if participant else None
    appointments = db.execute("SELECT * FROM appointments WHERE participant_id=? AND status IN ('scheduled','rescheduled') ORDER BY scheduled_at", (participant['id'],)).fetchall() if participant else []
    reports = db.execute("SELECT * FROM adverse_events WHERE participant_code=? ORDER BY reported_at DESC", (participant['participant_code'],)).fetchall() if participant else []
    consent = db.execute("""SELECT cf.version_no AS version, cr.decision AS status, cr.decided_at AS date FROM consent_records cr JOIN consent_forms cf ON cf.id=cr.consent_form_id WHERE cr.volunteer_user_id=? ORDER BY cr.decided_at DESC LIMIT 1""", (user.id,)).fetchone()
    history = db.execute("""SELECT cf.version_no AS version, cr.decision AS status, cr.decided_at AS date, 'Volunteer' AS actor FROM consent_records cr JOIN consent_forms cf ON cf.id=cr.consent_form_id WHERE cr.volunteer_user_id=? ORDER BY cr.decided_at DESC""", (user.id,)).fetchall()
    published_consent = db.execute("SELECT id, version_no, content, published_at FROM consent_forms WHERE trial_id=? AND status='published' ORDER BY version_no DESC LIMIT 1", (participant['trial_id'],)).fetchone() if participant else None
    return page(request, "portal/volunteer_dashboard.html", db=db, participant=participant, my_trial=trial, appointments=appointments, my_reports=reports, consent=consent, consent_history=history, published_consent=published_consent)

@app.get("/portal/volunteer/register", response_class=HTMLResponse)
def volunteer_register_form(request: Request, trial_id: str | None = None, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.VOLUNTEER))):
    trials = db.execute("SELECT * FROM trials WHERE status IN ('enrolling','screening') ORDER BY id").fetchall()
    tid = trial_id or (trials[0]["id"] if trials else None)
    form_def = db.execute("SELECT * FROM registration_forms WHERE trial_id=? AND status='published' ORDER BY version_no DESC LIMIT 1", (tid,)).fetchone() if tid else None
    return page(request, "portal/simple_form.html", db=db, action_title="Register for a Clinical Trial", post_url="/portal/volunteer/register", trials=trials, selected_trial=tid, form_def=form_def)

@app.post("/portal/volunteer/register")
def volunteer_register(request: Request, trial_id: str = Form(...), answers_json: str = Form("{}"), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.VOLUNTEER)), _: None = Depends(verify_csrf)):
    try:
        answers = json.loads(answers_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Registration information must be valid JSON.")
    ctms.submit_registration(db, actor=user.username, role=user.role.value, user_id=user.id, trial_id=trial_id, answers=answers, session_ref=audit_session_ref(request))
    return RedirectResponse("/portal/volunteer", 303)

@app.post("/portal/volunteer/consent")
def volunteer_consent(request: Request, decision: str = Form(...), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.VOLUNTEER)), _: None = Depends(verify_csrf)):
    participant = own_participant(db, user)
    if not participant: raise HTTPException(409, "Consent becomes available after an authorized participant record is linked.")
    try: ctms.record_consent(db, actor=user.username, role=user.role.value, volunteer_user_id=user.id, trial_id=participant['trial_id'], decision=decision, session_ref=audit_session_ref(request))
    except ValueError as e: raise HTTPException(400, str(e))
    return RedirectResponse("/portal/volunteer", 303)

@app.post("/portal/volunteer/reports")
def volunteer_report(request: Request, narrative: str = Form(...), onset_date: str = Form(...), serious: bool = Form(False), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.VOLUNTEER)), _: None = Depends(verify_csrf)):
    participant = own_participant(db, user)
    if not participant: raise HTTPException(409, "No participant record is linked to this account.")
    ctms.report_ae(db, actor=user.username, role=user.role.value, trial_id=participant['trial_id'], participant_code=participant['participant_code'], narrative=narrative, onset_date=safe_date(onset_date), serious=serious, session_ref=audit_session_ref(request))
    return RedirectResponse("/portal/volunteer", 303)

@app.get("/portal/company", response_class=HTMLResponse)
def company_dashboard(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY))):
    now = utcnow()
    all_esc = governance.list_escalations(db)

    # The queue that defines this role: escalations whose statutory response
    # clock is still open, with the live deadline and hours remaining derived
    # from the clock row — never from a stored snapshot (same discipline as
    # pv.with_live_status for AE clocks).
    awaiting = []
    for e in all_esc:
        if e["status"] != "open":
            continue
        row = dict(e)
        clock = db.execute(
            "SELECT * FROM statutory_clocks WHERE escalation_id=? ORDER BY started_at DESC LIMIT 1",
            (e["id"],)).fetchone()
        progress = governance.clock_progress(clock, now)
        row["deadline"] = clock["deadline"] if clock else None
        row["hours_left"] = progress["hours_left"]
        awaiting.append(row)

    open_issues = [e for e in all_esc if e["status"] not in ("closed", "resolved")]

    # Per-trial operational counts, derived on read (§6.5) — nothing cached.
    trials_view = []
    for t in db.execute("SELECT * FROM trials ORDER BY id").fetchall():
        row = dict(t)
        row["pending_registrations"] = db.execute(
            "SELECT COUNT(*) FROM registration_submissions WHERE trial_id=? AND status NOT IN ('eligible','not_eligible')",
            (t["id"],)).fetchone()[0]
        row["upcoming_appointments"] = db.execute(
            "SELECT COUNT(*) FROM appointments WHERE trial_id=? AND status IN ('scheduled','rescheduled')",
            (t["id"],)).fetchone()[0]
        row["open_issues"] = sum(1 for e in open_issues if e["trial_id"] == t["id"])
        trials_view.append(row)

    # Corrective-action plans the company has filed that are still in the
    # review loop (response submitted; reviewer or leadership yet to finish).
    corrective = db.execute(
        """SELECT ca.escalation_id, ca.trial_id, ca.expected_resolution,
                  ca.responsible_person, ca.submitted_at
             FROM corrective_actions ca JOIN escalations e ON e.id = ca.escalation_id
            WHERE e.status IN ('company_responded','under_leadership_review')
            ORDER BY ca.submitted_at DESC""").fetchall()

    return page(request, "portal/company_dashboard.html", db=db,
                trials=trials_view, awaiting_response=awaiting, open_issues=open_issues,
                open_corrective_actions=corrective, history_escalations=all_esc)

@app.get("/portal/company/operations", response_class=HTMLResponse)
def company_operations(request: Request, trial: str | None = None, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY))):
    trials = db.execute("SELECT * FROM trials ORDER BY id").fetchall()
    tid = trial or (trials[0]["id"] if trials else None)
    t = db.execute("SELECT * FROM trials WHERE id=?", (tid,)).fetchone() if tid else None
    c_forms = db.execute("SELECT * FROM consent_forms WHERE trial_id=? ORDER BY version_no DESC", (tid,)).fetchall() if tid else []
    r_form = db.execute("SELECT * FROM registration_forms WHERE trial_id=? AND status='published' ORDER BY version_no DESC LIMIT 1", (tid,)).fetchone() if tid else None
    reg_form = None
    if r_form:
        reg_form = dict(r_form)
        try:
            reg_form["fields"] = json.loads(reg_form.get("fields_json") or "[]")
        except json.JSONDecodeError:
            reg_form["fields"] = []
    criteria = db.execute("SELECT * FROM eligibility_criteria WHERE trial_id=? ORDER BY criterion_type, id", (tid,)).fetchall() if tid else []
    appts = db.execute("""SELECT a.*, p.participant_code, a.title AS visit_name, a.scheduled_at AS scheduled_date FROM appointments a JOIN participants p ON p.id=a.participant_id WHERE a.trial_id=? ORDER BY a.scheduled_at""", (tid,)).fetchall() if tid else []
    subs = db.execute("SELECT * FROM registration_submissions WHERE trial_id=? ORDER BY submitted_at DESC", (tid,)).fetchall() if tid else []
    issues = [e for e in governance.list_escalations(db, trial_id=tid) if e["status"] not in ("closed", "resolved")] if tid else []
    return page(request, "portal/company_operations.html", db=db, trials=trials, trial=t, selected_trial=tid,
                consent_forms=c_forms, registration_form=reg_form, criteria=criteria,
                appointments_queue=appts, submissions_queue=subs, issue_queue=issues)

@app.post("/portal/company/criteria")
def company_criteria(request: Request, trial_id: str = Form(...), criterion_type: str = Form(...), text: str = Form(...), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY)), _: None = Depends(verify_csrf)):
    ctms.create_criterion(db, actor=user.username, role=user.role.value, trial_id=trial_id, text=text, criterion_type=criterion_type, session_ref=audit_session_ref(request))
    return RedirectResponse(f"/portal/company/operations?trial={trial_id}", 303)

@app.post("/portal/company/forms/registration")
def company_reg_form(request: Request, trial_id: str = Form(...), fields_json: str = Form("[]"), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY)), _: None = Depends(verify_csrf)):
    try:
        json.loads(fields_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Registration form fields must be JSON.")
    ctms.publish_registration_form(db, actor=user.username, role=user.role.value, trial_id=trial_id, fields_json=fields_json, session_ref=audit_session_ref(request))
    return RedirectResponse(f"/portal/company/operations?trial={trial_id}", 303)

@app.post("/portal/company/forms/consent")
def company_consent_form(request: Request, trial_id: str = Form(...), content: str = Form(...), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY)), _: None = Depends(verify_csrf)):
    ctms.publish_consent_form(db, actor=user.username, role=user.role.value, trial_id=trial_id, content=content, session_ref=audit_session_ref(request))
    return RedirectResponse(f"/portal/company/operations?trial={trial_id}", 303)

@app.post("/portal/company/appointments")
def company_appointment(request: Request, trial_id: str = Form(...), participant_code: str = Form(...), title: str = Form(...), scheduled_at: str = Form(...), details: str = Form(""), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY)), _: None = Depends(verify_csrf)):
    participant = db.execute("SELECT * FROM participants WHERE trial_id=? AND participant_code=?", (trial_id, participant_code)).fetchone()
    if not participant:
        raise HTTPException(404, "Participant not found on this trial.")
    appointment_id = f"APT-{utcnow().strftime('%Y%m%d%H%M%S')}"
    now = utcnow().isoformat()
    db.execute("INSERT INTO appointments (id,trial_id,participant_id,title,scheduled_at,details,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,'scheduled',?,?,?)", (appointment_id, trial_id, participant['id'], title, scheduled_at, details, user.username, now, now))
    audit.record(db, actor=user.username, role=user.role.value, session_ref=audit_session_ref(request), action='create', resource_type='appointment', resource_id=appointment_id, after={'trial_id': trial_id, 'participant_code': participant_code, 'scheduled_at': scheduled_at}, reason='Company scheduled appointment')
    return RedirectResponse(f"/portal/company/operations?trial={trial_id}", 303)

@app.get("/portal/investigator", response_class=HTMLResponse)
def investigator_dashboard(request: Request, trial: str | None = None, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.INVESTIGATOR))):
    trials = db.execute("SELECT * FROM trials ORDER BY id").fetchall()
    tid = trial or (trials[0]["id"] if trials else None)
    t = db.execute("SELECT * FROM trials WHERE id=?", (tid,)).fetchone() if tid else None
    k = kpi.trial_kpi(db, tid) if tid else None
    # §9.3 (Investigator): the queue is ordered by how long each submission has
    # waited — the AI pre-screen finding rides alongside (advisory, versioned),
    # never as the decision itself.
    submissions = db.execute(
        """SELECT s.*, a.finding AS ai_finding, a.explanation AS ai_explanation,
                  a.engine_version AS ai_engine, a.confidence AS ai_confidence
             FROM registration_submissions s
             LEFT JOIN ai_findings a ON a.id = s.ai_finding_id
            WHERE s.trial_id = ?
            ORDER BY s.submitted_at ASC""", (tid,)).fetchall() if tid else []
    deviations = db.execute("SELECT * FROM deviations WHERE trial_id=? ORDER BY detected_date DESC", (tid,)).fetchall() if tid else []
    escalations = [e for e in governance.list_escalations(db) if e["trial_id"] == tid]
    return page(request, "portal/investigator_dashboard.html", db=db, trials=trials, selected_trial=tid, t=t, k=k, submissions=submissions, deviations=deviations, escalations=escalations)

@app.post("/portal/investigator/eligibility/{submission_id}")
def investigator_eligibility(request: Request, submission_id: str, decision: str = Form(...), reason: str = Form(...), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.INVESTIGATOR)), _: None = Depends(verify_csrf)):
    ctms.decide_eligibility(db, actor=user.username, role=user.role.value, investigator_id=user.id, submission_id=submission_id, decision=decision, reason=reason, session_ref=audit_session_ref(request))
    sub = db.execute("SELECT trial_id FROM registration_submissions WHERE id=?", (submission_id,)).fetchone()
    return RedirectResponse(f"/portal/investigator?trial={sub['trial_id'] if sub else ''}", 303)

@app.get("/portal/safety_officer", response_class=HTMLResponse)
def safety_dashboard(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.SAFETY_OFFICER))):
    now = utcnow()
    # §9.3 (Safety Officer): statutory-clock urgency is the dashboard's primary
    # sort key — a serious event with hours left on its 24-hour clock outranks
    # an uncoded mild event regardless of intake order. The suggestion columns
    # come from ae_codes (the AI's reviewable suggestion), never from the AE
    # row itself: coded_term stays NULL until a human confirms coding.
    uncoded = [pv.with_live_status(e, now) for e in db.execute(
        """SELECT e.*, c.suggested_term, c.suggested_code, c.suggestion_confidence,
                  c.engine_version AS suggestion_engine
             FROM adverse_events e
             LEFT JOIN ae_codes c ON c.adverse_event_id = e.id
            WHERE e.coded_term IS NULL
            ORDER BY e.reported_at DESC""").fetchall()]
    _CLOCK_RANK = {"breached": 0, "due_soon": 1, "on_track": 2}
    uncoded.sort(key=lambda e: (
        _CLOCK_RANK.get(e["timeline_status"], 3),
        e["hours_left"] is None,
        e["hours_left"] if e["hours_left"] is not None else 0.0,
    ))
    coded = [pv.with_live_status(e, now) for e in db.execute(
        "SELECT * FROM adverse_events WHERE coded_term IS NOT NULL ORDER BY reported_at DESC LIMIT 50").fetchall()]
    found = signals.detect(db)
    flagged = [s for s in found if s.flagged]
    escalations = [e for e in governance.list_escalations(db) if e["escalation_type"] == "safety_concern"]
    return page(request, "portal/safety_dashboard.html", db=db,
                uncoded_events=uncoded, coded_events=coded, clocks=pv.clock_counts(db, now),
                signals=found, flagged_signals=flagged, escalations=escalations, terms=pv.load_terms())

@app.post("/portal/safety_officer/ae/{adverse_event_id}/code")
def safety_code(request: Request, adverse_event_id: str, decision: str = Form(...), final_term: str = Form(""), final_code: str = Form(""), next: str = Form(""), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.SAFETY_OFFICER)), _: None = Depends(verify_csrf)):
    ctms.review_ae_code(db, actor=user.username, role=user.role.value, adverse_event_id=adverse_event_id, decision=decision, final_term=final_term or None, final_code=final_code or None, session_ref=audit_session_ref(request))
    # `next` returns the reviewer to the case page they were working on; only
    # safe internal paths are honoured, same rule as login's.
    destination = next if next.startswith("/") and not next.startswith("//") else "/portal/safety_officer"
    return RedirectResponse(destination, 303)

@app.get("/portal/leadership", response_class=HTMLResponse)
def leadership_dashboard(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.LEADERSHIP))):
    portfolio = kpi.portfolio_kpi(db)
    pending = [e for e in governance.list_escalations(db) if e["status"] == "under_leadership_review"]
    recent = [e for e in governance.list_escalations(db) if e["leadership_decision"]][:10]
    audit_head = audit.verify(db)
    return page(request, "portal/leadership_dashboard.html", db=db, portfolio=portfolio, pending_decisions=pending, recent_decisions=recent, audit_head=audit_head)

@app.get("/search", response_class=HTMLResponse)
def global_search(request: Request, q: str = "", db: Connection = Depends(get_db), user: User = Depends(require(UserRole.LEADERSHIP))):
    like = f"%{q.strip()}%"
    trials = db.execute("SELECT * FROM trials WHERE id LIKE ? OR title LIKE ?", (like, like)).fetchall() if q else []
    aes = db.execute("SELECT * FROM adverse_events WHERE id LIKE ? OR participant_code LIKE ? OR narrative LIKE ?", (like, like, like)).fetchall() if q else []
    escalations = db.execute("SELECT * FROM escalations WHERE id LIKE ? OR reason LIKE ? OR severity LIKE ? OR status LIKE ?", (like, like, like, like)).fetchall() if q else []
    return page(request, "portal/global_search.html", db=db, q=q, trials=trials, aes=aes, escalations=escalations)

# -------------------------------------------------------------------------- trials, AE, PRR
# Phase 4 (prompt.md §10.3): the trial page is a workspace, not a report — a
# persistent context header (identity, the four status dimensions, as-of time,
# the primary next action) and focused subviews reached by real, shareable
# URLs (`?view=`). Each subview is a section of one entity, which is the only
# legitimate use of tabs; nothing here is a lens or a fake hierarchy.
TRIAL_VIEWS = (
    "overview", "enrolment", "sites", "safety",
    "deviations", "queries", "milestones", "activity",
)

@app.get("/trial/{trial_id}", response_class=HTMLResponse)
def trial_detail(trial_id: str, request: Request, view: str = "overview", db: Connection = Depends(get_db), user: User = Depends(current_user)):
    trial = db.execute("SELECT * FROM trials WHERE id=?", (trial_id,)).fetchone()
    if not trial: raise HTTPException(404, "Trial not found")
    if user.role is UserRole.VOLUNTEER:
        p = own_participant(db, user)
        if not p or p['trial_id'] != trial_id: raise HTTPException(403, "Participants can view only their authorised trial.")
    if view not in TRIAL_VIEWS:
        view = "overview"  # an unknown subview name falls back, never 500s

    k = kpi.trial_kpi(db, trial_id)
    today = utcnow().date()

    sites = db.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM participants p
                          WHERE p.trial_id=? AND p.site_id=s.id) AS enrolled_here
             FROM sites s JOIN trial_sites ts ON ts.site_id = s.id
            WHERE ts.trial_id=? ORDER BY s.id""", (trial_id, trial_id)).fetchall()
    milestone_rows = db.execute(
        "SELECT * FROM milestones WHERE trial_id=? ORDER BY planned_date", (trial_id,)).fetchall()
    milestones, today_pct = _milestone_geometry(milestone_rows, today)
    deviations = db.execute("SELECT * FROM deviations WHERE trial_id=? ORDER BY detected_date DESC", (trial_id,)).fetchall()
    queries = db.execute("SELECT * FROM queries WHERE trial_id=? ORDER BY raised_date DESC", (trial_id,)).fetchall()
    participants = db.execute(
        "SELECT * FROM participants WHERE trial_id=? ORDER BY screened_date", (trial_id,)).fetchall()
    aes = [pv.with_live_status(e, utcnow()) for e in db.execute(
        "SELECT * FROM adverse_events WHERE trial_id=? ORDER BY reported_at DESC", (trial_id,)).fetchall()]
    trial_signals = [s for s in signals.detect(db) if s.trial_id == trial_id]
    escalations = governance.list_escalations(db, trial_id=trial_id)

    # Activity: audit rows for the trial itself and the records that belong to
    # it. The audit trail keys on resource_id, so "trial activity" is composed
    # honestly from the ids of its constituents rather than pretended to be a
    # stored view.
    related = {trial_id} | {e["id"] for e in aes} | {e["id"] for e in escalations}
    marks = ",".join("?" * len(related))
    activity = db.execute(
        f"""SELECT seq, actor, action, resource_type, resource_id, reason, timestamp_utc
              FROM audit_events WHERE resource_id IN ({marks})
             ORDER BY seq DESC LIMIT 30""", tuple(sorted(related))).fetchall()

    # The header's primary next action is derived, never written by hand: an
    # open serious event outranks an unreported major deviation, which outranks
    # the next milestone. Calm is a state too, and it says so.
    unreported_major = [d for d in deviations if not d["reported_to_ec"] and d["severity"] in ("major", "critical")]
    if k and k.open_saes:
        next_action = {"tone": "bad", "label": f"Review {k.open_saes} open serious event{'s' if k.open_saes != 1 else ''}", "href": f"/trial/{trial_id}?view=safety"}
    elif unreported_major:
        next_action = {"tone": "bad", "label": f"{len(unreported_major)} reportable deviation{'s' if len(unreported_major) != 1 else ''} not yet reported to EC", "href": f"/trial/{trial_id}?view=deviations"}
    elif k and k.next_milestone:
        next_action = {"tone": "warn", "label": f"Next milestone: {label(k.next_milestone)} in {k.days_to_next_milestone} days", "href": f"/trial/{trial_id}?view=milestones"}
    else:
        next_action = {"tone": "calm", "label": "No urgent exceptions on this trial", "href": None}

    counts = {
        "enrolment": len(participants), "sites": len(sites), "safety": len(aes),
        "deviations": len(deviations),
        "queries": sum(1 for q in queries if q["status"] != "closed"),
        "milestones": len(milestones), "activity": len(activity),
    }
    return page(request, "trial.html", db=db, trial=trial, k=k, view=view, counts=counts,
                sites=sites, milestones=milestones, today_pct=today_pct,
                deviations=deviations, queries=queries, participants=participants,
                aes=aes, trial_signals=trial_signals, escalations=escalations,
                activity=activity, unreported_major=unreported_major,
                next_action=next_action)


@app.get("/alerts", response_class=HTMLResponse)
def operational_alerts(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY, UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER, UserRole.LEADERSHIP))):
    """Portfolio alerts as a real queue (§10.2). Alerts are computed on read by
    alerts.evaluate — never stored — so a filter cannot resurrect a stale one."""
    found = alerts.evaluate(db)
    rows = [
        {"id": a.id, "rule": a.rule.value, "severity": a.severity.value,
         "trial_id": a.trial_id, "trial_title": a.trial_title,
         "message": a.message, "raised_at": a.raised_at.isoformat(),
         "deep_link": a.deep_link}
        for a in found
    ]
    result = queues.apply(rows, ALERT_SPEC, request.query_params)
    trial_rows = db.execute("SELECT id, title FROM trials ORDER BY id").fetchall()
    return page(request, "alerts.html", db=db, result=result, spec=ALERT_SPEC,
                dynamic_options={"trial": _trial_options(trial_rows)})


@app.get("/ae", response_class=HTMLResponse)
def adverse_events(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.SAFETY_OFFICER, UserRole.INVESTIGATOR))):
    """The AE register as a worklist (§10.2): filter/search/sort/paginate via
    AE_SPEC, rows inspect in place, the full record is one click deeper.
    Open to the two roles that hold FILE_ADVERSE_EVENT (auth.py) — the Safety
    Officer codes and the Investigator files at site; the nav advertises it to
    both, and the route, not the nav, is the boundary."""
    events = [pv.with_live_status(e, utcnow()) for e in db.execute("SELECT * FROM adverse_events ORDER BY reported_at DESC").fetchall()]
    result = queues.apply(events, AE_SPEC, request.query_params)
    trial_rows = db.execute("SELECT id, title FROM trials ORDER BY id").fetchall()
    return page(request, "ae.html", db=db, result=result, spec=AE_SPEC,
                trials=trial_rows, dynamic_options={"trial": _trial_options(trial_rows)},
                can_file=auth.has_permission(user, auth.Permission.FILE_ADVERSE_EVENT))

@app.post("/ae")
def adverse_event_file(request: Request, trial_id: str = Form(...), participant_code: str = Form(...),
                       onset_date: str = Form(...), narrative: str = Form(...),
                       severity: str = Form("moderate"), causality: str = Form("unknown"),
                       outcome: str = Form("unknown"), serious: bool = Form(False),
                       db: Connection = Depends(get_db),
                       user: User = Depends(auth.require_permission(auth.Permission.FILE_ADVERSE_EVENT)),
                       _: None = Depends(verify_csrf)):
    """Staff intake (§11.2). What is created, which clock begins, and what is
    still incomplete are explained on the case page the filer lands on — the
    event is not silently finalized: coding remains a Safety Officer decision."""
    try:
        new_id = ctms.report_ae(db, actor=user.username, role=user.role.value,
                                trial_id=trial_id, participant_code=participant_code,
                                narrative=narrative, onset_date=safe_date(onset_date),
                                serious=serious, severity=severity, causality=causality,
                                outcome=outcome, session_ref=audit_session_ref(request))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/ae/{new_id}?filed=1", 303)

@app.get("/ae/{adverse_event_id}", response_class=HTMLResponse)
def adverse_event_case(adverse_event_id: str, request: Request, filed: str | None = None, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.SAFETY_OFFICER, UserRole.INVESTIGATOR))):
    """The case record (§11.2): clinical fact, reporting obligation, workflow
    task and audit history kept visibly separate (§2). With the inspector's
    `X-Requested-With` header the same data renders as the queue's side-panel
    fragment — one template, one data assembly, two depths (§7.2)."""
    row = db.execute("SELECT * FROM adverse_events WHERE id=?", (adverse_event_id,)).fetchone()
    if not row: raise HTTPException(404, "Adverse event not found")
    event = pv.with_live_status(row, utcnow())
    coding = db.execute("SELECT * FROM ae_codes WHERE adverse_event_id=?", (adverse_event_id,)).fetchone()
    findings = db.execute(
        "SELECT * FROM ai_findings WHERE subject_type='adverse_event' AND subject_id=? ORDER BY created_at DESC",
        (adverse_event_id,)).fetchall()
    history = db.execute(
        "SELECT seq, actor, role, action, resource_type, reason, after_json, timestamp_utc FROM audit_events WHERE resource_id=? ORDER BY seq",
        (adverse_event_id,)).fetchall()
    trial = db.execute("SELECT id, title FROM trials WHERE id=?", (event["trial_id"],)).fetchone()
    context = dict(db=db, event=event, coding=coding, findings=findings, history=history,
                   trial=trial, filed=(filed == "1"),
                   can_review=(user.role is UserRole.SAFETY_OFFICER))
    if request.headers.get("x-requested-with") == "inspector":
        return page(request, "_ae_case.html", **context, fragment=True)
    return page(request, "ae_case.html", **context, fragment=False)

@app.get("/signals", response_class=HTMLResponse)
def prr_analysis(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.SAFETY_OFFICER))):
    found = signals.detect(db)
    rows = [dict(dataclasses.asdict(s), flagged=s.flagged) for s in found]
    result = queues.apply(rows, SIGNAL_SPEC, request.query_params)
    trial_rows = db.execute("SELECT id, title FROM trials ORDER BY id").fetchall()
    return page(request, "signals.html", db=db, result=result, spec=SIGNAL_SPEC,
                dynamic_options={"trial": _trial_options(trial_rows)},
                flagged=[s for s in found if s.flagged], min_cases=signals.MIN_CASES,
                case_floor=signals.MIN_CASES, threshold=signals.PRR_THRESHOLD,
                coded_total=db.execute("SELECT COUNT(*) FROM adverse_events WHERE coded_term IS NOT NULL").fetchone()[0],
                ae_total=db.execute("SELECT COUNT(*) FROM adverse_events").fetchone()[0],
                term_count=len(pv.load_terms()))

@app.get("/signals/{trial_id}/{term}", response_class=HTMLResponse)
def signal_detail(trial_id: str, term: str, request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.SAFETY_OFFICER))):
    """One trial/term pair as a reviewable signal workspace (§11.3): definition,
    denominators, the 2×2 the ratio comes from, caveats, the cases behind it,
    and the honest next step. 'Open investigation' is not a button to a deleted
    board — the investigation path of the current backend is the safety-concern
    escalation and its governance review package, and the page says so."""
    found = signals.detect(db)
    signal = next((s for s in found if s.trial_id == trial_id and s.coded_term == term), None)
    if signal is None:
        raise HTTPException(404, "No such trial/term signal — the set is re-derived on every read, so it may have dropped below the case floor.")
    trial = db.execute("SELECT * FROM trials WHERE id=?", (trial_id,)).fetchone()
    cases = [pv.with_live_status(e, utcnow()) for e in db.execute(
        "SELECT * FROM adverse_events WHERE trial_id=? AND coded_term=? ORDER BY reported_at DESC",
        (trial_id, term)).fetchall()]
    related_escalations = [e for e in governance.list_escalations(db, trial_id=trial_id)
                           if e["escalation_type"] == "safety_concern"]
    return page(request, "signal_detail.html", db=db, s=signal, trial=trial, cases=cases,
                related_escalations=related_escalations,
                can_raise=(user.role is UserRole.SAFETY_OFFICER),
                threshold=signals.PRR_THRESHOLD, case_floor=signals.MIN_CASES)

# ------------------------------------------------------------------------------- escalation
_RAISE = {UserRole.INVESTIGATOR: (EscalationType.PROTOCOL_DEVIATION, EscalationRaisedByRole.INVESTIGATOR), UserRole.SAFETY_OFFICER: (EscalationType.SAFETY_CONCERN, EscalationRaisedByRole.SAFETY_OFFICER)}

@app.get("/escalations", response_class=HTMLResponse)
def escalation_inbox(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY, UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER, UserRole.LEADERSHIP))):
    # The queue engine owns status/type/severity/trial filtering now — the old
    # ?status= chip row is superseded by allowlisted filters that survive a
    # refresh and combine (§10.2). The Company's scope cut stays server-side,
    # before the queue ever sees the rows.
    rows = governance.list_escalations(db)
    if user.role is UserRole.COMPANY: rows = [r for r in rows if r['status'] in ('open', 'company_responded', 'under_leadership_review')]
    result = queues.apply(rows, ESCALATION_SPEC, request.query_params)
    trial_rows = db.execute("SELECT id, title FROM trials ORDER BY id").fetchall()
    return page(request, "escalations.html", db=db, result=result, spec=ESCALATION_SPEC,
                trials={r['id']: r for r in trial_rows},
                dynamic_options={"trial": _trial_options(trial_rows)},
                can_raise=user.role in _RAISE, raise_types=[_RAISE[user.role][0].value] if user.role in _RAISE else [])

@app.get("/escalations/new", response_class=HTMLResponse)
def escalation_new(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER))):
    return page(request, "escalation_new.html", db=db, trials=db.execute("SELECT id,title FROM trials WHERE operational_status='active'").fetchall(), allowed_types=[_RAISE[user.role][0].value])

@app.post("/escalations")
def raise_escalation(request: Request, trial_id: str = Form(...), escalation_type: str = Form(...), severity: str = Form(...), reason: str = Form(...), recommended_action: str = Form(""), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER)), _: None = Depends(verify_csrf)):
    expected, raised = _RAISE[user.role]
    if escalation_type != expected.value: raise HTTPException(403, "This role may raise only its approved escalation type.")
    try: result = governance.raise_escalation(db, trial_id=trial_id, raised_by_role=raised.value, escalation_type=escalation_type, severity=severity, reason=reason, actor=user.username, actor_role=user.role.value, session_ref=audit_session_ref(request), recommended_action=recommended_action or None)
    except ValueError as e: raise HTTPException(400, str(e))
    return RedirectResponse(f"/escalations/{result['escalation']['id']}", 303)

@app.get("/escalations/{escalation_id}", response_class=HTMLResponse)
def escalation_detail(escalation_id: str, request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY, UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER, UserRole.LEADERSHIP))):
    package = governance.get(db, escalation_id)
    if not package: raise HTTPException(404, "Escalation not found")
    # The review package's own audit history (§11.4's "prove what happened"):
    # raise, response, review, decision — in sequence, with actor and reason.
    history = db.execute(
        "SELECT seq, actor, role, action, resource_type, reason, timestamp_utc FROM audit_events WHERE resource_id=? ORDER BY seq",
        (escalation_id,)).fetchall()
    now = utcnow()  # one as-of instant, shared by the clock math and its caption (§13.2)
    return page(request, "escalation_detail.html", db=db, package=package, history=history,
                progress=governance.clock_progress(package['clock'], now), as_of=now.isoformat(),
                can_respond=user.role is UserRole.COMPANY,
                can_review=user.role in (UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER),
                can_decide=user.role is UserRole.LEADERSHIP,
                decision_types=[d.value for d in LeadershipDecisionType])

@app.post("/escalations/{escalation_id}/respond")
def company_response(escalation_id: str, request: Request, explanation: str = Form(...), investigation_findings: str = Form(...), root_cause: str = Form(...), immediate_action: str = Form(...), corrective_action: str = Form(...), preventive_action: str = Form(...), participant_impact: str = Form(...), expected_resolution: str = Form(...), responsible_person: str = Form(...), supporting_documents: str = Form(""), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.COMPANY)), _: None = Depends(verify_csrf)):
    try: governance.submit_response(db, escalation_id=escalation_id, actor=user.username, actor_role=user.role.value, session_ref=audit_session_ref(request), supporting_documents=[x.strip() for x in supporting_documents.split(',') if x.strip()], explanation=explanation, investigation_findings=investigation_findings, root_cause=root_cause, immediate_action=immediate_action, corrective_action=corrective_action, preventive_action=preventive_action, participant_impact=participant_impact, expected_resolution=expected_resolution, responsible_person=responsible_person)
    except ValueError as e: raise HTTPException(400, str(e))
    return RedirectResponse(f"/escalations/{escalation_id}", 303)

@app.post("/escalations/{escalation_id}/review")
def reviewer_response(escalation_id: str, request: Request, outcome: str = Form(...), reason: str = Form(...), ai_finding_decision: str = Form(""), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER)), _: None = Depends(verify_csrf)):
    package = governance.get(db, escalation_id)
    if not package or ((package['escalation']['escalation_type'] == 'protocol_deviation') != (user.role is UserRole.INVESTIGATOR)): raise HTTPException(403, "Only the responsible oversight role may review this response.")
    try: governance.review(db, escalation_id=escalation_id, outcome=outcome, reason=reason, actor=user.username, actor_role=user.role.value, session_ref=audit_session_ref(request), ai_finding_decision=ai_finding_decision or None)
    except ValueError as e: raise HTTPException(400, str(e))
    return RedirectResponse(f"/escalations/{escalation_id}", 303)

@app.post("/escalations/{escalation_id}/decision")
def leadership_decision(escalation_id: str, request: Request, decision: str = Form(...), reason: str = Form(...), conditions: str = Form(""), db: Connection = Depends(get_db), user: User = Depends(require(UserRole.LEADERSHIP)), _: None = Depends(verify_csrf)):
    try: governance.decide(db, escalation_id=escalation_id, decision=decision, reason=reason, actor=user.username, actor_role=user.role.value, session_ref=audit_session_ref(request), conditions=[x.strip() for x in conditions.splitlines() if x.strip()])
    except ValueError as e: raise HTTPException(400, str(e))
    return RedirectResponse(f"/escalations/{escalation_id}", 303)

@app.get("/audit", response_class=HTMLResponse)
def audit_trail(request: Request, db: Connection = Depends(get_db), user: User = Depends(require(UserRole.LEADERSHIP))):
    # The audit trail is the one queue filtered in SQL (queues.audit_query) —
    # it can outgrow memory, and its filters map onto columns. Verification is
    # unaffected by anything filtered here: it always walks the full table, and
    # the page says so next to the controls. `verified_at` is the instant this
    # page's check ran — a verification claim without its time is not one (§13.2).
    audit.record(db, actor=user.username, role=user.role.value, session_ref=audit_session_ref(request), action='view', resource_type='audit_log', reason='Leadership audit review')
    result = queues.audit_query(db, request.query_params)
    checked_at = utcnow()
    return page(request, "audit.html", db=db, result=result,
                action_options=queues.AUDIT_ACTIONS, resource_options=queues.AUDIT_RESOURCE_TYPES,
                chain=audit.verify(db), verified_at=checked_at, as_of=checked_at)

# ----------------------------------------------------------------- search & coding APIs
_SEARCH_GROUP_LIMIT = 5

@app.get("/api/search", tags=["search"])
def api_search(q: str, db: Connection = Depends(get_db), user: User = Depends(current_user)):
    term = (q or "").strip()
    if len(term) < 2:
        return {
            "q": term, "generated_at": utcnow().isoformat(), "total": 0, "groups": [],
            "scope_note": "Type at least 2 characters — an identifier, term or sequence number.",
        }
    like = f"%{term}%"
    groups: list[dict] = []

    trials = [
        {"id": r["id"], "title": r["title"],
         "sub": f"PI {r['pi_name']} · {r['status'].replace('_', ' ')}",
         "href": f"/trial/{r['id']}"}
        for r in db.execute(
            """SELECT id, title, pi_name, status FROM trials
                WHERE id LIKE ? OR title LIKE ? OR ctri_number LIKE ?
                ORDER BY id LIMIT ?""",
            (like, like, like, _SEARCH_GROUP_LIMIT),
        )
    ]
    if trials:
        groups.append({"kind": "trial", "label": "Trials", "results": trials})

    participants = [
        {"id": r["participant_code"], "title": r["participant_code"],
         "sub": f"{r['trial_id']} · enrolled {r['enrolled_date'] or 'not yet'}",
         "href": f"/trial/{r['trial_id']}"}
        for r in db.execute(
            """SELECT participant_code, trial_id, enrolled_date FROM participants
                WHERE participant_code LIKE ? ORDER BY participant_code LIMIT ?""",
            (like, _SEARCH_GROUP_LIMIT),
        )
    ]
    if participants:
        groups.append({"kind": "participant", "label": "Participants (pseudonymous codes)", "results": participants})

    cases = [
        {"id": r["id"],
         "title": f"{r['id']} · {(r['coded_term'] or 'Uncoded narrative')}",
         "sub": f"{r['trial_id']} · participant {r['participant_code']} · {'serious' if r['serious'] else 'non-serious'}",
         "href": "/ae"}
        for r in db.execute(
            """SELECT id, trial_id, participant_code, coded_term, serious FROM adverse_events
                WHERE id LIKE ? OR coded_term LIKE ?
                ORDER BY reported_at DESC LIMIT ?""",
            (like, like, _SEARCH_GROUP_LIMIT),
        )
    ]
    if cases:
        groups.append({"kind": "case", "label": "Adverse-event cases", "results": cases})

    escalations = [
        {"id": r["id"],
         "title": f"{r['id']} · {r['escalation_type'].replace('_', ' ').capitalize()}",
         "sub": f"{r['trial_id']} · {r['severity']} · status: {r['status']}",
         "href": f"/escalations/{r['id']}"}
        for r in db.execute(
            """SELECT id, trial_id, escalation_type, severity, status FROM escalations
                WHERE id LIKE ? OR reason LIKE ?
                ORDER BY created_at DESC LIMIT ?""",
            (like, like, _SEARCH_GROUP_LIMIT),
        )
    ]
    if escalations:
        groups.append({"kind": "escalation", "label": "Escalations", "results": escalations})

    if term.lstrip("#").isdigit():
        seq = int(term.lstrip("#"))
        audit_rows = [
            {"id": f"#{r['seq']}",
             "title": f"#{r['seq']} · {r['action']} · {r['resource_type']}",
             "sub": f"{r['actor']} · {r['timestamp_utc'][:16].replace('T', ' ')} UTC",
             "href": "/audit"}
            for r in db.execute(
                """SELECT seq, actor, action, resource_type, timestamp_utc
                     FROM audit_events WHERE seq = ? LIMIT 1""",
                (seq,),
            )
        ]
        if audit_rows:
            groups.append({"kind": "audit", "label": "Audit sequence", "results": audit_rows})

    return {
        "q": term,
        "generated_at": utcnow().isoformat(),
        "total": sum(len(g["results"]) for g in groups),
        "groups": groups,
        "scope_note": "Results are limited to records every signed-in role may read; clinical narratives are never searched.",
    }

class _CodeRequest(BaseModel):
    narrative: str = Field(min_length=1, max_length=10000)

@app.get("/api/pv/code", tags=["pv"], deprecated=True)
def api_code(narrative: str):
    return {
        "narrative": narrative,
        "normalised": pv.normalise(narrative),
        "suggestions": [r.as_dict() for r in pv.code(narrative)],
        "vocabulary": "app/terms.csv (curated for this demonstration — not MedDRA)",
    }

@app.post("/api/pv/code", tags=["pv"])
def api_code_body(
    payload: _CodeRequest,
    user: User = Depends(current_user),
    _csrf: None = Depends(verify_csrf_header),
):
    return {
        "narrative": payload.narrative,
        "normalised": pv.normalise(payload.narrative),
        "suggestions": [r.as_dict() for r in pv.code(payload.narrative)],
        "vocabulary": "app/terms.csv (curated for this demonstration — not MedDRA)",
    }
