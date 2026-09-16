"""Pharmacovigilance — term coding and statutory reporting clocks.

Two jobs.

**Coding.** A free-text narrative ("patient had a bad headache") is matched to a
controlled term ("Headache", VW-T0001) so events can be counted, compared across
trials, and surfaced as a safety signal. Free text cannot be aggregated; two sites
writing "loose motion" and "diarrhoea" describe one signal and count as none.

The vocabulary is `app/terms.csv` — **our own, written for this demonstration.**
MedDRA and WHODrug are the real dictionaries and they are licensed; we do not have
them, we do not approximate them, and every coded result carries `source="curated"`
so nothing downstream can quietly imply otherwise. The interface is the part that
matters: swap the CSV for a licensed dictionary and `code()` does not change.

**Clocks.** New Drugs and Clinical Trials Rules 2019, Third Schedule: a serious adverse
event must reach the Ethics Committee and the licensing authority **within 24 hours** of
the investigator becoming aware of it, with a full narrative **within 14 days**. Those
deadlines are stored fields computed from the server clock at intake, not a countdown
drawn over a date — the moment the clock started is itself a regulated fact and has to
survive a refresh, an export and an inspection.

*Storing the deadline and storing the status are two different things, and only the first
one is safe.* The deadline is an input fact: it never changes. The status is a conclusion
about *now*, so a stored status is wrong the instant the clock crosses a boundary while
nobody is looking at the page. Every status this module reports is therefore **derived on
read** from the stored deadline by `status_for` / `with_live_status` / `clock_counts`; the
stored `timeline_status` column is retained as an intake-time snapshot for the record and
is never treated as truth. All three helpers default to `models.utcnow()`, normalise any
aware offset to UTC, and read a naive timestamp as UTC rather than raising.

A serious event whose 24-hour deadline is *missing or unreadable* must never render as
safe. There is no separate enum member for that state in `models.TimelineStatus`, so the
conservative reading is used — `BREACHED`, i.e. "do not treat this as on track" — and
`clock_reason()` / `with_live_status()['clock_unknown']` / `clock_counts()['unknown']`
carry the distinction explicitly so the interface can say *why*.

**What this clock is not.** `CLOCK_PROTOTYPE_LIMITATIONS` records the limits in code:
the regulatory applicability of these periods to a given trial is not established here,
and no external submission timestamp is recorded, so a derived status describes the
passage of a deadline and not whether a filing was in fact late.
"""

from __future__ import annotations

import csv
import difflib
import re
from .db import Connection  # driver-neutral: SQLite or Postgres
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import settings
from .models import CodingSource, TimelineStatus, utcnow

#: The one clock this module reads. Aware-only by construction (`utcnow` is aware UTC),
#: which is what makes the naive/aware comparison crash impossible here.
UTC = timezone.utc

#: Honest limits of the clock as built, kept in code rather than in a slide.
#: Each entry is a gap in what this module can actually support.
CLOCK_PROTOTYPE_LIMITATIONS: tuple[str, ...] = (
    "Prototype clock: the applicability of the 24-hour and 14-day periods to any "
    "particular trial is not established here. A derived status reports the passage of "
    "a stored deadline, and is not a legal or regulatory finding.",
    "No external submission timestamp is recorded. The system knows when an event was "
    "entered and therefore when its deadline falls; it does not know when the Ethics "
    "Committee or the licensing authority actually received a report. 'Breached' means "
    "the deadline passed, not that a filing was late.",
    "Timestamps are normalised to UTC. A naive stored or supplied timestamp is read as "
    "UTC, which is the right assumption for this system's own records and the wrong one "
    "for a timestamp captured in local time elsewhere.",
    "The clock is driven by the server clock at read time. Nothing notifies anyone when "
    "a deadline passes; the state changes only when a screen, an alert run or an export "
    "recomputes it.",
)

TERMS_CSV = Path(__file__).resolve().parent / "terms.csv"

#: Below this, a fuzzy match is a guess rather than a suggestion, and a wrong coded term
#: is worse than an uncoded one — it hides an event inside the wrong bucket.
#:
#: Set at 0.80 rather than higher because morphological variants land there:
#: "syncopal" against "syncope" scores 0.80, and letting a serious event go uncoded to
#: avoid a weak second suggestion is the wrong trade. `MIN_FUZZY_LEN` is what keeps this
#: floor safe; without it, 0.80 would code half the portfolio as flatulence.
FUZZY_FLOOR = 0.80

#: Fuzzy matching is only attempted on synonyms at least this long. Short ones score
#: absurdly well against unrelated words — "gas" against "as" rates 0.80 — so a low
#: minimum turns a routine note into a spurious gastrointestinal event. Short synonyms
#: still match exactly and as phrases; they just do not get to guess.
MIN_FUZZY_LEN = 7

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Coding must not care that one site wrote "Head-ache." and another "head ache".
    """
    return _SPACE.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


@dataclass(frozen=True)
class Term:
    code: str
    term: str
    soc: str
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class CodingResult:
    code: str
    term: str
    soc: str
    confidence: float
    #: How the match was made — shown in the UI so a 0.78 fuzzy hit is never mistaken
    #: for an exact one.
    method: str
    source: CodingSource = CodingSource.CURATED

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "term": self.term,
            "soc": self.soc,
            "confidence": self.confidence,
            "method": self.method,
            "source": self.source.value,
        }


@lru_cache(maxsize=1)
def load_terms(path: str | None = None) -> tuple[Term, ...]:
    """Read the vocabulary once. Synonyms are normalised at load, not per query."""
    with open(path or TERMS_CSV, newline="", encoding="utf-8") as fh:
        return tuple(
            Term(
                code=row["code"],
                term=row["term"],
                soc=row["soc"],
                synonyms=tuple(
                    normalise(s) for s in (row["synonyms"] or row["term"]).split("|") if s.strip()
                ),
            )
            for row in csv.DictReader(fh)
        )


def _phrase_present(phrase: str, text: str) -> bool:
    """Whole-word containment.

    Word boundaries are not optional here: "mi" and "gas" are legitimate synonyms and
    both appear inside dozens of unrelated words. Plain substring matching would code
    "administered" as a myocardial infarction.
    """
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _best_window_ratio(phrase: str, words: list[str]) -> float:
    """Best `difflib` ratio between a synonym and any same-length run of words.

    Comparing a two-word synonym against a forty-word narrative always scores near zero,
    because most of the narrative is irrelevant to the match. Sliding a window the size
    of the synonym is what lets "diarhea" find "diarrhoea" inside a full sentence.
    """
    n = len(phrase.split())
    best = 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(words) - size + 1)):
            window = " ".join(words[i : i + size])
            ratio = difflib.SequenceMatcher(None, phrase, window).ratio()
            if ratio > best:
                best = ratio
    return best


def code(narrative: str, limit: int = 3) -> list[CodingResult]:
    """Match a narrative to controlled terms, best first.

    Three passes, in descending order of trust:

    1. **exact** — the whole narrative is the synonym. Confidence 1.0.
    2. **phrase** — the synonym appears as whole words inside the narrative. Confidence
       scales with how much of the narrative the phrase accounts for, so "headache" in a
       three-word note is a stronger signal than the same word buried in a paragraph.
    3. **fuzzy** — `difflib` over a sliding window, for typos and spelling variants.

    Returns an empty list rather than a low-confidence guess when nothing clears the
    floor. Uncoded is an honest state; miscoded is not.
    """
    text = normalise(narrative)
    if not text:
        return []
    words = text.split()
    hits: dict[str, CodingResult] = {}

    for entry in load_terms():
        best: tuple[float, str] | None = None

        for syn in entry.synonyms:
            if syn == text:
                best = (1.0, "exact")
                break
            if _phrase_present(syn, text):
                # Coverage: how much of the note this phrase accounts for, floored so a
                # confirmed phrase match never drops into fuzzy territory.
                coverage = len(syn.split()) / max(len(words), 1)
                score = round(min(0.97, 0.85 + 0.12 * coverage), 3)
                if best is None or score > best[0]:
                    best = (score, "phrase")

        if best is None:
            ratio = max(
                (_best_window_ratio(s, words) for s in entry.synonyms if len(s) >= MIN_FUZZY_LEN),
                default=0.0,
            )
            if ratio >= FUZZY_FLOOR:
                best = (round(ratio, 3), "fuzzy")

        if best is not None:
            existing = hits.get(entry.code)
            if existing is None or best[0] > existing.confidence:
                hits[entry.code] = CodingResult(
                    code=entry.code, term=entry.term, soc=entry.soc,
                    confidence=best[0], method=best[1],
                )

    return sorted(hits.values(), key=lambda r: (-r.confidence, r.term))[:limit]


def code_best(narrative: str) -> CodingResult | None:
    """The single best match, or None if nothing cleared the floor."""
    results = code(narrative, limit=1)
    return results[0] if results else None


def code_uncoded_events(conn: Connection, commit: bool = True) -> int:
    """Code every adverse event that has no term yet. Returns how many were coded.

    Used by the seeder, and safe to re-run: an event that already has a term is left
    alone, so a re-run never overwrites a human's coding decision with a machine's.
    """
    rows = conn.execute(
        "SELECT id, narrative FROM adverse_events WHERE coded_term IS NULL"
    ).fetchall()
    n = 0
    for row in rows:
        result = code_best(row["narrative"])
        if result is None:
            continue
        conn.execute(
            """UPDATE adverse_events
                  SET coded_term = ?, coded_code = ?, coding_confidence = ?, coding_source = ?
                WHERE id = ?""",
            (result.term, result.code, result.confidence, result.source.value, row["id"]),
        )
        n += 1
    if commit:
        conn.commit()
    return n


# ------------------------------------------------------------------------- clocks


#: Reasons a clock cannot be evaluated. `ok` is the only one that permits a status of
#: ON_TRACK; the other two are the states that must never be rendered as safe.
REASON_OK = "ok"
REASON_NOT_SERIOUS = "not_serious"
REASON_MISSING = "deadline_missing"
REASON_MALFORMED = "deadline_malformed"

#: The set of reasons that mean "the clock is unknown, do not show this as safe".
UNKNOWN_REASONS = (REASON_MISSING, REASON_MALFORMED)

#: Column holding the 24-hour reporting deadline. Named once so the helpers below cannot
#: drift from each other.
DEADLINE_FIELD = "deadline_24h"
NARRATIVE_DEADLINE_FIELD = "deadline_14d"


# ------------------------------------------------------------------ time handling


def as_utc(value: datetime) -> datetime:
    """Normalise any timestamp to aware UTC.

    A naive timestamp is *read as UTC*, not rejected: every timestamp this system writes
    is UTC, so a naive one is a serialisation that lost its offset rather than a local
    time. The alternative — raising — would take a page down over a formatting detail.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a stored timestamp to aware UTC. `None` when absent or unreadable.

    Accepts ISO-8601 text (with `Z` or an offset), a `datetime`, a `date`, or `None`.
    Never raises: a malformed deadline is a state the callers must handle, not an
    exception that turns the adverse-event screen into a 500.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, date):
        return as_utc(datetime.combine(value, time(0, 0)))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return as_utc(parsed)


def _field(event: Any, name: str, default: Any = None) -> Any:
    """Read a column from a row, a mapping, or a model. Missing means `default`.

    `sqlite3.Row` raises `IndexError` for an unknown key and a dict raises `KeyError`;
    both mean the caller did not select the column, which is not worth an exception in a
    helper whose whole job is to be safe about incomplete input. An object that is not
    subscriptable at all (a pydantic model) falls through to attribute access, so a
    column read works the same whether the caller hands over a row or a model.
    """
    try:
        return event[name]
    except (KeyError, IndexError, TypeError):
        return getattr(event, name, default)


def _now(now: datetime | None) -> datetime:
    """The reference instant: the caller's, normalised, or the real server clock."""
    return utcnow() if now is None else as_utc(now)


def is_serious(event: Any) -> bool:
    """Whether a row/model represents a serious event.

    Booleans arrive as `True`, `1`, `"1"` or `"true"` depending on the driver and on
    whether the row came from SQLite, Postgres or pydantic; all four are accepted so a
    driver switch cannot silently stop a clock from starting.
    """
    value = _field(event, "serious", False)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "t", "yes")
    return bool(value)


def event_deadline(event: Any, field: str = DEADLINE_FIELD) -> datetime | None:
    """The stored deadline as aware UTC, or `None` if it is missing or unreadable."""
    return parse_timestamp(_field(event, field))


def clock_reason(event: Any) -> str:
    """Why a clock reads the way it does.

    One of `REASON_NOT_SERIOUS`, `REASON_MISSING`, `REASON_MALFORMED`, `REASON_OK`.
    The distinction matters because a serious event with no readable deadline is a data
    defect that has to be visible, not a safe event.
    """
    if not is_serious(event):
        return REASON_NOT_SERIOUS
    raw = _field(event, DEADLINE_FIELD)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return REASON_MISSING
    return REASON_OK if event_deadline(event) is not None else REASON_MALFORMED


def _hours_between(deadline: datetime, now: datetime) -> float:
    """Unrounded signed hours, so boundary comparisons are not decided by rounding."""
    return (deadline - now).total_seconds() / 3600


def status_for_deadline(deadline: datetime | None, now: datetime | None = None) -> TimelineStatus:
    """Live status for a deadline, using the same boundaries as intake and the seeder.

    * `hours_left <= 0` — the deadline has arrived or passed: `BREACHED`. The boundary is
      inclusive because a deadline is a moment, not a direction of travel; a clock that
      reads "0 hours left" has run out.
    * `hours_left <= sae_due_soon_hours` — inside the warning window: `DUE_SOON`.
    * otherwise `ON_TRACK`.

    `None` — no deadline — is `BREACHED`: a serious event with no readable deadline must
    not read as safe. See the module docstring for why the conservative reading is taken.
    """
    if deadline is None:
        return TimelineStatus.BREACHED
    hours_left = _hours_between(as_utc(deadline), _now(now))
    if hours_left <= 0:
        return TimelineStatus.BREACHED
    if hours_left <= settings.sae_due_soon_hours:
        return TimelineStatus.DUE_SOON
    return TimelineStatus.ON_TRACK


def status_for(event: Any, now: datetime | None = None) -> TimelineStatus:
    """The live status of one adverse-event row: derived, never the stored column.

    A non-serious event has no statutory clock and is `NOT_APPLICABLE`. A serious event is
    classified from its stored `deadline_24h` against `now` (default: the real server
    clock, aware UTC). A serious event whose deadline is missing or unreadable is
    `BREACHED`, never `ON_TRACK` — an absent deadline must not look like a met one.
    """
    if not is_serious(event):
        return TimelineStatus.NOT_APPLICABLE
    if event_deadline(event) is None:
        return TimelineStatus.BREACHED
    return status_for_deadline(event_deadline(event), now)


def with_live_status(event: Any, now: datetime | None = None) -> dict:
    """The row as a dict, with the live status written over the stored one.

    Returns every stored column the caller selected, plus:

    `timeline_status`         live, derived (overwrites the stored value for consumers)
    `stored_timeline_status`  the intake-time snapshot, kept for the record but unused
    `clock_reason`            `ok` / `not_serious` / `deadline_missing` / `deadline_malformed`
    `clock_unknown`           True when the deadline is unusable and the status is a
                              conservative BREACHED rather than a measured one
    `hours_left`              signed hours to the 24-hour deadline, `None` when unknown
    `status_source`           `"derived"`, so a consumer cannot mistake the value for a
                              stored field

    Templates render `timeline_status` and therefore show the live state without any
    change; nothing here reads the stored column as truth.
    """
    reference = _now(now)
    # A pydantic model is not iterable into `dict()`; take its field mapping instead, so
    # a model and the row it came from round-trip the same way.
    row = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    deadline = event_deadline(event)
    row["stored_timeline_status"] = _field(event, "timeline_status")
    row["timeline_status"] = status_for(event, reference).value
    row["clock_reason"] = clock_reason(event)
    row["clock_unknown"] = clock_reason(event) in UNKNOWN_REASONS
    # No deadline means no meaningful hours: `None`, not a fabricated large number.
    row["hours_left"] = None if deadline is None else round(_hours_between(deadline, reference), 1)
    row["status_source"] = "derived"
    return row


def clock_counts(conn: Connection, now: datetime | None = None) -> dict:
    """Live counts of every adverse event by derived 24-hour clock state.

    Keys:

    `total`          every adverse event examined
    `serious`        serious events — the events that carry a statutory clock
    `breached`       serious events whose deadline has arrived or passed
    `due_soon`       serious events inside the warning window
    `on_track`       serious events outside it
    `not_applicable` non-serious events, which carry no clock
    `unknown`        serious events whose deadline is missing or unreadable
    `unknown_event_ids`  their ids, so a screen can name them

    `breached + due_soon + on_track + not_applicable == total`, always: the buckets
    partition the table. `unknown` is *not* a fifth bucket — those events are already
    counted in `breached` by the conservative reading — it is a subset marker, so
    `unknown <= breached`. A consumer that alerts on `breached` therefore covers them,
    and one that wants to say "and N of these have no recorded deadline" can.
    """
    reference = _now(now)
    counts = {
        "total": 0, "serious": 0, "breached": 0,
        "due_soon": 0, "on_track": 0, "not_applicable": 0,
    }
    unknown_ids: list[Any] = []
    for row in conn.execute(
        "SELECT id, serious, deadline_24h, timeline_status FROM adverse_events ORDER BY id"
    ):
        counts["total"] += 1
        counts[status_for(row, reference).value] += 1
        if is_serious(row):
            counts["serious"] += 1
            if clock_reason(row) in UNKNOWN_REASONS:
                unknown_ids.append(_field(row, "id"))
    counts["unknown"] = len(unknown_ids)
    counts["unknown_event_ids"] = tuple(unknown_ids)
    return counts


def compute_clocks(
    reported_at: datetime, serious: bool, now: datetime | None = None
) -> tuple[datetime | None, datetime | None, TimelineStatus]:
    """Return `(deadline_24h, deadline_14d, timeline_status)` for one event.

    Called on intake, where the returned deadlines are stored and the status is stored
    with them as a snapshot (see the module docstring — the snapshot is never read back
    as truth; `status_for` recomputes it).

    A non-serious AE carries no statutory clock at all — `NOT_APPLICABLE` rather than a
    deadline nobody owes. Reporting a non-serious event as if it had a 24-hour deadline
    would be as wrong as missing a real one.

    `reported_at` is normalised to aware UTC, so a caller handing over a naive timestamp
    or a `+05:30` offset gets deadlines on the same instant in the same representation:
    storage never mixes naive and aware rows, and no later comparison can crash on it.
    `now` defaults to the real server clock.
    """
    if not serious:
        return None, None, TimelineStatus.NOT_APPLICABLE

    reported = as_utc(reported_at)
    deadline_24h = reported + timedelta(hours=settings.sae_initial_report_hours)
    deadline_14d = reported + timedelta(days=settings.sae_narrative_days)

    return deadline_24h, deadline_14d, status_for_deadline(deadline_24h, now)


def hours_remaining(deadline: datetime | str | None, now: datetime | None = None) -> float | None:
    """Signed hours to a deadline. Negative means the deadline has passed — the sign is
    the point, so this deliberately does not clamp at zero.

    Accepts a stored ISO-8601 string as well as a `datetime`, and normalises both sides
    to aware UTC. Returns `None` for a missing or unreadable deadline: "unknown" and
    "zero hours left" are different things and must not be conflated. `now` defaults to
    the real server clock.
    """
    parsed = parse_timestamp(deadline)
    if parsed is None:
        return None
    return round(_hours_between(parsed, _now(now)), 1)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print('usage: python -m app.pv "free text narrative"')
        raise SystemExit(2)

    narrative = " ".join(sys.argv[1:])
    results = code(narrative)
    print(f'"{narrative}"')
    print(f"  normalised: {normalise(narrative)}")
    if not results:
        print(f"  no term above the {FUZZY_FLOOR} confidence floor — left uncoded")
        raise SystemExit(1)
    for i, r in enumerate(results):
        marker = "→" if i == 0 else " "
        print(f"  {marker} {r.term:<32} {r.code}  {r.confidence:.2f}  {r.method:<6} source={r.source.value}")
    print(f"  ({len(load_terms())} terms in app/terms.csv — curated for this demo, not MedDRA)")
