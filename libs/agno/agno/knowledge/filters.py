from __future__ import annotations

from typing import Any, List

# ============================================================
# Base Expression
# ============================================================


class FilterExpr:
    """Base class for all filter expressions."""

    # Logical operator overloads
    def __or__(self, other: FilterExpr) -> OR:
        return OR(self, other)

    def __and__(self, other: FilterExpr) -> AND:
        return AND(self, other)

    def __invert__(self) -> NOT:
        return NOT(self)

    def to_dict(self) -> dict:
        raise NotImplementedError("Subclasses must implement to_dict()")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"


# ============================================================
# Comparison & Inclusion Filters
# ============================================================


class EQ(FilterExpr):
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "EQ", "key": self.key, "value": self.value}


class IN(FilterExpr):
    def __init__(self, key: str, values: List[Any]):
        self.key = key
        self.values = values

    def to_dict(self) -> dict:
        return {"op": "IN", "key": self.key, "values": self.values}


class GT(FilterExpr):
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "GT", "key": self.key, "value": self.value}


class LT(FilterExpr):
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "LT", "key": self.key, "value": self.value}


# ============================================================
# Logical Operators
# ============================================================


class AND(FilterExpr):
    def __init__(self, *conditions: FilterExpr):
        self.conditions = list(conditions)

    def to_dict(self) -> dict:
        return {"op": "AND", "conditions": [c.to_dict() for c in self.conditions]}


class OR(FilterExpr):
    def __init__(self, *conditions: FilterExpr):
        self.conditions = list(conditions)

    def to_dict(self) -> dict:
        return {"op": "OR", "conditions": [c.to_dict() for c in self.conditions]}


class NOT(FilterExpr):
    def __init__(self, condition: FilterExpr):
        self.condition = condition

    def to_dict(self) -> dict:
        return {"op": "NOT", "condition": self.condition.to_dict()}
