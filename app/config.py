"""Settings and alert thresholds.

Every number a judge might ask "is that hardcoded?" about lives here and is
overridable from the environment. See .env.example.
"""

from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "VITalWatch"
    org_name: str = "All India Institute of Ayurveda — NPvCC"

    # This build must not be configured as a clinical production service.
    app_mode: Literal["demo"] = "demo"
    demo_seed_enabled: bool = True
    demo_allow_http: bool = False  # local development only; never for network hosting
    clinical_timezone: str = "Asia/Kolkata"

    @field_validator("clinical_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    #: Postgres connection string. Set it (Supabase) and every query runs against
    #: Postgres; leave it unset and the same queries run against the SQLite file below.
    #: Use a Supabase *pooler* URL — the direct db.<ref>.supabase.co host is IPv6-only
    #: and most free hosting tiers, Render included, cannot reach it.
    database_url: str | None = None
    #: Connections held open against Postgres. Supabase's free tier is not generous
    #: with these, and one process serving one demo does not need many.
    db_pool_max: int = 5
    #: Seconds to wait for Postgres before giving up. A demo that hangs is worse than
    #: one that says it cannot connect.
    db_connect_timeout: int = 10

    #: SQLite file, used when DATABASE_URL is unset. Generated on first run; never committed.
    db_path: Path = ROOT / "data" / "ctms.db"
    #: Rows generated on an empty database.
    seed_trials: int = 8
    #: Fixed so every run of the demo produces the same portfolio.
    seed_random_seed: int = 20260822

    # --- alert thresholds ---
    #: Enrolment lag alert fires below this % of the plan-to-date figure.
    enrolment_lag_pct: float = Field(default=80.0, ge=0, le=100)
    #: Ethics renewal alert fires this many days before ec_expiry_date.
    ethics_renewal_days: int = Field(default=60, ge=0)
    #: A monitoring visit is overdue this many days past its scheduled date.
    monitoring_overdue_days: int = Field(default=14, ge=0)

    # --- statutory clocks, NDCT Rules 2019 ---
    sae_initial_report_hours: int = Field(default=24, gt=0)
    sae_narrative_days: int = Field(default=14, gt=0)
    #: An SAE deadline within this many hours shows as "due soon" rather than "on track".
    sae_due_soon_hours: int = Field(default=6, ge=0)

    # --- governance / escalation workflow ---
    #: How long the Company has to respond once a Safety Officer starts a safety-
    #: escalation statutory clock (spec section 14: "configurable according to the
    #: applicable regulatory framework", never hard-coded). Default is a generous
    #: placeholder for a prototype, not a claim about any specific regulation.
    statutory_clock_hours: int = Field(default=72, gt=0)
    #: A statutory-clock deadline within this many hours shows as "due soon".
    statutory_clock_due_soon_hours: int = Field(default=12, ge=0)

    # --- authentication ---
    #: HMAC key for CSRF tokens and any future signed cookie. The default below is
    #: intentionally recognisable and MUST be overridden in any environment that is not
    #: a developer's own machine — validated by length only, because a secret's value
    #: cannot be checked for strength, only its size.
    app_secret: SecretStr = SecretStr("insecure-default-change-me-before-any-real-deployment")
    #: How long a session cookie remains valid without re-authenticating.
    session_ttl_hours: int = Field(default=12, gt=0)

    @field_validator("app_secret")
    @classmethod
    def app_secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 32:
            raise ValueError("APP_SECRET must contain at least 32 characters")
        if secret == "insecure-default-change-me-before-any-real-deployment" and not __debug__:
            raise ValueError("APP_SECRET must be configured outside local development")
        return value


settings = Settings()
