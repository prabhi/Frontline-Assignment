"""Layer 4 fake speech boundaries for safe, repeatable voice evaluations.

The classes in this module model only the contracts at the speech boundaries.
They do not open audio files, call an STT/TTS provider, or produce audio. This
makes known transcript outcomes testable without credentials or phone calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from evals.policy import PolicyViolation
from evals.trace import ScriptedModelAdapter, ScriptedTurn, evaluate_trace


@dataclass(frozen=True)
class SpeechFixture:
    """Synthetic STT result and the entities expected from its transcript."""

    audio_id: str
    transcript: str
    entities: Mapping[str, str] = field(default_factory=dict)


class FixtureSTT:
    """In-memory replacement for STT; returns only explicitly supplied fixtures."""

    def __init__(self, fixtures: list[SpeechFixture]):
        self._fixtures = {fixture.audio_id: fixture for fixture in fixtures}
        self.calls: list[str] = []

    def transcribe(self, audio_id: str) -> SpeechFixture:
        self.calls.append(audio_id)
        return self._fixtures[audio_id]


@dataclass(frozen=True)
class TTSRequest:
    """A TTS request captured instead of being sent to Cartesia."""

    text: str
    settings: Mapping[str, object]


class RecordingTTS:
    """No-op TTS fake which retains every requested synthesis operation."""

    def __init__(self) -> None:
        self.requests: list[TTSRequest] = []

    def synthesize(self, text: str, *, settings: Mapping[str, object]) -> None:
        self.requests.append(TTSRequest(text=text, settings=dict(settings)))


@dataclass(frozen=True)
class VoiceSimulationResult:
    """Inspectable evidence from one deterministic STT -> model -> TTS pass."""

    transcript: str
    turn: ScriptedTurn
    events: tuple[str, ...]
    violations: tuple[PolicyViolation, ...]


class VoiceBoundarySimulator:
    """Connect fake STT/TTS to the Layer 3 scripted-model and trace evaluator.

    ``prior_turns`` lets a case establish trusted state such as a successful
    carrier verification without relying on a live model or a production call.
    """

    def __init__(
        self,
        *,
        stt: FixtureSTT,
        model: ScriptedModelAdapter,
        tts: RecordingTTS,
        internal_goal: float,
        internal_ceiling: float,
        prior_turns: tuple[ScriptedTurn, ...] = (),
    ) -> None:
        self._stt = stt
        self._model = model
        self._tts = tts
        self._internal_goal = internal_goal
        self._internal_ceiling = internal_ceiling
        self._prior_turns = prior_turns

    def run(self, audio_id: str) -> VoiceSimulationResult:
        fixture = self._stt.transcribe(audio_id)
        turn = self._model.respond(fixture.transcript)
        violations = evaluate_trace(
            [*self._prior_turns, turn],
            internal_goal=self._internal_goal,
            internal_ceiling=self._internal_ceiling,
        )
        self._tts.synthesize(
            turn.assistant_text,
            settings={"channel": "telephony", "sample_rate": 8000},
        )
        return VoiceSimulationResult(
            transcript=fixture.transcript,
            turn=turn,
            events=("stt", "model", "tts"),
            violations=tuple(violations),
        )
