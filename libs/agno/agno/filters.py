"""Search filter expressions for filtering knowledge base documents and search results.

This module provides a set of filter operators for constructing complex search queries
that can be applied to knowledge bases, vector databases, and other searchable content.

Filter Types:
    - Comparison: EQ (equals), NEQ (not equals), GT (greater than), GTE (greater than or equal),
      LT (less than), LTE (less than or equal)
    - Inclusion: IN (value in list)
    - String: CONTAINS (substring match), STARTSWITH (prefix match)
    - Logical: AND, OR, NOT

Example:
    >>> from agno.filters import EQ, GT, IN, AND, OR, NOT
    >>>
    >>> # Simple equality filter
    >>> filter = EQ("category", "technology")
    >>>
    >>> # Complex filter with multiple conditions
    >>> filter = AND(
    ...     EQ("status", "published"),
    ...     GT("views", 1000),
    ...     IN("category", ["tech", "science"])
    ... )
    >>>
    >>> # Using OR logic
    >>> filter = OR(EQ("priority", "high"), EQ("urgent", True))
    >>>
    >>> # Negating conditions
    >>> filter = NOT(EQ("status", "archived"))
    >>>
    >>> # Complex nested logic
    >>> filter = OR(
    ...     AND(EQ("type", "article"), GT("word_count", 500)),
    ...     AND(EQ("type", "tutorial"), NOT(EQ("difficulty", "beginner")))
    ... )
"""

from __future__ import annotations

from typing import Any, List

# Maximum recursion depth for nested filter expressions (prevents stack overflow attacks)
MAX_FILTER_DEPTH: int = 10

# ============================================================
# Base Expression
# ============================================================


class FilterExpr:
    """Base class for all filter expressions.

    Filters can be combined using AND, OR, and NOT classes:
    - AND: Combine filters where both expressions must be true
    - OR: Combine filters where either expression can be true
    - NOT: Negate a filter expression

    Example:
        >>> # Create complex filters using AND, OR, NOT
        >>> filter = OR(AND(EQ("status", "active"), GT("age", 18)), EQ("role", "admin"))
        >>> # Equivalent to: (status == "active" AND age > 18) OR role == "admin"
    """

    # Logical operator overloads
    def __or__(self, other: FilterExpr) -> OR:
        """Combine two filters with OR logic."""
        return OR(self, other)

    def __and__(self, other: FilterExpr) -> AND:
        """Combine two filters with AND logic."""
        return AND(self, other)

    def __invert__(self) -> NOT:
        """Negate a filter."""
        return NOT(self)

    def to_dict(self) -> dict:
        """Convert the filter expression to a dictionary representation."""
        raise NotImplementedError("Subclasses must implement to_dict()")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"


# ============================================================
# Comparison & Inclusion Filters
# ============================================================


class EQ(FilterExpr):
    """Equality filter - matches documents where a field equals a specific value.

    Args:
        key: The field name to compare
        value: The value to match against

    Example:
        >>> # Match documents where status is "published"
        >>> filter = EQ("status", "published")
        >>>
        >>> # Match documents where author_id is 123
        >>> filter = EQ("author_id", 123)
    """

    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "EQ", "key": self.key, "value": self.value}


class IN(FilterExpr):
    """Inclusion filter - matches documents where a field's value is in a list of values.

    Args:
        key: The field name to check
        values: List of acceptable values

    Example:
        >>> # Match documents where category is either "tech", "science", or "engineering"
        >>> filter = IN("category", ["tech", "science", "engineering"])
        >>>
        >>> # Match documents where status is either "draft" or "published"
        >>> filter = IN("status", ["draft", "published"])
    """

    def __init__(self, key: str, values: List[Any]):
        self.key = key
        self.values = values

    def to_dict(self) -> dict:
        return {"op": "IN", "key": self.key, "values": self.values}


class GT(FilterExpr):
    """Greater than filter - matches documents where a field's value is greater than a threshold.

    Args:
        key: The field name to compare
        value: The threshold value

    Example:
        >>> # Match documents where age is greater than 18
        >>> filter = GT("age", 18)
        >>>
        >>> # Match documents where price is greater than 100.0
        >>> filter = GT("price", 100.0)
        >>>
        >>> # Match documents created after a certain timestamp
        >>> filter = GT("created_at", 1234567890)
    """

    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "GT", "key": self.key, "value": self.value}


class LT(FilterExpr):
    """Less than filter - matches documents where a field's value is less than a threshold.

    Args:
        key: The field name to compare
        value: The threshold value

    Example:
        >>> # Match documents where age is less than 65
        >>> filter = LT("age", 65)
        >>>
        >>> # Match documents where price is less than 50.0
        >>> filter = LT("price", 50.0)
        >>>
        >>> # Match documents created before a certain timestamp
        >>> filter = LT("created_at", 1234567890)
    """

    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "LT", "key": self.key, "value": self.value}


class NEQ(FilterExpr):
    """Not-equal filter - matches documents where a field does not equal a specific value.

    Args:
        key: The field name to compare
        value: The value to compare against

    Example:
        >>> # Match documents where status is not "archived"
        >>> filter = NEQ("status", "archived")
    """

    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "NEQ", "key": self.key, "value": self.value}


class GTE(FilterExpr):
    """Greater than or equal filter - matches documents where a field's value is >= a threshold.

    Args:
        key: The field name to compare
        value: The threshold value

    Example:
        >>> # Match documents where age is 18 or older
        >>> filter = GTE("age", 18)
        >>>
        >>> # Match documents created on or after a certain timestamp
        >>> filter = GTE("created_at", "2025-01-01T00:00:00Z")
    """

    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "GTE", "key": self.key, "value": self.value}


class LTE(FilterExpr):
    """Less than or equal filter - matches documents where a field's value is <= a threshold.

    Args:
        key: The field name to compare
        value: The threshold value

    Example:
        >>> # Match documents where age is 65 or younger
        >>> filter = LTE("age", 65)
        >>>
        >>> # Match documents created on or before a certain timestamp
        >>> filter = LTE("created_at", "2025-12-31T23:59:59Z")
    """

    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "LTE", "key": self.key, "value": self.value}


# ============================================================
# String Matching Filters
# ============================================================


class CONTAINS(FilterExpr):
    """Substring match filter - matches documents where a field contains a substring (case-insensitive).

    Args:
        key: The field name to search
        value: The substring to search for

    Example:
        >>> # Match documents where user_id contains "admin"
        >>> filter = CONTAINS("user_id", "admin")
        >>>
        >>> # Match documents where name contains "john"
        >>> filter = CONTAINS("name", "john")
    """

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "CONTAINS", "key": self.key, "value": self.value}


class STARTSWITH(FilterExpr):
    """Prefix match filter - matches documents where a field starts with a given string.

    Args:
        key: The field name to search
        value: The prefix to match

    Example:
        >>> # Match documents where name starts with "Agent"
        >>> filter = STARTSWITH("name", "Agent")
        >>>
        >>> # Match documents where session_id starts with "sess_"
        >>> filter = STARTSWITH("session_id", "sess_")
    """

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def to_dict(self) -> dict:
        return {"op": "STARTSWITH", "key": self.key, "value": self.value}


# ============================================================
# Logical Operators
# ============================================================


class AND(FilterExpr):
    """Logical AND operator - matches documents where ALL expressions are true.

    Combines multiple filter expressions where every expression must be satisfied
    for a document to match.

    Args:
        *expressions: Variable number of FilterExpr expressions to combine with AND logic

    Example:
        >>> # Match documents where status is "published" AND age > 18
        >>> filter = AND(EQ("status", "published"), GT("age", 18))
        >>>
        >>> # Multiple expressions
        >>> filter = AND(
        ...     EQ("status", "active"),
        ...     GT("score", 80),
        ...     IN("category", ["tech", "science"])
        ... )
    """

    def __init__(self, *expressions: FilterExpr):
        self.expressions = list(expressions)

    def to_dict(self) -> dict:
        return {"op": "AND", "conditions": [e.to_dict() for e in self.expressions]}


class OR(FilterExpr):
    """Logical OR operator - matches documents where ANY expression is true.

    Combines multiple filter expressions where at least one expression must be satisfied
    for a document to match.

    Args:
        *expressions: Variable number of FilterExpr expressions to combine with OR logic

    Example:
        >>> # Match documents where status is "published" OR status is "archived"
        >>> filter = OR(EQ("status", "published"), EQ("status", "archived"))
        >>>
        >>> # Complex: Match VIP users OR users with high score
        >>> filter = OR(
        ...     EQ("membership", "VIP"),
        ...     GT("score", 1000)
        ... )
    """

    def __init__(self, *expressions: FilterExpr):
        self.expressions = list(expressions)

    def to_dict(self) -> dict:
        return {"op": "OR", "conditions": [e.to_dict() for e in self.expressions]}


class NOT(FilterExpr):
    """Logical NOT operator - matches documents where the expression is NOT true.

    Negates a filter expression, matching documents that don't satisfy the expression.

    Args:
        expression: The FilterExpr expression to negate

    Example:
        >>> # Match documents where status is NOT "draft"
        >>> filter = NOT(EQ("status", "draft"))
        >>>
        >>> # Exclude inactive users with low scores
        >>> filter = NOT(AND(EQ("status", "inactive"), LT("score", 10)))
        >>>
        >>> # Match users who are NOT in the blocked list
        >>> filter = NOT(IN("user_id", [101, 102, 103]))
    """

    def __init__(self, expression: FilterExpr):
        self.expression = expression

    def to_dict(self) -> dict:
        return {"op": "NOT", "condition": self.expression.to_dict()}


def get_filter_value(data: dict, key: str) -> Any:
    if key in data:
        return data[key]

    current: Any = data
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def matches_filter_expr(data: dict, expression: FilterExpr) -> bool:
    if isinstance(expression, EQ):
        return get_filter_value(data, expression.key) == expression.value

    if isinstance(expression, IN):
        return get_filter_value(data, expression.key) in expression.values

    if isinstance(expression, GT):
        try:
            return get_filter_value(data, expression.key) > expression.value
        except TypeError:
            return False

    if isinstance(expression, LT):
        try:
            return get_filter_value(data, expression.key) < expression.value
        except TypeError:
            return False

    if isinstance(expression, NEQ):
        value = get_filter_value(data, expression.key)
        if value is None and expression.key not in data:
            # Check nested path too
            parts = expression.key.split(".")
            current = data
            key_exists = True
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    key_exists = False
                    break
            if not key_exists:
                return False
        return value != expression.value

    if isinstance(expression, GTE):
        try:
            return get_filter_value(data, expression.key) >= expression.value
        except TypeError:
            return False

    if isinstance(expression, LTE):
        try:
            return get_filter_value(data, expression.key) <= expression.value
        except TypeError:
            return False

    if isinstance(expression, CONTAINS):
        value = get_filter_value(data, expression.key)
        if isinstance(value, str):
            return expression.value.lower() in value.lower()
        if isinstance(value, (list, tuple, set)):
            if isinstance(expression.value, str):
                search_lower = expression.value.lower()
                return any(
                    (isinstance(v, str) and v.lower() == search_lower) or v == expression.value for v in value
                )
            return expression.value in value
        return False

    if isinstance(expression, STARTSWITH):
        value = get_filter_value(data, expression.key)
        return isinstance(value, str) and value.lower().startswith(expression.value.lower())

    if isinstance(expression, AND):
        return all(matches_filter_expr(data, expr) for expr in expression.expressions)

    if isinstance(expression, OR):
        return any(matches_filter_expr(data, expr) for expr in expression.expressions)

    if isinstance(expression, NOT):
        return not matches_filter_expr(data, expression.expression)

    raise ValueError(f"Unsupported filter expression type: {type(expression).__name__}")


# ============================================================
# Deserialization
# ============================================================


def from_dict(filter_dict: dict, _depth: int = 0) -> FilterExpr:
    """Reconstruct a FilterExpr object from its dictionary representation.

    This function deserializes filter expressions that were serialized using the
    to_dict() method, enabling filters to be passed through JSON APIs and reconstructed
    on the server side.

    Args:
        filter_dict: Dictionary representation of a filter expression with an "op" key
        _depth: Internal parameter tracking recursion depth. Do not pass manually.

    Returns:
        FilterExpr: The reconstructed filter expression object

    Raises:
        ValueError: If the filter dictionary has an invalid structure, unknown operator,
            or exceeds max recursion depth.

    Example:
        >>> # Serialize and deserialize a simple filter
        >>> original = EQ("status", "published")
        >>> serialized = original.to_dict()
        >>> # {"op": "EQ", "key": "status", "value": "published"}
        >>> reconstructed = from_dict(serialized)
        >>>
        >>> # Complex filter with nested expressions
        >>> complex_filter = OR(AND(EQ("type", "article"), GT("views", 1000)), IN("priority", ["high", "urgent"]))
        >>> serialized = complex_filter.to_dict()
        >>> reconstructed = from_dict(serialized)
        >>>
        >>> # From JSON API
        >>> import json
        >>> json_str = '{"op": "AND", "conditions": [{"op": "EQ", "key": "status", "value": "active"}, {"op": "GT", "key": "age", "value": 18}]}'
        >>> filter_dict = json.loads(json_str)
        >>> filter_expr = from_dict(filter_dict)
    """
    # Check recursion depth limit
    if _depth >= MAX_FILTER_DEPTH:
        raise ValueError(f"Filter expression exceeds maximum nesting depth of {MAX_FILTER_DEPTH}")

    if not isinstance(filter_dict, dict) or "op" not in filter_dict:
        raise ValueError(f"Invalid filter dictionary: must contain 'op' key. Got: {filter_dict}")

    op = filter_dict["op"]

    # Comparison and inclusion operators
    if op == "EQ":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"EQ filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return EQ(filter_dict["key"], filter_dict["value"])

    elif op == "IN":
        if "key" not in filter_dict or "values" not in filter_dict:
            raise ValueError(f"IN filter requires 'key' and 'values' fields. Got: {filter_dict}")
        return IN(filter_dict["key"], filter_dict["values"])

    elif op == "GT":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"GT filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return GT(filter_dict["key"], filter_dict["value"])

    elif op == "LT":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"LT filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return LT(filter_dict["key"], filter_dict["value"])

    elif op == "NEQ":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"NEQ filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return NEQ(filter_dict["key"], filter_dict["value"])

    elif op == "GTE":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"GTE filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return GTE(filter_dict["key"], filter_dict["value"])

    elif op == "LTE":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"LTE filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return LTE(filter_dict["key"], filter_dict["value"])

    elif op == "CONTAINS":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"CONTAINS filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return CONTAINS(filter_dict["key"], filter_dict["value"])

    elif op == "STARTSWITH":
        if "key" not in filter_dict or "value" not in filter_dict:
            raise ValueError(f"STARTSWITH filter requires 'key' and 'value' fields. Got: {filter_dict}")
        return STARTSWITH(filter_dict["key"], filter_dict["value"])

    # Logical operators
    elif op == "AND":
        if "conditions" not in filter_dict:
            raise ValueError(f"AND filter requires 'conditions' field. Got: {filter_dict}")
        conditions = [from_dict(cond, _depth + 1) for cond in filter_dict["conditions"]]
        return AND(*conditions)

    elif op == "OR":
        if "conditions" not in filter_dict:
            raise ValueError(f"OR filter requires 'conditions' field. Got: {filter_dict}")
        conditions = [from_dict(cond, _depth + 1) for cond in filter_dict["conditions"]]
        return OR(*conditions)

    elif op == "NOT":
        if "condition" not in filter_dict:
            raise ValueError(f"NOT filter requires 'condition' field. Got: {filter_dict}")
        return NOT(from_dict(filter_dict["condition"], _depth + 1))

    else:
        raise ValueError(f"Unknown filter operator: {op}")
