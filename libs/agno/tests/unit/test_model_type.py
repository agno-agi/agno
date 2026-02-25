"""
Unit tests for the ModelType enum and its integration with metrics accumulation.

Tests cover:
- ModelType enum values and str behavior
- Model base class model_type attribute
- accumulate_model_metrics with ModelType enum
- Dict key storage uses string values
- Agent init sets model_type on resolved models
- Backward compatibility with string model_type values
"""

from unittest.mock import MagicMock

from agno.metrics import (
    MessageMetrics,
    Metrics,
    ModelMetrics,
    ModelType,
    SessionMetrics,
    accumulate_eval_metrics,
    accumulate_model_metrics,
)

# ---------------------------------------------------------------------------
# ModelType enum basics
# ---------------------------------------------------------------------------


class TestModelTypeEnum:
    def test_enum_values(self):
        assert ModelType.MODEL.value == "model"
        assert ModelType.OUTPUT_MODEL.value == "output_model"
        assert ModelType.PARSER_MODEL.value == "parser_model"
        assert ModelType.MEMORY_MODEL.value == "memory_model"
        assert ModelType.REASONING_MODEL.value == "reasoning_model"
        assert ModelType.SESSION_SUMMARY_MODEL.value == "session_summary_model"
        assert ModelType.CULTURE_MODEL.value == "culture_model"
        assert ModelType.LEARNING_MODEL.value == "learning_model"
        assert ModelType.COMPRESSION_MODEL.value == "compression_model"

    def test_str_enum_equality_with_strings(self):
        """ModelType(str, Enum) should compare equal to its string value."""
        assert ModelType.MODEL == "model"
        assert ModelType.OUTPUT_MODEL == "output_model"
        assert ModelType.REASONING_MODEL == "reasoning_model"

    def test_enum_members_are_unique(self):
        values = [m.value for m in ModelType]
        assert len(values) == len(set(values))

    def test_enum_is_hashable(self):
        """Can be used as dict keys."""
        d = {ModelType.MODEL: "main", ModelType.OUTPUT_MODEL: "output"}
        assert d[ModelType.MODEL] == "main"


# ---------------------------------------------------------------------------
# Model base class integration
# ---------------------------------------------------------------------------


class TestModelTypeOnModel:
    def test_default_model_type(self):
        """Model instances default to ModelType.MODEL."""
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        assert model.model_type == ModelType.MODEL

    def test_model_type_can_be_overridden(self):
        """model_type can be set to a different ModelType value."""
        from agno.models.openai.chat import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        model.model_type = ModelType.OUTPUT_MODEL
        assert model.model_type == ModelType.OUTPUT_MODEL


# ---------------------------------------------------------------------------
# accumulate_model_metrics with ModelType
# ---------------------------------------------------------------------------


def _make_model_response(input_tokens=10, output_tokens=5, total_tokens=15, cost=None, ttft=None):
    """Create a mock ModelResponse with response_usage."""
    usage = MessageMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost=cost,
        time_to_first_token=ttft,
    )
    response = MagicMock()
    response.response_usage = usage
    return response


def _make_model(model_id="gpt-4o-mini", provider="OpenAI", model_type=ModelType.MODEL):
    """Create a mock Model with the given attributes."""
    model = MagicMock()
    model.id = model_id
    model.get_provider.return_value = provider
    model.model_type = model_type
    return model


class TestAccumulateModelMetrics:
    def test_enum_model_type_creates_correct_dict_key(self):
        """Using ModelType enum should store under the string value key."""
        run_metrics = Metrics()
        model_response = _make_model_response()
        model = _make_model()

        accumulate_model_metrics(model_response, model, ModelType.MODEL, run_metrics)

        assert "model" in run_metrics.details
        assert len(run_metrics.details["model"]) == 1

    def test_output_model_type_key(self):
        run_metrics = Metrics()
        model_response = _make_model_response()
        model = _make_model()

        accumulate_model_metrics(model_response, model, ModelType.OUTPUT_MODEL, run_metrics)

        assert "output_model" in run_metrics.details

    def test_memory_model_type_key(self):
        run_metrics = Metrics()
        model_response = _make_model_response()
        model = _make_model()

        accumulate_model_metrics(model_response, model, ModelType.MEMORY_MODEL, run_metrics)

        assert "memory_model" in run_metrics.details

    def test_string_model_type_still_works(self):
        """Backward compatibility: raw strings should still work."""
        run_metrics = Metrics()
        model_response = _make_model_response()
        model = _make_model()

        accumulate_model_metrics(model_response, model, "model", run_metrics)

        assert "model" in run_metrics.details

    def test_tokens_accumulate_correctly(self):
        run_metrics = Metrics()
        model = _make_model()

        accumulate_model_metrics(_make_model_response(10, 5, 15), model, ModelType.MODEL, run_metrics)
        accumulate_model_metrics(_make_model_response(20, 10, 30), model, ModelType.MODEL, run_metrics)

        assert run_metrics.input_tokens == 30
        assert run_metrics.output_tokens == 15
        assert run_metrics.total_tokens == 45

    def test_multiple_model_types_in_same_run(self):
        """Simulates an agent run using model + output_model."""
        run_metrics = Metrics()
        main_model = _make_model("gpt-4o", "OpenAI")
        output_model = _make_model("gpt-4o-mini", "OpenAI")

        accumulate_model_metrics(_make_model_response(100, 50, 150), main_model, ModelType.MODEL, run_metrics)
        accumulate_model_metrics(_make_model_response(20, 10, 30), output_model, ModelType.OUTPUT_MODEL, run_metrics)

        details = run_metrics.details
        assert "model" in details
        assert "output_model" in details
        assert details["model"][0].id == "gpt-4o"
        assert details["output_model"][0].id == "gpt-4o-mini"
        assert run_metrics.total_tokens == 180

    def test_accumulate_does_not_set_run_ttft(self):
        """Run TTFT is set by providers via set_time_to_first_token(), not by accumulate_model_metrics."""
        run_metrics = Metrics()
        model = _make_model()

        accumulate_model_metrics(_make_model_response(ttft=0.5), model, ModelType.MODEL, run_metrics)
        assert run_metrics.time_to_first_token is None

    def test_none_response_usage_is_no_op(self):
        run_metrics = Metrics()
        model = _make_model()
        response = MagicMock()
        response.response_usage = None

        accumulate_model_metrics(response, model, ModelType.MODEL, run_metrics)
        # No details added when response_usage is None
        assert run_metrics.details is None


# ---------------------------------------------------------------------------
# accumulate_eval_metrics with enum-keyed details
# ---------------------------------------------------------------------------


class TestAccumulateEvalMetrics:
    def test_eval_prefixes_string_keys_correctly(self):
        """accumulate_eval_metrics should create 'eval_model' from 'model' key."""
        eval_metrics = Metrics(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            details={
                "model": [
                    ModelMetrics(id="gpt-4o-mini", provider="OpenAI", input_tokens=10, output_tokens=5, total_tokens=15)
                ]
            },
        )

        run_metrics = Metrics(details={})

        accumulate_eval_metrics(eval_metrics, run_metrics, prefix="eval")

        assert "eval_model" in run_metrics.details
        assert run_metrics.input_tokens == 10


# ---------------------------------------------------------------------------
# Metrics.to_dict / from_dict round-trip with enum keys
# ---------------------------------------------------------------------------


class TestMetricsSerialization:
    def test_to_dict_preserves_string_keys(self):
        """details dict keys should be strings in the serialized output."""
        metrics = Metrics(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            details={
                "model": [
                    ModelMetrics(id="gpt-4o", provider="OpenAI", input_tokens=100, output_tokens=50, total_tokens=150)
                ]
            },
        )
        d = metrics.to_dict()
        assert "model" in d["details"]

    def test_from_dict_round_trip(self):
        metrics = Metrics(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            details={
                "model": [
                    ModelMetrics(id="gpt-4o", provider="OpenAI", input_tokens=100, output_tokens=50, total_tokens=150)
                ],
                "output_model": [
                    ModelMetrics(
                        id="gpt-4o-mini", provider="OpenAI", input_tokens=20, output_tokens=10, total_tokens=30
                    )
                ],
            },
        )
        d = metrics.to_dict()
        restored = Metrics.from_dict(d)
        assert "model" in restored.details
        assert "output_model" in restored.details
        assert restored.details["model"][0].id == "gpt-4o"

    def test_session_metrics_from_dict_with_string_keys(self):
        """SessionMetrics.from_dict should handle details from run Metrics (dict format)."""
        data = {
            "input_tokens": 100,
            "total_tokens": 150,
            "details": {"model": [{"id": "gpt-4o", "provider": "OpenAI", "input_tokens": 100, "total_tokens": 150}]},
        }
        session = SessionMetrics.from_dict(data)
        assert session.details is not None
        assert len(session.details) == 1
        assert session.details["model"][0].id == "gpt-4o"


# ---------------------------------------------------------------------------
# Agent init sets model_type
# ---------------------------------------------------------------------------


class TestAgentInitModelType:
    def test_agent_model_gets_model_type_set(self):
        """Agent's model should have model_type=MODEL after init."""
        from agno.agent import Agent
        from agno.models.openai.chat import OpenAIChat

        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
        assert agent.model.model_type == ModelType.MODEL

    def test_agent_output_model_gets_type_set(self):
        from agno.agent import Agent
        from agno.models.openai.chat import OpenAIChat

        agent = Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            output_model=OpenAIChat(id="gpt-4o-mini"),
        )
        assert agent.output_model.model_type == ModelType.OUTPUT_MODEL

    def test_agent_parser_model_gets_type_set(self):
        from agno.agent import Agent
        from agno.models.openai.chat import OpenAIChat

        agent = Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            parser_model=OpenAIChat(id="gpt-4o-mini"),
        )
        assert agent.parser_model.model_type == ModelType.PARSER_MODEL

    def test_agent_reasoning_model_gets_type_set(self):
        from agno.agent import Agent
        from agno.models.openai.chat import OpenAIChat

        agent = Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            reasoning_model=OpenAIChat(id="gpt-4o-mini"),
        )
        assert agent.reasoning_model.model_type == ModelType.REASONING_MODEL


# ---------------------------------------------------------------------------
# Re-export shim
# ---------------------------------------------------------------------------


class TestReExportShim:
    def test_model_type_importable_from_models_metrics(self):
        from agno.models.metrics import ModelType as MT

        assert MT is ModelType
        assert MT.MODEL.value == "model"
