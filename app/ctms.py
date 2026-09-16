"""Core CTMS lifecycle services.

This module owns the upstream participant and Company workflow.  It intentionally
contains no final AI decisions: eligibility and coding suggestions are persisted as
AI findings for authorised human review.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from . import audit, pv
from .db import Connection, begin_audit_append
from .models import utcnow

LIFECYCLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trial_versions (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), version_no INTEGER NOT NULL,
 configuration_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(trial_id, version_no)
);
CREATE TABLE IF NOT EXISTS eligibility_criteria (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), criterion_text TEXT NOT NULL,
 criterion_type TEXT NOT NULL CHECK(criterion_type IN ('inclusion','exclusion')),
 required INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,
 created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registration_forms (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), version_no INTEGER NOT NULL,
 fields_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
 created_by TEXT NOT NULL, created_at TEXT NOT NULL, published_at TEXT
);
CREATE TABLE IF NOT EXISTS registration_submissions (
 id TEXT PRIMARY KEY, form_id TEXT NOT NULL REFERENCES registration_forms(id), trial_id TEXT NOT NULL REFERENCES trials(id),
 volunteer_user_id TEXT NOT NULL REFERENCES users(id), answers_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('submitted','prescreened','investigator_review','more_information_required','eligible','not_eligible')),
 ai_finding_id TEXT, submitted_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, decision_reason TEXT
);
CREATE TABLE IF NOT EXISTS consent_forms (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), version_no INTEGER NOT NULL,
 content TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','published','retired')),
 created_by TEXT NOT NULL, created_at TEXT NOT NULL, published_at TEXT
);
CREATE TABLE IF NOT EXISTS consent_records (
 id TEXT PRIMARY KEY, consent_form_id TEXT NOT NULL REFERENCES consent_forms(id),
 submission_id TEXT REFERENCES registration_submissions(id), participant_id TEXT,
 volunteer_user_id TEXT NOT NULL REFERENCES users(id), decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')),
 decided_at TEXT NOT NULL, UNIQUE(consent_form_id, volunteer_user_id)
);
CREATE TABLE IF NOT EXISTS participant_user_access (
 user_id TEXT PRIMARY KEY REFERENCES users(id), participant_id TEXT NOT NULL REFERENCES participants(id)
);
CREATE TABLE IF NOT EXISTS appointments (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), participant_id TEXT NOT NULL REFERENCES participants(id),
 title TEXT NOT NULL, scheduled_at TEXT NOT NULL, details TEXT, status TEXT NOT NULL CHECK(status IN ('scheduled','rescheduled','completed','cancelled')),
 created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enrollments (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), participant_id TEXT NOT NULL REFERENCES participants(id),
 submission_id TEXT NOT NULL REFERENCES registration_submissions(id), investigator_id TEXT NOT NULL REFERENCES users(id),
 status TEXT NOT NULL CHECK(status IN ('enrolled','not_eligible','more_information_required')), reason TEXT NOT NULL, decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ae_codes (
 id TEXT PRIMARY KEY, adverse_event_id TEXT NOT NULL REFERENCES adverse_events(id), suggested_term TEXT, suggested_code TEXT,
 engine_version TEXT NOT NULL, suggestion_confidence REAL, reviewer_id TEXT, final_term TEXT, final_code TEXT,
 decision TEXT CHECK(decision IN ('confirmed','corrected','uncoded')), reviewed_at TEXT, UNIQUE(adverse_event_id)
);
CREATE TABLE IF NOT EXISTS prr_calculations (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), coded_term TEXT NOT NULL, event_reports INTEGER NOT NULL,
 reference_reports INTEGER NOT NULL, prr REAL, calculated_at TEXT NOT NULL, calculated_by TEXT NOT NULL, ai_observation TEXT NOT NULL, reviewed_by TEXT
);
CREATE TABLE IF NOT EXISTS safety_signals (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), prr_calculation_id TEXT REFERENCES prr_calculations(id),
 status TEXT NOT NULL CHECK(status IN ('open','under_review','closed')), severity TEXT NOT NULL, observation TEXT NOT NULL,
 created_by TEXT NOT NULL, created_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS safety_reports (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), summary TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigation_reports (
 id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(id), escalation_id TEXT REFERENCES escalations(id),
 summary TEXT NOT NULL, findings TEXT NOT NULL, recommendation TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), trial_id TEXT REFERENCES trials(id),
 kind TEXT NOT NULL, message TEXT NOT NULL, href TEXT, status TEXT NOT NULL DEFAULT 'unread', created_at TEXT NOT NULL, read_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_registration_trial_status ON registration_submissions(trial_id,status);
CREATE INDEX IF NOT EXISTS ix_appointments_participant ON appointments(participant_id,scheduled_at);
CREATE INDEX IF NOT EXISTS ix_notifications_user_status ON notifications(user_id,status);
"""

#: The enum vocabularies `report_ae` validates against (models.py is the source
#: of truth; read once here so the error messages can name the allowed values).
from .models import AECausality, AEOutcome, AESeverity  # noqa: E402

_AE_SEVERITIES = {e.value for e in AESeverity}
_AE_CAUSALITIES = {e.value for e in AECausality}
_AE_OUTCOMES = {e.value for e in AEOutcome}


def ensure_schema(conn: Connection) -> None:
    # SQLite supports executescript; the driver wrapper does too. Split keeps Postgres safe.
    for statement in LIFECYCLE_SCHEMA.split(';'):
        if statement.strip():
            conn.execute(statement)
    # Audit extension preserves old rows and has no effect on their historic hashes.
    try:
        conn.execute("ALTER TABLE audit_events ADD COLUMN role TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE audit_events ADD COLUMN session_ref TEXT")
    except Exception:
        pass
    conn.commit()

def _row_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"

def _audit(conn: Connection, actor: str, role: str, action: str, resource: str, resource_id: str, *, before=None, after=None, reason=None, session_ref: str | None = None) -> None:
    audit.record(conn, actor=actor, role=role, session_ref=session_ref, action=action, resource_type=resource, resource_id=resource_id, before=before, after=after, reason=reason, commit=False)

def _finding(conn: Connection, *, kind: str, subject_type: str, subject_id: str, engine: str, input_summary: str, finding: str, explanation: str, recommendation: str | None) -> str:
    fid = _row_id('AIF')
    conn.execute("""INSERT INTO ai_findings (id,kind,subject_type,subject_id,engine_version,input_summary,finding,explanation,confidence,recommended_action,created_at,human_reviewer,human_decision,review_timestamp)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (fid,kind,subject_type,subject_id,engine,input_summary,finding,explanation,None,recommendation,utcnow().isoformat(),None,None,None))
    return fid

def create_trial(conn: Connection, *, actor: str, role: str, title: str, protocol_no: str, phase: str, therapeutic_area: str, target: int, pi_name: str, session_ref: str | None = None) -> str:
    trial_id = _row_id('TRL')
    now = utcnow().isoformat()
    begin_audit_append(conn)
    row = (trial_id,title,protocol_no,phase,'protocol',therapeutic_area,target,pi_name,now[:10],'draft','normal','none')
    conn.execute("""INSERT INTO trials (id,title,protocol_no,phase,status,therapeutic_area,target_enrolment,pi_name,start_date,operational_status,safety_status,leadership_status)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", row)
    conn.execute("INSERT INTO trial_versions (id,trial_id,version_no,configuration_json,created_by,created_at) VALUES (?,?,?,?,?,?)", (_row_id('TV'),trial_id,1,'{}',actor,now))
    _audit(conn,actor,role,'create','trial',trial_id,after={'id':trial_id,'title':title,'lifecycle':'draft'},reason='Company created trial configuration',session_ref=session_ref)
    conn.commit(); return trial_id

def create_criterion(conn: Connection, *, actor: str, role: str, trial_id: str, text: str, criterion_type: str, session_ref: str | None = None) -> str:
    if criterion_type not in ('inclusion','exclusion') or not text.strip(): raise ValueError('A non-empty inclusion or exclusion criterion is required.')
    cid=_row_id('ELG'); now=utcnow().isoformat(); begin_audit_append(conn)
    conn.execute("INSERT INTO eligibility_criteria (id,trial_id,criterion_text,criterion_type,required,active,created_by,created_at) VALUES (?,?,?,?,1,1,?,?)",(cid,trial_id,text.strip(),criterion_type,actor,now))
    _audit(conn,actor,role,'create','eligibility_criterion',cid,after={'trial_id':trial_id,'type':criterion_type,'text':text.strip()},reason='Company eligibility configuration',session_ref=session_ref)
    conn.commit(); return cid

def submit_registration(conn: Connection, *, actor: str, role: str, user_id: str, trial_id: str, answers: dict[str,Any], session_ref: str | None = None) -> str:
    form=conn.execute("SELECT * FROM registration_forms WHERE trial_id=? AND status='published' ORDER BY version_no DESC LIMIT 1",(trial_id,)).fetchone()
    if not form: raise ValueError('No published registration form exists for this trial.')
    sid=_row_id('REG'); now=utcnow().isoformat(); begin_audit_append(conn)
    conn.execute("INSERT INTO registration_submissions (id,form_id,trial_id,volunteer_user_id,answers_json,status,submitted_at) VALUES (?,?,?,?,?,'submitted',?)",(sid,form['id'],trial_id,user_id,json.dumps(answers),now))
    criteria=conn.execute("SELECT criterion_text,criterion_type FROM eligibility_criteria WHERE trial_id=? AND active=1",(trial_id,)).fetchall()
    corpus=' '.join(str(v).lower() for v in answers.values())
    failures=[c['criterion_text'] for c in criteria if c['criterion_type']=='exclusion' and c['criterion_text'].lower() in corpus]
    missing=[c['criterion_text'] for c in criteria if c['criterion_type']=='inclusion' and c['criterion_text'].lower() not in corpus]
    result='potentially_not_eligible' if failures else ('needs_investigator_review' if missing else 'potentially_eligible')
    finding=_finding(conn,kind='eligibility_prescreen',subject_type='registration_submission',subject_id=sid,engine='criteria-prescreen-1.0',input_summary='Registration answers compared with configured criteria.',finding=result,explanation=json.dumps({'matched':[], 'failed':failures, 'missing_information':missing}),recommendation='Investigator review required; AI cannot make final eligibility decision.')
    conn.execute("UPDATE registration_submissions SET status='investigator_review',ai_finding_id=? WHERE id=?",(finding,sid))
    _audit(conn,actor,role,'create','registration_submission',sid,after={'trial_id':trial_id,'status':'investigator_review','ai_finding_id':finding},reason='Volunteer submitted registration',session_ref=session_ref)
    conn.commit(); return sid

def record_consent(conn: Connection, *, actor: str, role: str, volunteer_user_id: str, trial_id: str, decision: str, session_ref: str | None = None) -> str:
    """Record the participant's explicit accept/reject decision for a published version."""
    if decision not in ('accepted', 'rejected'):
        raise ValueError('Consent decision must be accepted or rejected.')
    form = conn.execute("SELECT * FROM consent_forms WHERE trial_id=? AND status='published' ORDER BY version_no DESC LIMIT 1", (trial_id,)).fetchone()
    if not form:
        raise ValueError('No published consent form exists for this trial.')
    now = utcnow().isoformat(); record_id = _row_id('CON')
    participant = conn.execute("SELECT participant_id FROM participant_user_access WHERE user_id=?", (volunteer_user_id,)).fetchone()
    submission = conn.execute("SELECT id FROM registration_submissions WHERE volunteer_user_id=? AND trial_id=? ORDER BY submitted_at DESC LIMIT 1", (volunteer_user_id, trial_id)).fetchone()
    begin_audit_append(conn)
    conn.execute("INSERT INTO consent_records (id,consent_form_id,submission_id,participant_id,volunteer_user_id,decision,decided_at) VALUES (?,?,?,?,?,?,?)", (record_id, form['id'], submission['id'] if submission else None, participant['participant_id'] if participant else None, volunteer_user_id, decision, now))
    if participant:
        conn.execute("UPDATE participants SET consent_version=?, consent_date=? WHERE id=?", (str(form['version_no']), now, participant['participant_id']))
    _audit(conn, actor, role, 'create', 'consent_record', record_id, after={'trial_id':trial_id,'version':form['version_no'],'decision':decision}, reason='Volunteer consent decision', session_ref=session_ref)
    conn.commit()
    return record_id

def decide_eligibility(conn: Connection, *, actor: str, role: str, investigator_id: str, submission_id: str, decision: str, reason: str, session_ref: str | None = None) -> None:
    if decision not in ('eligible','not_eligible','more_information_required') or not reason.strip(): raise ValueError('Use an approved eligibility decision and provide a reason.')
    sub=conn.execute('SELECT * FROM registration_submissions WHERE id=?',(submission_id,)).fetchone()
    if not sub or sub['status']!='investigator_review': raise ValueError('This submission is not awaiting investigator review.')
    now=utcnow().isoformat(); begin_audit_append(conn)
    conn.execute('UPDATE registration_submissions SET status=?,reviewed_by=?,reviewed_at=?,decision_reason=? WHERE id=?',(decision,actor,now,reason.strip(),submission_id))
    if sub['ai_finding_id']:
        conn.execute('UPDATE ai_findings SET human_reviewer=?,human_decision=?,review_timestamp=? WHERE id=?',(actor,decision,now,sub['ai_finding_id']))
    if decision=='eligible':
        pid=_row_id('PT'); trial=conn.execute('SELECT * FROM trials WHERE id=?',(sub['trial_id'],)).fetchone(); site=conn.execute('SELECT site_id FROM trial_sites WHERE trial_id=? LIMIT 1',(sub['trial_id'],)).fetchone()
        site_id=site['site_id'] if site else 'UNASSIGNED'
        conn.execute("INSERT INTO participants (id,participant_code,trial_id,site_id,screened_date,enrolled_date,status,consent_version,consent_date) VALUES (?,?,?,?,?,?,?,'pending','')",(pid,f"{sub['trial_id']}-{uuid.uuid4().hex[:6].upper()}",sub['trial_id'],site_id,now[:10],now[:10],'enrolled'))
        conn.execute('INSERT INTO participant_user_access (user_id,participant_id) VALUES (?,?)',(sub['volunteer_user_id'],pid))
        conn.execute("INSERT INTO enrollments (id,trial_id,participant_id,submission_id,investigator_id,status,reason,decided_at) VALUES (?,?,?,?,?,?,?,?)",(_row_id('ENR'),sub['trial_id'],pid,submission_id,investigator_id,'enrolled',reason.strip(),now))
        conn.execute('UPDATE trials SET actual_enrolment=actual_enrolment+1 WHERE id=?',(sub['trial_id'],))
    _audit(conn,actor,role,'update','registration_submission',submission_id,before={'status':'investigator_review'},after={'status':decision},reason=reason.strip(),session_ref=session_ref)
    conn.commit()

def report_ae(conn: Connection, *, actor: str, role: str, trial_id: str, participant_code: str, narrative: str, onset_date: str, serious: bool=False, severity: str='moderate', causality: str='possible', outcome: str='unknown', session_ref: str | None = None) -> str:
    """File an adverse event.

    `severity`/`causality`/`outcome` default to the volunteer self-report
    values (a participant reports what they felt; clinical grading lands at
    review). Staff intake — the Safety Officer's /ae form — passes all three
    explicitly; each is validated against its enum vocabulary in models.py so
    a misspelled grade is a 400, never a silent 'unknown'.
    """
    if severity not in _AE_SEVERITIES: raise ValueError(f"Severity must be one of: {', '.join(sorted(_AE_SEVERITIES))}.")
    if causality not in _AE_CAUSALITIES: raise ValueError(f"Causality must be one of: {', '.join(sorted(_AE_CAUSALITIES))}.")
    if outcome not in _AE_OUTCOMES: raise ValueError(f"Outcome must be one of: {', '.join(sorted(_AE_OUTCOMES))}.")
    p=conn.execute('SELECT * FROM participants WHERE participant_code=? AND trial_id=?',(participant_code,trial_id)).fetchone()
    if not p: raise ValueError('Participant is not authorised for this trial.')
    coded=pv.code_best(narrative)
    aid=_row_id('AE'); now=utcnow(); begin_audit_append(conn)
    term=getattr(coded,'term',None) if coded else None; code=getattr(coded,'code',None) if coded else None; confidence=getattr(coded,'confidence',None) if coded else None
    deadline_24h, deadline_14d, timeline = pv.compute_clocks(now, serious, now=now)
    conn.execute("""INSERT INTO adverse_events (id,trial_id,site_id,participant_code,narrative,onset_date,serious,severity,causality,outcome,coded_term,coded_code,coding_confidence,coding_source,reported_at,deadline_24h,deadline_14d,timeline_status)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(aid,trial_id,p['site_id'],participant_code,narrative.strip(),onset_date,1 if serious else 0,severity,causality,outcome,term,code,confidence,'suggested' if term else 'uncoded',now.isoformat(),deadline_24h.isoformat() if deadline_24h else None,deadline_14d.isoformat() if deadline_14d else None,timeline.value))
    fid=_finding(conn,kind='ae_coding_suggestion',subject_type='adverse_event',subject_id=aid,engine='curated-coder-1.0',input_summary=narrative.strip(),finding=term or 'No reliable coding suggestion',explanation='Automated coding suggestion only; Safety Officer must confirm, correct, or leave uncoded.',recommendation='Safety Officer review required.')
    conn.execute('INSERT INTO ae_codes (id,adverse_event_id,suggested_term,suggested_code,engine_version,suggestion_confidence,decision) VALUES (?,?,?,?,?,?,?)',(_row_id('AEC'),aid,term,code,'curated-coder-1.0',confidence,'uncoded'))
    _audit(conn,actor,role,'create','adverse_event',aid,after={'trial_id':trial_id,'participant_code':participant_code,'ai_finding_id':fid},reason='Participant adverse-event report',session_ref=session_ref)
    conn.commit(); return aid

def review_ae_code(conn: Connection, *, actor: str, role: str, adverse_event_id: str, decision: str, final_term: str|None, final_code: str|None, session_ref: str | None = None) -> None:
    if decision not in ('confirmed','corrected','uncoded'): raise ValueError('Invalid coding decision.')
    now=utcnow().isoformat(); begin_audit_append(conn)
    conn.execute('UPDATE ae_codes SET reviewer_id=?,final_term=?,final_code=?,decision=?,reviewed_at=? WHERE adverse_event_id=?',(actor,final_term,final_code,decision,now,adverse_event_id))
    conn.execute('UPDATE adverse_events SET coded_term=?,coded_code=?,coding_source=? WHERE id=?',(final_term,final_code,'safety_officer' if decision!='uncoded' else 'uncoded',adverse_event_id))
    conn.execute("UPDATE ai_findings SET human_reviewer=?,human_decision=?,review_timestamp=? WHERE subject_type='adverse_event' AND subject_id=? AND human_decision IS NULL",(actor,decision,now,adverse_event_id))
    _audit(conn,actor,role,'update','ae_code',adverse_event_id,after={'decision':decision,'term':final_term},reason='Safety Officer coding review',session_ref=session_ref)
    conn.commit()
