from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import auth, ctms, datagen, db

with TemporaryDirectory() as directory:
    conn = db.connect(Path(directory) / "ctms.db")
    db.init_schema(conn)
    datagen.seed(conn)
    ctms.ensure_schema(conn)
    aliases = {
        "principal_investigator": "investigator",
        "study_coordinator": "investigator",
        "monitor": "investigator",
        "pharmacovigilance": "safety_officer",
        "ethics_committee": "leadership",
        "administration": "leadership",
        "regulator": "leadership",
    }
    for old, new in aliases.items():
        conn.execute("UPDATE users SET role=? WHERE role=?", (new, old))
    trial_id = conn.execute("SELECT id FROM trials LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO registration_forms (id,trial_id,version_no,fields_json,status,created_by,created_at,published_at) VALUES ('rf-1',?,1,'[]','published','company',datetime('now'),datetime('now'))",
        (trial_id,),
    )
    conn.commit()
    company = auth.authenticate(conn, "company.demo", "AiiaCompany#01")
    investigator = auth.authenticate(conn, "investigator.demo", "AiiaTrialLead#01")
    volunteer = auth.authenticate(conn, "volunteer.demo", "CtmsVolunteer#01")
    safety = auth.authenticate(conn, "safety.demo", "AiiaSafety#01")
    assert all((company, investigator, volunteer, safety))
    ctms.create_criterion(conn, actor=company.username, role="company", trial_id=trial_id, text="adult participant", criterion_type="inclusion")
    submission_id = ctms.submit_registration(conn, actor=volunteer.username, role="volunteer", user_id=volunteer.id, trial_id=trial_id, answers={"age": "adult participant"})
    ctms.decide_eligibility(conn, actor=investigator.username, role="investigator", investigator_id=investigator.id, submission_id=submission_id, decision="eligible", reason="Eligibility verified by Investigator.")
    submission = conn.execute("SELECT status,ai_finding_id FROM registration_submissions WHERE id=?", (submission_id,)).fetchone()
    assert submission["status"] == "eligible"
    finding = conn.execute("SELECT human_reviewer,human_decision FROM ai_findings WHERE id=?", (submission["ai_finding_id"],)).fetchone()
    assert finding["human_reviewer"] == investigator.username and finding["human_decision"] == "eligible"
    participant_code = conn.execute("SELECT participant_code FROM participants ORDER BY rowid DESC LIMIT 1").fetchone()["participant_code"]
    event_id = ctms.report_ae(conn, actor=volunteer.username, role="volunteer", trial_id=trial_id, participant_code=participant_code, narrative="fever and headache", onset_date="2026-08-01", serious=False)
    ctms.review_ae_code(conn, actor=safety.username, role="safety_officer", adverse_event_id=event_id, decision="confirmed", final_term="Fever", final_code="VW-T0001")
    assert conn.execute("SELECT human_decision FROM ai_findings WHERE subject_id=?", (event_id,)).fetchone()["human_decision"] == "confirmed"
    conn.close()
print("lifecycle-workflow-ok")
