# Evaluation findings

This file records known policy gaps discovered by the offline evaluation suite.
They are strict expected failures: an unexpected pass is also a failure because
the finding and its test then need review. The tests could not execute in this
workspace because `pytest` is unavailable; evidence below is static inspection
plus tests written directly against the relevant real handlers.

## FND-001 — normal agreement can exceed the load ceiling

`call_helpers.record_agreement` accepts an arbitrary positive `agreed_price`
for a normal agreement. It does not compare the value with
`context.load_context["maxRate"]`. The prompt says the ceiling must never be
exceeded, so a model/tool-call error can record and submit an above-ceiling
normal agreement.

Expected-failure test: `test_real_handler_rejects_normal_agreement_above_ceiling`.

**Evidence:** the handler converts `agreed_price` to `float`, calls
`save_agreement`, then `notify_carrier_quote`; it never reads
`load_context["maxRate"]`. The test supplies 2,600 against a 2,500 ceiling.

**Impact:** an unsafe tool call can persist and submit a rate the prompt forbids.

**Smallest fix:** before `save_agreement`, reject a normal agreement above the
loaded ceiling; preserve `above_max=True` for above-ceiling follow-up bids.

## FND-002 — normal agreement contact fields are not required

The prompt requires name and phone before any agreement is recorded. The
handler requires them only for `above_max=True`; for a normal agreement it can
record no name and substitutes caller ID when phone is absent.

Expected-failure test: `test_real_handler_requires_name_and_phone_for_normal_agreement`.

**Evidence:** contact validation is only inside `if above_max`; normal calls
can omit name and use `context.caller_phone` as fallback.

**Impact:** a rate can be recorded/submitted without the promised carrier contact.

**Smallest fix:** require non-empty name and phone before every agreement
write. If caller ID is an approved phone source, use it only after name exists.

## FND-003 — transfer does not require confirmed carrier identity

`TransferToolHandler.handle_transfer_to_human` checks that a load exists and
has broker routing, but it does not inspect verified/confirmed carrier state.
The prompt requires carrier verification before transfer; a direct model tool
call can bypass that prerequisite once a load UUID is present.

Expected-failure test: `test_real_transfer_handler_requires_confirmed_identity`.

**Evidence:** the transfer handler checks load UUID, load existence, and
routing, but not `carrier_identity_confirmed`, `caller_mc`, or an equivalent.

**Impact:** a direct model tool call can transfer an unverified caller to a broker.

**Smallest fix:** reject unless a backend-owned confirmation flag is true, or
centralize the trusted identity predicate and use it in both identity flows.

## Not a handler finding: confidential speech remains prompt-only

No production component inspects assistant text before TTS. The Layer 1
policy evaluator therefore makes a confidential goal/ceiling disclosure a
hard trace-evaluation failure, but it cannot currently prevent the live model
from speaking one. This requires either a deliberately approved runtime guard
or reliable model-level evaluation; neither is silently introduced by this
test suite.

**Evidence:** assistant text flows from the LLM directly to TTS; Layer 4 now
records a synthetic TTS request and flags a fixture leak, but cannot intercept
a live reply.

**Impact:** confidential-rate compliance remains probabilistic during a call.

**Smallest fix:** this change intentionally adds no runtime guard. First expand
the trace/model and voice-fixture corpus; any pre-TTS guard needs an explicit
product decision about its false-positive behavior.
