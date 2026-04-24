"""Hardcoded plan catalogue.

Deliberately not a DB table in Phase 5a: plans change rarely, we want
them versioned in git next to the code that keys off them, and a
runtime swap can't accidentally reduce a paying customer's quota. A
plan rename / price change ships as a code change + migration if the
`plan_code` itself rotates.

When we add Mollie in Phase 5b, each Plan will also carry a
`mollie_price_id` — the Mollie product/subscription template it maps
to. Stays here, still version-controlled.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    code: str                  # immutable identifier stored on Subscription rows
    name: str                  # display name
    price_eur_cents: int       # 0 for free; integer cents to avoid float drift
    monthly_scan_quota: int    # scans per calendar month; 0 = unlimited
    description: str

    @property
    def is_free(self) -> bool:
        return self.price_eur_cents == 0

    @property
    def is_unlimited(self) -> bool:
        return self.monthly_scan_quota == 0


# Catalogue. Order matters — used in marketing pages / upgrade flows.
_PLAN_LIST: tuple[Plan, ...] = (
    Plan(
        code="free",
        name="Free",
        price_eur_cents=0,
        monthly_scan_quota=5,
        description=(
            "Kick the tires — 5 scans per month, full feature set, no credit "
            "card required."
        ),
    ),
    Plan(
        code="pro",
        name="Pro",
        price_eur_cents=1900,   # 19.00 EUR
        monthly_scan_quota=100,
        description=(
            "For consultants and small teams — 100 scans per month, priority "
            "support, PDF branding."
        ),
    ),
    Plan(
        code="business",
        name="Business",
        price_eur_cents=9900,   # 99.00 EUR
        monthly_scan_quota=1000,
        description=(
            "Large agencies and in-house DPOs — 1000 scans per month, multi-"
            "user workspaces, SLA response."
        ),
    ),
)

DEFAULT_PLAN_CODE = "free"

PLANS: dict[str, Plan] = {p.code: p for p in _PLAN_LIST}


def list_plans() -> list[Plan]:
    return list(_PLAN_LIST)


def get_plan(code: str | None) -> Plan:
    """Return the plan matching ``code``, falling back to the free tier
    when the argument is missing or unknown. Callers should treat a
    missing subscription row as "free"."""
    if code is None:
        return PLANS[DEFAULT_PLAN_CODE]
    return PLANS.get(code, PLANS[DEFAULT_PLAN_CODE])
