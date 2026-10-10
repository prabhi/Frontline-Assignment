"""Layer 2 contracts against real handlers with fake external boundaries."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import call_helpers
from transfer_tool_handler import TransferToolHandler


async def _callback_collector(results: list[dict], payload: str, **_kwargs) -> None:
    results.append(json.loads(payload))


@pytest.mark.asyncio
async def test_real_verify_handler_stages_identity_without_persisting():
    context = SimpleNamespace()
    results: list[dict] = []
    upsert = MagicMock()
    carrier = {"data": {"dbaName": "ACME TRUCKING", "mcNumber": "123456"}}

    with (
        patch.object(call_helpers, "fetch_carrier_by_mc", new=AsyncMock(return_value=carrier)),
        patch.object(call_helpers.NegotiationDBService, "upsert_carrier_phone", new=upsert),
    ):
        await call_helpers.verify_carrier(
            "verify_carrier", "eval-verify", {"mc_number": "123456"}, None,
            context, lambda payload, **kwargs: _callback_collector(results, payload, **kwargs),
        )

    assert results[-1]["status"] == "success"
    assert context.caller_mc == "123456"
    assert context.carrier_name == "Acme Trucking"
    assert context.awaiting_carrier_identity_confirmation is True
    upsert.assert_not_called()


@pytest.mark.asyncio
async def test_real_end_handler_blocks_end_after_human_transfer():
    context = SimpleNamespace(call_mode="HUMAN_ONLY")
    results: list[dict] = []

    await call_helpers.end_call(
        "end_call", "eval-end", {"reason": "agreement"}, None, context,
        lambda payload, **kwargs: _callback_collector(results, payload, **kwargs),
    )

    assert results == [{"status": "ignored", "message": "Call already transferred to human. end_call ignored."}]
    assert not hasattr(context, "end_reason")


def _transfer_handler() -> tuple[TransferToolHandler, MagicMock]:
    orchestrator = MagicMock()
    handler = TransferToolHandler(
        orchestrator=orchestrator,
        http_session=MagicMock(), stt=MagicMock(), tts=MagicMock(), llm=MagicMock(),
        skip_tts_processor=MagicMock(), transcript=MagicMock(), speech_sync=MagicMock(),
        audiobuffer=MagicMock(), context_aggregator=MagicMock(),
    )
    handler._speech_sync.schedule_after_speech = AsyncMock()
    return handler, orchestrator


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="FND-003: transfer handler requires a load but does not require confirmed carrier identity.",
)
async def test_real_transfer_handler_requires_confirmed_identity():
    handler, orchestrator = _transfer_handler()
    context = SimpleNamespace(
        load_uuid="LOAD-001", carrier_identity_confirmed=False, caller_mc=None
    )
    results: list[dict] = []
    load = {"id": "LOAD-001", "load_id": "LOAD-001", "carrier_sales_rep_phone": "+15555550101"}

    with patch("transfer_tool_handler.NegotiationDBService.get_load", return_value=load):
        await handler.handle_transfer_to_human(
            "transfer_to_human", "eval-transfer",
            {"reason": "asked for a person", "load_number": "LOAD-001"}, None,
            context, lambda payload, **kwargs: _callback_collector(results, payload, **kwargs),
        )

    assert results[-1]["status"] == "error"
    orchestrator.set_transfer_metadata.assert_not_called()
