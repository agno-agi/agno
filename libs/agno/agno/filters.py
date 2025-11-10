"""Search filter expressions for filtering knowledge base documents and search results.

This module provides a set of filter operators for constructing complex search queries
that can be applied to knowledge bases, vector databases, and other searchable content.

Filter Types:
    - Comparison: EQ (equals), GT (greater than), LT (less than)
    - Inclusion: IN (value in list)
    - Logical: AND, OR, NOT

Operators can be combined using Python operators:
    - `&` for AND
    - `|` for OR
    - `~` for NOT

Example:
    >>> from agno.filters import EQ, GT, IN, AND, OR
    >>>
    >>> # Simple equality filter
    >>> filter = EQ("category", "technology")
    >>>
    >>> # Complex filter with multiple conditions
    >>> filter = (
    ...     EQ("status", "published") &
    ...     GT("views", 1000) &
    ...     IN("category", ["tech", "science"])
    ... )
    >>>
    >>> # Using OR logic
    >>> filter = EQ("priority", "high") | EQ("urgent", True)
    >>>
    >>> # Negating conditions
    >>> filter = ~EQ("status", "archived")
    >>>
    >>> # Complex nested logic
    >>> filter = (
    ...     (EQ("type", "article") & GT("word_count", 500)) |
    ...     (EQ("type", "tutorial") & ~EQ("difficulty", "beginner"))
    ... )
"""

from __future__ import annotations

from typing import Any, List

# ============================================================
# Base Expression
# ============================================================


class FilterExpr:
    """Base class for all filter expressions.

    Provides logical operator overloads for combining filter expressions:
    - `|` (OR): Combine filters where either expression can be true
    - `&` (AND): Combine filters where both expressions must be true
    - `~` (NOT): Negate a filter expression

    Example:
        >>> # Create complex filters using operators
        >>> filter = (EQ("status", "active") & GT("age", 18)) | EQ("role", "admin")
        >>> # Equivalent to: (status == "active" AND age > 18) OR role == "admin"
    """

    # Logical operator overloads
    def __or__(self, other: FilterExpr) -> OR:
        """Combine two filters with OR logic using the | operator."""
        return OR(self, other)

    def __and__(self, other: FilterExpr) -> AND:
        """Combine two filters with AND logic using the & operator."""
        return AND(self, other)

    def __invert__(self) -> NOT:
        """Negate a filter using the ~ operator."""
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
        >>> # Using the & operator (preferred syntax)
        >>> filter = EQ("status", "published") & GT("age", 18)
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
        >>> # Using the | operator (preferred syntax)
        >>> filter = EQ("status", "published") | EQ("status", "archived")
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
        >>> # Using the ~ operator (preferred syntax)
        >>> filter = ~EQ("status", "draft")
        >>>
        >>> # Exclude inactive users with low scores
        >>> filter = ~(EQ("status", "inactive") & LT("score", 10))
        >>>
        >>> # Match users who are NOT in the blocked list
        >>> filter = ~IN("user_id", [101, 102, 103])
    """

    def __init__(self, expression: FilterExpr):
        self.expression = expression

    def to_dict(self) -> dict:
        return {"op": "NOT", "condition": self.expression.to_dict()}
