from __future__ import annotations


CANONICAL_UNITS: dict[str, str] = {
    "anc": "cells/uL",
    "hgb": "g/dL",
    "cr": "mg/dL",
    "bili": "mg/dL",
    "age": "years",
    "lvef": "%",
    "egfr": "mL/min/1.73m2",
}

_FIELD_ALIASES = {
    "creatinine": "cr",
    "serum_creatinine": "cr",
    "bilirubin": "bili",
    "total_bili": "bili",
    "total_bilirubin": "bili",
    "hemoglobin": "hgb",
}

_ANC_FACTORS = {
    "cells/ul": 1.0,
    "cells/ml": 0.001,
    "x10^9/l": 1000.0,
    "x109/l": 1000.0,
    "10^9/l": 1000.0,
    "10e9/l": 1000.0,
}

_HGB_FACTORS = {
    "g/dl": 1.0,
    "g/l": 0.1,
}

_CR_FACTORS = {
    "mg/dl": 1.0,
    "umol/l": 1.0 / 88.42,
    "umol/liter": 1.0 / 88.42,
}

_BILI_FACTORS = {
    "mg/dl": 1.0,
    "umol/l": 1.0 / 17.1,
    "umol/liter": 1.0 / 17.1,
}

_STRICT_UNITS = {
    "age": {"years", "year", "yr", "yrs"},
    "lvef": {"%", "percent", "percentage"},
    "egfr": {"ml/min/1.73m2"},
}


class UnitNormalizationError(ValueError):
    pass


def _normalized_field(field: str) -> str:
    key = field.strip().lower()
    return _FIELD_ALIASES.get(key, key)


def _normalized_unit(unit: str) -> str:
    normalized = unit.strip().lower()
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("\u00d7", "x")
    normalized = normalized.replace("*", "x")
    normalized = normalized.replace("\u00b5", "u").replace("\u03bc", "u")
    normalized = normalized.replace("\u00b2", "2")
    return normalized


def normalize(field: str, value: float | int, from_unit: str | None) -> float:
    field_key = _normalized_field(field)
    canonical = CANONICAL_UNITS.get(field_key)
    if canonical is None:
        return float(value)

    if from_unit is None:
        raise UnitNormalizationError(f"Missing unit for field '{field}'")

    unit_key = _normalized_unit(from_unit)

    if field_key == "anc":
        factor = _ANC_FACTORS.get(unit_key)
    elif field_key == "hgb":
        factor = _HGB_FACTORS.get(unit_key)
    elif field_key == "cr":
        factor = _CR_FACTORS.get(unit_key)
    elif field_key == "bili":
        factor = _BILI_FACTORS.get(unit_key)
    elif field_key in _STRICT_UNITS:
        factor = 1.0 if unit_key in {_normalized_unit(item) for item in _STRICT_UNITS[field_key]} else None
    else:
        factor = None

    if factor is None:
        raise UnitNormalizationError(f"Cannot normalize unit '{from_unit}' for field '{field}'")

    return float(value) * factor
