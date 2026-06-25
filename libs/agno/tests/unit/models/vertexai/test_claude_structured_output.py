import pytest

from agno.models.vertexai.claude import Claude


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("claude-sonnet-4-5@20250929", True),
        ("claude-haiku-4-5@20251001", True),
        ("claude-opus-4-5@20251101", True),
        ("claude-sonnet-4-6@20260217", True),
        ("claude-3-5-haiku@20241022", False),
        ("claude-3-sonnet@20240229", False),
        ("claude-3-opus@20240229", False),
        ("claude-sonnet-4@20250514", False),
        ("claude-opus-4@20250514", False),
    ],
)
def test_supports_structured_outputs(model_id: str, expected: bool):
    model = Claude(id=model_id)
    assert model._supports_structured_outputs() is expected
    assert model.supports_native_structured_outputs is expected
