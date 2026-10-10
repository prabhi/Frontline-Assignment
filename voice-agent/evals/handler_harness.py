"""Fake-service harness for calling the production agreement handler.

The handler is not copied or reimplemented. Tests call
``call_helpers.record_agreement`` and patch only its write boundaries, so the
captured effects describe precisely what production code attempted to persist
or submit.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import call_helpers


@dataclass
class RecordedEffects:
    """All write-like operations attempted by one real handler invocation."""

    agreements: list[dict[str, Any]] = field(default_factory=list)
    quote_submissions: list[dict[str, Any]] = field(default_factory=list)
    callbacks: list[dict[str, Any]] = field(default_factory=list)


def make_context(
    *, load_id: str = "LOAD-001", caller_phone: str = "+15555550100",
    caller_mc: str = "123456", max_rate: float = 2500,
) -> SimpleNamespace:
    """Build the minimal context shape consumed by ``record_agreement``."""
    return SimpleNamespace(
        load_uuid=load_id,
        call_id="call-001",
        caller_phone=caller_phone,
        caller_mc=caller_mc,
        load_context={"load_id": load_id, "maxRate": max_rate},
    )


@contextmanager
def capture_agreement_effects() -> Iterator[RecordedEffects]:
    """Patch all record/quote write boundaries used by the real handler."""
    effects = RecordedEffects()

    def save_agreement(
        load_id: str, agreed_price: float, call_id: str | None, above_max: bool,
        contact_name: str | None, contact_phone: str | None,
    ) -> str:
        effects.agreements.append(
            {
                "load_id": load_id,
                "agreed_price": agreed_price,
                "call_id": call_id,
                "above_max": above_max,
                "carrier_contact_name": contact_name,
                "carrier_contact_phone": contact_phone,
            }
        )
        return "fake-negotiation-001"

    def submit_quote(**kwargs: Any) -> None:
        effects.quote_submissions.append(kwargs)

    with (
        patch.object(call_helpers, "save_agreement", new=MagicMock(side_effect=save_agreement)),
        patch.object(
            call_helpers.NegotiationDBService,
            "notify_carrier_quote",
            new=MagicMock(side_effect=submit_quote),
        ),
    ):
        yield effects


async def invoke_record_agreement(
    arguments: dict[str, Any], *, context: SimpleNamespace | None = None,
    effects: RecordedEffects,
) -> dict[str, Any]:
    """Invoke the production handler and decode its callback result."""
    if context is None:
        context = make_context()

    async def callback(payload: str, **_kwargs: Any) -> None:
        effects.callbacks.append(json.loads(payload))

    await call_helpers.record_agreement(
        "record_agreement", "eval-tool-call", arguments, None, context, callback
    )
    return effects.callbacks[-1]
