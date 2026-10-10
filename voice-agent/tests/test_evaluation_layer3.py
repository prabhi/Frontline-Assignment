"""Layer 3 deterministic scripted-model trace evaluations."""

from evals.trace import (
    DeterministicJudge,
    Layer3MetricCollector,
    ScriptedModelAdapter,
    ScriptedTurn,
    TraceExpectation,
    ToolEvent,
    evaluate_trace,
)


GOAL = 2200
CEILING = 2500


def test_scripted_adapter_and_fake_judge_accept_a_compliant_trace():
    turns = [
        ScriptedTurn("Let me check that.", (ToolEvent("verify_carrier", result_status="success"),)),
        ScriptedTurn("One moment.", (ToolEvent("get_load_context", result_status="success"),)),
        ScriptedTurn(
            "Great, eighteen hundred works.",
            (ToolEvent("record_agreement", {"agreed_price": 1800, "carrier_contact_name": "Jamie", "carrier_contact_phone": "+15555550101"}, "success"),),
        ),
        ScriptedTurn("I will send the confirmation now.", (ToolEvent("end_call", {"reason": "agreement"}, "success"),)),
    ]
    adapter = ScriptedModelAdapter(turns)
    replayed = [adapter.respond("fixture caller") for _ in turns]
    violations = evaluate_trace(replayed, internal_goal=GOAL, internal_ceiling=CEILING)

    assert violations == []
    assert DeterministicJudge().judge(replayed, violations).score == 5


def test_trace_evaluator_reports_confidential_leak_and_bad_tool_order():
    turns = [
        ScriptedTurn(
            "Our max rate is $2,500.",
            (ToolEvent("get_load_context", result_status="success"),),
        )
    ]
    violations = evaluate_trace(turns, internal_goal=GOAL, internal_ceiling=CEILING)

    assert {violation.rule for violation in violations} >= {
        "internal_ceiling_disclosed",
        "forbidden_pricing_term",
        "load_before_carrier_verification",
    }
    assert DeterministicJudge().judge(turns, violations).score == 1


def test_metric_collector_reports_labelled_policy_tool_and_faithfulness_metrics():
    compliant = [
        ScriptedTurn("Let me verify that.", (ToolEvent("verify_carrier", result_status="success"),))
    ]
    violating = [ScriptedTurn("Our max rate is $2,500.")]
    judge = DeterministicJudge()
    collector = Layer3MetricCollector()
    collector.record(
        "compliant", expectation=TraceExpectation(frozenset(), frozenset({"verify_carrier"})),
        turns=compliant, violations=[], judge_result=judge.judge(compliant, []),
    )
    violations = evaluate_trace(violating, internal_goal=GOAL, internal_ceiling=CEILING)
    collector.record(
        "leak", expectation=TraceExpectation(
            frozenset({"internal_ceiling_disclosed", "forbidden_pricing_term"}), frozenset()
        ),
        turns=violating, violations=violations, judge_result=judge.judge(violating, violations),
    )

    metrics = collector.summary()

    assert metrics.cases == 2
    assert metrics.policy.precision == metrics.policy.recall == metrics.policy.f1 == 1.0
    assert metrics.tool_selection.precision == metrics.tool_selection.recall == 1.0
    assert metrics.mean_judge_scores["faithfulness"] == 3.0
