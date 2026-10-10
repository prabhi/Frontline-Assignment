"""Layer 3 scripted-model trace evaluator and deterministic judge seam.

No model is called here.  ``ScriptedModelAdapter`` deliberately supplies
fixture turns, making the state-machine and policy checks repeatable in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evals.policy import PolicyViolation, evaluate_assistant_text, evaluate_normal_agreement


@dataclass(frozen=True)
class ToolEvent:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_status: str | None = None


@dataclass(frozen=True)
class ScriptedTurn:
    assistant_text: str
    tool_calls: tuple[ToolEvent, ...] = ()


class ScriptedModelAdapter:
    """Deterministic replacement for the conversation model in offline evals."""

    def __init__(self, turns: list[ScriptedTurn]):
        self._turns = iter(turns)

    def respond(self, _caller_text: str) -> ScriptedTurn:
        return next(self._turns)


@dataclass(frozen=True)
class JudgeResult:
    score: int
    reasons: tuple[str, ...]


class DeterministicJudge:
    """Fake LLM-judge interface used to test scoring/report plumbing.

    It is intentionally conservative and deterministic.  A future live judge
    can implement the same ``judge`` method outside merge-blocking CI.
    """

    def judge(self, turns: list[ScriptedTurn], violations: list[PolicyViolation]) -> JudgeResult:
        if violations:
            return JudgeResult(1, ("hard policy violation present",))
        if not turns or any(len(turn.assistant_text) > 280 for turn in turns):
            return JudgeResult(3, ("response is missing or too long",))
        return JudgeResult(5, ("fixture trace is concise and policy-compliant",))


def evaluate_trace(
    turns: list[ScriptedTurn], *, internal_goal: float, internal_ceiling: float
) -> list[PolicyViolation]:
    """Evaluate ordering and safety invariants over a scripted agent trace."""
    violations: list[PolicyViolation] = []
    carrier_verified = False
    load_found = False
    agreement_recorded = False
    transferred = False

    for turn in turns:
        violations.extend(
            evaluate_assistant_text(
                turn.assistant_text,
                internal_goal=internal_goal,
                internal_ceiling=internal_ceiling,
            )
        )
        for tool in turn.tool_calls:
            if tool.name == "verify_carrier" and tool.result_status == "success":
                carrier_verified = True
            elif tool.name == "get_load_context":
                if not carrier_verified:
                    violations.append(PolicyViolation("load_before_carrier_verification", tool.name))
                if tool.result_status == "success":
                    load_found = True
            elif tool.name == "record_agreement":
                if not load_found:
                    violations.append(PolicyViolation("agreement_before_load", tool.name))
                if not tool.arguments.get("above_max", False):
                    violations.extend(
                        evaluate_normal_agreement(
                            agreed_price=float(tool.arguments.get("agreed_price", 0)),
                            internal_ceiling=internal_ceiling,
                            contact_name=tool.arguments.get("carrier_contact_name"),
                            contact_phone=tool.arguments.get("carrier_contact_phone"),
                        )
                    )
                agreement_recorded = tool.result_status == "success"
            elif tool.name == "transfer_to_human":
                if not carrier_verified:
                    violations.append(PolicyViolation("transfer_before_carrier_verification", tool.name))
                if not load_found:
                    violations.append(PolicyViolation("transfer_before_load", tool.name))
                transferred = tool.result_status == "transferring"
            elif tool.name == "end_call":
                if transferred:
                    violations.append(PolicyViolation("end_after_transfer", tool.name))
                if tool.arguments.get("reason") == "agreement" and not agreement_recorded:
                    violations.append(PolicyViolation("end_agreement_before_record", tool.name))
    return violations
