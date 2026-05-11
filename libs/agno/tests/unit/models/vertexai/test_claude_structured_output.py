from agno.models.vertexai.claude import Claude


class TestNormalizeModelId:
    def test_at_format(self):
        model = Claude(id="claude-sonnet-4@20250514")
        assert model._normalize_model_id() == "claude-sonnet-4-20250514"

    def test_haiku_at_format(self):
        model = Claude(id="claude-3-5-haiku@20241022")
        assert model._normalize_model_id() == "claude-3-5-haiku-20241022"

    def test_hyphen_format(self):
        model = Claude(id="claude-sonnet-4-5-20250929")
        assert model._normalize_model_id() == "claude-sonnet-4-5-20250929"


class TestSupportsStructuredOutputs:
    def test_claude_4_5_sonnet_supports(self):
        model = Claude(id="claude-sonnet-4-5@20250929")
        assert model._supports_structured_outputs() is True
        assert model.supports_native_structured_outputs is True

    def test_claude_4_5_haiku_supports(self):
        model = Claude(id="claude-haiku-4-5@20251001")
        assert model._supports_structured_outputs() is True
        assert model.supports_native_structured_outputs is True

    def test_claude_opus_4_5_supports(self):
        model = Claude(id="claude-opus-4-5@20251101")
        assert model._supports_structured_outputs() is True
        assert model.supports_native_structured_outputs is True

    def test_claude_3_5_haiku_does_not_support(self):
        model = Claude(id="claude-3-5-haiku@20241022")
        assert model._supports_structured_outputs() is False
        assert model.supports_native_structured_outputs is False

    def test_claude_3_sonnet_does_not_support(self):
        model = Claude(id="claude-3-sonnet@20240229")
        assert model._supports_structured_outputs() is False
        assert model.supports_native_structured_outputs is False

    def test_claude_sonnet_4_0_does_not_support(self):
        model = Claude(id="claude-sonnet-4@20250514")
        assert model._supports_structured_outputs() is False
        assert model.supports_native_structured_outputs is False
