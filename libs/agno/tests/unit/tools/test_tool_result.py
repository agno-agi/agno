from agno.tools.function import ToolResult


def test_tool_result_preserves_meta_in_model_dump_round_trip():
    result = ToolResult(content="done", meta={"trace_id": "abc-123", "score": 0.98})

    dumped = result.model_dump()
    restored = ToolResult.model_validate(dumped)

    assert dumped["meta"] == {"trace_id": "abc-123", "score": 0.98}
    assert restored.meta == {"trace_id": "abc-123", "score": 0.98}
