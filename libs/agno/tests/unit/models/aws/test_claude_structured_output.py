from agno.models.aws import Claude


class TestNormalizeModelId:
    def test_global_prefix(self):
        model = Claude(id="global.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert model._normalize_model_id() == "claude-sonnet-4-5-20250929"

    def test_us_prefix(self):
        model = Claude(id="us.anthropic.claude-3-5-haiku-20241022-v1:0")
        assert model._normalize_model_id() == "claude-3-5-haiku-20241022"

    def test_no_prefix(self):
        model = Claude(id="anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert model._normalize_model_id() == "claude-sonnet-4-5-20250929"

    def test_simple_id(self):
        model = Claude(id="claude-sonnet-4-5-20250929")
        assert model._normalize_model_id() == "claude-sonnet-4-5-20250929"


class TestSupportsStructuredOutputs:
    def test_claude_4_5_sonnet_supports(self):
        model = Claude(id="global.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert model._supports_structured_outputs() is True
        assert model.supports_native_structured_outputs is True

    def test_claude_4_5_haiku_supports(self):
        model = Claude(id="us.anthropic.claude-haiku-4-5-20251001-v1:0")
        assert model._supports_structured_outputs() is True
        assert model.supports_native_structured_outputs is True

    def test_claude_opus_4_5_supports(self):
        model = Claude(id="anthropic.claude-opus-4-5-20251101-v1:0")
        assert model._supports_structured_outputs() is True
        assert model.supports_native_structured_outputs is True

    def test_claude_3_5_haiku_does_not_support(self):
        model = Claude(id="us.anthropic.claude-3-5-haiku-20241022-v1:0")
        assert model._supports_structured_outputs() is False
        assert model.supports_native_structured_outputs is False

    def test_claude_3_sonnet_does_not_support(self):
        model = Claude(id="anthropic.claude-3-sonnet-20240229-v1:0")
        assert model._supports_structured_outputs() is False
        assert model.supports_native_structured_outputs is False

    def test_claude_sonnet_4_0_does_not_support(self):
        # claude-sonnet-4-20250514 is in NON_STRUCTURED_OUTPUT_ALIASES
        model = Claude(id="global.anthropic.claude-sonnet-4-20250514-v1:0")
        assert model._supports_structured_outputs() is False
        assert model.supports_native_structured_outputs is False
