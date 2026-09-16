"""Synthetic portfolio generator.

Everything in this system is invented. No real patient, no real trial, no real AIIA
record touches this codebase — that is the point, and it is why the footer says so on
every page.

The generator is seeded from `settings.seed_random_seed`, so the portfolio is identical
on every run. That matters twice: the demo script can name a specific trial, and a
regenerated database matches the screenshots in the deck.

The data is shaped to make the dashboard say something. Some trials enrol ahead of
plan and some behind; one is enrolling without a CTRI number; one ethics approval
expires inside the renewal window; some monitoring visits are overdue; some SAEs are
past their 24-hour clock. A portfolio where nothing is wrong demonstrates nothing.
"""

from __future__ import annotations

import random
from .db import Connection  # driver-neutral: SQLite or Postgres
import uuid
from datetime import date, datetime, time, timedelta, timezone

from . import audit, auth, case_data, pv
from .config import settings

TODAY = date(2026, 8, 22)

THERAPEUTIC_AREAS = [
    ("Rheumatology", "Amavata (Rheumatoid Arthritis)"),
    ("Metabolic", "Madhumeha (Type 2 Diabetes Mellitus)"),
    ("Respiratory", "Tamaka Shwasa (Bronchial Asthma)"),
    ("Dermatology", "Kitibha (Plaque Psoriasis)"),
    ("Gastroenterology", "Grahani (Irritable Bowel Syndrome)"),
    ("Hepatology", "Yakrit Roga (Non-Alcoholic Fatty Liver)"),
    ("Neurology", "Anidra (Primary Insomnia)"),
    ("Cardiology", "Hridroga (Dyslipidaemia)"),
]

FORMULATIONS = [
    "Guduchi Ghana Vati", "Ashwagandha Churna", "Triphala Guggulu", "Punarnava Mandur",
    "Shirishadi Kwatha", "Kutajarishta", "Arjuna Ksheerapaka", "Yashtimadhu Ghrita",
]

SITES = [
    ("All India Institute of Ayurveda", "New Delhi", "Delhi", 120),
    ("National Institute of Ayurveda", "Jaipur", "Rajasthan", 90),
    ("Government Ayurveda College", "Thiruvananthapuram", "Kerala", 80),
    ("IPGT&RA, Gujarat Ayurved University", "Jamnagar", "Gujarat", 75),
    ("Ayurveda Mahavidyalaya", "Pune", "Maharashtra", 60),
    ("Regional Ayurveda Research Institute", "Guwahati", "Assam", 45),
    ("Government Ayurveda Medical College", "Bengaluru", "Karnataka", 70),
    ("Shri Dhanwantry Ayurvedic College", "Chandigarh", "Punjab", 50),
    ("State Ayurvedic College", "Lucknow", "Uttar Pradesh", 65),
    ("Ayurveda Regional Research Institute", "Bhubaneswar", "Odisha", 40),
    ("Government Ayurveda College", "Nagpur", "Maharashtra", 55),
    ("North Eastern Institute of Ayurveda", "Shillong", "Meghalaya", 35),
]

PI_NAMES = [
    "Dr. R. Krishnan", "Dr. S. Deshpande", "Dr. A. Nair", "Dr. M. Bhattacharya",
    "Dr. P. Iyer", "Dr. V. Sharma", "Dr. K. Menon", "Dr. T. Rao",
    "Dr. N. Chatterjee", "Dr. L. Pillai", "Dr. G. Kulkarni", "Dr. H. Joshi",
]


DEVIATION_CATEGORIES = [
    ("Visit window", "Follow-up visit conducted outside the protocol-defined window", "minor"),
    ("Consent", "Consent re-signed on the amended version after the first dose", "major"),
    ("Eligibility", "Participant enrolled with a haemoglobin value below the inclusion threshold", "critical"),
    ("Trial drug", "Dispensing log entry missing for one participant-visit", "minor"),
    ("Procedure", "Scheduled laboratory sample not collected at the week-8 visit", "major"),
    ("Documentation", "Source document not signed by the investigator within the required period", "minor"),
]

QUERY_FIELDS = [
    ("SYSBP", "Systolic BP recorded as 220 mmHg — please confirm or correct."),
    ("AESTDAT", "Adverse event start date precedes the informed consent date."),
    ("VISITDAT", "Visit date is after the date of the following visit. Please clarify."),
    ("CONMED", "Concomitant medication recorded with no start date."),
    ("HGB", "Haemoglobin value outside the physiological range. Confirm the unit."),
    ("WEIGHT", "Weight differs by 14 kg from the previous visit. Please verify."),
]

QUERY_RAISERS = ["dm.aiia", "monitor.north", "monitor.south", "dm.npvcc"]


def _dt(d: date, hour: int = 9, minute: int = 0) -> str:
    return datetime.combine(d, time(hour, minute), tzinfo=timezone.utc).isoformat()


def _id(prefix: str, n: int) -> str:
    return f"{prefix}-{n:03d}"


def seed(conn: Connection) -> None:
    """Populate an empty database. Called from `db.init` on startup."""
    rng = random.Random(settings.seed_random_seed)

    sites = _seed_sites(conn, rng)
    trials = _seed_trials(conn, rng, sites)
    _seed_milestones(conn, rng, trials)
    participants = _seed_participants(conn, rng, trials)
    _seed_visits(conn, rng, trials, participants)
    _seed_deviations(conn, rng, trials, participants)
    _seed_queries(conn, rng, trials, participants)
    _seed_adverse_events(conn, rng, trials, participants)
    # The investigation case is generated last, from its own random stream, so that
    # adding it cannot shift a single value in the eight trials above. Those trials
    # keep their audit rows at seq 1-8 byte for byte; the case only appends seq 9.
    trials.append(_seed_case(conn))
    _seed_audit(conn, trials)
    _seed_users(conn)
    conn.commit()

    # Reported after the case is in, or the count would describe a portfolio that no
    # longer exists by the time the line is printed.
    # Aliased: Postgres names every COUNT column "count", and two identically named
    # columns collapse into one another in a mapping row.
    counts = conn.execute(
        "SELECT COUNT(*) AS total, COUNT(coded_term) AS coded FROM adverse_events"
    ).fetchone()
    total, coded = counts["total"], counts["coded"]
    print(f"[datagen] coded {coded}/{total} adverse events against app/terms.csv")


# ------------------------------------------------------------------------- sites


def _seed_sites(conn: Connection, rng: random.Random) -> list[dict]:
    rows = []
    for i, (name, city, state, capacity) in enumerate(SITES, start=1):
        # Two sites are still being brought up — "sites activated" should never read n/n,
        # because a portfolio where every site is live has nothing to manage.
        activated = i <= len(SITES) - 2
        row = {
            "id": _id("SITE", i),
            "name": name,
            "city": city,
            "state": state,
            "status": "activated" if activated else "planned",
            "activated_date": (TODAY - timedelta(days=rng.randint(200, 600))).isoformat()
            if activated else None,
            "pi_name": PI_NAMES[i - 1],
            "capacity": capacity,
        }
        conn.execute(
            """INSERT INTO sites (id, name, city, state, status, activated_date, pi_name, capacity)
               VALUES (:id,:name,:city,:state,:status,:activated_date,:pi_name,:capacity)""",
            row,
        )
        rows.append(row)
    return rows


# ------------------------------------------------------------------------ trials


def _seed_trials(conn: Connection, rng: random.Random, sites: list[dict]) -> list[dict]:
    active_sites = [s for s in sites if s["status"] == "activated"]
    statuses = [
        "enrolling", "enrolling", "enrolling", "enrolling",
        "follow_up", "screening", "ctri_registered", "close_out",
    ]
    phases = ["II", "III", "II", "observational", "III", "II", "IV", "III"]
    rows: list[dict] = []

    for i in range(1, settings.seed_trials + 1):
        area, title = THERAPEUTIC_AREAS[(i - 1) % len(THERAPEUTIC_AREAS)]
        status = statuses[(i - 1) % len(statuses)]
        started = TODAY - timedelta(days=rng.randint(120, 700))
        target = rng.choice([40, 50, 60, 70, 90, 110])

        # Trial 3 enrols without a CTRI number. Prospective registration is mandatory,
        # so this is a finding the portfolio is supposed to surface, not an oversight.
        registered = not (i == 3)
        ec_approval = started - timedelta(days=rng.randint(30, 90))

        # Trial 2's ethics approval expires inside the renewal window, so the EC-renewal
        # alert has something real to fire on.
        if i == 2:
            ec_expiry = TODAY + timedelta(days=21)
        elif status == "close_out":
            ec_expiry = TODAY + timedelta(days=rng.randint(200, 400))
        else:
            ec_expiry = ec_approval + timedelta(days=365 * rng.randint(2, 3))

        # Enrolment fraction, deliberately mixed: trials 1 and 5 run behind plan.
        fraction = {1: 0.34, 5: 0.41}.get(i, rng.uniform(0.62, 0.95))
        if status in ("ctri_registered", "screening"):
            fraction = rng.uniform(0.0, 0.08)
        if status == "close_out":
            fraction = 1.0

        trial_sites = rng.sample(active_sites, rng.randint(2, min(4, len(active_sites))))
        row = {
            "id": _id("STU", i),
            "title": f"{title} — {rng.choice(FORMULATIONS)}",
            "protocol_no": f"AIIA/CTP/{2024 + (i % 3)}/{i:02d}",
            "ctri_number": f"CTRI/{started.year}/{rng.randint(1,12):02d}/{rng.randint(100000,999999)}"
            if registered else None,
            "phase": phases[(i - 1) % len(phases)],
            "status": status,
            "therapeutic_area": area,
            "ec_approval_date": ec_approval.isoformat(),
            "ec_expiry_date": ec_expiry.isoformat(),
            "ctri_registration_date": (started - timedelta(days=rng.randint(5, 25))).isoformat()
            if registered else None,
            "target_enrolment": target,
            "actual_enrolment": int(target * fraction),
            "pi_name": rng.choice(PI_NAMES),
            "start_date": started.isoformat(),
            "end_date": None,
        }
        conn.execute(
            """INSERT INTO trials
               (id, title, protocol_no, ctri_number, phase, status, therapeutic_area,
                ec_approval_date, ec_expiry_date, ctri_registration_date,
                target_enrolment, actual_enrolment, pi_name, start_date, end_date)
               VALUES (:id,:title,:protocol_no,:ctri_number,:phase,:status,:therapeutic_area,
                       :ec_approval_date,:ec_expiry_date,:ctri_registration_date,
                       :target_enrolment,:actual_enrolment,:pi_name,:start_date,:end_date)""",
            row,
        )
        for site in trial_sites:
            conn.execute(
                "INSERT INTO trial_sites (trial_id, site_id) VALUES (?,?)", (row["id"], site["id"])
            )
        row["site_ids"] = [s["id"] for s in trial_sites]
        rows.append(row)
    return rows


# --------------------------------------------------------------------- milestones

MILESTONE_PLAN = [
    ("ec_approval", -60),
    ("ctri_registration", -20),
    ("first_site_activated", 10),
    ("first_subject_in", 30),
    ("fifty_pct_enrolled", 180),
    ("last_subject_in", 400),
    ("database_lock", 480),
    ("close_out", 540),
]


def _seed_milestones(conn: Connection, rng: random.Random, trials: list[dict]) -> None:
    for trial in trials:
        started = date.fromisoformat(trial["start_date"])
        for n, (mtype, offset) in enumerate(MILESTONE_PLAN, start=1):
            planned = started + timedelta(days=offset)
            if planned <= TODAY:
                # A milestone in the past is either done or missed. Most are done.
                achieved = rng.random() < 0.82
                actual = (planned + timedelta(days=rng.randint(-5, 20))).isoformat() if achieved else None
                status = "achieved" if achieved else "missed"
            else:
                actual = None
                # Due inside 45 days with the trial behind plan reads as at risk.
                status = "at_risk" if (planned - TODAY).days < 45 and rng.random() < 0.4 else "planned"
            conn.execute(
                """INSERT INTO milestones (id, trial_id, type, planned_date, actual_date, status)
                   VALUES (?,?,?,?,?,?)""",
                (f"{trial['id']}-MS-{n:02d}", trial["id"], mtype, planned.isoformat(), actual, status),
            )


# ----------------------------------------------------------------------- participants


def _seed_participants(conn: Connection, rng: random.Random, trials: list[dict]) -> list[dict]:
    age_bands = ["18-29", "30-39", "40-49", "50-59", "60-69", "70+"]
    rows: list[dict] = []

    for trial in trials:
        enrolled_target = trial["actual_enrolment"]
        if not enrolled_target:
            continue
        # Roughly one in five screened participants screen-fails — a realistic ratio, and the
        # screen-failure-rate KPI needs failures to be non-trivial.
        screened_total = int(enrolled_target * rng.uniform(1.15, 1.35)) + 1
        started = date.fromisoformat(trial["start_date"])
        span = max((TODAY - started).days, 30)

        for n in range(1, screened_total + 1):
            site_id = trial["site_ids"][n % len(trial["site_ids"])]
            screened = started + timedelta(days=rng.randint(20, span))
            enrolled = n <= enrolled_target
            if enrolled:
                status = rng.choices(
                    ["enrolled", "completed", "withdrawn"], weights=[70, 22, 8]
                )[0]
            else:
                status = "screen_failed"
            row = {
                "id": str(uuid.uuid4()),
                "participant_code": f"{trial['id'].replace('STU', 'AIIA')}-{n:03d}",
                "trial_id": trial["id"],
                "site_id": site_id,
                "screened_date": screened.isoformat(),
                "enrolled_date": (screened + timedelta(days=rng.randint(1, 14))).isoformat()
                if enrolled else None,
                "status": status,
                "arm": rng.choice(["Trial drug", "Control"]) if enrolled else None,
                "age_band": rng.choice(age_bands),
                "sex": rng.choice(["M", "F"]),
                "consent_version": f"v{rng.randint(1,3)}.0",
                "consent_date": screened.isoformat(),
            }
            conn.execute(
                """INSERT INTO participants
                   (id, participant_code, trial_id, site_id, screened_date, enrolled_date,
                    status, arm, age_band, sex, consent_version, consent_date)
                   VALUES (:id,:participant_code,:trial_id,:site_id,:screened_date,:enrolled_date,
                           :status,:arm,:age_band,:sex,:consent_version,:consent_date)""",
                row,
            )
            rows.append(row)
    return rows


# ------------------------------------------------------------------------- visits

VISIT_SCHEDULE = [("Screening", 0), ("Baseline", 14), ("Week 4", 42), ("Week 8", 70), ("Week 12", 98)]


def _seed_visits(
    conn: Connection, rng: random.Random, trials: list[dict], participants: list[dict]
) -> None:
    # Participant visits.
    for participant in participants:
        if participant["status"] == "screen_failed":
            continue
        anchor = date.fromisoformat(participant["enrolled_date"] or participant["screened_date"])
        for name, offset in VISIT_SCHEDULE:
            scheduled = anchor + timedelta(days=offset)
            if scheduled > TODAY:
                status, actual = "upcoming", None
            elif rng.random() < 0.90:
                status = "completed"
                actual = (scheduled + timedelta(days=rng.randint(-2, 5))).isoformat()
            elif (TODAY - scheduled).days > 14:
                status, actual = "missed", None
            else:
                status, actual = "overdue", None
            conn.execute(
                """INSERT INTO visits
                   (id, trial_id, site_id, participant_code, visit_name, scheduled_date,
                    actual_date, window_days, status, monitoring_visit, report_filed)
                   VALUES (?,?,?,?,?,?,?,?,?,0,0)""",
                (
                    str(uuid.uuid4()), participant["trial_id"], participant["site_id"],
                    participant["participant_code"], name, scheduled.isoformat(), actual, 7, status,
                ),
            )

    # Site monitoring visits — quarterly per trial-site. These drive the overdue alert,
    # and a visit conducted but with no report filed still counts as outstanding.
    #
    # Historical visits are essentially all completed, because a portfolio where a
    # quarter of all monitoring never happened is not a dashboard finding, it is a
    # broken institution — and an alert that fires on every trial is one nobody reads.
    # Exactly three trials carry a genuinely missed visit, planted below.
    for trial in trials:
        started = date.fromisoformat(trial["start_date"])
        for site_id in trial["site_ids"]:
            scheduled = started + timedelta(days=90)
            n = 1
            while scheduled <= TODAY + timedelta(days=90):
                if scheduled > TODAY:
                    status, actual, filed = "upcoming", None, 0
                else:
                    status = "completed"
                    actual = (scheduled + timedelta(days=rng.randint(0, 6))).isoformat()
                    # A visit that happened but produced no report is still outstanding.
                    filed = 1 if rng.random() < 0.88 else 0
                conn.execute(
                    """INSERT INTO visits
                       (id, trial_id, site_id, participant_code, visit_name, scheduled_date,
                        actual_date, window_days, status, monitoring_visit, report_filed)
                       VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
                    (
                        str(uuid.uuid4()), trial["id"], site_id, None,
                        f"Monitoring visit {n}", scheduled.isoformat(), actual, 14, status, filed,
                    ),
                )
                scheduled += timedelta(days=90)
                n += 1

    _plant_overdue_monitoring(conn, trials)


#: Trials given a genuinely missed monitoring visit, so the overdue rule has exactly
#: three things to fire on rather than forty.
OVERDUE_MONITORING_STUDIES = {"STU-002": 47, "STU-004": 96, "STU-005": 21}


def _plant_overdue_monitoring(conn: Connection, trials: list[dict]) -> None:
    """Give three trials one overdue monitoring visit each, at known ages.

    Planted rather than left to chance: the demo script names these trials, and a
    generator that sometimes produces four and sometimes none makes the script a lie.
    The ages straddle the 90-day mark so both severity levels of the rule are visible.
    """
    by_id = {s["id"]: s for s in trials}
    for trial_id, days_late in OVERDUE_MONITORING_STUDIES.items():
        trial = by_id.get(trial_id)
        if not trial:
            continue
        scheduled = TODAY - timedelta(days=days_late)
        conn.execute(
            """INSERT INTO visits
               (id, trial_id, site_id, participant_code, visit_name, scheduled_date,
                actual_date, window_days, status, monitoring_visit, report_filed)
               VALUES (?,?,?,NULL,?,?,NULL,14,'overdue',1,0)""",
            (
                str(uuid.uuid4()), trial_id, trial["site_ids"][0],
                "Monitoring visit (not conducted)", scheduled.isoformat(),
            ),
        )


# --------------------------------------------------------------------- deviations


def _seed_deviations(
    conn: Connection, rng: random.Random, trials: list[dict], participants: list[dict]
) -> None:
    by_trial: dict[str, list[dict]] = {}
    for s in participants:
        by_trial.setdefault(s["trial_id"], []).append(s)

    for trial in trials:
        pool = by_trial.get(trial["id"], [])
        if not pool:
            continue
        for _ in range(rng.randint(2, 9)):
            category, description, severity = rng.choice(DEVIATION_CATEGORIES)
            participant = rng.choice(pool)
            detected = date.fromisoformat(participant["screened_date"]) + timedelta(days=rng.randint(5, 90))
            if detected > TODAY:
                detected = TODAY - timedelta(days=rng.randint(1, 30))
            # Major and critical deviations are reportable to the EC. Some have not been
            # reported — that gap is the whole reason the dashboard shows this column.
            reportable = severity in ("major", "critical")
            reported = reportable and rng.random() < 0.7
            conn.execute(
                """INSERT INTO deviations
                   (id, trial_id, site_id, participant_code, category, description,
                    detected_date, severity, reported_to_ec, reported_date, resolution)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), trial["id"], participant["site_id"], participant["participant_code"],
                    category, description, detected.isoformat(), severity,
                    1 if reported else 0,
                    (detected + timedelta(days=rng.randint(1, 5))).isoformat() if reported else None,
                    "Retrained site staff; corrective action documented." if rng.random() < 0.5 else None,
                ),
            )


# ------------------------------------------------------------------------ queries


def _seed_queries(
    conn: Connection, rng: random.Random, trials: list[dict], participants: list[dict]
) -> None:
    by_trial: dict[str, list[dict]] = {}
    for s in participants:
        by_trial.setdefault(s["trial_id"], []).append(s)

    for trial in trials:
        pool = by_trial.get(trial["id"], [])
        if not pool:
            continue
        for _ in range(rng.randint(4, 16)):
            field, question = rng.choice(QUERY_FIELDS)
            participant = rng.choice(pool)
            # Some queries are deliberately old — open-query ageing is a KPI and needs a tail.
            raised = TODAY - timedelta(days=rng.choice([2, 5, 9, 14, 21, 30, 45, 62, 91]))
            status = rng.choices(["open", "answered", "closed"], weights=[35, 20, 45])[0]
            answered = raised + timedelta(days=rng.randint(1, 8)) if status in ("answered", "closed") else None
            closed = answered + timedelta(days=rng.randint(1, 6)) if status == "closed" and answered else None
            conn.execute(
                """INSERT INTO queries
                   (id, trial_id, site_id, participant_code, field, question,
                    raised_date, raised_by, answered_date, closed_date, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), trial["id"], participant["site_id"], participant["participant_code"],
                    field, question, raised.isoformat(), rng.choice(QUERY_RAISERS),
                    answered.isoformat() if answered else None,
                    closed.isoformat() if closed else None, status,
                ),
            )


# ----------------------------------------------------------------- adverse events


#: Non-serious narratives. Deliberately written the way site staff actually write them —
#: "loose stools", not "diarrhoea" — because coding free text is the point of app/pv.py.
AE_ROUTINE = [
    ("mild headache reported on day 3, resolved without treatment", "mild"),
    ("nausea after morning dose, settled within two hours", "mild"),
    ("loose stools for two days, participant continued on trial drug", "mild"),
    ("mild body ache after the evening dose", "mild"),
    ("gastric discomfort after evening dose", "moderate"),
    ("dizziness on standing, blood pressure recorded as normal", "moderate"),
    ("elevated liver enzymes on routine labs, repeat scheduled", "moderate"),
    ("generalised skin rash, antihistamine started", "moderate"),
    ("difficulty sleeping through the night since week 2", "mild"),
    ("tiredness through the day, no other complaint", "mild"),
    ("joint pains in both knees, unchanged from baseline", "moderate"),
    ("dry cough at night, no fever", "mild"),
]

#: Serious events. Six of these are seeded, no more — an SAE rate of one in eight would
#: itself be the headline finding, and would drown the ones that matter.
AE_SERIOUS = [
    ("severe abdominal pain, participant hospitalised for observation", "severe", "not_recovered"),
    ("acute urticaria with facial swelling, emergency admission", "severe", "recovering"),
    ("syncopal episode at home, admitted overnight", "severe", "recovered"),
    ("jaundice with raised bilirubin, trial drug withdrawn", "severe", "not_recovered"),
    ("breathlessness on exertion, admitted for evaluation", "severe", "recovering"),
    ("severe vomiting with dehydration, intravenous fluids given", "severe", "recovered"),
]

#: The safety signal. One trial reports the same skin reaction far more often than the
#: rest of the portfolio — which is invisible in free text and obvious once coded, and
#: is exactly what the DSMB view exists to surface.
SIGNAL_STUDY = "STU-004"
SIGNAL_NARRATIVES = [
    "itching over both forearms, topical relief given",
    "itchy skin over the arms after the morning dose",
    "persistent itching on the forearms, no rash seen",
    "pruritus of both arms reported at the week 4 visit",
    "itching over forearms and neck, settled overnight",
    "complains of itch over the arms since starting trial drug",
    "itching over both forearms again this week",
]


def _insert_ae(
    conn: Connection, rng: random.Random, trial: dict, participant: dict,
    narrative: str, severity: str, serious: bool, outcome: str | None = None,
    reported_hours_ago: float | None = None,
) -> None:
    now = datetime.combine(TODAY, time(12, 0), tzinfo=timezone.utc)

    if reported_hours_ago is not None:
        # Serious events get an exact reporting time, because the 24-hour clock state is
        # what the demo shows and it must not depend on a dice roll.
        reported = now - timedelta(hours=reported_hours_ago)
        onset = reported.date() - timedelta(days=rng.randint(0, 1))
    else:
        onset = TODAY - timedelta(days=rng.randint(1, 120))
        # Reported some hours after onset — the gap is why a clock can already be
        # breached at the moment the event is entered.
        reported = datetime.combine(
            onset, time(rng.randint(8, 20), rng.choice([0, 15, 30, 45])), tzinfo=timezone.utc
        ) + timedelta(hours=rng.randint(1, 30))

    deadline_24h = deadline_14d = None
    timeline_status = "not_applicable"
    if serious:
        deadline_24h = reported + timedelta(hours=settings.sae_initial_report_hours)
        deadline_14d = reported + timedelta(days=settings.sae_narrative_days)
        hours_left = (deadline_24h - now).total_seconds() / 3600
        timeline_status = (
            "breached" if hours_left < 0
            else "due_soon" if hours_left < settings.sae_due_soon_hours
            else "on_track"
        )

    conn.execute(
        """INSERT INTO adverse_events
           (id, trial_id, site_id, participant_code, narrative, onset_date, serious,
            severity, causality, outcome, coded_term, coded_code, coding_confidence,
            coding_source, suspect_drug, drug_code, drug_coding_source,
            reported_at, deadline_24h, deadline_14d, timeline_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,'uncoded',?,NULL,'uncoded',?,?,?,?)""",
        (
            str(uuid.uuid4()), trial["id"], participant["site_id"], participant["participant_code"],
            narrative, onset.isoformat(), 1 if serious else 0, severity,
            rng.choices(
                ["unrelated", "unlikely", "possible", "probable", "certain"],
                weights=[20, 20, 35, 20, 5],
            )[0],
            outcome or rng.choices(
                ["recovered", "recovering", "not_recovered", "recovered_with_sequelae", "unknown"],
                weights=[55, 20, 12, 8, 5],
            )[0],
            trial["title"].split("—")[-1].strip(),
            reported.isoformat(),
            deadline_24h.isoformat() if deadline_24h else None,
            deadline_14d.isoformat() if deadline_14d else None,
            timeline_status,
        ),
    )


def _seed_adverse_events(
    conn: Connection, rng: random.Random, trials: list[dict], participants: list[dict]
) -> None:
    """Around fifty events: routine ones spread across the portfolio, six serious ones,
    and one clustered term in a single trial."""
    by_trial: dict[str, list[dict]] = {}
    for s in participants:
        if s["status"] != "screen_failed":
            by_trial.setdefault(s["trial_id"], []).append(s)

    # Routine events, spread across every trial that has enrolled anyone.
    for trial in trials:
        pool = by_trial.get(trial["id"], [])
        if not pool:
            continue
        for _ in range(rng.randint(2, 6)):
            narrative, severity = rng.choice(AE_ROUTINE)
            _insert_ae(conn, rng, trial, rng.choice(pool), narrative, severity, serious=False)

    # The clustered skin reaction. Same trial, same term, seven times.
    signal_study = next((s for s in trials if s["id"] == SIGNAL_STUDY), None)
    signal_pool = by_trial.get(SIGNAL_STUDY, [])
    if signal_study and signal_pool:
        for narrative in SIGNAL_NARRATIVES:
            _insert_ae(
                conn, rng, signal_study, rng.choice(signal_pool), narrative, "mild", serious=False
            )

    # Six serious events, at fixed reporting times relative to the demo clock. Two are
    # already past their 24-hour deadline, one is inside the final hours, three are on
    # track — so the AE screen shows all three clock states at once, and nobody has to
    # wait for a countdown to run down on stage.
    hours_ago = [216, 30, 20, 8, 3, 1]  # breached, breached, due soon, then on track
    eligible = [s for s in trials if by_trial.get(s["id"])]
    for (narrative, severity, outcome), reported_hours_ago in zip(AE_SERIOUS, hours_ago):
        trial = rng.choice(eligible)
        _insert_ae(
            conn, rng, trial, rng.choice(by_trial[trial["id"]]), narrative, severity,
            serious=True, outcome=outcome, reported_hours_ago=reported_hours_ago,
        )

    # Code every narrative against the curated vocabulary. Done here rather than left to
    # the UI so the portfolio arrives already aggregable — an AE table full of "Uncoded"
    # is a screen that cannot answer a safety question.
    pv.code_uncoded_events(conn, commit=False)


# -------------------------------------------------------------------------- audit


def _seed_audit(conn: Connection, trials: list[dict]) -> None:
    """Lay down a short prior history so the chain is not empty at demo time.

    Timestamps are back-dated to each trial's start; the seeder is the only caller ever
    allowed to pass a timestamp (see `audit.record`).
    """
    for trial in trials:
        audit.record(
            conn,
            actor="system.seed",
            action="create",
            resource_type="trial",
            resource_id=trial["id"],
            after={
                "id": trial["id"],
                "title": trial["title"],
                "protocol_no": trial["protocol_no"],
                "status": trial["status"],
                "target_enrolment": trial["target_enrolment"],
            },
            reason="Synthetic portfolio generated for demonstration. No real trial data.",
            timestamp=_dt(date.fromisoformat(trial["start_date"])),
            commit=False,
        )


# ------------------------------------------------------------------- investigation case


def _seed_case(conn: Connection) -> dict:
    """The AYU-008 case the investigation feature is built on. See `app/case_data.py`.

    Shaped to be investigated rather than to look healthy: enrolment well behind plan,
    and three hepatic events written three different ways, close together in exposure
    time, inside the first monitoring interval. Every figure the case file states is
    computed from these rows at request time — none of it is a caption.
    """
    rng = random.Random(settings.seed_random_seed + 1)
    started = date.fromisoformat(case_data.START_DATE)

    trial = {
        "id": case_data.TRIAL_ID,
        "title": case_data.TITLE,
        "protocol_no": case_data.PROTOCOL_NO,
        "ctri_number": case_data.CTRI_NUMBER,
        "phase": case_data.PHASE,
        "status": "enrolling",
        "therapeutic_area": case_data.THERAPEUTIC_AREA,
        "ec_approval_date": (started - timedelta(days=48)).isoformat(),
        "ec_expiry_date": (started + timedelta(days=317)).isoformat(),
        "ctri_registration_date": (started - timedelta(days=12)).isoformat(),
        "target_enrolment": case_data.TARGET_ENROLMENT,
        "actual_enrolment": case_data.ACTUAL_ENROLMENT,
        "pi_name": case_data.PI_NAME,
        "start_date": case_data.START_DATE,
        "end_date": None,
    }
    conn.execute(
        """INSERT INTO trials
           (id, title, protocol_no, ctri_number, phase, status, therapeutic_area,
            ec_approval_date, ec_expiry_date, ctri_registration_date,
            target_enrolment, actual_enrolment, pi_name, start_date, end_date)
           VALUES (:id,:title,:protocol_no,:ctri_number,:phase,:status,:therapeutic_area,
                   :ec_approval_date,:ec_expiry_date,:ctri_registration_date,
                   :target_enrolment,:actual_enrolment,:pi_name,:start_date,:end_date)""",
        trial,
    )

    # All twelve sites, which is what makes site-level recruitment variation a real
    # thing to look at rather than an assertion.
    site_ids = [r["id"] for r in conn.execute("SELECT id FROM sites ORDER BY id")]
    for site_id in site_ids:
        conn.execute(
            "INSERT INTO trial_sites (trial_id, site_id) VALUES (?,?)",
            (case_data.TRIAL_ID, site_id),
        )

    for kind, offset in (
        ("ec_approval", -48), ("ctri_registration", -12), ("first_site_activated", 6),
        ("first_subject_in", 21), ("fifty_pct_enrolled", 250), ("last_subject_in", 400),
    ):
        planned = started + timedelta(days=offset)
        done = planned <= TODAY and kind != "fifty_pct_enrolled"
        conn.execute(
            """INSERT INTO milestones (id, trial_id, type, planned_date, actual_date, status)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid.uuid4()), case_data.TRIAL_ID, kind, planned.isoformat(),
             planned.isoformat() if done else None, "achieved" if done else "planned"),
        )

    # Enrolment is deliberately concentrated: the first four sites take most of it, so
    # "site-level variation" is visible in the data and not just listed as a factor.
    weights = [0.26, 0.21, 0.16, 0.11] + [0.03] * (len(site_ids) - 4)
    participants: list[dict] = []
    for n in range(1, case_data.ACTUAL_ENROLMENT + 1):
        site_id = rng.choices(site_ids, weights=weights, k=1)[0]
        screened = started + timedelta(days=rng.randint(14, 175))
        participant = {
            "id": str(uuid.uuid4()),
            "participant_code": f"AYU-008-{n:03d}",
            "trial_id": case_data.TRIAL_ID,
            "site_id": site_id,
            "screened_date": screened.isoformat(),
            "enrolled_date": (screened + timedelta(days=rng.randint(3, 10))).isoformat(),
            "status": "enrolled",
            "arm": rng.choice(["Trial drug", "Control"]),
            # Protocol population is 30-65, so no band outside it appears.
            "age_band": rng.choice(["30-39", "40-49", "50-59", "60-69"]),
            "sex": rng.choice(["F", "M"]),
            "consent_version": "v2.1",
            "consent_date": screened.isoformat(),
        }
        conn.execute(
            """INSERT INTO participants
               (id, participant_code, trial_id, site_id, screened_date, enrolled_date,
                status, arm, age_band, sex, consent_version, consent_date)
               VALUES (:id,:participant_code,:trial_id,:site_id,:screened_date,:enrolled_date,
                       :status,:arm,:age_band,:sex,:consent_version,:consent_date)""",
            participant,
        )
        participants.append(participant)

    # Screen failures, so the screen-failure rate the recruitment evidence quotes is a
    # real quotient and not a number typed into a template.
    for n in range(1, 39):
        screened = started + timedelta(days=rng.randint(14, 175))
        conn.execute(
            """INSERT INTO participants
               (id, participant_code, trial_id, site_id, screened_date, enrolled_date,
                status, arm, age_band, sex, consent_version, consent_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), f"AYU-008-S{n:03d}", case_data.TRIAL_ID,
             rng.choice(site_ids), screened.isoformat(), None, "screen_failed", None,
             rng.choice(["30-39", "40-49", "50-59", "60-69"]), rng.choice(["F", "M"]),
             "v2.1", screened.isoformat()),
        )

    # Visits. The 8-week LFT points are named, because the protocol evidence and the
    # event timing are read against them and a visit called "Week 8" would not carry
    # that. Only visits that have come due are created.
    by_code = {s["participant_code"]: s for s in participants}
    for participant in participants:
        enrolled = date.fromisoformat(participant["enrolled_date"])
        for name, day in (
            ("Screening", 0), ("Week 4", 28), ("Week 8 — LFT", 56),
            ("Week 16 — LFT", 112), ("Week 24 — LFT (end of treatment)", 168),
        ):
            scheduled = enrolled + timedelta(days=day)
            if scheduled > TODAY:
                continue
            completed = rng.random() < 0.93
            conn.execute(
                """INSERT INTO visits
                   (id, trial_id, site_id, participant_code, visit_name, scheduled_date,
                    actual_date, window_days, status, monitoring_visit, report_filed)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), case_data.TRIAL_ID, participant["site_id"],
                 participant["participant_code"], name, scheduled.isoformat(),
                 scheduled.isoformat() if completed else None, 7,
                 "completed" if completed else "missed", 0, 0),
            )

    # The three events. Left uncoded on insert and coded below by the same routine that
    # coded the rest of the portfolio — three narratives written three ways arriving at
    # one controlled term is the thing the investigation is about, so it has to actually
    # happen rather than be asserted.
    for number, narrative, day, severity in case_data.AE_CASES:
        participant = by_code[f"AYU-008-{number:03d}"]
        onset = date.fromisoformat(participant["enrolled_date"]) + timedelta(days=day)
        conn.execute(
            """INSERT INTO adverse_events
               (id, trial_id, site_id, participant_code, narrative, onset_date, serious,
                severity, causality, outcome, coding_source, drug_coding_source,
                suspect_drug, reported_at, timeline_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), case_data.TRIAL_ID, participant["site_id"],
             participant["participant_code"], narrative, onset.isoformat(), 0, severity,
             "possible", "recovering", "uncoded", "uncoded", case_data.INTERVENTION,
             _dt(onset + timedelta(days=2), 11), "not_applicable"),
        )

    pv.code_uncoded_events(conn, commit=False)
    return trial


# ----------------------------------------------------------------------------- users

#: One demo account per role, so every lens and every write route can be exercised
#: end to end without inventing a login on the fly. Fixed, documented, demo-only
#: credentials — see README.md and .env.example, both of which say so in the same
#: words: rotate every one of these before any real deployment.
#:
#: (username, password, role, display_name, pi_name)
#: `pi_name` is set only for the principal_investigator account, and is one of the
#: names `_seed_trials` actually assigns — otherwise the investigator lens would
#: scope to a PI with no trials, which demonstrates nothing.
#:
#: `company.demo` and `leadership.demo` correspond to the specification's Company
#: and Leadership roles (see UserRole's docstring). Both have a real write route
#: through the escalation workflow (app/governance.py, /escalations/*): Company
#: submits a structured response to an escalation raised against its trial, and
#: Leadership records the final governance decision. See app/main.py's
#: /portal/company and /portal/leadership routes for their dashboards.
DEMO_USERS = [
    ("volunteer.demo", "CtmsVolunteer#01", "volunteer", "Participant (Demo)", None),
    ("company.demo", "AiiaCompany#01", "company", "Company Operations (Demo)", None),
    ("investigator.demo", "AiiaTrialLead#01", "investigator", "Investigator (Demo)", "Dr. A. Nair"),
    ("safety.demo", "AiiaSafety#01", "safety_officer", "Safety Officer (Demo)", None),
    ("leadership.demo", "AiiaLeadership#01", "leadership", "Leadership (Demo)", None),
]


def _seed_users(conn: Connection) -> None:
    """One account per `UserRole`, with fixed demo-only credentials.

    Passwords are hashed with `auth.hash_password` before they touch the database —
    the same function `auth.authenticate` verifies against — so this seed exercises
    the real hashing path rather than a shortcut that only looks like it.
    """
    for username, password, role, display_name, pi_name in DEMO_USERS:
        password_hash, salt = auth.hash_password(password)
        conn.execute(
            """INSERT INTO users
               (id, username, password_hash, salt, role, display_name, pi_name, active, created_at)
               VALUES (?,?,?,?,?,?,?,1,?)""",
            (
                str(uuid.uuid4()), username, password_hash, salt, role, display_name,
                pi_name, _dt(TODAY),
            ),
        )
    print(f"[datagen] seeded {len(DEMO_USERS)} demo accounts, one per role — "
          f"see README.md for usernames (passwords are not printed)")
