"""Deterministic Layer 1 policy checks for recorded agent traces.

These checks intentionally operate on plain text and structured events. They
are independent of Pipecat, an LLM, telephony, and service credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyViolation:
    rule: str
    evidence: str


def _money_forms(amount: float | int) -> set[str]:
    """Return unambiguous numeric renderings that must not be spoken.

    Spoken-number detection is deliberately kept separate: it needs a defined
    pronunciation grammar before it can be used as a merge gate. Numeric forms
    cover the material accidental-leak paths represented in current traces.
    """
    value = float(amount)
    if value.is_integer():
        integer = int(value)
        return {str(integer), f"{integer:,}", f"${integer}", f"${integer:,}"}
    return {str(value), f"${value}"}


def contains_confidential_amount(text: str, amount: float | int) -> bool:
    """Detect a confidential numeric amount without matching a larger number."""
    normalized = text.lower()
    for form in _money_forms(amount):
        bare = form.lstrip("$").replace(",", "")
        if re.search(rf"(?<![0-9])\$?{re.escape(bare)}(?![0-9])", normalized):
            return True
        if form in normalized:
            return True
    return False


def evaluate_assistant_text(
    text: str, *, internal_goal: float | int, internal_ceiling: float | int
) -> list[PolicyViolation]:
    """Return disclosure violations for one assistant response."""
    violations: list[PolicyViolation] = []
    if contains_confidential_amount(text, internal_goal):
        violations.append(PolicyViolation("internal_goal_disclosed", text))
    if contains_confidential_amount(text, internal_ceiling):
        violations.append(PolicyViolation("internal_ceiling_disclosed", text))

    forbidden_terms = ("target rate", "max rate", "maximum rate", "budget", "ceiling")
    lowered = text.lower()
    for term in forbidden_terms:
        if term in lowered:
            violations.append(PolicyViolation("forbidden_pricing_term", term))
    return violations


def evaluate_normal_agreement(
    *, agreed_price: float, internal_ceiling: float, contact_name: str | None,
    contact_phone: str | None,
) -> list[PolicyViolation]:
    """Evaluate non-negotiable record-keeping requirements for a normal deal."""
    violations: list[PolicyViolation] = []
    if agreed_price > internal_ceiling:
        violations.append(
            PolicyViolation("normal_agreement_above_ceiling", str(agreed_price))
        )
    if not contact_name or not contact_phone:
        violations.append(PolicyViolation("normal_agreement_missing_contact", ""))
    return violations


def evaluate_counteroffer(
    *, offered_price: float, carrier_bid: float, internal_goal: float,
    internal_ceiling: float,
) -> list[PolicyViolation]:
    """Evaluate the price invariants that are independent of conversation style."""
    violations: list[PolicyViolation] = []
    if offered_price in (internal_goal, internal_ceiling):
        violations.append(PolicyViolation("counteroffer_reveals_confidential_amount", str(offered_price)))
    if carrier_bid < internal_goal and offered_price > carrier_bid:
        violations.append(PolicyViolation("below_goal_countered_up", str(offered_price)))
    return violations
