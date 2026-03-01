from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.engine.evaluator import EvaluationResult, evaluate_trial


def _criterion(*, type_value: str = "inclusion", expression: dict, manual_review_required: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        trial_id=uuid4(),
        type=type_value,
        text="criterion",
        expression=expression,
        manual_review_required=manual_review_required,
        rule_version="1.0.0",
    )


def test_simple_comparison_met_and_not_met() -> None:
    criterion = _criterion(expression={"op": "gte", "field": "age", "value": 18, "unit": "years"})

    met = evaluate_trial([criterion], {"age": 21})
    not_met = evaluate_trial([criterion], {"age": 17})

    assert met.criteria_results[0].result == EvaluationResult.MET
    assert met.overall == EvaluationResult.MET
    assert not_met.criteria_results[0].result == EvaluationResult.NOT_MET
    assert not_met.overall == EvaluationResult.NOT_MET


def test_compound_and_with_temporal() -> None:
    criterion = _criterion(
        expression={
            "op": "and",
            "operands": [
                {"op": "gte", "field": "anc", "value": 1000, "unit": "cells/uL"},
                {"op": "within_days", "field": "anc_date", "days": 14},
            ],
        }
    )
    recent_date = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()

    result = evaluate_trial([criterion], {"anc": 1200, "anc_unit": "cells/uL", "anc_date": recent_date})

    assert result.criteria_results[0].result == EvaluationResult.MET


def test_exclusion_criterion_reversal() -> None:
    criterion = _criterion(type_value="exclusion", expression={"op": "is_true", "field": "prior_transplant"})

    result = evaluate_trial([criterion], {"prior_transplant": True})

    assert result.criteria_results[0].result == EvaluationResult.NOT_MET
    assert result.overall == EvaluationResult.NOT_MET


def test_missing_field_is_incomplete() -> None:
    criterion = _criterion(expression={"op": "gte", "field": "age", "value": 18, "unit": "years"})

    result = evaluate_trial([criterion], {})

    assert result.criteria_results[0].result == EvaluationResult.INCOMPLETE
    assert result.overall == EvaluationResult.INCOMPLETE


def test_manual_review_required_overrides_expression() -> None:
    criterion = _criterion(
        expression={"op": "gte", "field": "age", "value": 18, "unit": "years"},
        manual_review_required=True,
    )

    result = evaluate_trial([criterion], {"age": 100})

    assert result.criteria_results[0].result == EvaluationResult.MANUAL_REVIEW
    assert result.overall == EvaluationResult.MANUAL_REVIEW


def test_near_miss_population_for_simple_comparison() -> None:
    criterion = _criterion(expression={"op": "gte", "field": "age", "value": 18, "unit": "years"})

    result = evaluate_trial([criterion], {"age": 17})
    near_miss = result.criteria_results[0].near_miss

    assert near_miss is not None
    assert near_miss.field == "age"
    assert near_miss.operator == "gte"
    assert near_miss.delta == -1.0


def test_unit_normalization_anc_109l_to_cells_ul() -> None:
    criterion = _criterion(expression={"op": "gte", "field": "anc", "value": 1000, "unit": "cells/uL"})

    result = evaluate_trial([criterion], {"anc": 1.2, "anc_unit": "x10^9/L"})

    assert result.criteria_results[0].result == EvaluationResult.MET


def test_overall_result_severity_ordering() -> None:
    incomplete = _criterion(expression={"op": "gte", "field": "age", "value": 18, "unit": "years"})
    manual = _criterion(expression={"op": "is_true", "field": "x"}, manual_review_required=True)
    not_met = _criterion(expression={"op": "gte", "field": "ecog", "value": 0})

    manual_over_incomplete = evaluate_trial([incomplete, manual], {})
    ineligible_wins = evaluate_trial([incomplete, manual, not_met], {"ecog": 1})

    assert manual_over_incomplete.overall == EvaluationResult.MANUAL_REVIEW
    assert ineligible_wins.overall == EvaluationResult.NOT_MET
