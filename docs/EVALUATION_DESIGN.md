# Voice agent evaluation design

## Purpose

This design gives the team a safe, repeatable way to evaluate the freight
negotiation agent before prompt, tool, or integration changes merge. It keeps
the existing single-prompt/Pipecat architecture intact. The default suite has
no production credentials, makes no network requests, creates no Daily rooms,
and writes no production data.

The highest-risk outcomes are a confidential-rate disclosure, accepting a
rate above the ceiling, a fabricated lookup result, an incorrect tool sequence,
an incomplete agreement, and an unsafe transfer. The evaluation suite measures
those outcomes directly rather than treating prompt text alone as evidence.

## Safety and test doubles

**Every evaluation uses fake services.** This follows the repository's current
test pattern:

- use `unittest.mock.MagicMock`/`AsyncMock` for orchestration, Pipecat
  collaborators, callbacks, and database methods;
- inject `httpx.MockTransport` for API clients, never a real HTTP transport;
- patch a service at the call site (for example,
  `NegotiationDBService.get_load` or `fetch_carrier_by_mc`), as the existing
  voice-agent tests do;
- provide in-memory fixture data for carriers, loads, tool results, quotes,
  notifications, transcripts, and audio metadata.

The current harness patches the write/network boundaries it invokes. A global
network-deny guard is planned hardening, not a completed feature; until then,
tests must patch every invoked boundary at its call site. Test credentials,
when an import requires them, are non-secret placeholders such as
`http://test-suite.local` and `test-key`.

External service boundaries are always replaced as follows:

| Production boundary | Evaluation double |
| --- | --- |
| Daily PSTN, rooms, SIP, dial-out | no-op room/transfer recorder |
| OpenAI conversation model | scripted model adapter returning fixture turns/tool calls |
| Deepgram STT | fixture transcript adapter |
| Cartesia TTS | text/audio-request recorder |
| Supabase and Storage | in-memory repository / patched DB methods |
| Highway and legacy carrier API | `AsyncMock` carrier responses |
| KCH quote API and Salesforce | `httpx.MockTransport` responses |
| Slack | no-op notification recorder |

## Four layers

### Implementation status

| Layer | Current status | Implementation |
| --- | --- | --- |
| 1: policy/data contracts | Implemented | `evals/policy.py`, `test_evaluation_layer1.py` |
| 2: handler contracts | Implemented, scoped | `handler_harness.py`, Layer 1–2 tests |
| 3: scripted agent trace | Implemented, offline only | `trace.py`, `test_evaluation_layer3.py` |
| 4: voice-boundary simulation | Implemented, simulated interface | `evals/voice.py`, `test_evaluation_layer4.py` |

The implementation adds evaluation-only modules and tests. It does not alter
the prompt, call flow, tool registration, handler behavior, or runtime config.

### Layer 1 — deterministic policy and data contracts

This is the fastest required CI layer. It exercises pure functions and a
policy evaluator over fixture conversation events. It does not import or run a
voice pipeline.

Implemented scenarios cover numeric confidential-value detection, forbidden
pricing terms, above-ceiling/missing-contact policy, and countering upward
after a below-goal bid. Load-reference and end-reason coverage remains in the
existing functional suite rather than this new layer.

Metrics:

- **hard-rule pass rate:** 100%;
- **fixture coverage:** each required policy has a compliant and a violating
  example;
- **confidential-value detection:** 100% recall for numeric and normalized
  written forms in the fixture corpus;
- **price arithmetic accuracy:** 100% for zone and ceiling checks;
- **runtime:** reported, with a target of seconds rather than minutes.

A hard-rule failure blocks a merge. Hard rules include exposing an internal
goal/ceiling, a normal agreement above the ceiling, fabricated lookup results,
and malformed references reaching a lookup.

### Layer 2 — tool-handler and state-machine contracts

This layer calls existing handlers directly with `MagicMock`/`AsyncMock`
dependencies. It verifies the stateful boundaries that prompts alone cannot
guarantee.

Implemented scenarios call real handlers for successful MC verification without
premature persistence, normal and above-max agreement writes, quote-submission
intent, end-call blocking after human transfer, and transfer identity
preconditions. Existing tests cover phone-first precedence, malformed load
IDs, routing, and several transfer failures. Additional branches remain work.

Metrics:

- **tool-contract pass rate:** 100%;
- **tool-order pass rate:** 100% for fixture traces;
- **side-effect containment:** 100% of writes, notifications, and quote
  submissions are captured by fakes; zero real calls;
- **branch coverage:** each success, not-found, validation-error, and
  dependency-error branch represented by a fixture;
- **diagnostic completeness:** every failure reports scenario, event sequence,
  expected state, actual state, and captured fake side effects.

This layer should explicitly expose current gaps instead of masking them. For
example, the present `record_agreement` handler does not enforce the ceiling
or contact details for a normal agreement; an evaluation should report that as
an unmet intended policy until product behavior is changed deliberately.

### Layer 3 — prompt/agent trace evaluation with an LLM-judge interface

The system prompt remains the production prompt. A scripted model adapter is
given caller turns and returns a fixture assistant message plus fixture tool
calls. The trace is then checked by the deterministic policy evaluator.

The adapter is deliberately fake in the required suite: no OpenAI call is
made. The initial implementation includes a compliant agreement trace and a
negative trace that leaks the ceiling and requests a load before verification.
The remaining adversarial cases are an explicit fixture-expansion backlog.

An injected **LLM-judge interface** assesses qualitative dimensions that are
not safe to gate with string rules: concise natural speech, helpfulness of a
budget deflection, negotiation coherence, and handoff usefulness. Required CI
uses a deterministic fake judge returning versioned fixture scores. This tests
the harness and report format without a model dependency.

Metrics:

- **hard-policy pass rate:** 100%; deterministic evaluator remains the source
  of truth for safety;
- **required-tool selection/order:** 100% for golden traces;
- **judge rubric score:** reported by criterion (target >=4/5 for golden
  compliant traces); never overrides a hard-policy failure;
- **judge/expected agreement:** 100% on the calibrated fixture set;
- **trace coverage:** all high-risk call paths and their negative variants.

The judge input must treat transcript text as data, require structured JSON
with evidence, and avoid production PII. A live judge is intentionally outside
the default framework: it would require an approved evaluation key and cannot
be called a deterministic, credential-free test.

### Layer 4 — voice-boundary and end-to-end simulation

This layer evaluates the speech interfaces without using real speech services.
`FixtureSTT` returns labelled synthetic transcripts and `RecordingTTS` records
the text and requested telephony settings. `VoiceBoundarySimulator` connects
those fakes to the Layer 3 scripted-model adapter and policy evaluator. The
production single prompt and pipeline remain unchanged; this is an evaluation
adapter, not a second agent implementation.

The implemented cases cover labelled MC/load/price entities, STT -> model ->
TTS sequencing, clarification after a corrupt transcript without a lookup, and
detecting confidential text in a recorded TTS request. They use text and
metadata fixtures only: no audio is decoded, generated, uploaded, or sent to a
provider.

The corpus must include MC numbers, load references, prices, names, yes/no
confirmations, noise/error variants, and number-word variants such as “one
two three” and “eighteen-five”. It should use only consented or synthetic
audio/metadata fixtures; no caller recordings are required.

Metrics:

- **STT fixture entity exact-match rate:** 100% for the labelled MC, load ID,
  and price fixture; phone and yes/no variants are backlog;
- **downstream safety rate:** 100%: an ambiguous or corrupt entity must prompt
  for clarification, not cause a lookup/agreement;
- **TTS request correctness:** 100% of emitted text preserves allowed public
  numbers and excludes confidential values/tool names;
- **pipeline sequencing:** 100%: transcript -> assistant response -> tool
  event -> TTS request follows expected order;
- **voice-fixture coverage:** one clean entity fixture and one corrupt/noise
  clarification fixture are implemented; phone, confirmation, and further
  misrecognition variants are backlog.

This is an interface simulation, not a Deepgram or Cartesia quality claim. It
proves handling of known synthetic transcription outcomes and records what
would be sent to TTS; it does not assess acoustic recognition or synthesized
audio quality.

## Nondeterminism

Default CI is deterministic: fixed fixture inputs, scripted model output,
fixed fake-judge result, and no clock/network dependency. It must be
repeatable bit-for-bit apart from explicitly ignored timing fields.

If an approved future model-in-the-loop or speech-provider benchmark is added,
it must remain separate from the merge-blocking offline suite:

1. use isolated evaluation credentials and the same fake tools;
2. run each scenario at least five times;
3. report per-run traces and aggregate pass rate, never only an average;
4. treat any confidentiality, price-ceiling, or unsafe-tool failure as an
   immediate failure;
5. version the model/provider, prompt, fixtures, temperature, and evaluator;
6. use a calibrated judge and preserve the evidence used for each judgment.

This optional benchmark informs release decisions; it does not make the test
suite dependent on an external model or provider.

## Reports and interpretation

Each run should emit machine-readable JSON and a concise human-readable
summary. A failure must identify the scenario, source layer, caller/assistant
turn, tool event, violated rule, expected result, actual result, and fake side
effect log. Reports must never contain credentials or real phone numbers.

## Assumptions and limitations

- Fixture loads accurately represent the normalized production load contract,
  including opening rate, internal goal, ceiling, routing, and requirements.
- Intended product policy is that confidential-rate disclosure and an
  above-ceiling normal agreement are release-blocking failures.
- The suite validates behavior against scripted transcripts and model traces;
  it does not prove live GPT compliance.
- It does not verify real PSTN connectivity, Daily SIP transfer, Deepgram
  transcription accuracy, Cartesia naturalness, provider latency/uptime,
  Supabase migrations, recording uploads, Slack delivery, or KCH submission.
- Those integrations require separately authorized staging tests with
  development resources and are explicitly outside this safe fake-service
  framework.
