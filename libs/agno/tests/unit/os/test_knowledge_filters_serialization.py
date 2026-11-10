"""Tests that knowledge_filters serialize correctly in AgentResponse.

Covers the fix for https://github.com/agno-agi/agno/issues/6547 where
FilterExpr objects caused PydanticSerializationError on GET /agents.
"""

import json

from agno.filters import AND, EQ, GT, IN, LT, NOT, OR, from_dict
from agno.os.routers.agents.schema import AgentResponse


def _serialize_knowledge_filters(knowledge_filters):
    """Replicate the serialization logic from AgentResponse.from_agent."""
    return (
        [f.to_dict() if hasattr(f, "to_dict") else f for f in knowledge_filters]
        if isinstance(knowledge_filters, list)
        else knowledge_filters
    )


def _make_response(knowledge_filters) -> AgentResponse:
    """Build a minimal AgentResponse with the given knowledge_filters."""
    serialized = _serialize_knowledge_filters(knowledge_filters)
    knowledge = {"knowledge_filters": serialized} if serialized is not None else None
    return AgentResponse(name="test-agent", knowledge=knowledge)


# -- Dict-style filters (most common usage) --


def test_dict_filters_pass_through():
    """Dict-style filters must be preserved as-is, not iterated over."""
    filters = {"user_id": "jordan_mitchell", "region": "north_america"}
    result = _serialize_knowledge_filters(filters)
    assert result == filters


def test_dict_filters_roundtrip_json():
    """AgentResponse with dict filters must survive Pydantic JSON serialization."""
    resp = _make_response({"user_id": "jordan_mitchell"})
    dumped = json.loads(resp.model_dump_json())
    assert dumped["knowledge"]["knowledge_filters"] == {"user_id": "jordan_mitchell"}


# -- List[FilterExpr] filters --


def test_simple_eq_filter():
    filters = [EQ("status", "published")]
    result = _serialize_knowledge_filters(filters)
    assert result == [{"op": "EQ", "key": "status", "value": "published"}]


def test_or_with_nested_and():
    """The exact pattern from issue #6547."""
    filters = [
        OR(
            EQ("knowledge_type", "general"),
            AND(
                EQ("knowledge_type", "user_specific"),
                IN("username", ["user1", "user2"]),
            ),
        )
    ]
    result = _serialize_knowledge_filters(filters)
    assert len(result) == 1
    assert result[0]["op"] == "OR"
    assert len(result[0]["conditions"]) == 2
    assert result[0]["conditions"][0] == {"op": "EQ", "key": "knowledge_type", "value": "general"}
    and_cond = result[0]["conditions"][1]
    assert and_cond["op"] == "AND"
    assert len(and_cond["conditions"]) == 2


def test_not_filter():
    filters = [NOT(EQ("status", "archived"))]
    result = _serialize_knowledge_filters(filters)
    assert result == [{"op": "NOT", "condition": {"op": "EQ", "key": "status", "value": "archived"}}]


def test_gt_lt_filters():
    filters = [GT("age", 18), LT("price", 100)]
    result = _serialize_knowledge_filters(filters)
    assert result[0] == {"op": "GT", "key": "age", "value": 18}
    assert result[1] == {"op": "LT", "key": "price", "value": 100}


def test_filter_expr_roundtrip_json():
    """AgentResponse with FilterExpr list must survive Pydantic JSON serialization."""
    resp = _make_response([OR(EQ("a", 1), EQ("b", 2))])
    dumped = json.loads(resp.model_dump_json())
    kf = dumped["knowledge"]["knowledge_filters"]
    assert kf == [
        {"op": "OR", "conditions": [{"op": "EQ", "key": "a", "value": 1}, {"op": "EQ", "key": "b", "value": 2}]}
    ]


def test_filter_expr_to_dict_from_dict_roundtrip():
    """FilterExpr -> to_dict -> from_dict should reconstruct equivalent objects."""
    original = OR(
        AND(EQ("type", "article"), GT("views", 1000)),
        AND(EQ("type", "tutorial"), NOT(EQ("difficulty", "beginner"))),
    )
    reconstructed = from_dict(original.to_dict())
    assert reconstructed.to_dict() == original.to_dict()


# -- None filters --


def test_none_filters():
    result = _serialize_knowledge_filters(None)
    assert result is None


def test_none_filters_roundtrip_json():
    resp = _make_response(None)
    dumped = json.loads(resp.model_dump_json())
    assert dumped.get("knowledge") is None
