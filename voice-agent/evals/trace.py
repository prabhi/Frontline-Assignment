"""Layer 3 scripted-model trace evaluator and deterministic judge seam.

No model is called here.  ``ScriptedModelAdapter`` deliberately supplies
fixture turns, making the state-machine and policy checks repeatable in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

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
    """Versioned qualitative scores returned by a judge implementation.

    A future LLM judge can return these same dimensions with evidence. The
    offline judge below keeps the contract deterministic for merge-blocking CI.
    """

    scores: Mapping[str, int]
    reasons: tuple[str, ...]

    @property
    def score(self) -> int:
        """Compatibility summary: the lowest rubric score, never an average."""
        return min(self.scores.values())


@dataclass(frozen=True)
class TraceExpectation:
    """Human-labelled expected outcomes for one trace evaluation case."""

    expected_violation_rules: frozenset[str]
    expected_tool_calls: frozenset[str]


@dataclass(frozen=True)
class ClassificationMetrics:
    """Precision/recall counts and derived values for a labelled binary set."""

    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 1.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0


@dataclass(frozen=True)
class Layer3Metrics:
    """Aggregated labelled trace metrics, including judge faithfulness score."""

    cases: int
    policy: ClassificationMetrics
    tool_selection: ClassificationMetrics
    mean_judge_scores: Mapping[str, float]


class Layer3MetricCollector:
    """Collect label-based metrics without coupling CI to an LLM judge.

    Precision/recall compare evaluation output with a human-authored
    ``TraceExpectation``. Faithfulness is a named judge dimension; its score is
    reported separately and must include judge evidence in a future live judge.
    """

    def __init__(self) -> None:
        self._policy_expected: set[str] = set()
        self._policy_observed: set[str] = set()
        self._tools_expected: set[str] = set()
        self._tools_observed: set[str] = set()
        self._scores: dict[str, list[int]] = {}
        self._cases = 0

    def record(
        self,
        case_id: str,
        *,
        expectation: TraceExpectation,
        turns: list[ScriptedTurn],
        violations: list[PolicyViolation],
        judge_result: JudgeResult,
    ) -> None:
        """Record one uniquely named case and its expected/observed outcomes."""
        self._cases += 1
        self._policy_expected.update(f"{case_id}:{rule}" for rule in expectation.expected_violation_rules)
        self._policy_observed.update(f"{case_id}:{item.rule}" for item in violations)
        actual_tools = {tool.name for turn in turns for tool in turn.tool_calls}
        self._tools_expected.update(f"{case_id}:{name}" for name in expectation.expected_tool_calls)
        self._tools_observed.update(f"{case_id}:{name}" for name in actual_tools)
        for dimension, score in judge_result.scores.items():
            self._scores.setdefault(dimension, []).append(score)

    def summary(self) -> Layer3Metrics:
        def classification(expected: set[str], observed: set[str]) -> ClassificationMetrics:
            return ClassificationMetrics(
                true_positive=len(expected & observed),
                false_positive=len(observed - expected),
                false_negative=len(expected - observed),
            )

        return Layer3Metrics(
            cases=self._cases,
            policy=classification(self._policy_expected, self._policy_observed),
            tool_selection=classification(self._tools_expected, self._tools_observed),
            mean_judge_scores={
                dimension: sum(scores) / len(scores)
                for dimension, scores in self._scores.items()
            },
        )


class DeterministicJudge:
    """Fake LLM-judge interface used to test scoring/report plumbing.

    It is intentionally conservative and deterministic.  A future live judge
    can implement the same ``judge`` method outside merge-blocking CI.
    """

    def judge(self, turns: list[ScriptedTurn], violations: list[PolicyViolation]) -> JudgeResult:
        if violations:
            return JudgeResult(
                {"conciseness": 1, "helpfulness": 1, "negotiation_coherence": 1,
                 "handoff_usefulness": 1, "faithfulness": 1},
                ("hard policy violation present",),
            )
        if not turns or any(len(turn.assistant_text) > 280 for turn in turns):
            return JudgeResult(
                {"conciseness": 3, "helpfulness": 3, "negotiation_coherence": 3,
                 "handoff_usefulness": 3, "faithfulness": 3},
                ("response is missing or too long",),
            )
        return JudgeResult(
            {"conciseness": 5, "helpfulness": 5, "negotiation_coherence": 5,
             "handoff_usefulness": 5, "faithfulness": 5},
            ("fixture trace is concise and policy-compliant",),
        )


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
