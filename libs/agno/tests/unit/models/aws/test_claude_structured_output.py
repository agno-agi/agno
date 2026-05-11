import pytest

from agno.models.aws import Claude


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("global.anthropic.claude-sonnet-4-5-20250929-v1:0", True),
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", True),
        ("anthropic.claude-opus-4-5-20251101-v1:0", True),
        ("us.anthropic.claude-sonnet-4-6-20260217-v1:0", True),
        ("us.anthropic.claude-3-5-haiku-20241022-v1:0", False),
        ("anthropic.claude-3-sonnet-20240229-v1:0", False),
        ("global.anthropic.claude-3-opus-20240229-v1:0", False),
        ("global.anthropic.claude-sonnet-4-20250514-v1:0", False),
        ("anthropic.claude-opus-4-20250514-v1:0", False),
    ],
)
def test_supports_structured_outputs(model_id: str, expected: bool):
    model = Claude(id=model_id)
    assert model._supports_structured_outputs() is expected
    assert model.supports_native_structured_outputs is expected
