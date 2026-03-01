from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, model_validator


class ComparisonExpr(BaseModel):
    op: Literal["gte", "lte", "gt", "lt", "eq", "neq"]
    field: str
    value: float | int | str | bool
    unit: str | None = None


class BooleanExpr(BaseModel):
    op: Literal["is_true", "is_false"]
    field: str


class SetExpr(BaseModel):
    op: Literal["in", "not_in"]
    field: str
    values: list[float | int | str | bool]


class TemporalExpr(BaseModel):
    op: Literal["within_days"]
    field: str
    days: int = Field(gt=0)


class CompoundExpr(BaseModel):
    op: Literal["and", "or", "not"]
    operands: list["Expression"]

    @model_validator(mode="after")
    def validate_operands(self) -> "CompoundExpr":
        if self.op == "not" and len(self.operands) != 1:
            raise ValueError("not expression requires exactly one operand")
        if self.op in {"and", "or"} and len(self.operands) < 2:
            raise ValueError(f"{self.op} expression requires at least two operands")
        return self


Expression = Annotated[
    Union[ComparisonExpr, BooleanExpr, SetExpr, TemporalExpr, CompoundExpr],
    Field(discriminator="op"),
]

CompoundExpr.model_rebuild()

EXPRESSION_ADAPTER = TypeAdapter(Expression)


def validate_expression(payload: dict) -> Expression:
    return EXPRESSION_ADAPTER.validate_python(payload)
