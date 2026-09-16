"""Server-side work queues — filter, search, sort, paginate (prompt.md §10.2).

One honest mechanism for every queue-shaped surface in the product — the AE
register, PRR signals, the escalation inbox, operational alerts, and the audit
trail. It exists because the alternative is what the codebase had before: five
tables with five ad-hoc (or absent) filter bars, none of which survived a
refresh.

The contract this module keeps, per the brief:

* **Filter state lives in the URL.** Every control is a plain GET form or a
  link; a bookmarked URL reproduces the view exactly. That is also why there
  are no "saved views" — durable named views need a persistence table and
  audited writes, which do not exist, and §10.2 forbids faking them.
* **Search is scoped to identifiers.** Queue search matches record ids,
  participant codes, coded terms and the raiser's name — never clinical
  narrative text (§0.1's query-string rule). What a field may be searched is
  declared per surface in `search_keys`, not assumed.
* **Sort and filter allowlists are explicit.** A param naming an unknown
  filter or sort falls back to the default rather than raising or, worse,
  interpolating into SQL. The audit trail's SQL path builds its WHERE clause
  only from the same declared specs.
* **Counts are honest.** `matched` is the post-filter total across all pages,
  `total` the pre-filter population, so the UI can distinguish "no records",
  "no matches" and "page beyond range" instead of silently rendering zero.

Two execution paths, one interface:

* `apply(rows, spec, args)` — in-Python, for datasets that are *derived* in
  Python anyway (AEs carry a live clock status from `pv.with_live_status`,
  signals come from `signals.detect`, alerts from `alerts.evaluate`). Running
  SQL first and re-deriving after would sort by stale snapshots.
* `audit_query(conn, args)` — SQL, because the audit table is the one surface
  that can grow past comfortable in-memory sizes, and its filters map cleanly
  onto columns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .db import Connection

#: Rows per page. Small enough that a page is a screenful, large enough that
#: the seeded portfolio never needs more than a handful of pages.
PER_PAGE = 15


# --------------------------------------------------------------------------- specs


@dataclass(frozen=True)
class FilterSpec:
    """One allowlisted filter.

    `param`   — the query-string name (`?clock=breached`).
    `label`   — human label for the active-filter summary.
    `options` — (value, label) pairs rendered as a <select>. Empty means the
                route supplies them dynamically (e.g. trials).
    `key`     — row accessor: the row value compared (case-insensitively) to
                the selected option. `None` means a custom `match` is used.
    `match`   — optional custom predicate `(row, value) -> bool`.
    """

    param: str
    label: str
    options: tuple[tuple[str, str], ...] = ()
    key: str | None = None
    match: Callable[[Any, str], bool] | None = None

    def test(self, row: Any, value: str) -> bool:
        if self.match is not None:
            return self.match(row, value)
        current = row.get(self.key) if isinstance(row, dict) else getattr(row, self.key, None)
        if current is None:
            return False
        if isinstance(current, bool):
            return value == ("1" if current else "0")
        return str(current).lower() == value.lower()


@dataclass(frozen=True)
class SortSpec:
    """One allowlisted sort. `key` sorts ascending; `desc=True` reverses the
    DEFAULT direction only — the reader can still flip it with `dir`."""

    param: str
    label: str
    key: Callable[[Any], Any]
    desc: bool = False


@dataclass(frozen=True)
class QueueSpec:
    """The full declaration of one queue surface."""

    name: str
    search_keys: tuple[str, ...] = ()
    search_label: str = "Search"
    filters: tuple[FilterSpec, ...] = ()
    sorts: tuple[SortSpec, ...] = ()
    default_sort: str = ""
    per_page: int = PER_PAGE

    def sort(self, param: str | None) -> SortSpec:
        for s in self.sorts:
            if s.param == param:
                return s
        # Unknown/absent sort params fall back to the declared default, never
        # to the caller's string.
        for s in self.sorts:
            if s.param == self.default_sort:
                return s
        return self.sorts[0]


@dataclass
class QueueResult:
    """What a route hands its template. `params` is the cleaned echo of the
    query string — the only values allowed back into URLs — so a template can
    never resurrect a rejected param."""

    rows: list[Any]
    matched: int
    total: int
    page: int
    pages: int
    per_page: int
    q: str
    sort: SortSpec
    desc: bool
    active: list[str] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)

    @property
    def filtered(self) -> bool:
        return bool(self.q) or bool(self.active)

    @property
    def showing_from(self) -> int:
        return 0 if not self.rows else (self.page - 1) * self.per_page + 1

    @property
    def showing_to(self) -> int:
        return (self.page - 1) * self.per_page + len(self.rows)


def _clean_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return min(max(int(value), lo), hi)
    except (TypeError, ValueError):
        return default


def apply(rows: Iterable[Any], spec: QueueSpec, args: Any) -> QueueResult:
    """Filter, search, sort and paginate `rows` against the request's `args`.

    `args` is anything mapping-like (Starlette's QueryParams included). Rows
    may be dicts (`pv.with_live_status` output) or objects with attributes
    (signal/alert dataclasses are converted by the route first).
    """
    population = [dict(r) if not isinstance(r, dict) else r for r in rows]
    total = len(population)

    q = (args.get("q") or "").strip()
    active: list[str] = []
    params: dict[str, str] = {}

    # --- filters -------------------------------------------------------------
    out = population
    for f in spec.filters:
        value = (args.get(f.param) or "").strip()
        if not value:
            continue
        valid = {v for v, _ in f.options}
        if valid and value not in valid:
            continue  # reject silently: an unknown option is no filter at all
        option_label = next((lbl for v, lbl in f.options if v == value), value)
        out = [r for r in out if f.test(r, value)]
        active.append(f"{f.label}: {option_label}")
        params[f.param] = value

    # --- search --------------------------------------------------------------
    if q and spec.search_keys:
        needle = q.lower()

        def hit(row: dict) -> bool:
            for key in spec.search_keys:
                value = row.get(key)
                if value is not None and needle in str(value).lower():
                    return True
            return False

        out = [r for r in out if hit(r)]
        params["q"] = q

    matched = len(out)

    # --- sort ----------------------------------------------------------------
    # `dir` is the DISPLAYED direction, always: dir=desc means the largest
    # value reads first, regardless of what the spec considers natural. Absent,
    # it defaults to the spec's natural direction. It is echoed only when it
    # differs from that natural direction, which keeps URLs short and stable.
    sort = spec.sort(args.get("sort"))
    dir_param = (args.get("dir") or "").lower()
    desc = sort.desc if dir_param not in ("asc", "desc") else (dir_param == "desc")
    out = sorted(out, key=sort.key, reverse=desc)
    params["sort"] = sort.param
    if desc != sort.desc:
        params["dir"] = "desc" if desc else "asc"

    # --- paginate ------------------------------------------------------------
    pages = max(1, math.ceil(matched / spec.per_page))
    page = _clean_int(args.get("page"), 1, 1, pages)
    start = (page - 1) * spec.per_page
    if page > 1:
        params["page"] = str(page)

    return QueueResult(
        rows=out[start : start + spec.per_page],
        matched=matched,
        total=total,
        page=page,
        pages=pages,
        per_page=spec.per_page,
        q=q,
        sort=sort,
        desc=desc,
        active=active,
        params=params,
    )


# ------------------------------------------------------------------ audit (SQL)
#
# The audit trail is the exception that earns a SQL path: it is the one queue
# whose population can outgrow memory, and its filters are plain columns. The
# allowlists below are the same discipline as QueueSpec — a param outside them
# does not reach the WHERE clause.

AUDIT_ACTIONS = ("create", "update", "delete", "view")

#: Resource types a reader can meaningfully filter by. Deliberately not built
#: from a DISTINCT scan per request — the vocabulary is small and stable.
AUDIT_RESOURCE_TYPES = (
    "adverse_event", "ae_code", "ai_finding", "appointment", "audit_log",
    "consent_form", "consent_record", "corrective_action", "eligibility_criterion",
    "escalation", "leadership_decision", "participant", "registration_form",
    "registration_submission", "statutory_clock", "trial",
)

_AUDIT_SORTS = {"seq": "seq", "time": "timestamp_utc", "actor": "actor", "action": "action"}


def audit_query(conn: Connection, args: Any, per_page: int = 25) -> dict[str, Any]:
    """Filtered, sorted, paginated audit events — in SQL.

    Returns a dict the template reads exactly like a QueueResult, plus
    `actors` (for the filter select) and the cleaned `params` echo. Chain
    verification is unaffected by anything here: it always walks the full
    table (`audit.verify`), and the template says so next to the filters.
    """
    where, params, active, echo = [], [], [], {}

    actor = (args.get("actor") or "").strip()
    action = (args.get("action") or "").strip().lower()
    rtype = (args.get("resource_type") or "").strip().lower()
    date_from = (args.get("date_from") or "").strip()
    date_to = (args.get("date_to") or "").strip()
    q = (args.get("q") or "").strip()

    if actor:
        where.append("actor = ?")
        params.append(actor)
        active.append(f"Actor: {actor}")
        echo["actor"] = actor
    if action in AUDIT_ACTIONS:
        where.append("action = ?")
        params.append(action)
        active.append(f"Action: {action}")
        echo["action"] = action
    if rtype in AUDIT_RESOURCE_TYPES:
        where.append("resource_type = ?")
        params.append(rtype)
        active.append(f"Resource: {rtype.replace('_', ' ')}")
        echo["resource_type"] = rtype
    from datetime import date

    def _iso_day(value: str) -> str | None:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return None

    bad_date = False
    if date_from:
        day = _iso_day(date_from)
        if day is None:
            bad_date = True
        else:
            where.append("timestamp_utc >= ?")
            params.append(f"{day}T00:00:00")
            active.append(f"From: {day}")
            echo["date_from"] = day
    if date_to:
        day = _iso_day(date_to)
        if day is None:
            bad_date = True
        else:
            where.append("timestamp_utc <= ?")
            params.append(f"{day}T23:59:59.999999")
            active.append(f"To: {day}")
            echo["date_to"] = day
    if q:
        # Identifiers only: actor name, resource id, resource type. `reason`
        # and the JSON payloads are deliberately not searched from a URL.
        like = f"%{q}%"
        where.append("(resource_id LIKE ? OR actor LIKE ?)")
        params.extend((like, like))
        echo["q"] = q

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    matched = conn.execute(f"SELECT COUNT(*) FROM audit_events{clause}", params).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

    sort_param = (args.get("sort") or "seq").strip()
    column = _AUDIT_SORTS.get(sort_param, "seq")
    direction = "ASC" if (args.get("dir") or "").lower() == "asc" else "DESC"
    echo["sort"] = sort_param if sort_param in _AUDIT_SORTS else "seq"
    if direction == "ASC":
        echo["dir"] = "asc"

    pages = max(1, math.ceil(matched / per_page))
    page = _clean_int(args.get("page"), 1, 1, pages)
    if page > 1:
        echo["page"] = str(page)

    rows = conn.execute(
        f"SELECT * FROM audit_events{clause} ORDER BY {column} {direction}, seq DESC LIMIT ? OFFSET ?",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()

    actors = [
        r[0]
        for r in conn.execute("SELECT DISTINCT actor FROM audit_events ORDER BY actor").fetchall()
    ]

    return {
        "rows": rows,
        "matched": matched,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "active": active,
        "params": echo,
        "actors": actors,
        "filtered": bool(active or q),
        "q": q,
        "sort": sort_param if sort_param in _AUDIT_SORTS else "seq",
        "dir": direction.lower(),
        "showing_from": 0 if not rows else (page - 1) * per_page + 1,
        "showing_to": (page - 1) * per_page + len(rows),
        "filter_error": "Dates must use YYYY-MM-DD; the unparseable date was ignored."
        if bad_date
        else None,
    }
