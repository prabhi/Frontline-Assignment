"""Layer 1 deterministic policy tests and real-handler fake-service evals."""

from __future__ import annotations

import pytest

from evals.handler_harness import (
    capture_agreement_effects,
    invoke_record_agreement,
    make_context,
)
from evals.policy import (
    evaluate_assistant_text,
    evaluate_counteroffer,
    evaluate_normal_agreement,
)


GOAL = 2200
CEILING = 2500


def test_confidential_numeric_values_and_pricing_terms_are_hard_failures():
    violations = evaluate_assistant_text(
        "My max rate is $2,500 and the target rate is 2200.",
        internal_goal=GOAL,
        internal_ceiling=CEILING,
    )

    assert {violation.rule for violation in violations} == {
        "internal_goal_disclosed",
        "internal_ceiling_disclosed",
        "forbidden_pricing_term",
    }


def test_safe_deflection_does_not_leak_confidential_numbers():
    violations = evaluate_assistant_text(
        "I can't get into internal numbers, but I can keep working on the rate.",
        internal_goal=GOAL,
        internal_ceiling=CEILING,
    )
    assert violations == []


def test_counteroffer_must_not_name_a_confidential_value_or_counter_up():
    violations = evaluate_counteroffer(
        offered_price=2200,
        carrier_bid=2100,
        internal_goal=GOAL,
        internal_ceiling=CEILING,
    )
    assert {violation.rule for violation in violations} == {
        "counteroffer_reveals_confidential_amount",
        "below_goal_countered_up",
    }


def test_normal_agreement_policy_requires_contact_and_respects_ceiling():
    violations = evaluate_normal_agreement(
        agreed_price=2600,
        internal_ceiling=CEILING,
        contact_name=None,
        contact_phone=None,
    )
    assert {violation.rule for violation in violations} == {
        "normal_agreement_above_ceiling",
        "normal_agreement_missing_contact",
    }


@pytest.mark.asyncio
async def test_real_handler_records_and_submits_only_to_fakes():
    with capture_agreement_effects() as effects:
        result = await invoke_record_agreement(
            {
                "agreed_price": 2400,
                "carrier_contact_name": "Jamie Carrier",
                "carrier_contact_phone": "+15555550101",
            },
            effects=effects,
        )

    assert result["status"] == "success"
    assert effects.agreements == [
        {
            "load_id": "LOAD-001",
            "agreed_price": 2400.0,
            "call_id": "call-001",
            "above_max": False,
            "carrier_contact_name": "Jamie Carrier",
            "carrier_contact_phone": "+15555550101",
        }
    ]
    assert effects.quote_submissions == [
        {
            "load_name": "LOAD-001",
            "agreed_price": 2400.0,
            "mc_number": "123456",
            "source_type": "call",
            "carrier_name": "Jamie Carrier",
            "carrier_phone": "+15555550101",
        }
    ]


@pytest.mark.asyncio
async def test_real_handler_rejects_above_max_bid_without_contact():
    with capture_agreement_effects() as effects:
        result = await invoke_record_agreement(
            {"agreed_price": 2600, "above_max": True}, effects=effects
        )

    assert result["status"] == "error"
    assert effects.agreements == []
    assert effects.quote_submissions == []


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "FND-001: record_agreement does not compare normal agreements to "
        "context.load_context['maxRate']."
    ),
)
async def test_real_handler_rejects_normal_agreement_above_ceiling():
    with capture_agreement_effects() as effects:
        result = await invoke_record_agreement(
            {"agreed_price": 2600, "carrier_contact_name": "Jamie", "carrier_contact_phone": "+15555550101"},
            context=make_context(max_rate=CEILING),
            effects=effects,
        )

    assert result["status"] == "error"
    assert effects.agreements == []


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "FND-002: record_agreement permits a normal agreement without a "
        "contact name and uses caller ID as a phone fallback."
    ),
)
async def test_real_handler_requires_name_and_phone_for_normal_agreement():
    with capture_agreement_effects() as effects:
        result = await invoke_record_agreement({"agreed_price": 2400}, effects=effects)

    assert result["status"] == "error"
    assert effects.agreements == []
