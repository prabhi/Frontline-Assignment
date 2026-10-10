# Offline evaluation harness

This is an evaluation-only addition: **no production behavior changes**. It
does not alter the prompt, call flow, tool registration, or live configuration.
All implemented cases use fixture data and fake services.

## Run

After installing the documented voice-agent and test dependencies:

```bash
cd voice-agent
SUPABASE_URL=http://test-suite.local SUPABASE_SERVICE_ROLE_KEY=test-key \
  python -m pytest tests/test_evaluation_layer1.py tests/test_evaluation_layer2.py tests/test_evaluation_layer3.py tests/test_evaluation_layer4.py -v --tb=short
```

`FND-001`, `FND-002`, and `FND-003` are intentional strict expected failures.
They are documented in `../../docs/EVALUATION_FINDINGS.md`; an unexpected pass
also fails because the finding must then be reviewed.

## Add a case

1. For a pure policy, add a function in `evals/policy.py` and compliant and
   violating examples in `test_evaluation_layer1.py`.
2. For a handler boundary, call the real handler in Layer 2 and patch every
   external dependency at its call site with `MagicMock`, `AsyncMock`, or
   `httpx.MockTransport`.
3. For agent behavior, add `ScriptedTurn`/`ToolEvent` fixtures in Layer 3 and
   assert `evaluate_trace` violations and the judge score.
4. For a speech boundary case, add a synthetic `SpeechFixture` and use
   `VoiceBoundarySimulator` with `FixtureSTT` and `RecordingTTS` in Layer 4.
   Assert the transcript, entity labels, event order, policy result, and the
   captured TTS request; do not add real audio or a provider call.
5. For a current policy gap, add strict `xfail` with an `FND-*` reason and
   document evidence, impact, and smallest fix in the findings file.

Do not add real Daily, OpenAI, Deepgram, Cartesia, Supabase, Slack, KCH, or
Salesforce calls to these tests.

## Not verified against live services

PSTN/Daily connectivity, SIP transfer, real STT accuracy, TTS quality,
provider latency/uptime, database migrations/writes, recording upload, Slack,
KCH submission, and live-model compliance are not verified. Layer 4 simulates
the STT/TTS interfaces only; it does not decode audio or measure recognition
or synthesis quality. A global network-deny guard is also not implemented.

## Illustrative expected pytest output

This is an expected sample, **not an observed test run**. This workspace cannot
run it because `pytest` is unavailable.

```text
tests/test_evaluation_layer1.py::test_confidential_numeric_values_and_pricing_terms_are_hard_failures PASSED
tests/test_evaluation_layer1.py::test_safe_deflection_does_not_leak_confidential_numbers PASSED
tests/test_evaluation_layer1.py::test_counteroffer_must_not_name_a_confidential_value_or_counter_up PASSED
tests/test_evaluation_layer1.py::test_normal_agreement_policy_requires_contact_and_respects_ceiling PASSED
tests/test_evaluation_layer1.py::test_real_handler_records_and_submits_only_to_fakes PASSED
tests/test_evaluation_layer1.py::test_real_handler_rejects_above_max_bid_without_contact PASSED
tests/test_evaluation_layer1.py::test_real_handler_rejects_normal_agreement_above_ceiling XFAIL [FND-001]
tests/test_evaluation_layer1.py::test_real_handler_requires_name_and_phone_for_normal_agreement XFAIL [FND-002]
tests/test_evaluation_layer2.py::test_real_verify_handler_stages_identity_without_persisting PASSED
tests/test_evaluation_layer2.py::test_real_end_handler_blocks_end_after_human_transfer PASSED
tests/test_evaluation_layer2.py::test_real_transfer_handler_requires_confirmed_identity XFAIL [FND-003]
tests/test_evaluation_layer3.py::test_scripted_adapter_and_fake_judge_accept_a_compliant_trace PASSED
tests/test_evaluation_layer3.py::test_trace_evaluator_reports_confidential_leak_and_bad_tool_order PASSED
tests/test_evaluation_layer4.py::test_fixture_stt_returns_labelled_entities_exactly PASSED
tests/test_evaluation_layer4.py::test_voice_simulator_orders_stt_model_tts_and_records_telephony_request PASSED
tests/test_evaluation_layer4.py::test_corrupt_transcript_prompts_for_clarification_without_a_lookup PASSED
tests/test_evaluation_layer4.py::test_voice_simulator_flags_confidential_text_before_recording_tts_request PASSED

======================= 14 passed, 3 xfailed ========================
```
