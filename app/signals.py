"""Safety signal detection — disproportionality across the coded adverse-event set.

This is what coding was *for*. A narrative reading "loose motion" and another reading
"diarrhoea" describe one safety signal and count as none until both carry the same term.
Once they do, the question becomes arithmetic: **is any term reported more often in one
trial than the rest of the portfolio would lead you to expect?**

The measure is the **proportional reporting ratio**, the standard first-pass screen in
pharmacovigilance. For a term T in trial S, over a 2x2 contingency table:

                        term T      other terms
    this trial             a             b
    other trials          c             d

    PRR = (a / (a + b)) / (c / (c + d))

A PRR of 3 means the term accounts for three times the share of this trial's events that
it accounts for elsewhere. The conventional screening threshold is **PRR >= 2 with at
least 3 cases** — the case minimum matters because with a=1 the ratio is arithmetically
enormous and epidemiologically meaningless.

**What this is not.** A signal is a hypothesis for a human to investigate, not a finding
and not a causal claim. Disproportionality says a term is over-represented *relative to
the rest of this dataset*; it says nothing about incidence, and it cannot, because the
denominator is other reports rather than patients exposed. With portfolio counts in the
tens, treat the ranking as a triage order for a Data Safety Monitoring Board and nothing
more. Real practice adds a chi-square or a confidence interval on the PRR; both are
noise at this volume, so we report the case count honestly instead of dressing a small
number in statistics it cannot support.
"""

from __future__ import annotations

from .db import Connection  # driver-neutral: SQLite or Postgres
from dataclasses import dataclass

#: Minimum cases before a ratio is worth showing. Below this the PRR is arithmetic
#: rather than evidence: one case of a rare term in a small trial produces a huge ratio.
MIN_CASES = 3

#: Conventional disproportionality threshold. A term taking twice the share of a trial's
#: events that it takes across the rest of the portfolio is worth a human looking at it.
PRR_THRESHOLD = 2.0


@dataclass(frozen=True)
class Signal:
    trial_id: str
    trial_title: str
    coded_term: str
    coded_code: str
    #: `a` — cases of this term in this trial.
    cases: int
    #: `a + b` — all coded events in this trial.
    trial_events: int
    #: `c` — cases of this term everywhere else.
    other_cases: int
    #: `c + d` — all coded events everywhere else.
    other_events: int
    serious: int
    severe: int
    #: None when the term appears nowhere else — the ratio would be division by zero,
    #: and "unprecedented in the portfolio" is a different statement from "twice as
    #: common", so it is shown as its own state rather than as an infinity.
    prr: float | None

    @property
    def flagged(self) -> bool:
        """Meets the conventional screening criterion."""
        return self.cases >= MIN_CASES and (self.prr is None or self.prr >= PRR_THRESHOLD)

    def as_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "coded_term": self.coded_term,
            "coded_code": self.coded_code,
            "cases": self.cases,
            "serious": self.serious,
            "prr": self.prr,
            "flagged": self.flagged,
            "contingency": {
                "a": self.cases,
                "b": self.trial_events - self.cases,
                "c": self.other_cases,
                "d": self.other_events - self.other_cases,
            },
        }


def detect(conn: Connection, min_cases: int = MIN_CASES) -> list[Signal]:
    """Rank every trial-and-term pair by PRR, strongest first.

    Uncoded events are excluded from both sides of the ratio rather than counted as a
    category. They are an absence of information, and letting them inflate the
    denominator would quietly depress every PRR in the portfolio.
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM adverse_events WHERE coded_term IS NOT NULL"
    ).fetchone()[0]
    if not total:
        return []

    per_trial = {
        r["trial_id"]: r["n"]
        for r in conn.execute(
            """SELECT trial_id, COUNT(*) AS n FROM adverse_events
                WHERE coded_term IS NOT NULL GROUP BY trial_id"""
        )
    }
    per_term = {
        r["coded_term"]: r["n"]
        for r in conn.execute(
            """SELECT coded_term, COUNT(*) AS n FROM adverse_events
                WHERE coded_term IS NOT NULL GROUP BY coded_term"""
        )
    }

    signals: list[Signal] = []
    for row in conn.execute(
        """SELECT a.trial_id, s.title AS trial_title, a.coded_term, a.coded_code,
                  COUNT(*) AS cases,
                  SUM(a.serious) AS serious,
                  SUM(CASE WHEN a.severity = 'severe' THEN 1 ELSE 0 END) AS severe
             FROM adverse_events a JOIN trials s ON s.id = a.trial_id
            WHERE a.coded_term IS NOT NULL
            -- s.title is grouped explicitly rather than left bare: SQLite allows a
            -- non-aggregated column here and Postgres rejects it.
            GROUP BY a.trial_id, s.title, a.coded_term, a.coded_code
           HAVING COUNT(*) >= ?""",
        (min_cases,),
    ):
        a = row["cases"]
        trial_events = per_trial[row["trial_id"]]
        other_cases = per_term[row["coded_term"]] - a
        other_events = total - trial_events

        # Division by zero has two distinct causes and they mean different things:
        # no other events at all (nothing to compare against) versus this term never
        # seen elsewhere (which is itself the finding). Both give None, not infinity.
        if other_events == 0 or other_cases == 0:
            prr = None
        else:
            prr = round((a / trial_events) / (other_cases / other_events), 2)

        signals.append(
            Signal(
                trial_id=row["trial_id"],
                trial_title=row["trial_title"],
                coded_term=row["coded_term"],
                coded_code=row["coded_code"],
                cases=a,
                trial_events=trial_events,
                other_cases=other_cases,
                other_events=other_events,
                serious=row["serious"] or 0,
                severe=row["severe"] or 0,
                prr=prr,
            )
        )

    # Unprecedented terms (prr is None) sort above measured ones: a term seen nowhere
    # else in the portfolio is the strongest form of the same observation.
    return sorted(
        signals,
        key=lambda s: (not s.flagged, s.prr is not None, -(s.prr or 0.0), -s.cases),
    )


if __name__ == "__main__":
    from .db import connect

    found = detect(connect())
    print(f"{len(found)} trial/term pair(s) with >= {MIN_CASES} cases")
    for s in found:
        ratio = "no other cases" if s.prr is None else f"PRR {s.prr:>5.2f}"
        flag = "SIGNAL" if s.flagged else "      "
        print(f"  {flag}  {s.trial_id}  {s.coded_term:<20} n={s.cases:<3} "
              f"{ratio:<16} serious={s.serious}")
