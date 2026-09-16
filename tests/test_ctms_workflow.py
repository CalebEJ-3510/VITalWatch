"""End-to-end coverage for the Volunteer consent workflow and audit session_ref.

Two things this file pins down that no other test covers:

* A Volunteer can accept or reject a published consent form through the real HTTP
  route (`/portal/volunteer/consent`), and the decision, form version, and history
  are all recorded and re-rendered correctly (spec section 7's consent requirements).
* `audit_events.session_ref` is populated end-to-end from an authenticated request —
  through `app/main.py`'s `audit_session_ref`, into `app/ctms.py` and
  `app/governance.py` mutation calls, into the stored row — not merely accepted as
  a keyword argument and dropped.

Isolated the same way `tests/test_audit_integrity.py` is: the database environment is
redirected to a throwaway temporary directory before `app` is imported, so this file
can never reach a developer's real `data/ctms.db` or an inherited `DATABASE_URL`.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vitalwatch-ctms-workflow-tests-"))
atexit.register(shutil.rmtree, _TEST_DIR, ignore_errors=True)
os.environ["DATABASE_URL"] = ""
os.environ["DB_PATH"] = str(_TEST_DIR / "isolation-probe.db")
os.environ.setdefault("DEMO_ALLOW_HTTP", "true")
os.environ.setdefault("APP_SECRET", "ctms-workflow-tests-throwaway-secret-not-for-deployment-use")

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, ctms, db as database  # noqa: E402
from app.config import settings  # noqa: E402

settings.database_url = None
settings.demo_allow_http = True

if database.is_postgres():  # pragma: no cover — only reachable on a misconfigured machine
    raise RuntimeError("CTMS workflow tests refuse to run against Postgres")


@pytest.fixture()
def conn(tmp_path):
    """A schema-initialised database with one trial, one criterion, one published
    registration form and one published consent form — the minimum a Volunteer needs
    to register, be reviewed, and reach the consent step."""
    settings.db_path = tmp_path / "ctms.db"
    c = database.connect(settings.db_path)
    database.init_schema(c)
    ctms.ensure_schema(c)

    trial_id = "STU-TEST"
    now = "2026-09-01T00:00:00+00:00"
    c.execute(
        "INSERT INTO trials (id,title,protocol_no,phase,status,therapeutic_area,"
        "target_enrolment,actual_enrolment,pi_name,start_date,operational_status,"
        "safety_status,leadership_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (trial_id, "Test trial", "PROTO-001", "II", "enrolling", "Metabolic",
         100, 0, "Dr. Test", "2026-01-01", "active", "normal", "none"),
    )
    c.execute(
        "INSERT INTO registration_forms (id,trial_id,version_no,fields_json,status,"
        "created_by,created_at,published_at) VALUES ('RF-1',?,1,'[]','published','company',?,?)",
        (trial_id, now, now),
    )
    c.execute(
        "INSERT INTO consent_forms (id,trial_id,version_no,content,status,created_by,"
        "created_at,published_at) VALUES ('CF-1',?,1,'You may withdraw at any time.',"
        "'published','company',?,?)",
        (trial_id, now, now),
    )
    # A real site, linked to the trial: `ctms.decide_eligibility` writes the new
    # participant's `site_id` against `trial_sites`, and `participants.site_id` is a
    # hard foreign key to `sites(id)` — there is no site row it can fall back to.
    c.execute(
        "INSERT INTO sites (id,name,city,state,status,pi_name,capacity) "
        "VALUES ('SITE-TEST','Test Site','Test City','Test State','activated','Dr. Test',50)"
    )
    c.execute("INSERT INTO trial_sites (trial_id,site_id) VALUES (?,'SITE-TEST')", (trial_id,))
    c.commit()
    try:
        yield c, trial_id
    finally:
        c.close()


def _enrol_volunteer(conn, trial_id: str, *, username="volunteer.test", password="Vol#Test01"):
    """Seed one volunteer account, submit a registration, and have an Investigator
    approve it — the real path to a `participants` row and a linked consent decision."""
    password_hash, salt = auth.hash_password(password)
    c = conn
    c.execute(
        "INSERT INTO users (id,username,password_hash,salt,role,display_name,pi_name,"
        "active,created_at) VALUES ('USR-VOL','%s',?,?,'volunteer','Test Volunteer',NULL,1,"
        "'2026-09-01T00:00:00+00:00')" % username,
        (password_hash, salt),
    )
    c.execute(
        "INSERT INTO users (id,username,password_hash,salt,role,display_name,pi_name,"
        "active,created_at) VALUES ('USR-INV','investigator.test',?,?,'investigator',"
        "'Test Investigator','Dr. Test',1,'2026-09-01T00:00:00+00:00')",
        (*auth.hash_password("Inv#Test01"),),
    )
    c.commit()
    submission_id = ctms.submit_registration(
        c, actor=username, role="volunteer", user_id="USR-VOL", trial_id=trial_id,
        answers={"age": "adult"},
    )
    ctms.decide_eligibility(
        c, actor="investigator.test", role="investigator", investigator_id="USR-INV",
        submission_id=submission_id, decision="eligible", reason="Meets criteria.",
    )
    return submission_id


def _login(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login")
    token = _csrf_from(page.text)
    posted = client.post(
        "/login", data={"csrf_token": token, "username": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    assert posted.status_code == 303, posted.text


def _csrf_from(html: str) -> str:
    import re
    tag = re.search(r'<input[^>]*name="csrf_token"[^>]*>', html, re.IGNORECASE)
    value = re.search(r'value="([^"]*)"', tag.group(0))
    return value.group(1)


# --------------------------------------------------------------------------- consent


def test_volunteer_can_accept_the_published_consent_form(conn):
    c, trial_id = conn
    _enrol_volunteer(c, trial_id)
    from app.main import app

    with TestClient(app) as client:
        _login(client, "volunteer.test", "Vol#Test01")

        dashboard = client.get("/portal/volunteer")
        assert dashboard.status_code == 200
        assert "You may withdraw at any time." in dashboard.text
        assert "Accept this consent version" in dashboard.text

        token = _csrf_from(dashboard.text)
        posted = client.post(
            "/portal/volunteer/consent",
            data={"csrf_token": token, "decision": "accepted"},
            follow_redirects=False,
        )
        assert posted.status_code == 303

        after = client.get("/portal/volunteer")
        assert "Accepted" in after.text
        assert "your decision for version" in after.text

    record = c.execute("SELECT decision FROM consent_records WHERE volunteer_user_id='USR-VOL'").fetchone()
    assert record["decision"] == "accepted"
    participant = c.execute("SELECT consent_version FROM participants").fetchone()
    assert participant["consent_version"] == "1"


def test_volunteer_can_reject_the_published_consent_form(conn):
    c, trial_id = conn
    _enrol_volunteer(c, trial_id)
    from app.main import app

    with TestClient(app) as client:
        _login(client, "volunteer.test", "Vol#Test01")
        dashboard = client.get("/portal/volunteer")
        token = _csrf_from(dashboard.text)
        posted = client.post(
            "/portal/volunteer/consent",
            data={"csrf_token": token, "decision": "rejected"},
            follow_redirects=False,
        )
        assert posted.status_code == 303

        after = client.get("/portal/volunteer")
        assert "Rejected" in after.text

    record = c.execute("SELECT decision FROM consent_records WHERE volunteer_user_id='USR-VOL'").fetchone()
    assert record["decision"] == "rejected"


def test_a_second_consent_decision_is_recorded_as_history(conn):
    """A volunteer who has already decided is shown the decision, not the form again —
    and a later published version reopens the decision. Here: the history list carries
    the one decision made, by version."""
    c, trial_id = conn
    _enrol_volunteer(c, trial_id)
    ctms.record_consent(c, actor="volunteer.test", role="volunteer", volunteer_user_id="USR-VOL",
                         trial_id=trial_id, decision="accepted")
    from app.main import app

    with TestClient(app) as client:
        _login(client, "volunteer.test", "Vol#Test01")
        dashboard = client.get("/portal/volunteer")
        assert "v1" in dashboard.text
        assert "Accepted" in dashboard.text
        # The decision is already on file for the current published version, so the
        # accept/reject form must not be re-offered.
        assert "Accept this consent version" not in dashboard.text


def test_consent_decision_must_be_accepted_or_rejected(conn):
    c, trial_id = conn
    with pytest.raises(ValueError, match="accepted or rejected"):
        ctms.record_consent(c, actor="volunteer.test", role="volunteer", volunteer_user_id="USR-VOL",
                             trial_id=trial_id, decision="maybe")


# --------------------------------------------------------------- audit session_ref


def test_session_ref_is_populated_end_to_end_through_ctms_mutations(conn):
    """A real authenticated HTTP request's session reference must land in the audit
    row for a ctms.py mutation (registration submission), not just be accepted and
    dropped."""
    c, trial_id = conn
    password_hash, salt = auth.hash_password("Vol#Test01")
    c.execute(
        "INSERT INTO users (id,username,password_hash,salt,role,display_name,pi_name,"
        "active,created_at) VALUES ('USR-VOL','volunteer.test',?,?,'volunteer',"
        "'Test Volunteer',NULL,1,'2026-09-01T00:00:00+00:00')",
        (password_hash, salt),
    )
    c.commit()
    from app.main import app

    with TestClient(app) as client:
        _login(client, "volunteer.test", "Vol#Test01")
        token = client.cookies.get(auth.SESSION_COOKIE)
        assert token, "the login must have set a session cookie"
        expected_ref = auth.session_reference(token)
        assert expected_ref is not None

        form = client.get("/portal/volunteer/register")
        csrf = _csrf_from(form.text)
        posted = client.post(
            "/portal/volunteer/register",
            data={"csrf_token": csrf, "trial_id": trial_id, "answers": '{"age":"adult"}'},
            follow_redirects=False,
        )
        assert posted.status_code == 303

    row = c.execute(
        "SELECT session_ref, role, actor FROM audit_events WHERE resource_type='registration_submission' "
        "ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "the registration submission must have written an audit row"
    assert row["session_ref"] == expected_ref
    assert row["role"] == "volunteer"
    assert row["actor"] == "volunteer.test"


def test_session_ref_is_populated_end_to_end_through_governance_escalation(conn):
    """The same guarantee for app/governance.py: an Investigator's protocol-deviation
    escalation, raised over HTTP, carries the requester's session_ref into the audit
    row governance.raise_escalation writes."""
    c, trial_id = conn
    password_hash, salt = auth.hash_password("Inv#Test01")
    c.execute(
        "INSERT INTO users (id,username,password_hash,salt,role,display_name,pi_name,"
        "active,created_at) VALUES ('USR-INV','investigator.test',?,?,'investigator',"
        "'Test Investigator','Dr. Test',1,'2026-09-01T00:00:00+00:00')",
        (password_hash, salt),
    )
    c.commit()
    from app.main import app

    with TestClient(app) as client:
        _login(client, "investigator.test", "Inv#Test01")
        token = client.cookies.get(auth.SESSION_COOKIE)
        expected_ref = auth.session_reference(token)

        form = client.get("/escalations/new")
        csrf = _csrf_from(form.text)
        posted = client.post(
            "/escalations",
            data={
                "csrf_token": csrf, "trial_id": trial_id, "escalation_type": "protocol_deviation",
                "severity": "major", "reason": "Monitoring visit window exceeded.",
                "recommended_action": "Investigator review.",
            },
            follow_redirects=False,
        )
        assert posted.status_code == 303, posted.text

    row = c.execute(
        "SELECT session_ref, role, actor FROM audit_events WHERE resource_type='escalation' "
        "ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "raising an escalation must have written an audit row"
    assert row["session_ref"] == expected_ref
    assert row["role"] == "investigator"
    assert row["actor"] == "investigator.test"


def test_session_ref_is_none_for_a_direct_call_with_no_session(conn):
    """The other half of the contract: a call made with no session reference stores
    NULL, not a placeholder — `session_ref` must never be invented."""
    c, trial_id = conn
    _enrol_volunteer(c, trial_id)
    ctms.record_consent(c, actor="volunteer.test", role="volunteer", volunteer_user_id="USR-VOL",
                         trial_id=trial_id, decision="accepted")
    row = c.execute(
        "SELECT session_ref FROM audit_events WHERE resource_type='consent_record' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert row["session_ref"] is None
