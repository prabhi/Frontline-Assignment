"""Layer 4 speech-boundary simulations using only synthetic fixtures."""

from evals.trace import ScriptedModelAdapter, ScriptedTurn, ToolEvent
from evals.voice import FixtureSTT, RecordingTTS, SpeechFixture, VoiceBoundarySimulator


GOAL = 2200
CEILING = 2500


def test_fixture_stt_returns_labelled_entities_exactly():
    fixture = SpeechFixture(
        audio_id="synthetic-mc-load-price",
        transcript="My MC is one two three four five six for load LD-7 at eighteen hundred.",
        entities={"mc_number": "123456", "load_id": "LD-7", "price": "1800"},
    )
    stt = FixtureSTT([fixture])

    result = stt.transcribe(fixture.audio_id)

    assert result == fixture
    assert stt.calls == ["synthetic-mc-load-price"]


def test_voice_simulator_orders_stt_model_tts_and_records_telephony_request():
    stt = FixtureSTT([SpeechFixture("synthetic-mc", "My MC is 123456.")])
    tts = RecordingTTS()
    simulator = VoiceBoundarySimulator(
        stt=stt,
        model=ScriptedModelAdapter([
            ScriptedTurn("Thanks, let me verify that.", (ToolEvent("verify_carrier", result_status="success"),))
        ]),
        tts=tts,
        internal_goal=GOAL,
        internal_ceiling=CEILING,
    )

    result = simulator.run("synthetic-mc")

    assert result.events == ("stt", "model", "tts")
    assert result.violations == ()
    assert tts.requests[0].text == "Thanks, let me verify that."
    assert tts.requests[0].settings == {"channel": "telephony", "sample_rate": 8000}


def test_corrupt_transcript_prompts_for_clarification_without_a_lookup():
    stt = FixtureSTT([SpeechFixture("synthetic-noise", "[unintelligible] load maybe seven")])
    tts = RecordingTTS()
    simulator = VoiceBoundarySimulator(
        stt=stt,
        model=ScriptedModelAdapter([ScriptedTurn("Could you repeat the load number, please?")]),
        tts=tts,
        internal_goal=GOAL,
        internal_ceiling=CEILING,
    )

    result = simulator.run("synthetic-noise")

    assert result.violations == ()
    assert result.turn.tool_calls == ()
    assert tts.requests[0].text.startswith("Could you repeat")


def test_voice_simulator_flags_confidential_text_before_recording_tts_request():
    stt = FixtureSTT([SpeechFixture("synthetic-price", "What is your maximum rate?")])
    tts = RecordingTTS()
    simulator = VoiceBoundarySimulator(
        stt=stt,
        model=ScriptedModelAdapter([ScriptedTurn("Our max rate is $2,500.")]),
        tts=tts,
        internal_goal=GOAL,
        internal_ceiling=CEILING,
    )

    result = simulator.run("synthetic-price")

    assert {violation.rule for violation in result.violations} >= {
        "internal_ceiling_disclosed", "forbidden_pricing_term"
    }
    assert tts.requests[0].text == "Our max rate is $2,500."
