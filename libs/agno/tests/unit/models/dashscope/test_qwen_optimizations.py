"""
Unit tests for Qwen optimizations in DashScope model.

Tests the following features:
- Auto-configuration of model variants
- Parallel function calls
- Reasoning content support
- vLLM native parsing
- Local deployment detection
"""

import pytest

from agno.models.dashscope import DashScope


class TestAutoConfiguration:
    """Test automatic model variant detection and configuration."""

    def test_qvq_auto_config(self):
        """QvQ models should auto-enable thinking and reasoning."""
        model = DashScope(id="qvq-max")
        assert model._model_variant == "qvq"
        assert model.enable_thinking is True
        assert model.use_reasoning_content is True
        assert model.fncall_prompt_type == "qwen"

    def test_qwq_auto_config(self):
        """QwQ models should be detected as QvQ variant."""
        model = DashScope(id="Qwen/QwQ-32B-Preview")
        assert model._model_variant == "qvq"
        assert model.enable_thinking is True

    def test_qwen3_vl_auto_config(self):
        """Qwen3-VL models should use qwen template."""
        model = DashScope(id="qwen-vl-plus")
        assert model._model_variant == "qwen3-vl"
        assert model.fncall_prompt_type == "qwen"

    def test_qwen3_coder_auto_config(self):
        """Qwen3-Coder should use nous template."""
        model = DashScope(id="Qwen/Qwen2.5-Coder-7B-Instruct")
        assert model._model_variant == "qwen3-coder"
        assert model.fncall_prompt_type == "nous"

    def test_qwen3_auto_config(self):
        """Qwen3 models should use nous template."""
        model = DashScope(id="qwen3-plus")
        assert model._model_variant == "qwen3"
        assert model.fncall_prompt_type == "nous"

    def test_qwen25_auto_config(self):
        """Qwen2.5 should enable reasoning content."""
        model = DashScope(id="Qwen/Qwen2.5-7B-Instruct")
        assert model._model_variant == "qwen2.5"
        assert model.use_reasoning_content is True

    def test_max_tokens_auto_config(self):
        """Max input tokens should be set based on model tier."""
        model_max = DashScope(id="qwen-max")
        assert model_max.max_input_tokens == 128000

        model_turbo = DashScope(id="qwen-turbo")
        assert model_turbo.max_input_tokens == 1000000

        model_plus = DashScope(id="qwen-plus")
        assert model_plus.max_input_tokens == 32768

    def test_auto_configure_disabled(self):
        """Auto-configure can be disabled."""
        model = DashScope(id="qvq-max", auto_configure=False)
        assert model._model_variant is None
        assert model.enable_thinking is False  # Not auto-enabled


class TestLocalDeploymentDetection:
    """Test detection of local vs cloud deployments."""

    def test_localhost_detection(self):
        """localhost URLs should be detected as local."""
        model = DashScope(base_url="http://localhost:8000/v1")
        assert model._is_local_deployment() is True

    def test_127_detection(self):
        """127.0.0.1 should be detected as local."""
        model = DashScope(base_url="http://127.0.0.1:8000/v1")
        assert model._is_local_deployment() is True

    def test_port_8000_detection(self):
        """Port 8000 (vLLM default) should be detected as local."""
        model = DashScope(base_url="http://192.168.1.100:8000/v1")
        assert model._is_local_deployment() is True

    def test_ollama_port_detection(self):
        """Port 11434 (Ollama default) should be detected as local."""
        model = DashScope(base_url="http://localhost:11434/v1")
        assert model._is_local_deployment() is True

    def test_official_api_not_local(self):
        """Official DashScope URL should not be detected as local."""
        model = DashScope()  # Uses default base_url
        assert model._is_local_deployment() is False

    def test_vllm_native_parsing_for_local_coder(self):
        """Local Coder models should auto-enable vLLM native parsing."""
        model = DashScope(
            id="Qwen/Qwen2.5-Coder-7B-Instruct",
            base_url="http://localhost:8000/v1",
        )
        assert model.use_vllm_native_parsing is True


class TestRequestParams:
    """Test request parameter generation with optimizations."""

    def test_reasoning_content_param(self):
        """Reasoning content should be added for Qwen2.5+."""
        model = DashScope(id="qwen-plus")
        params = model.get_request_params()

        assert "extra_body" in params
        assert params["extra_body"]["reasoning_content"] is True

    def test_parallel_calls_param(self):
        """Parallel calls should be added when tools are provided."""
        model = DashScope(id="qwen-plus", max_parallel_calls=10)
        tools = [{"type": "function", "function": {"name": "test"}}]
        params = model.get_request_params(tools=tools)

        assert params["extra_body"]["max_parallel_calls"] == 10

    def test_fncall_template_param(self):
        """Function call template should be added for non-default."""
        model = DashScope(id="qwen-plus")  # Auto-sets to 'nous' for qwen3
        tools = [{"type": "function", "function": {"name": "test"}}]
        params = model.get_request_params(tools=tools)

        # Should have fncall_prompt_type since it's not 'qwen'
        assert params["extra_body"]["fncall_prompt_type"] == "nous"

    def test_thinking_params(self):
        """Thinking parameters should be added for QvQ."""
        model = DashScope(id="qvq-max", thinking_budget=5000)
        params = model.get_request_params()

        assert params["extra_body"]["enable_thinking"] is True
        assert params["extra_body"]["thinking_budget"] == 5000

    def test_vllm_native_parsing_param(self):
        """vLLM native parsing should be added for local coder."""
        model = DashScope(
            id="Qwen/Qwen2.5-Coder-7B-Instruct",
            base_url="http://localhost:8000/v1",
        )
        tools = [{"type": "function", "function": {"name": "test"}}]
        params = model.get_request_params(tools=tools)

        assert params["extra_body"]["use_raw_api"] is True
        assert params["extra_body"]["guided_decoding_backend"] == "outlines"

    def test_max_tokens_enforcement(self):
        """Max tokens should not exceed model limits."""
        model = DashScope(id="qwen-plus")  # max_input_tokens=32768
        params = model.get_request_params()

        # Default max_tokens should be within limits
        if "max_tokens" in params:
            assert params["max_tokens"] <= 32768

    def test_empty_extra_body_cleanup(self):
        """Empty extra_body should be removed."""
        model = DashScope(
            id="qwen-plus",
            use_reasoning_content=False,  # Disable all extras
            auto_configure=False,
        )
        params = model.get_request_params()

        # Should not have extra_body if empty
        assert "extra_body" not in params or not params["extra_body"]


class TestAPIKeyHandling:
    """Test API key handling for local vs cloud."""

    def test_api_key_required_for_cloud(self):
        """API key should be required for non-local deployments."""
        model = DashScope(api_key=None)

        with pytest.raises(Exception):  # Should raise authentication error
            model._get_client_params()

    def test_api_key_optional_for_local(self):
        """API key should be optional for local deployments."""
        model = DashScope(
            api_key=None,
            base_url="http://localhost:8000/v1",
        )

        params = model._get_client_params()
        assert params["api_key"] == "EMPTY"  # vLLM accepts "EMPTY"

    def test_api_key_from_env(self, monkeypatch):
        """API key should be read from environment."""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-123")

        model = DashScope()
        params = model._get_client_params()

        assert params["api_key"] == "test-key-123"

    def test_qwen_api_key_fallback(self, monkeypatch):
        """Should fallback to QWEN_API_KEY if DASHSCOPE_API_KEY not set."""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.setenv("QWEN_API_KEY", "test-qwen-key")

        model = DashScope()
        assert model.api_key == "test-qwen-key"


class TestParallelFunctionCalls:
    """Test parallel function call configuration."""

    def test_default_parallel_limit(self):
        """Default parallel limit should be 5."""
        model = DashScope(id="qwen-plus")
        assert model.max_parallel_calls == 5

    def test_custom_parallel_limit(self):
        """Custom parallel limit should be respected."""
        model = DashScope(id="qwen-plus", max_parallel_calls=10)
        assert model.max_parallel_calls == 10

    def test_disable_parallel(self):
        """Parallel can be disabled with max_parallel_calls=1."""
        model = DashScope(id="qwen-plus", max_parallel_calls=1)
        assert model.max_parallel_calls == 1

        tools = [{"type": "function", "function": {"name": "test"}}]
        params = model.get_request_params(tools=tools)

        # Should not add max_parallel_calls if it's 1
        assert params["extra_body"].get("max_parallel_calls", 1) == 1


class TestFunctionCallTemplates:
    """Test function call template types."""

    def test_qwen_template(self):
        """Qwen template should be set correctly."""
        model = DashScope(id="qwen-plus", fncall_prompt_type="qwen")
        assert model.fncall_prompt_type == "qwen"

    def test_nous_template(self):
        """Nous template should be set correctly."""
        model = DashScope(id="qwen-plus", fncall_prompt_type="nous")
        assert model.fncall_prompt_type == "nous"

    def test_glm4_template(self):
        """GLM4 template should be set correctly."""
        model = DashScope(id="qwen-plus", fncall_prompt_type="glm4")
        assert model.fncall_prompt_type == "glm4"


class TestBackwardCompatibility:
    """Test that existing code still works."""

    def test_basic_usage_unchanged(self):
        """Basic usage without new params should still work."""
        model = DashScope(id="qwen-plus")
        assert model.id == "qwen-plus"
        assert model.name == "Qwen"
        assert model.provider == "Dashscope"

    def test_thinking_params_unchanged(self):
        """Existing thinking params should still work."""
        model = DashScope(
            id="qvq-max",
            enable_thinking=True,
            thinking_budget=5000,
        )
        assert model.enable_thinking is True
        assert model.thinking_budget == 5000

    def test_include_thoughts_alias(self):
        """include_thoughts should still work as alias."""
        model = DashScope(id="qvq-max", include_thoughts=True)
        params = model.get_request_params()
        assert params["extra_body"]["enable_thinking"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
