from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel

from app.engine.schema import BooleanExpr, ComparisonExpr, CompoundExpr, Expression, SetExpr, TemporalExpr, validate_expression
from app.engine.units import CANONICAL_UNITS, UnitNormalizationError, normalize


class EvaluationResult(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    INCOMPLETE = "incomplete"
    MANUAL_REVIEW = "manual_review"


class NearMiss(BaseModel):
    field: str
    actual_value: float | str | bool
    required_value: float | str
    operator: str
    delta: float | None


class CriterionResult(BaseModel):
    criterion_id: str
    result: EvaluationResult
    raw_text: str
    expression: dict
    near_miss: NearMiss | None = None


class TrialResult(BaseModel):
    trial_id: str
    overall: EvaluationResult
    criteria_results: list[CriterionResult]
    version_hash: str
    trial_name: str | None = None


class CriterionLike(Protocol):
    id: Any
    trial_id: Any
    type: Any
    text: str
    expression: dict
    manual_review_required: bool
    rule_version: str | None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _comparison(actual: Any, required: Any, op: str) -> bool:
    if op == "gte":
        return actual >= required
    if op == "lte":
        return actual <= required
    if op == "gt":
        return actual > required
    if op == "lt":
        return actual < required
    if op == "eq":
        return actual == required
    if op == "neq":
        return actual != required
    raise ValueError(f"Unsupported comparison op '{op}'")


def _evaluate_comparison(expr: ComparisonExpr, patient_data: dict[str, Any]) -> EvaluationResult:
    if expr.field not in patient_data or patient_data[expr.field] is None:
        return EvaluationResult.INCOMPLETE

    actual_value = patient_data[expr.field]
    required_value = expr.value

    if _is_number(actual_value) and _is_number(required_value):
        if expr.field in CANONICAL_UNITS:
            actual_unit = patient_data.get(f"{expr.field}_unit") or CANONICAL_UNITS[expr.field]
            required_unit = expr.unit or CANONICAL_UNITS[expr.field]
            try:
                actual_norm = normalize(expr.field, float(actual_value), actual_unit)
                required_norm = normalize(expr.field, float(required_value), required_unit)
            except UnitNormalizationError:
                return EvaluationResult.MANUAL_REVIEW
        else:
            actual_unit = patient_data.get(f"{expr.field}_unit")
            if expr.unit and actual_unit and expr.unit != actual_unit:
                return EvaluationResult.MANUAL_REVIEW
            actual_norm = float(actual_value)
            required_norm = float(required_value)

        return EvaluationResult.MET if _comparison(actual_norm, required_norm, expr.op) else EvaluationResult.NOT_MET

    if expr.unit and patient_data.get(f"{expr.field}_unit") and patient_data.get(f"{expr.field}_unit") != expr.unit:
        return EvaluationResult.MANUAL_REVIEW

    return EvaluationResult.MET if _comparison(actual_value, required_value, expr.op) else EvaluationResult.NOT_MET


def _evaluate_boolean(expr: BooleanExpr, patient_data: dict[str, Any]) -> EvaluationResult:
    if expr.field not in patient_data or patient_data[expr.field] is None:
        return EvaluationResult.INCOMPLETE

    value = patient_data[expr.field]
    # Coerce common truthy/falsy string and int representations from form inputs
    if isinstance(value, bool):
        coerced = value
    elif isinstance(value, int) and value in (0, 1):
        coerced = bool(value)
    elif isinstance(value, str):
        if value.strip().lower() in {"true", "yes", "1"}:
            coerced = True
        elif value.strip().lower() in {"false", "no", "0"}:
            coerced = False
        else:
            return EvaluationResult.MANUAL_REVIEW
    else:
        return EvaluationResult.MANUAL_REVIEW
    value = coerced

    if expr.op == "is_true":
        return EvaluationResult.MET if value else EvaluationResult.NOT_MET
    return EvaluationResult.MET if not value else EvaluationResult.NOT_MET


def _evaluate_set(expr: SetExpr, patient_data: dict[str, Any]) -> EvaluationResult:
    if expr.field not in patient_data or patient_data[expr.field] is None:
        return EvaluationResult.INCOMPLETE

    actual = patient_data[expr.field]
    allowed = set(expr.values)
    if isinstance(actual, list):
        present = any(item in allowed for item in actual)
    else:
        present = actual in allowed

    if expr.op == "in":
        return EvaluationResult.MET if present else EvaluationResult.NOT_MET
    return EvaluationResult.MET if not present else EvaluationResult.NOT_MET


def _evaluate_temporal(expr: TemporalExpr, patient_data: dict[str, Any]) -> EvaluationResult:
    if expr.field not in patient_data or patient_data[expr.field] is None:
        return EvaluationResult.INCOMPLETE

    observed = _coerce_datetime(patient_data[expr.field])
    if observed is None:
        return EvaluationResult.MANUAL_REVIEW

    now = datetime.now(UTC)
    delta_days = abs((now - observed).total_seconds()) / 86400
    return EvaluationResult.MET if delta_days <= expr.days else EvaluationResult.NOT_MET


def _evaluate_compound(expr: CompoundExpr, patient_data: dict[str, Any]) -> EvaluationResult:
    results = [_evaluate_expression(item, patient_data) for item in expr.operands]

    if expr.op == "and":
        if any(result == EvaluationResult.NOT_MET for result in results):
            return EvaluationResult.NOT_MET
        if any(result == EvaluationResult.MANUAL_REVIEW for result in results):
            return EvaluationResult.MANUAL_REVIEW
        if any(result == EvaluationResult.INCOMPLETE for result in results):
            return EvaluationResult.INCOMPLETE
        return EvaluationResult.MET

    if expr.op == "or":
        if any(result == EvaluationResult.MET for result in results):
            return EvaluationResult.MET
        if any(result == EvaluationResult.MANUAL_REVIEW for result in results):
            return EvaluationResult.MANUAL_REVIEW
        if any(result == EvaluationResult.INCOMPLETE for result in results):
            return EvaluationResult.INCOMPLETE
        return EvaluationResult.NOT_MET

    operand = results[0]
    if operand == EvaluationResult.MET:
        return EvaluationResult.NOT_MET
    if operand == EvaluationResult.NOT_MET:
        return EvaluationResult.MET
    return operand


def _evaluate_expression(expr: Expression, patient_data: dict[str, Any]) -> EvaluationResult:
    if isinstance(expr, ComparisonExpr):
        return _evaluate_comparison(expr, patient_data)
    if isinstance(expr, BooleanExpr):
        return _evaluate_boolean(expr, patient_data)
    if isinstance(expr, SetExpr):
        return _evaluate_set(expr, patient_data)
    if isinstance(expr, TemporalExpr):
        return _evaluate_temporal(expr, patient_data)
    return _evaluate_compound(expr, patient_data)


def _build_near_miss(expr: ComparisonExpr, patient_data: dict[str, Any]) -> NearMiss | None:
    actual = patient_data.get(expr.field)
    if actual is None:
        return None

    required = expr.value
    if _is_number(actual) and _is_number(required):
        actual_value = float(actual)
        required_value = float(required)
        if expr.field in CANONICAL_UNITS:
            try:
                actual_unit = patient_data.get(f"{expr.field}_unit") or CANONICAL_UNITS[expr.field]
                required_unit = expr.unit or CANONICAL_UNITS[expr.field]
                actual_value = normalize(expr.field, actual_value, actual_unit)
                required_value = normalize(expr.field, required_value, required_unit)
            except UnitNormalizationError:
                return None

        return NearMiss(
            field=expr.field,
            actual_value=actual_value,
            required_value=required_value,
            operator=expr.op,
            delta=actual_value - required_value,
        )

    if isinstance(actual, (str, bool)) and isinstance(required, (str, bool)):
        return NearMiss(
            field=expr.field,
            actual_value=actual,
            required_value=required,
            operator=expr.op,
            delta=None,
        )

    return None


def _criteria_hash(trial_criteria: list[CriterionLike]) -> str:
    canonical = []
    for criterion in trial_criteria:
        canonical.append(
            {
                "id": str(criterion.id),
                "type": str(criterion.type),
                "text": criterion.text,
                "expression": criterion.expression,
                "manual_review_required": criterion.manual_review_required,
                "rule_version": criterion.rule_version,
            }
        )
    canonical.sort(key=lambda item: item["id"])
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest


def _criterion_result(criterion: CriterionLike, patient_data: dict[str, Any]) -> CriterionResult:
    expression_payload = criterion.expression or {}

    if criterion.manual_review_required:
        return CriterionResult(
            criterion_id=str(criterion.id),
            result=EvaluationResult.MANUAL_REVIEW,
            raw_text=criterion.text,
            expression=expression_payload,
            near_miss=None,
        )

    try:
        expression = validate_expression(expression_payload)
    except Exception:
        return CriterionResult(
            criterion_id=str(criterion.id),
            result=EvaluationResult.MANUAL_REVIEW,
            raw_text=criterion.text,
            expression=expression_payload,
            near_miss=None,
        )

    result = _evaluate_expression(expression, patient_data)

    if str(criterion.type) == "exclusion":
        if result == EvaluationResult.MET:
            result = EvaluationResult.NOT_MET
        elif result == EvaluationResult.NOT_MET:
            result = EvaluationResult.MET

    near_miss = None
    if result == EvaluationResult.NOT_MET and isinstance(expression, ComparisonExpr):
        near_miss = _build_near_miss(expression, patient_data)

    return CriterionResult(
        criterion_id=str(criterion.id),
        result=result,
        raw_text=criterion.text,
        expression=expression_payload,
        near_miss=near_miss,
    )


def _overall(results: list[CriterionResult]) -> EvaluationResult:
    if any(item.result == EvaluationResult.NOT_MET for item in results):
        return EvaluationResult.NOT_MET
    if any(item.result == EvaluationResult.MANUAL_REVIEW for item in results):
        return EvaluationResult.MANUAL_REVIEW
    if any(item.result == EvaluationResult.INCOMPLETE for item in results):
        return EvaluationResult.INCOMPLETE
    return EvaluationResult.MET


def evaluate_trial(
    trial_criteria: list[CriterionLike], patient_data: dict[str, Any], trial_id: str | None = None
) -> TrialResult:
    if not trial_criteria:
        return TrialResult(
            trial_id=trial_id or "",
            overall=EvaluationResult.MANUAL_REVIEW,
            criteria_results=[],
            version_hash=_criteria_hash([]),
        )

    resolved_trial_id = trial_id or str(trial_criteria[0].trial_id)
    criteria_results = [_criterion_result(criterion, patient_data) for criterion in trial_criteria]
    return TrialResult(
        trial_id=resolved_trial_id,
        overall=_overall(criteria_results),
        criteria_results=criteria_results,
        version_hash=_criteria_hash(trial_criteria),
    )


def evaluate_all_trials(trials_with_criteria: list[Any], patient_data: dict[str, Any]) -> list[TrialResult]:
    results: list[TrialResult] = []

    for item in trials_with_criteria:
        trial_name: str | None = None
        trial_id_override: str | None = None

        if isinstance(item, dict):
            criteria = item.get("criteria", [])
            trial_id_override = str(item["trial_id"]) if item.get("trial_id") is not None else None
            trial_name = item.get("trial_name")
        elif isinstance(item, tuple) and len(item) == 2:
            trial_id_override = str(item[0])
            criteria = item[1]
        else:
            criteria = getattr(item, "criteria", [])
            if getattr(item, "trial_id", None) is not None:
                trial_id_override = str(item.trial_id)
            trial_name = getattr(item, "trial_name", None)

        trial_result = evaluate_trial(criteria, patient_data)
        if trial_id_override is not None:
            trial_result.trial_id = trial_id_override
        if trial_name:
            trial_result.trial_name = trial_name
        results.append(trial_result)

    return results
