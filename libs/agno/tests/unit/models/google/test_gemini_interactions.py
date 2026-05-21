"""Unit tests for GeminiInteractions model class."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from agno.media import Audio, File, Image, Video
from agno.models.google.gemini_interactions import GeminiInteractions
from agno.models.message import Message


class TestGetClient:
    """Tests for client initialization."""

    def test_get_client_with_api_key(self):
        model = GeminiInteractions(api_key="test-key")

        with patch("agno.models.google.gemini_interactions.genai.Client") as mock_client_cls:
            model.get_client()
            _, kwargs = mock_client_cls.call_args
            assert kwargs["api_key"] == "test-key"

    def test_get_client_caches_instance(self):
        model = GeminiInteractions(api_key="test-key")

        with patch("agno.models.google.gemini_interactions.genai.Client") as mock_client_cls:
            client1 = model.get_client()
            client2 = model.get_client()
            assert client1 is client2
            mock_client_cls.assert_called_once()

    def test_get_client_timeout_configuration(self):
        model = GeminiInteractions(api_key="test-key", timeout=30.0)

        with patch("agno.models.google.gemini_interactions.genai.Client") as mock_client_cls:
            model.get_client()
            _, kwargs = mock_client_cls.call_args
            assert kwargs["http_options"]["timeout"] == 30000


class TestFormatTools:
    """Tests for tool formatting."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_no_tools(self):
        model = self._make_model()
        result = model._format_tools(None)
        assert result == []

    def test_function_tools(self):
        model = self._make_model()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ]
        result = model._format_tools(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather for a city"
        assert result[0]["parameters"] == {"type": "object", "properties": {"city": {"type": "string"}}}

    def test_builtin_search_tool_added_in_request_kwargs(self):
        """Built-in tools are added in _get_request_kwargs, not _format_tools."""
        model = GeminiInteractions(api_key="test-key", search=True)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert {"type": "google_search"} in kwargs["tools"]

    def test_builtin_url_context_tool_added_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", url_context=True)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert {"type": "url_context"} in kwargs["tools"]

    def test_builtin_code_execution_tool_added_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", code_execution=True)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert {"type": "code_execution"} in kwargs["tools"]

    def test_function_object_tools(self):
        """_format_tools handles Function objects from the agent."""
        from agno.tools.function import Function

        def dummy_func(x: str) -> str:
            """A dummy function."""
            return x

        func = Function(name="dummy", description="A dummy function", entrypoint=dummy_func)
        model = self._make_model()
        result = model._format_tools([func])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "dummy"


class TestBuildInput:
    """Tests for message formatting into interaction turns."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_user_message(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hello")]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "user_input"
        assert steps[0]["content"] == [{"type": "text", "text": "Hello"}]

    def test_system_message_skipped(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hi"),
        ]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "user_input"

    def test_assistant_message_without_tool_calls_skipped(self):
        """Assistant messages without tool calls produce no steps (text responses are not re-sent)."""
        model = self._make_model()
        messages = [Message(role="assistant", content="I can help")]
        steps = model._build_input(messages)
        assert len(steps) == 0

    def test_tool_call_message(self):
        model = self._make_model()
        messages = [
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                    }
                ],
            )
        ]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "function_call"
        assert steps[0]["id"] == "call_123"
        assert steps[0]["name"] == "get_weather"
        assert steps[0]["arguments"] == {"city": "Paris"}

    def test_tool_result_message(self):
        model = self._make_model()
        messages = [Message(role="tool", content="Sunny, 25C", tool_call_id="call_123", tool_name="get_weather")]
        steps = model._build_input(messages)
        assert len(steps) == 1
        assert steps[0]["type"] == "function_result"
        assert steps[0]["call_id"] == "call_123"
        assert steps[0]["name"] == "get_weather"
        assert steps[0]["result"] == "Sunny, 25C"

    def test_tool_call_with_invalid_json_arguments(self):
        model = self._make_model()
        messages = [
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_456",
                        "type": "function",
                        "function": {"name": "func", "arguments": "not valid json"},
                    }
                ],
            )
        ]
        steps = model._build_input(messages)
        assert steps[0]["type"] == "function_call"
        assert steps[0]["arguments"] == {}

    def test_multi_turn_conversation(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="Hi"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
            ),
            Message(role="tool", content="result", tool_call_id="c1", tool_name="f"),
            Message(role="user", content="How are you?"),
        ]
        steps = model._build_input(messages)
        # system skipped, assistant with tool_calls -> function_call, tool -> function_result, user -> user_input
        assert len(steps) == 4
        assert steps[0]["type"] == "user_input"
        assert steps[1]["type"] == "function_call"
        assert steps[2]["type"] == "function_result"
        assert steps[3]["type"] == "user_input"


class TestGetRequestKwargs:
    """Tests for request parameter building."""

    def _make_model(self, **kwargs):
        return GeminiInteractions(api_key="test-key", **kwargs)

    def test_basic_request(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hello")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["model"] == "gemini-3-flash-preview"
        assert "input" in kwargs
        assert "system_instruction" not in kwargs

    def test_system_instruction_extracted(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="You are a poet"),
            Message(role="user", content="Write a haiku"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["system_instruction"] == "You are a poet"

    def test_generation_config(self):
        model = self._make_model(temperature=0.5, top_p=0.9, max_output_tokens=100)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["generation_config"]["temperature"] == 0.5
        assert kwargs["generation_config"]["top_p"] == 0.9
        assert kwargs["generation_config"]["max_output_tokens"] == 100

    def test_generation_config_omitted_when_empty(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "generation_config" not in kwargs

    def test_tools_included(self):
        model = self._make_model()
        # Tools are already formatted by _format_tools before reaching _get_request_kwargs
        tools = [
            {"type": "function", "name": "func", "description": "desc", "parameters": {}},
        ]
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages, tools=tools)
        assert "tools" in kwargs
        assert kwargs["tools"][0]["name"] == "func"

    def test_store_parameter(self):
        model = self._make_model(store=False)
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["store"] is False

    def test_previous_interaction_id_from_provider_data(self):
        """Previous interaction ID is read from assistant message provider_data,
        and only the new turn is sent (server holds history)."""
        model = self._make_model()
        messages = [
            Message(role="user", content="First message"),
            Message(role="assistant", content="Response", provider_data={"interaction_id": "interactions/abc123"}),
            Message(role="user", content="Follow up"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["previous_interaction_id"] == "interactions/abc123"
        # Server-side history: don't replay "First message", send only "Follow up".
        assert kwargs["input"] == [{"type": "user_input", "content": [{"type": "text", "text": "Follow up"}]}]

    def test_no_previous_interaction_id_on_first_turn(self):
        model = self._make_model()
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "previous_interaction_id" not in kwargs

    def test_thinking_config(self):
        model = self._make_model(thinking_level="high")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["generation_config"]["thinking_level"] == "high"

    def test_response_modalities(self):
        model = self._make_model(response_modalities=["text", "image"])
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["response_modalities"] == ["text", "image"]

    def test_generation_config_passthrough_merges_with_fields(self):
        """Supported keys from generation_config are merged into the request config."""
        model = self._make_model(
            temperature=0.5,
            generation_config={"top_p": 0.9, "thinking_summaries": "auto", "tool_choice": "auto"},
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="Hi")])
        cfg = kwargs["generation_config"]
        assert cfg["temperature"] == 0.5
        assert cfg["top_p"] == 0.9
        assert cfg["thinking_summaries"] == "auto"
        assert cfg["tool_choice"] == "auto"

    def test_generation_config_passthrough_overrides_fields(self):
        """When the same key is set on both, the passthrough wins."""
        model = self._make_model(temperature=0.5, generation_config={"temperature": 0.9})
        kwargs = model._get_request_kwargs([Message(role="user", content="Hi")])
        assert kwargs["generation_config"]["temperature"] == 0.9

    def test_generation_config_accepts_pydantic_object(self):
        """Pydantic models (e.g. GenerateContentConfig) are dumped with exclude_none."""
        from typing import Optional as _Opt

        from pydantic import BaseModel as _PydBase

        class FakeConfig(_PydBase):
            temperature: _Opt[float] = None
            top_p: _Opt[float] = None
            max_output_tokens: _Opt[int] = None  # unset, should be excluded

        model = self._make_model(generation_config=FakeConfig(temperature=0.8, top_p=0.95))
        kwargs = model._get_request_kwargs([Message(role="user", content="Hi")])
        cfg = kwargs["generation_config"]
        assert cfg["temperature"] == 0.8
        assert cfg["top_p"] == 0.95
        assert "max_output_tokens" not in cfg

    def test_store_false_opts_out_of_server_state(self):
        """store=False disables previous_interaction_id chaining; full history is sent."""
        model = self._make_model(store=False)
        messages = [
            Message(role="user", content="First turn"),
            Message(role="assistant", content="Reply 1", provider_data={"interaction_id": "interactions/abc"}),
            Message(role="user", content="Follow up"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert "previous_interaction_id" not in kwargs
        # Full history is sent: user1 + assistant1 (no tool calls -> skipped) + user2
        # _build_input emits a user_input step for each user message
        input_steps = kwargs["input"]
        user_steps = [s for s in input_steps if s["type"] == "user_input"]
        assert len(user_steps) == 2
        assert user_steps[0]["content"][0]["text"] == "First turn"
        assert user_steps[1]["content"][0]["text"] == "Follow up"

    def test_input_sliced_when_previous_interaction_id_set(self):
        """When previous_interaction_id is set, only messages after the prior assistant turn are sent."""
        model = self._make_model()
        messages = [
            Message(role="user", content="First turn"),
            Message(role="assistant", content="Reply 1", provider_data={"interaction_id": "interactions/abc"}),
            Message(role="user", content="Follow up"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["previous_interaction_id"] == "interactions/abc"
        # Only the new user message should be in input - server has the prior turns
        input_steps = kwargs["input"]
        assert len(input_steps) == 1
        assert input_steps[0]["type"] == "user_input"
        assert input_steps[0]["content"][0]["text"] == "Follow up"

    def test_input_includes_all_messages_on_first_turn(self):
        """Without a previous_interaction_id, full message history is sent."""
        model = self._make_model()
        messages = [Message(role="user", content="Hello")]
        kwargs = model._get_request_kwargs(messages)
        assert "previous_interaction_id" not in kwargs
        assert kwargs["input"][0]["content"][0]["text"] == "Hello"

    def test_input_sliced_includes_tool_results_after_assistant(self):
        """Mid-tool-call: send only tool result steps after the prior assistant turn."""
        model = self._make_model()
        messages = [
            Message(role="user", content="Weather?"),
            Message(
                role="assistant",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}],
                provider_data={"interaction_id": "interactions/abc"},
            ),
            Message(role="tool", tool_call_id="c1", tool_name="weather", content="Sunny"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["previous_interaction_id"] == "interactions/abc"
        input_steps = kwargs["input"]
        assert len(input_steps) == 1
        assert input_steps[0]["type"] == "function_result"
        assert input_steps[0]["call_id"] == "c1"
        assert input_steps[0]["result"] == "Sunny"


class TestDeepResearchAgentPath:
    """Tests for the Deep Research agent path (agent + agent_config).

    The SDK enforces that `model`/`generation_config` and `agent`/`agent_config`
    are mutually exclusive; these tests assert we never mix them.
    """

    def _make_model(self, **kwargs):
        return GeminiInteractions(api_key="test-key", **kwargs)

    def test_default_uses_model_path_not_agent(self):
        model = self._make_model()
        kwargs = model._get_request_kwargs([Message(role="user", content="Hi")])
        assert "model" in kwargs
        assert "agent" not in kwargs
        assert "agent_config" not in kwargs

    def test_agent_set_uses_agent_path_and_omits_model(self):
        model = self._make_model(agent="deep-research-preview-04-2026")
        kwargs = model._get_request_kwargs([Message(role="user", content="Research jazz")])
        assert kwargs["agent"] == "deep-research-preview-04-2026"
        assert "model" not in kwargs
        assert "generation_config" not in kwargs

    def test_deep_research_forces_background_and_store(self):
        # Deep Research requires background=true (and store=true) for the
        # autonomous loop; the model must force both regardless of `store`.
        model = self._make_model(agent="deep-research-preview-04-2026", store=False)
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["background"] is True
        assert kwargs["store"] is True

    def test_model_path_does_not_force_background(self):
        model = self._make_model()
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert "background" not in kwargs

    def test_agent_path_drops_system_message(self):
        # Deep Research rejects system_instruction and treats input as the
        # research request. Agno's framework boilerplate is neither sent as
        # system_instruction nor folded into input on the agent path.
        model = self._make_model(agent="deep-research-preview-04-2026")
        messages = [
            Message(role="system", content="Be concise."),
            Message(role="user", content="What is a TPU?"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert "system_instruction" not in kwargs
        assert kwargs["input"] == [{"type": "user_input", "content": [{"type": "text", "text": "What is a TPU?"}]}]

    def test_agent_path_only_sends_new_turn_when_continuing(self):
        # With previous_interaction_id set, the server already has history;
        # send only the newest user turn, not the replayed conversation.
        model = self._make_model(agent="deep-research-preview-04-2026")
        messages = [
            Message(role="system", content="boilerplate"),
            Message(role="user", content="Research TPUs"),
            Message(role="assistant", content="Here is the plan", provider_data={"interaction_id": "int-1"}),
            Message(role="user", content="Focus on competitors"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["previous_interaction_id"] == "int-1"
        assert kwargs["input"] == [
            {"type": "user_input", "content": [{"type": "text", "text": "Focus on competitors"}]}
        ]

    def test_model_path_still_sends_system_instruction(self):
        model = self._make_model()
        messages = [
            Message(role="system", content="Be concise."),
            Message(role="user", content="What is a TPU?"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["system_instruction"] == "Be concise."

    def test_deep_research_agent_config_built(self):
        model = self._make_model(
            agent="deep-research-pro-preview-12-2025",
            collaborative_planning=True,
            thinking_summaries="auto",
            visualization="auto",
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="Research jazz")])
        assert kwargs["agent_config"] == {
            "type": "deep-research",
            "collaborative_planning": True,
            "thinking_summaries": "auto",
            "visualization": "auto",
        }

    def test_generation_config_never_sent_on_agent_path(self):
        # Even if generation params are set, the agent path must not send them
        # (the SDK raises ValueError if agent + generation_config are combined).
        model = self._make_model(
            agent="deep-research-pro-preview-12-2025",
            temperature=0.7,
            max_output_tokens=500,
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert "generation_config" not in kwargs
        assert "agent" in kwargs

    def test_non_deep_research_agent_sends_no_agent_config(self):
        model = self._make_model(agent="some-future-agent")
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["agent"] == "some-future-agent"
        assert "agent_config" not in kwargs
        assert "model" not in kwargs

    def test_mcp_servers_added_to_tools(self):
        model = self._make_model(
            agent="deep-research-preview-04-2026",
            mcp_servers=[
                {
                    "name": "Deploy Tracker",
                    "url": "https://mcp.example.com/mcp",
                    "headers": {"Authorization": "Bearer tok"},
                    "allowed_tools": ["status"],
                }
            ],
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="check deploys")])
        assert {
            "type": "mcp_server",
            "name": "Deploy Tracker",
            "url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer tok"},
            "allowed_tools": ["status"],
        } in kwargs["tools"]

    def test_multiple_mcp_servers(self):
        model = self._make_model(
            agent="deep-research-preview-04-2026",
            mcp_servers=[
                {"url": "https://a.example.com/mcp"},
                {"url": "https://b.example.com/mcp"},
            ],
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        mcp = [t for t in kwargs["tools"] if t["type"] == "mcp_server"]
        assert len(mcp) == 2
        assert {t["url"] for t in mcp} == {"https://a.example.com/mcp", "https://b.example.com/mcp"}

    def test_mcp_server_type_key_cannot_be_overridden(self):
        # A user-supplied mcp_servers entry with a stray "type" key must not
        # be able to clobber the discriminator the SDK uses to route the tool.
        model = self._make_model(
            agent="deep-research-preview-04-2026",
            mcp_servers=[{"url": "https://x.example.com/mcp", "type": "function"}],
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        mcp = [t for t in kwargs["tools"] if t.get("type") == "mcp_server"]
        assert len(mcp) == 1
        assert mcp[0]["url"] == "https://x.example.com/mcp"
        # No tool should have been registered as a function as a side effect.
        assert not any(t.get("type") == "function" for t in kwargs["tools"])

    def test_file_search_added_to_tools(self):
        model = self._make_model(
            agent="deep-research-preview-04-2026",
            file_search_store_names=["fileSearchStores/my-store"],
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="compare to our docs")])
        assert {
            "type": "file_search",
            "file_search_store_names": ["fileSearchStores/my-store"],
        } in kwargs["tools"]

    def test_no_extra_tools_when_unset(self):
        model = self._make_model(agent="deep-research-preview-04-2026")
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        # No mcp/file_search configured -> not present (Deep Research has its
        # own defaults server-side when tools is omitted).
        assert "tools" not in kwargs

    def test_deep_research_partial_config(self):
        # Only the knobs that are set should appear; type is always present.
        model = self._make_model(
            agent="deep-research-preview-04-2026",
            collaborative_planning=True,
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["agent_config"] == {"type": "deep-research", "collaborative_planning": True}

    def test_agent_path_keeps_shared_params(self):
        # service_tier / store still flow on the agent path; the system message
        # is dropped (not sent as system_instruction, not folded into input).
        model = self._make_model(
            agent="deep-research-pro-preview-12-2025",
            service_tier="priority",
            store=True,
        )
        messages = [
            Message(role="system", content="Be thorough"),
            Message(role="user", content="Research the Apollo program"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert "system_instruction" not in kwargs
        assert kwargs["input"] == [
            {"type": "user_input", "content": [{"type": "text", "text": "Research the Apollo program"}]}
        ]
        assert kwargs["service_tier"] == "priority"
        # store is forced True on the agent path regardless of the configured value
        assert kwargs["store"] is True


class TestAntigravityAgentPath:
    """Tests for the Antigravity agent path.

    Antigravity differs from Deep Research:
      - it does NOT support background=True (foreground autonomous loop)
      - it takes an `environment` parameter (string id or full dict config)
      - it carries no agent_config (no deep-research knobs apply)
    """

    def _make_model(self, **kwargs):
        return GeminiInteractions(api_key="test-key", **kwargs)

    def test_antigravity_uses_agent_path(self):
        model = self._make_model(agent="antigravity-preview-05-2026", environment="remote")
        kwargs = model._get_request_kwargs([Message(role="user", content="Plot solar growth")])
        assert kwargs["agent"] == "antigravity-preview-05-2026"
        assert "model" not in kwargs
        assert "generation_config" not in kwargs

    def test_antigravity_forces_store_but_not_background(self):
        # Antigravity runs in the foreground; the SDK rejects background=True.
        # We must force store=True (server-side state is required) but must
        # not force background.
        model = self._make_model(
            agent="antigravity-preview-05-2026",
            environment="remote",
            store=False,
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["store"] is True
        assert "background" not in kwargs

    def test_antigravity_forwards_environment_string(self):
        model = self._make_model(agent="antigravity-preview-05-2026", environment="remote")
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["environment"] == "remote"

    def test_antigravity_forwards_environment_id(self):
        model = self._make_model(agent="antigravity-preview-05-2026", environment="env_abc123")
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["environment"] == "env_abc123"

    def test_antigravity_forwards_environment_dict(self):
        # Full EnvironmentConfig should pass through unchanged.
        env_dict = {
            "type": "remote",
            "sources": [{"type": "git", "url": "https://example.com/repo"}],
            "network": {"allow_internet_access": True},
        }
        model = self._make_model(agent="antigravity-preview-05-2026", environment=env_dict)
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert kwargs["environment"] == env_dict

    def test_antigravity_emits_no_agent_config(self):
        # agent_config is deep-research-specific; setting deep-research knobs
        # on Antigravity must not produce an agent_config block.
        model = self._make_model(
            agent="antigravity-preview-05-2026",
            environment="remote",
            collaborative_planning=True,
            thinking_summaries="auto",
            visualization="auto",
        )
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert "agent_config" not in kwargs

    def test_environment_not_sent_on_model_path(self):
        # `environment` is meaningful only on the agent path; on the model
        # path it must be silently dropped (the SDK rejects it).
        model = self._make_model(environment="remote")
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert "environment" not in kwargs

    def test_environment_not_sent_when_unset_on_agent_path(self):
        model = self._make_model(agent="antigravity-preview-05-2026")
        kwargs = model._get_request_kwargs([Message(role="user", content="x")])
        assert "environment" not in kwargs

    def test_antigravity_drops_system_message(self):
        # Same agent-path system_instruction rule as Deep Research applies.
        model = self._make_model(agent="antigravity-preview-05-2026", environment="remote")
        messages = [
            Message(role="system", content="Be concise."),
            Message(role="user", content="Plot solar growth"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert "system_instruction" not in kwargs

    def test_antigravity_multi_turn_only_sends_new_turn(self):
        # With previous_interaction_id set, the server already has the prior
        # sandbox state and conversation; only the new user turn goes on the
        # wire. Same slicing rule as Deep Research.
        model = self._make_model(agent="antigravity-preview-05-2026", environment="remote")
        messages = [
            Message(role="system", content="boilerplate"),
            Message(role="user", content="Plot solar growth and save as solar.png"),
            Message(
                role="assistant",
                content="Done, saved to solar.png",
                provider_data={"interaction_id": "int-ag-1"},
            ),
            Message(role="user", content="Now turn it into a 3-slide HTML deck"),
        ]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["previous_interaction_id"] == "int-ag-1"
        assert kwargs["input"] == [
            {"type": "user_input", "content": [{"type": "text", "text": "Now turn it into a 3-slide HTML deck"}]}
        ]


class TestAgentBackgroundPolling:
    """The agent path runs in the background; invoke() must poll to terminal."""

    def _make_model(self, **kwargs):
        return GeminiInteractions(api_key="test-key", agent="deep-research-preview-04-2026", **kwargs)

    def test_poll_returns_immediately_if_already_terminal(self):
        model = self._make_model()
        done = MagicMock()
        done.status = "completed"
        # No client calls needed; already terminal.
        assert model._poll_until_terminal(done) is done

    def test_poll_loops_until_completed(self):
        model = self._make_model(agent_poll_interval=0.0)

        in_progress = MagicMock()
        in_progress.status = "in_progress"
        in_progress.id = "interactions/dr-1"

        completed = MagicMock()
        completed.status = "completed"
        completed.id = "interactions/dr-1"

        mock_client = MagicMock()
        # First get() still in progress, second completed.
        mock_client.interactions.get.side_effect = [in_progress, completed]

        with patch.object(model, "get_client", return_value=mock_client):
            result = model._poll_until_terminal(in_progress)

        assert result is completed
        assert mock_client.interactions.get.call_count == 2

    def test_poll_times_out(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model(agent_poll_interval=0.0, agent_max_wait=0.0)

        in_progress = MagicMock()
        in_progress.status = "in_progress"
        in_progress.id = "interactions/dr-1"

        mock_client = MagicMock()
        mock_client.interactions.get.return_value = in_progress

        with patch.object(model, "get_client", return_value=mock_client):
            with pytest.raises(ModelProviderError, match="did not complete"):
                model._poll_until_terminal(in_progress)

    def test_invoke_polls_on_agent_path(self):
        from agno.models.google.gemini_interactions import ModelOutputStep, TextContent

        model = self._make_model(agent_poll_interval=0.0)

        in_progress = MagicMock()
        in_progress.status = "in_progress"
        in_progress.id = "interactions/dr-1"

        text = MagicMock(spec=TextContent)
        text.text = "Research complete."
        text.annotations = None
        text.__class__ = TextContent
        step = MagicMock(spec=ModelOutputStep)
        step.content = [text]
        step.__class__ = ModelOutputStep
        completed = MagicMock()
        completed.status = "completed"
        completed.id = "interactions/dr-1"
        completed.steps = [step]
        completed.usage = None

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = in_progress
        mock_client.interactions.get.return_value = completed

        msg = Message(role="user", content="Research X")
        with patch.object(model, "get_client", return_value=mock_client):
            resp = model.invoke([msg], assistant_message=Message(role="assistant"))

        # create() called with background+store forced; then polled to completion.
        _, create_kwargs = mock_client.interactions.create.call_args
        assert create_kwargs["background"] is True
        assert create_kwargs["store"] is True
        mock_client.interactions.get.assert_called_with("interactions/dr-1")
        assert resp.content == "Research complete."


class TestParseInteractionResponse:
    """Tests for parsing Interaction API responses."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def _make_model_output_step(self, text):
        """Create a mock ModelOutputStep with TextContent."""
        from agno.models.google.gemini_interactions import ModelOutputStep, TextContent

        mock_text = MagicMock(spec=TextContent)
        mock_text.text = text
        mock_text.__class__ = TextContent

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.content = [mock_text]
        mock_step.__class__ = ModelOutputStep
        return mock_step

    def _make_thought_step(self, summary_text, signature=None):
        from agno.models.google.gemini_interactions import TextContent, ThoughtStep

        # ThoughtStep.summary is List[TextContent | ImageContent]
        mock_summary_item = MagicMock(spec=TextContent)
        mock_summary_item.text = summary_text
        mock_summary_item.__class__ = TextContent

        mock_step = MagicMock(spec=ThoughtStep)
        mock_step.summary = [mock_summary_item]
        mock_step.signature = signature
        mock_step.__class__ = ThoughtStep
        return mock_step

    def _make_function_call_step(self, call_id, name, arguments, signature=None):
        from agno.models.google.gemini_interactions import FunctionCallStep

        mock_step = MagicMock(spec=FunctionCallStep)
        mock_step.id = call_id
        mock_step.name = name
        mock_step.arguments = arguments
        mock_step.signature = signature
        mock_step.__class__ = FunctionCallStep
        return mock_step

    def test_parse_text_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/test123"
        mock_interaction.steps = [self._make_model_output_step("Hello, world!")]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.role == "assistant"
        assert response.content == "Hello, world!"
        assert response.provider_data["interaction_id"] == "interactions/test123"

    def test_parse_deep_research_citation_types(self):
        """Deep Research emits url_citation, file_citation, and place_citation.

        All go to citations.raw; only url_citation populates citations.urls.
        """
        from agno.models.google.gemini_interactions import ModelOutputStep, TextContent

        url_ann = MagicMock()
        url_ann.type = "url_citation"
        url_ann.url = "https://example.com/jazz"
        url_ann.title = "Jazz history"

        file_ann = MagicMock()
        file_ann.type = "file_citation"

        place_ann = MagicMock()
        place_ann.type = "place_citation"

        unknown_ann = MagicMock()
        unknown_ann.type = "something_new"

        mock_text = MagicMock(spec=TextContent)
        mock_text.text = "Jazz originated in New Orleans."
        mock_text.annotations = [url_ann, file_ann, place_ann, unknown_ann]
        mock_text.__class__ = TextContent

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.content = [mock_text]
        mock_step.__class__ = ModelOutputStep

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/dr1"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = self._make_model()._parse_provider_response(mock_interaction)
        # url + file + place captured in raw; unknown skipped
        assert response.citations is not None
        assert len(response.citations.raw) == 3
        # only the url citation produces a UrlCitation
        assert len(response.citations.urls) == 1
        assert response.citations.urls[0].url == "https://example.com/jazz"

    def test_parse_function_call_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/test456"
        mock_interaction.steps = [self._make_function_call_step("call_1", "get_weather", {"city": "Paris"})]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["id"] == "call_1"
        assert response.tool_calls[0]["function"]["name"] == "get_weather"
        assert response.tool_calls[0]["function"]["arguments"] == '{"city": "Paris"}'

    def _make_function_result_step(self, call_id, result, name=None, is_error=None):
        from agno.models.google.gemini_interactions import FunctionResultStep

        mock_step = MagicMock(spec=FunctionResultStep)
        mock_step.call_id = call_id
        mock_step.result = result
        mock_step.name = name
        mock_step.is_error = is_error
        mock_step.__class__ = FunctionResultStep
        return mock_step

    def test_agent_path_pairs_function_call_with_result(self):
        """On the agent path, Antigravity returns FunctionCallStep + matching
        FunctionResultStep. Surfacing them as model.tool_calls would make Agno
        dispatch locally and 400 on the follow-up turn; instead, pair them
        into ToolExecution records so AgentOS/run_response.tools shows the
        full audit (tool name, args, result, is_error)."""
        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/ag1"
        mock_interaction.steps = [
            self._make_model_output_step("Listing the sandbox..."),
            self._make_function_call_step("call_ag_1", "list_files", {"path": "."}),
            self._make_function_result_step("call_ag_1", "main.py\nREADME.md"),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.content == "Listing the sandbox..."
        assert response.tool_calls == []
        assert response.tool_executions is not None
        assert len(response.tool_executions) == 1
        te = response.tool_executions[0]
        assert te.tool_call_id == "call_ag_1"
        assert te.tool_name == "list_files"
        assert te.tool_args == {"path": "."}
        assert te.result == "main.py\nREADME.md"
        assert te.tool_call_error is None

    def test_agent_path_client_tool_falls_through_to_tool_calls(self):
        """Regression for PR review: on the agent path, a FunctionCallStep
        with NO matching FunctionResultStep is a client-declared tool the
        autonomous loop is asking us to dispatch. Surface it as tool_calls
        (not silently dropped) so the run loop executes and posts the result."""
        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/client-pending"
        mock_interaction.steps = [
            self._make_function_call_step("call_client_1", "send_email", {"to": "yash@phidata.com"}),
            # NOTE: no matching FunctionResultStep - this is a client tool
            # the server is waiting for us to dispatch.
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert not response.tool_executions
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["id"] == "call_client_1"
        assert response.tool_calls[0]["function"]["name"] == "send_email"
        assert response.tool_calls[0]["function"]["arguments"] == '{"to": "yash@phidata.com"}'

    def test_agent_path_records_error_results(self):
        """is_error from FunctionResultStep flows to ToolExecution.tool_call_error."""
        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/ag-err"
        mock_interaction.steps = [
            self._make_function_call_step("call_err", "read_file", {"path": "/nope"}),
            self._make_function_result_step("call_err", "No such file", is_error=True),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.tool_executions[0].tool_call_error is True
        assert response.tool_executions[0].result == "No such file"

    def test_agent_path_records_code_execution(self):
        """Code execution call + result pair into a ToolExecution named
        'code_execution' with code/language args and stdout result."""
        # Build the Arguments via the real type so model_dump works.
        from google.genai._interactions.types.code_execution_call_step import Arguments as CEArgs

        from agno.models.google.gemini_interactions import (
            CodeExecutionCallStep,
            CodeExecutionResultStep,
        )
        from agno.models.google.gemini_interactions import (
            CodeExecutionCallStep as _CECall,
        )

        call_step = MagicMock(spec=_CECall)
        call_step.__class__ = CodeExecutionCallStep
        call_step.id = "call_ce_1"
        call_step.arguments = CEArgs(code="print(2 + 2)", language="python")
        call_step.signature = None

        result_step = MagicMock(spec=CodeExecutionResultStep)
        result_step.__class__ = CodeExecutionResultStep
        result_step.call_id = "call_ce_1"
        result_step.result = "4\n"
        result_step.is_error = False
        result_step.signature = None

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/ce1"
        mock_interaction.steps = [call_step, result_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        te = response.tool_executions[0]
        assert te.tool_name == "code_execution"
        assert te.tool_args == {"code": "print(2 + 2)", "language": "python"}
        assert te.result == "4\n"
        assert te.tool_call_error is False

    def test_agent_path_records_url_context(self):
        """URL context call + result pair into a ToolExecution with the
        per-URL status JSON-serialized into the result string."""
        from google.genai._interactions.types.url_context_call_step import Arguments as UCArgs
        from google.genai._interactions.types.url_context_result_step import Result as UCResult

        from agno.models.google.gemini_interactions import URLContextCallStep, URLContextResultStep

        call_step = MagicMock(spec=URLContextCallStep)
        call_step.__class__ = URLContextCallStep
        call_step.id = "call_uc_1"
        call_step.arguments = UCArgs(urls=["https://example.com"])
        call_step.signature = None

        result_step = MagicMock(spec=URLContextResultStep)
        result_step.__class__ = URLContextResultStep
        result_step.call_id = "call_uc_1"
        result_step.result = [UCResult(status="success", url="https://example.com")]
        result_step.is_error = None
        result_step.signature = None

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/uc1"
        mock_interaction.steps = [call_step, result_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        te = response.tool_executions[0]
        assert te.tool_name == "url_context"
        assert te.tool_args == {"urls": ["https://example.com"]}
        assert te.result is not None
        assert "https://example.com" in te.result
        assert "success" in te.result

    def test_parse_thought_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/thought1"
        mock_interaction.steps = [
            self._make_thought_step("Let me think about this...", signature="sig123"),
            self._make_model_output_step("Here is my answer."),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.reasoning_content == "Let me think about this..."
        assert response.content == "Here is my answer."
        assert response.provider_data["thought_signature"] == "sig123"

    def test_summarize_thought_truncates_and_strips_heading(self):
        from agno.models.google.gemini_interactions import _summarize_thought

        assert _summarize_thought("**Locating Initial Data**\n\nbody") == "Locating Initial Data"
        # No heading: first non-empty line wins.
        assert _summarize_thought("\n\nLet me think\n\nMore...") == "Let me think"
        # Long line is truncated with ellipsis.
        long = "x" * 300
        out = _summarize_thought(long, max_chars=50)
        assert len(out) == 50
        assert out.endswith("…")

    def test_parse_usage_metrics(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/metrics1"
        mock_interaction.steps = [self._make_model_output_step("Hello")]

        mock_usage = MagicMock()
        mock_usage.total_input_tokens = 10
        mock_usage.total_output_tokens = 20
        mock_usage.total_tokens = 30
        mock_interaction.usage = mock_usage

        response = model._parse_provider_response(mock_interaction)
        assert response.response_usage is not None
        assert response.response_usage.input_tokens == 10
        assert response.response_usage.output_tokens == 20
        assert response.response_usage.total_tokens == 30

    def test_parse_empty_response(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/empty1"
        mock_interaction.steps = []
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.role == "assistant"
        assert response.content is None
        assert response.tool_calls == []

    def test_parse_failed_status_raises_with_error(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/fail1"
        mock_interaction.status = "failed"
        mock_interaction.error = "rate limit exceeded"
        mock_interaction.steps = None

        with pytest.raises(ModelProviderError, match="rate limit exceeded"):
            model._parse_provider_response(mock_interaction)

    def test_parse_failed_status_without_error_detail(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/fail2"
        mock_interaction.status = "failed"
        mock_interaction.error = None
        mock_interaction.steps = None

        with pytest.raises(ModelProviderError, match="no error detail"):
            model._parse_provider_response(mock_interaction)

    def test_parse_cancelled_status_raises(self):
        # A cancelled interaction is terminal but unsuccessful; the parser
        # must not silently return an empty response.
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/cancel1"
        mock_interaction.status = "cancelled"
        mock_interaction.error = None
        mock_interaction.steps = None

        with pytest.raises(ModelProviderError, match="cancelled"):
            model._parse_provider_response(mock_interaction)

    def test_parse_incomplete_status_raises(self):
        # An incomplete interaction means the autonomous loop stopped before
        # finishing; surface this rather than returning a partial response.
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/inc1"
        mock_interaction.status = "incomplete"
        mock_interaction.error = "max_steps_reached"
        mock_interaction.steps = None

        with pytest.raises(ModelProviderError, match="incomplete.*max_steps_reached"):
            model._parse_provider_response(mock_interaction)

    def test_interaction_id_in_provider_data(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/first"
        mock_interaction.steps = []
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.provider_data["interaction_id"] == "interactions/first"

    def test_multiple_function_calls(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/multi"
        mock_interaction.steps = [
            self._make_function_call_step("call_1", "func_a", {"x": 1}),
            self._make_function_call_step("call_2", "func_b", {"y": 2}),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0]["function"]["name"] == "func_a"
        assert response.tool_calls[1]["function"]["name"] == "func_b"

    def test_function_call_with_signature(self):
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/sig"
        mock_interaction.steps = [
            self._make_function_call_step("call_1", "func", {"x": 1}, signature="thought_sig_abc"),
        ]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.tool_calls[0]["thought_signature"] == "thought_sig_abc"

    def test_parse_none_usage_fields(self):
        """Usage fields that are None should default to 0."""
        model = self._make_model()

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/nullusage"
        mock_interaction.steps = [self._make_model_output_step("Hi")]

        mock_usage = MagicMock()
        mock_usage.total_input_tokens = None
        mock_usage.total_output_tokens = None
        mock_usage.total_tokens = None
        mock_interaction.usage = mock_usage

        response = model._parse_provider_response(mock_interaction)
        assert response.response_usage.input_tokens == 0
        assert response.response_usage.output_tokens == 0
        assert response.response_usage.total_tokens == 0


class TestInvoke:
    """Tests for the invoke method."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_process_model_response_propagates_tool_executions(self):
        """Regression: _process_model_response in base.py must copy
        provider_response.tool_executions onto the accumulated
        model_response so they reach run_response.tools. Mustafa caught
        this; we kept setting them in the parser and base dropped them."""
        from agno.models.response import ModelResponse, ToolExecution

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        # Build an interaction with one server-side tool call+result pair so
        # the agent-path parser produces a ToolExecution.
        model.agent = "antigravity-preview-05-2026"
        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/propagate1"
        mock_interaction.usage = None
        parser_helper = TestParseInteractionResponse()
        mock_interaction.steps = [
            parser_helper._make_function_call_step("call_propagate_1", "list_files", {"path": "/"}),
            parser_helper._make_function_result_step("call_propagate_1", "main.py"),
        ]
        mock_client.interactions.create.return_value = mock_interaction

        messages = [Message(role="user", content="ls")]
        assistant_message = Message(role="assistant")
        aggregated = ModelResponse()
        model._process_model_response(
            messages=messages,
            assistant_message=assistant_message,
            model_response=aggregated,
        )

        assert aggregated.tool_executions is not None
        assert len(aggregated.tool_executions) == 1
        te = aggregated.tool_executions[0]
        assert isinstance(te, ToolExecution)
        assert te.tool_name == "list_files"
        assert te.result == "main.py"

    def test_invoke_calls_interactions_create(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/invoke1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.interactions.create.return_value = mock_interaction

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        model.invoke(messages, assistant_message)

        mock_client.interactions.create.assert_called_once()
        call_kwargs = mock_client.interactions.create.call_args[1]
        assert call_kwargs["model"] == "gemini-3-flash-preview"
        assert "input" in call_kwargs

    def test_invoke_passes_tools(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/tools1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.interactions.create.return_value = mock_interaction

        # Tools passed to invoke() are already formatted by _format_tools (Interactions API format)
        tools = [
            {"type": "function", "name": "search", "description": "Search", "parameters": {}},
        ]
        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        model.invoke(messages, assistant_message, tools=tools)

        call_kwargs = mock_client.interactions.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["name"] == "search"

    def test_invoke_error_raises_model_provider_error(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.side_effect = Exception("API error")

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        with pytest.raises(ModelProviderError, match="API error"):
            model.invoke(messages, assistant_message)

    def test_invoke_returns_interaction_id_in_provider_data(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/tracked1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.interactions.create.return_value = mock_interaction

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        response = model.invoke(messages, assistant_message)
        assert response.provider_data["interaction_id"] == "interactions/tracked1"


class TestInvokeAsync:
    """Tests for the async invoke method."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    @pytest.mark.asyncio
    async def test_ainvoke_calls_interactions_create(self):
        from unittest.mock import AsyncMock

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/async1"
        mock_interaction.steps = []
        mock_interaction.usage = None
        mock_client.aio.interactions.create = AsyncMock(return_value=mock_interaction)

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        await model.ainvoke(messages, assistant_message)

        mock_client.aio.interactions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ainvoke_error_raises_model_provider_error(self):
        from unittest.mock import AsyncMock

        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.aio.interactions.create = AsyncMock(side_effect=Exception("Async error"))

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        with pytest.raises(ModelProviderError, match="Async error"):
            await model.ainvoke(messages, assistant_message)


class TestInvokeStream:
    """Tests for streaming invoke."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_invoke_stream_sets_stream_param(self):
        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.return_value = iter([])

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        list(model.invoke_stream(messages, assistant_message))

        call_kwargs = mock_client.interactions.create.call_args[1]
        assert call_kwargs["stream"] is True

    def test_invoke_stream_handles_text_delta(self):
        from agno.models.google.gemini_interactions import DeltaText, interaction_types

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        # Create a mock StepDelta event with DeltaText
        mock_event = MagicMock(spec=interaction_types.StepDelta)
        mock_event.__class__ = interaction_types.StepDelta
        mock_delta = MagicMock(spec=DeltaText)
        mock_delta.__class__ = DeltaText
        mock_delta.text = "Hello"
        mock_event.delta = mock_delta

        mock_client.interactions.create.return_value = iter([mock_event])

        messages = [Message(role="user", content="Hi")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        assert any(r.content == "Hello" for r in responses)

    def test_invoke_stream_handles_image_delta(self):
        """Streamed visualization charts (DeltaImage) surface incrementally."""
        import base64

        from agno.models.google.gemini_interactions import DeltaImage, interaction_types

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        png = base64.b64encode(b"fake-png-bytes").decode()
        mock_event = MagicMock(spec=interaction_types.StepDelta)
        mock_event.__class__ = interaction_types.StepDelta
        mock_delta = MagicMock(spec=DeltaImage)
        mock_delta.__class__ = DeltaImage
        mock_delta.data = png
        mock_delta.mime_type = "image/png"
        mock_event.delta = mock_delta

        mock_client.interactions.create.return_value = iter([mock_event])

        responses = list(model.invoke_stream([Message(role="user", content="chart it")], Message(role="assistant")))
        imgs = [img for r in responses if r.images for img in r.images]
        assert len(imgs) == 1

    def test_invoke_stream_handles_interaction_created(self):
        from agno.models.google.gemini_interactions import interaction_types

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        mock_event = MagicMock(spec=interaction_types.InteractionCreatedEvent)
        mock_event.__class__ = interaction_types.InteractionCreatedEvent
        mock_event.interaction = MagicMock()
        mock_event.interaction.id = "interactions/stream1"

        mock_client.interactions.create.return_value = iter([mock_event])

        messages = [Message(role="user", content="Hi")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        assert any(
            r.provider_data and r.provider_data.get("interaction_id") == "interactions/stream1" for r in responses
        )
        assert any(r.role == "assistant" for r in responses)

    def test_invoke_stream_merges_thought_signature(self):
        """thought_signature must merge into provider_data without clobbering siblings."""
        from agno.models.google.gemini_interactions import (
            DeltaThoughtSignature,
            DeltaThoughtSummary,
            TextContent,
            interaction_types,
        )

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        text = MagicMock(spec=TextContent)
        text.text = "**Clarifying User Intent**\n\nThe request is vague..."
        text.__class__ = TextContent
        summary_delta = MagicMock(spec=DeltaThoughtSummary)
        summary_delta.__class__ = DeltaThoughtSummary
        summary_delta.content = text
        summary_evt = MagicMock(spec=interaction_types.StepDelta)
        summary_evt.__class__ = interaction_types.StepDelta
        summary_evt.delta = summary_delta
        summary_evt.index = 0

        sig_delta = MagicMock(spec=DeltaThoughtSignature)
        sig_delta.__class__ = DeltaThoughtSignature
        sig_delta.signature = "sig-abc"
        sig_evt = MagicMock(spec=interaction_types.StepDelta)
        sig_evt.__class__ = interaction_types.StepDelta
        sig_evt.delta = sig_delta
        sig_evt.index = 0

        mock_client.interactions.create.return_value = iter([summary_evt, sig_evt])

        responses = list(model.invoke_stream([Message(role="user", content="hi")], Message(role="assistant")))
        sig_responses = [r for r in responses if r.provider_data and "thought_signature" in r.provider_data]
        assert sig_responses
        assert sig_responses[0].provider_data["thought_signature"] == "sig-abc"

    def test_invoke_stream_handles_function_call_with_argument_deltas(self):
        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionCallStep,
            interaction_types,
        )

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        # StepStart with FunctionCallStep (arguments initially empty)
        mock_step = MagicMock(spec=FunctionCallStep)
        mock_step.__class__ = FunctionCallStep
        mock_step.id = "call_stream_1"
        mock_step.name = "get_weather"
        mock_step.arguments = {}
        mock_step.signature = None

        mock_start = MagicMock(spec=interaction_types.StepStart)
        mock_start.__class__ = interaction_types.StepStart
        mock_start.step = mock_step
        mock_start.index = 0

        # DeltaArgumentsDelta with the actual arguments
        mock_delta = MagicMock(spec=DeltaArgumentsDelta)
        mock_delta.__class__ = DeltaArgumentsDelta
        mock_delta.arguments = '{"city": "London"}'

        mock_delta_event = MagicMock(spec=interaction_types.StepDelta)
        mock_delta_event.__class__ = interaction_types.StepDelta
        mock_delta_event.delta = mock_delta
        mock_delta_event.index = 0

        # StepStop to emit the complete tool call
        mock_stop = MagicMock(spec=interaction_types.StepStop)
        mock_stop.__class__ = interaction_types.StepStop
        mock_stop.index = 0

        mock_client.interactions.create.return_value = iter([mock_start, mock_delta_event, mock_stop])

        messages = [Message(role="user", content="Weather?")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        tool_responses = [r for r in responses if r.tool_calls]
        assert len(tool_responses) == 1
        assert tool_responses[0].tool_calls[0]["function"]["name"] == "get_weather"
        assert tool_responses[0].tool_calls[0]["function"]["arguments"] == '{"city": "London"}'

    def test_invoke_stream_agent_path_pairs_call_with_result(self):
        """Streaming variant: FunctionCallStep StepStart -> args via deltas ->
        StepStop -> FunctionResultStep StepStart should yield a ToolExecution
        (with finalized args) and no client-side tool_calls."""
        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionCallStep,
            FunctionResultStep,
            interaction_types,
        )

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        # FunctionCallStep starts with empty args; args stream in via deltas.
        call_step = MagicMock(spec=FunctionCallStep)
        call_step.__class__ = FunctionCallStep
        call_step.id = "call_ag_stream_1"
        call_step.name = "list_files"
        call_step.arguments = {}
        call_step.signature = None

        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        arg_delta = MagicMock(spec=DeltaArgumentsDelta)
        arg_delta.__class__ = DeltaArgumentsDelta
        arg_delta.arguments = '{"path": "."}'

        arg_delta_event = MagicMock(spec=interaction_types.StepDelta)
        arg_delta_event.__class__ = interaction_types.StepDelta
        arg_delta_event.delta = arg_delta
        arg_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        # FunctionResultStep arrives next as its own StepStart; result is
        # fully populated (result steps don't stream their payload).
        result_step = MagicMock(spec=FunctionResultStep)
        result_step.__class__ = FunctionResultStep
        result_step.call_id = "call_ag_stream_1"
        result_step.result = "main.py\nREADME.md"
        result_step.name = "list_files"
        result_step.is_error = None

        result_start = MagicMock(spec=interaction_types.StepStart)
        result_start.__class__ = interaction_types.StepStart
        result_start.step = result_step
        result_start.index = 1

        result_stop = MagicMock(spec=interaction_types.StepStop)
        result_stop.__class__ = interaction_types.StepStop
        result_stop.index = 1

        mock_client.interactions.create.return_value = iter(
            [call_start, arg_delta_event, call_stop, result_start, result_stop]
        )

        messages = [Message(role="user", content="What's in the sandbox?")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        assert all(not r.tool_calls for r in responses)
        tool_executions = [te for r in responses for te in (r.tool_executions or [])]
        assert len(tool_executions) == 1
        te = tool_executions[0]
        assert te.tool_call_id == "call_ag_stream_1"
        assert te.tool_name == "list_files"
        assert te.tool_args == {"path": "."}
        assert te.result == "main.py\nREADME.md"

    def test_invoke_stream_agent_path_buffers_args_for_non_function_steps(self):
        """Regression: previously only FunctionCallStep buffered args via
        deltas. For GoogleSearchCallStep (and any other typed-args call) the
        API can deliver an empty Arguments at StepStart and stream the JSON
        via DeltaArgumentsDelta - we'd lose the queries and log
        'google_search()' with no args."""
        from google.genai._interactions.types.google_search_call_step import Arguments as GSArgs

        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionResultStep,
            GoogleSearchCallStep,
            GoogleSearchResultStep,
            interaction_types,
        )

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        # StepStart with empty Arguments (queries=None) - mimics what the
        # user reported seeing for google_search.
        call_step = MagicMock(spec=GoogleSearchCallStep)
        call_step.__class__ = GoogleSearchCallStep
        call_step.id = "call_gs_1"
        call_step.arguments = GSArgs()
        call_step.search_type = None
        call_step.signature = None

        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        # Streamed args JSON arrives via deltas - we should buffer and merge.
        arg_delta = MagicMock(spec=DeltaArgumentsDelta)
        arg_delta.__class__ = DeltaArgumentsDelta
        arg_delta.arguments = '{"queries": ["openai gpt-5", "anthropic claude"]}'

        arg_delta_event = MagicMock(spec=interaction_types.StepDelta)
        arg_delta_event.__class__ = interaction_types.StepDelta
        arg_delta_event.delta = arg_delta
        arg_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        result_step = MagicMock(spec=GoogleSearchResultStep)
        result_step.__class__ = GoogleSearchResultStep
        result_step.call_id = "call_gs_1"
        result_step.result = []
        result_step.is_error = None
        result_step.signature = None

        result_start = MagicMock(spec=interaction_types.StepStart)
        result_start.__class__ = interaction_types.StepStart
        result_start.step = result_step
        result_start.index = 1

        result_stop = MagicMock(spec=interaction_types.StepStop)
        result_stop.__class__ = interaction_types.StepStop
        result_stop.index = 1

        # Sanity: a Function call/result mixed in to make sure non-function
        # buffering didn't break function buffering.
        del FunctionResultStep  # only here to make the import explicit

        mock_client.interactions.create.return_value = iter(
            [call_start, arg_delta_event, call_stop, result_start, result_stop]
        )

        messages = [Message(role="user", content="Search the web")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        tool_executions = [te for r in responses for te in (r.tool_executions or [])]
        assert len(tool_executions) == 1
        te = tool_executions[0]
        assert te.tool_name == "google_search"
        assert te.tool_args == {"queries": ["openai gpt-5", "anthropic claude"]}

    def test_invoke_stream_google_search_typed_call_delta_populates_args(self):
        """Real-protocol regression: GoogleSearchCallStep arrives with
        arguments=None at StepStart and the actual queries come on a
        DeltaGoogleSearchCall (NOT DeltaArgumentsDelta). Result content
        likewise arrives on DeltaGoogleSearchResult after the result step's
        StepStart, not on the step itself."""
        from google.genai.interactions import step_delta

        from agno.models.google.gemini_interactions import (
            GoogleSearchCallStep,
            GoogleSearchResultStep,
            interaction_types,
        )

        GoogleSearchCallArguments = step_delta.GoogleSearchCallArguments
        GoogleSearchResult = step_delta.GoogleSearchResult

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        # Call step: empty at StepStart (arguments=None on the real API).
        call_step = MagicMock(spec=GoogleSearchCallStep)
        call_step.__class__ = GoogleSearchCallStep
        call_step.id = "call_gs_1"
        call_step.arguments = None
        call_step.search_type = None
        call_step.signature = None

        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        # Typed call delta with the actual queries.
        typed_call_delta = MagicMock(spec=step_delta.DeltaGoogleSearchCall)
        typed_call_delta.__class__ = step_delta.DeltaGoogleSearchCall
        typed_call_delta.arguments = GoogleSearchCallArguments(queries=["Agno", "Agno library"])
        typed_call_delta.signature = None

        call_delta_event = MagicMock(spec=interaction_types.StepDelta)
        call_delta_event.__class__ = interaction_types.StepDelta
        call_delta_event.delta = typed_call_delta
        call_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        # Result step: empty at StepStart; content arrives on delta.
        result_step = MagicMock(spec=GoogleSearchResultStep)
        result_step.__class__ = GoogleSearchResultStep
        result_step.call_id = "call_gs_1"
        result_step.result = None
        result_step.is_error = None
        result_step.signature = None

        result_start = MagicMock(spec=interaction_types.StepStart)
        result_start.__class__ = interaction_types.StepStart
        result_start.step = result_step
        result_start.index = 1

        result_delta = MagicMock(spec=step_delta.DeltaGoogleSearchResult)
        result_delta.__class__ = step_delta.DeltaGoogleSearchResult
        result_delta.result = [GoogleSearchResult(search_suggestions="suggestion-html-blob")]
        result_delta.is_error = None
        result_delta.signature = None

        result_delta_event = MagicMock(spec=interaction_types.StepDelta)
        result_delta_event.__class__ = interaction_types.StepDelta
        result_delta_event.delta = result_delta
        result_delta_event.index = 1

        result_stop = MagicMock(spec=interaction_types.StepStop)
        result_stop.__class__ = interaction_types.StepStop
        result_stop.index = 1

        mock_client.interactions.create.return_value = iter(
            [call_start, call_delta_event, call_stop, result_start, result_delta_event, result_stop]
        )

        responses = list(model.invoke_stream([Message(role="user", content="search agno")], Message(role="assistant")))
        tool_executions = [te for r in responses for te in (r.tool_executions or [])]
        assert len(tool_executions) == 1
        te = tool_executions[0]
        assert te.tool_name == "google_search"
        assert te.tool_args == {"queries": ["Agno", "Agno library"]}
        # Result content (the typed Result objects) should be JSON-serialized
        # into the ToolExecution.result string.
        assert te.result is not None
        assert "suggestion-html-blob" in te.result

    def test_invoke_stream_function_result_content_via_delta(self):
        """Real-protocol regression: FunctionResultStep arrives with
        result=None at StepStart; the actual TextContent payload arrives on
        a DeltaFunctionResult before StepStop. The result text must end up
        on ToolExecution.result, not silently dropped."""
        from google.genai.interactions import step_delta

        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionCallStep,
            FunctionResultStep,
            TextContent,
            interaction_types,
        )

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        call_step = MagicMock(spec=FunctionCallStep)
        call_step.__class__ = FunctionCallStep
        call_step.id = "call_lf_1"
        call_step.name = "list_files"
        call_step.arguments = {}
        call_step.signature = None
        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        arg_delta = MagicMock(spec=DeltaArgumentsDelta)
        arg_delta.__class__ = DeltaArgumentsDelta
        arg_delta.arguments = '{"path": "/app"}'
        arg_delta_event = MagicMock(spec=interaction_types.StepDelta)
        arg_delta_event.__class__ = interaction_types.StepDelta
        arg_delta_event.delta = arg_delta
        arg_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        result_step = MagicMock(spec=FunctionResultStep)
        result_step.__class__ = FunctionResultStep
        result_step.call_id = "call_lf_1"
        result_step.result = None
        result_step.is_error = None
        result_step.name = None
        result_step.signature = None
        result_start = MagicMock(spec=interaction_types.StepStart)
        result_start.__class__ = interaction_types.StepStart
        result_start.step = result_step
        result_start.index = 1

        # Actual result content arrives as a delta with TextContent items.
        text_item = MagicMock(spec=TextContent)
        text_item.text = '{"files":["main.py","README.md"]}'
        text_item.__class__ = TextContent
        result_delta = MagicMock(spec=step_delta.DeltaFunctionResult)
        result_delta.__class__ = step_delta.DeltaFunctionResult
        result_delta.result = [text_item]
        result_delta.is_error = None
        result_delta.name = "list_files"
        result_delta.call_id = None
        result_delta_event = MagicMock(spec=interaction_types.StepDelta)
        result_delta_event.__class__ = interaction_types.StepDelta
        result_delta_event.delta = result_delta
        result_delta_event.index = 1

        result_stop = MagicMock(spec=interaction_types.StepStop)
        result_stop.__class__ = interaction_types.StepStop
        result_stop.index = 1

        mock_client.interactions.create.return_value = iter(
            [call_start, arg_delta_event, call_stop, result_start, result_delta_event, result_stop]
        )

        responses = list(model.invoke_stream([Message(role="user", content="ls /app")], Message(role="assistant")))
        tool_executions = [te for r in responses for te in (r.tool_executions or [])]
        assert len(tool_executions) == 1
        te = tool_executions[0]
        assert te.tool_name == "list_files"
        assert te.tool_args == {"path": "/app"}
        assert te.result == '{"files":["main.py","README.md"]}'

    def test_invoke_stream_code_execution_typed_deltas(self):
        """Real-protocol regression: CodeExecutionCallStep streams its code
        on DeltaCodeExecutionCall, and the stdout streams on
        DeltaCodeExecutionResult. Both surfaces must end up on the
        ToolExecution."""
        from google.genai.interactions import step_delta

        from agno.models.google.gemini_interactions import (
            CodeExecutionCallStep,
            CodeExecutionResultStep,
            interaction_types,
        )

        CodeExecutionCallArguments = step_delta.CodeExecutionCallArguments

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        call_step = MagicMock(spec=CodeExecutionCallStep)
        call_step.__class__ = CodeExecutionCallStep
        call_step.id = "call_ce_1"
        call_step.arguments = None
        call_step.signature = None
        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        typed_call_delta = MagicMock(spec=step_delta.DeltaCodeExecutionCall)
        typed_call_delta.__class__ = step_delta.DeltaCodeExecutionCall
        typed_call_delta.arguments = CodeExecutionCallArguments(code="env", language=None)
        typed_call_delta.signature = None
        call_delta_event = MagicMock(spec=interaction_types.StepDelta)
        call_delta_event.__class__ = interaction_types.StepDelta
        call_delta_event.delta = typed_call_delta
        call_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        result_step = MagicMock(spec=CodeExecutionResultStep)
        result_step.__class__ = CodeExecutionResultStep
        result_step.call_id = "call_ce_1"
        result_step.result = None
        result_step.is_error = None
        result_step.signature = None
        result_start = MagicMock(spec=interaction_types.StepStart)
        result_start.__class__ = interaction_types.StepStart
        result_start.step = result_step
        result_start.index = 1

        result_delta = MagicMock(spec=step_delta.DeltaCodeExecutionResult)
        result_delta.__class__ = step_delta.DeltaCodeExecutionResult
        result_delta.result = "PYTHONUNBUFFERED=1\nHOME=/root\n"
        result_delta.is_error = None
        result_delta.signature = None
        result_delta_event = MagicMock(spec=interaction_types.StepDelta)
        result_delta_event.__class__ = interaction_types.StepDelta
        result_delta_event.delta = result_delta
        result_delta_event.index = 1

        result_stop = MagicMock(spec=interaction_types.StepStop)
        result_stop.__class__ = interaction_types.StepStop
        result_stop.index = 1

        mock_client.interactions.create.return_value = iter(
            [call_start, call_delta_event, call_stop, result_start, result_delta_event, result_stop]
        )

        responses = list(model.invoke_stream([Message(role="user", content="env")], Message(role="assistant")))
        tool_executions = [te for r in responses for te in (r.tool_executions or [])]
        assert len(tool_executions) == 1
        te = tool_executions[0]
        assert te.tool_name == "code_execution"
        assert te.tool_args == {"code": "env"}
        assert te.result == "PYTHONUNBUFFERED=1\nHOME=/root\n"

    def test_invoke_stream_agent_path_tags_tool_call_completed_event(self):
        """Regression: the streaming consumer in agent/_response.py only
        routes tool_executions into run_response.tools (and emits the UI
        tool-call event) when model_response.event ==
        ModelResponseEvent.tool_call_completed.value. Without the tag, the
        AgentOS UI shows no tool activity even though the data is there."""
        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionCallStep,
            FunctionResultStep,
            interaction_types,
        )
        from agno.models.response import ModelResponseEvent

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        call_step = MagicMock(spec=FunctionCallStep)
        call_step.__class__ = FunctionCallStep
        call_step.id = "call_evt_1"
        call_step.name = "list_files"
        call_step.arguments = {}
        call_step.signature = None
        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        arg_delta = MagicMock(spec=DeltaArgumentsDelta)
        arg_delta.__class__ = DeltaArgumentsDelta
        arg_delta.arguments = '{"path": "/"}'
        arg_delta_event = MagicMock(spec=interaction_types.StepDelta)
        arg_delta_event.__class__ = interaction_types.StepDelta
        arg_delta_event.delta = arg_delta
        arg_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        result_step = MagicMock(spec=FunctionResultStep)
        result_step.__class__ = FunctionResultStep
        result_step.call_id = "call_evt_1"
        result_step.result = "data"
        result_step.is_error = None
        result_step.name = "list_files"
        result_step.signature = None
        result_start = MagicMock(spec=interaction_types.StepStart)
        result_start.__class__ = interaction_types.StepStart
        result_start.step = result_step
        result_start.index = 1
        result_stop = MagicMock(spec=interaction_types.StepStop)
        result_stop.__class__ = interaction_types.StepStop
        result_stop.index = 1

        mock_client.interactions.create.return_value = iter(
            [call_start, arg_delta_event, call_stop, result_start, result_stop]
        )

        responses = list(model.invoke_stream([Message(role="user", content="ls")], Message(role="assistant")))
        tagged = [r for r in responses if r.event == ModelResponseEvent.tool_call_completed.value]
        assert len(tagged) >= 1
        assert any(r.tool_executions for r in tagged)

    def test_invoke_stream_agent_path_flushes_client_tool_as_tool_call(self):
        """Regression: streaming variant of the Codex review. A FunctionCallStep
        that never gets a matching FunctionResultStep before the stream ends
        is a client-declared tool the autonomous loop is waiting for us to
        dispatch. Must be emitted as a tool_call on InteractionCompletedEvent,
        not silently dropped."""
        from agno.models.google.gemini_interactions import (
            DeltaArgumentsDelta,
            FunctionCallStep,
            interaction_types,
        )

        model = GeminiInteractions(api_key="test-key", agent="antigravity-preview-05-2026")
        mock_client = MagicMock()
        model.client = mock_client

        call_step = MagicMock(spec=FunctionCallStep)
        call_step.__class__ = FunctionCallStep
        call_step.id = "call_client_stream"
        call_step.name = "send_email"
        call_step.arguments = {}
        call_step.signature = None

        call_start = MagicMock(spec=interaction_types.StepStart)
        call_start.__class__ = interaction_types.StepStart
        call_start.step = call_step
        call_start.index = 0

        arg_delta = MagicMock(spec=DeltaArgumentsDelta)
        arg_delta.__class__ = DeltaArgumentsDelta
        arg_delta.arguments = '{"to": "yash@phidata.com"}'

        arg_delta_event = MagicMock(spec=interaction_types.StepDelta)
        arg_delta_event.__class__ = interaction_types.StepDelta
        arg_delta_event.delta = arg_delta
        arg_delta_event.index = 0

        call_stop = MagicMock(spec=interaction_types.StepStop)
        call_stop.__class__ = interaction_types.StepStop
        call_stop.index = 0

        # InteractionCompletedEvent arrives WITHOUT a matching result step.
        completed = MagicMock(spec=interaction_types.InteractionCompletedEvent)
        completed.__class__ = interaction_types.InteractionCompletedEvent
        completed.interaction = MagicMock()
        completed.interaction.id = "interactions/client-stream"
        completed.interaction.usage = None

        mock_client.interactions.create.return_value = iter([call_start, arg_delta_event, call_stop, completed])

        messages = [Message(role="user", content="Email Yash")]
        assistant_message = Message(role="assistant")

        responses = list(model.invoke_stream(messages, assistant_message))
        all_tool_calls = [tc for r in responses for tc in r.tool_calls]
        assert len(all_tool_calls) == 1
        assert all_tool_calls[0]["id"] == "call_client_stream"
        assert all_tool_calls[0]["function"]["name"] == "send_email"
        assert all_tool_calls[0]["function"]["arguments"] == '{"to": "yash@phidata.com"}'
        # And no ToolExecution because the loop never got to execute it.
        all_tool_executions = [te for r in responses for te in (r.tool_executions or [])]
        assert all_tool_executions == []

    def test_invoke_stream_error_raises_model_provider_error(self):
        from agno.exceptions import ModelProviderError

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.side_effect = Exception("Stream error")

        messages = [Message(role="user", content="Hello")]
        assistant_message = Message(role="assistant")

        with pytest.raises(ModelProviderError, match="Stream error"):
            list(model.invoke_stream(messages, assistant_message))


class TestBackgroundStreamReconnect:
    """Background interactions (Deep Research) end the initial SSE early and
    continue server-side. invoke_stream must reconnect until terminal."""

    def _make_model(self):
        # agent path forces background=True (the reconnect trigger). Tiny poll
        # interval so the test does not actually sleep.
        return GeminiInteractions(
            api_key="test-key",
            agent="deep-research-preview-04-2026",
            agent_poll_interval=0.0,
        )

    def _created_event(self, iid="interactions/dr-1"):
        from agno.models.google.gemini_interactions import interaction_types

        ev = MagicMock(spec=interaction_types.InteractionCreatedEvent)
        ev.__class__ = interaction_types.InteractionCreatedEvent
        ev.interaction = MagicMock()
        ev.interaction.id = iid
        ev.event_id = "e1"
        return ev

    def _text_delta(self, text, event_id="e2"):
        from agno.models.google.gemini_interactions import DeltaText, interaction_types

        ev = MagicMock(spec=interaction_types.StepDelta)
        ev.__class__ = interaction_types.StepDelta
        d = MagicMock(spec=DeltaText)
        d.__class__ = DeltaText
        d.text = text
        ev.delta = d
        ev.event_id = event_id
        return ev

    def test_reconnects_until_completed(self):
        from agno.models.google.gemini_interactions import ModelOutputStep, TextContent

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        # Initial stream: only created (then ends early, as background does).
        mock_client.interactions.create.return_value = iter([self._created_event()])

        # First get(): still running. Reconnect get(stream=True): delivers text.
        running = MagicMock()
        running.status = "in_progress"

        text = MagicMock(spec=TextContent)
        text.text = "Final report."
        text.annotations = None
        text.__class__ = TextContent
        step = MagicMock(spec=ModelOutputStep)
        step.content = [text]
        step.__class__ = ModelOutputStep
        completed = MagicMock()
        completed.status = "completed"
        completed.id = "interactions/dr-1"
        completed.steps = [step]
        completed.usage = None

        resumed_stream = iter([self._text_delta("Final report.")])

        # get() is called: (1) status check -> running, (2) stream resume,
        # then loop checks completed flag (set by... we have no completed event
        # in resumed_stream, so add a second status check that is terminal).
        get_calls = {"n": 0}

        def get_side_effect(*args, **kwargs):
            get_calls["n"] += 1
            if kwargs.get("stream"):
                return resumed_stream
            # non-stream status checks: first running, then completed
            return running if get_calls["n"] <= 1 else completed

        mock_client.interactions.get.side_effect = get_side_effect

        messages = [Message(role="user", content="Research X")]
        responses = list(model.invoke_stream(messages, Message(role="assistant")))

        # The reconnected stream's text + the final completed snapshot parse
        # should both surface the report.
        assert any("Final report." in (r.content or "") for r in responses)
        # create() forced background; reconnect used get(stream=True, last_event_id=...)
        assert mock_client.interactions.create.call_args[1]["background"] is True
        stream_get = [c for c in mock_client.interactions.get.call_args_list if c.kwargs.get("stream")]
        assert stream_get, "expected a get(stream=True) reconnect call"
        assert stream_get[0].kwargs.get("last_event_id") == "e1"

    def test_reconnect_times_out(self):
        from agno.exceptions import ModelProviderError

        model = GeminiInteractions(
            api_key="test-key",
            agent="deep-research-preview-04-2026",
            agent_poll_interval=0.0,
            agent_max_wait=0.0,  # immediate timeout
        )
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.return_value = iter([self._created_event()])
        running = MagicMock()
        running.status = "in_progress"
        mock_client.interactions.get.return_value = running

        with pytest.raises(ModelProviderError, match="did not complete"):
            list(model.invoke_stream([Message(role="user", content="x")], Message(role="assistant")))

    def test_error_event_raises(self):
        from agno.exceptions import ModelProviderError
        from agno.models.google.gemini_interactions import interaction_types

        model = self._make_model()
        mock_client = MagicMock()
        model.client = mock_client

        err = MagicMock(spec=interaction_types.ErrorEvent)
        err.__class__ = interaction_types.ErrorEvent
        err.error = "model overloaded"
        err.event_id = "e9"
        mock_client.interactions.create.return_value = iter([self._created_event(), err])

        with pytest.raises(ModelProviderError, match="model overloaded"):
            list(model.invoke_stream([Message(role="user", content="x")], Message(role="assistant")))

    def test_non_background_path_does_not_reconnect(self):
        # The model path (no agent) must not enter the reconnect loop.
        model = GeminiInteractions(api_key="test-key")
        mock_client = MagicMock()
        model.client = mock_client
        mock_client.interactions.create.return_value = iter([self._text_delta("hi")])

        list(model.invoke_stream([Message(role="user", content="x")], Message(role="assistant")))
        # get() must never be called on the model (non-background) path.
        mock_client.interactions.get.assert_not_called()


class TestToDict:
    """Tests for model serialization."""

    def test_basic_serialization(self):
        model = GeminiInteractions(api_key="test-key")
        d = model.to_dict()
        assert d["id"] == "gemini-3-flash-preview"
        assert d["name"] == "GeminiInteractions"
        assert d["provider"] == "Google"

    def test_serialization_with_params(self):
        model = GeminiInteractions(
            api_key="test-key",
            temperature=0.7,
            search=True,
            store=False,
        )
        d = model.to_dict()
        assert d["temperature"] == 0.7
        assert d["search"] is True
        assert d["store"] is False

    def test_none_values_excluded(self):
        model = GeminiInteractions(api_key="test-key")
        d = model.to_dict()
        assert "temperature" not in d
        assert "thinking_level" not in d

    def test_service_tier_serialization(self):
        model = GeminiInteractions(api_key="test-key", service_tier="flex")
        d = model.to_dict()
        assert d["service_tier"] == "flex"


class TestMultimodalInput:
    """Tests for multimodal input support in _build_input."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_image_from_bytes(self):
        model = self._make_model()
        img_bytes = b"\x89PNG\r\n\x1a\n"
        messages = [Message(role="user", content="What is this?", images=[Image(content=img_bytes)])]
        steps = model._build_input(messages)
        assert len(steps) == 1
        content = steps[0]["content"]
        assert len(content) == 2  # text + image
        assert content[0]["type"] == "text"
        image_item = content[1]
        assert image_item["type"] == "image"
        assert image_item["mime_type"] == "image/jpeg"
        assert image_item["data"] == base64.b64encode(img_bytes).decode("utf-8")

    def test_image_from_url(self):
        model = self._make_model()
        messages = [
            Message(
                role="user",
                content="Describe this",
                images=[Image(url="https://example.com/img.png", mime_type="image/png")],
            )
        ]
        steps = model._build_input(messages)
        image_item = steps[0]["content"][1]
        assert image_item["type"] == "image"
        assert image_item["uri"] == "https://example.com/img.png"
        assert image_item["mime_type"] == "image/png"

    def test_audio_from_bytes(self):
        model = self._make_model()
        audio_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "
        messages = [
            Message(role="user", content="Transcribe", audio=[Audio(content=audio_bytes, mime_type="audio/wav")])
        ]
        steps = model._build_input(messages)
        audio_item = steps[0]["content"][1]
        assert audio_item["type"] == "audio"
        assert audio_item["mime_type"] == "audio/wav"
        assert audio_item["data"] == base64.b64encode(audio_bytes).decode("utf-8")

    def test_video_from_url(self):
        model = self._make_model()
        messages = [
            Message(
                role="user",
                content="What happens in this video?",
                videos=[Video(url="https://example.com/video.mp4")],
            )
        ]
        steps = model._build_input(messages)
        video_item = steps[0]["content"][1]
        assert video_item["type"] == "video"
        assert video_item["uri"] == "https://example.com/video.mp4"

    def test_document_from_bytes(self):
        model = self._make_model()
        pdf_bytes = b"%PDF-1.4 fake content"
        messages = [
            Message(
                role="user",
                content="Summarize this document",
                files=[File(content=pdf_bytes, mime_type="application/pdf")],
            )
        ]
        steps = model._build_input(messages)
        doc_item = steps[0]["content"][1]
        assert doc_item["type"] == "document"
        assert doc_item["mime_type"] == "application/pdf"

    def test_multiple_media_types_combined(self):
        model = self._make_model()
        messages = [
            Message(
                role="user",
                content="Compare these",
                images=[Image(content=b"img1"), Image(content=b"img2")],
                audio=[Audio(content=b"audio1", mime_type="audio/mp3")],
            )
        ]
        steps = model._build_input(messages)
        content = steps[0]["content"]
        # 1 text + 2 images + 1 audio
        assert len(content) == 4
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image"
        assert content[2]["type"] == "image"
        assert content[3]["type"] == "audio"

    def test_image_only_no_text(self):
        """Message with only images and no text content."""
        model = self._make_model()
        messages = [Message(role="user", content=None, images=[Image(content=b"imgdata")])]
        steps = model._build_input(messages)
        assert len(steps) == 1
        content = steps[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "image"


class TestMultimodalOutput:
    """Tests for multimodal output parsing."""

    def _make_model(self):
        return GeminiInteractions(api_key="test-key")

    def test_parse_image_output(self):
        from agno.models.google.gemini_interactions import ImageContent, ModelOutputStep

        if ImageContent is None:
            pytest.skip("ImageContent not available in SDK")

        model = self._make_model()

        img_data = base64.b64encode(b"fake_png_data").decode("utf-8")
        mock_img = MagicMock(spec=ImageContent)
        mock_img.__class__ = ImageContent
        mock_img.data = img_data
        mock_img.mime_type = "image/png"
        mock_img.uri = None

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.__class__ = ModelOutputStep
        mock_step.content = [mock_img]

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/img_out"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.images is not None
        assert len(response.images) == 1
        assert response.images[0].content == b"fake_png_data"
        assert response.images[0].mime_type == "image/png"

    def test_parse_audio_output(self):
        from agno.models.google.gemini_interactions import AudioContent, ModelOutputStep

        if AudioContent is None:
            pytest.skip("AudioContent not available in SDK")

        model = self._make_model()

        audio_data = base64.b64encode(b"fake_wav_data").decode("utf-8")
        mock_audio = MagicMock(spec=AudioContent)
        mock_audio.__class__ = AudioContent
        mock_audio.data = audio_data
        mock_audio.mime_type = "audio/wav"
        mock_audio.uri = None

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.__class__ = ModelOutputStep
        mock_step.content = [mock_audio]

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/audio_out"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.audio is not None
        assert response.audio.content == b"fake_wav_data"
        assert response.audio.mime_type == "audio/wav"

    def test_parse_mixed_text_and_image_output(self):
        from agno.models.google.gemini_interactions import ImageContent, ModelOutputStep, TextContent

        if ImageContent is None:
            pytest.skip("ImageContent not available in SDK")

        model = self._make_model()

        mock_text = MagicMock(spec=TextContent)
        mock_text.__class__ = TextContent
        mock_text.text = "Here is the generated image:"

        img_data = base64.b64encode(b"generated_image").decode("utf-8")
        mock_img = MagicMock(spec=ImageContent)
        mock_img.__class__ = ImageContent
        mock_img.data = img_data
        mock_img.mime_type = "image/png"
        mock_img.uri = None

        mock_step = MagicMock(spec=ModelOutputStep)
        mock_step.__class__ = ModelOutputStep
        mock_step.content = [mock_text, mock_img]

        mock_interaction = MagicMock()
        mock_interaction.id = "interactions/mixed"
        mock_interaction.steps = [mock_step]
        mock_interaction.usage = None

        response = model._parse_provider_response(mock_interaction)
        assert response.content == "Here is the generated image:"
        assert response.images is not None
        assert len(response.images) == 1


class TestServiceTier:
    """Tests for service_tier (flex/priority inference)."""

    def test_service_tier_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", service_tier="flex")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["service_tier"] == "flex"

    def test_priority_tier_in_request_kwargs(self):
        model = GeminiInteractions(api_key="test-key", service_tier="priority")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert kwargs["service_tier"] == "priority"

    def test_no_service_tier_by_default(self):
        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "service_tier" not in kwargs


class TestStructuredOutput:
    """Tests for structured output / response_format."""

    def test_pydantic_model_response_format(self):
        from pydantic import BaseModel as PydanticModel

        class MovieReview(PydanticModel):
            title: str
            rating: int
            summary: str

        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Review The Matrix")]
        kwargs = model._get_request_kwargs(messages, response_format=MovieReview)
        assert kwargs["response_format"]["type"] == "text"
        assert kwargs["response_format"]["mime_type"] == "application/json"
        assert "schema" in kwargs["response_format"]
        schema = kwargs["response_format"]["schema"]
        assert "title" in schema["properties"]
        assert "rating" in schema["properties"]
        assert "summary" in schema["properties"]

    def test_dict_response_format_passthrough(self):
        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        custom_format = {"type": "text", "json_schema": {"type": "object"}}
        kwargs = model._get_request_kwargs(messages, response_format=custom_format)
        assert kwargs["response_format"] == custom_format

    def test_no_response_format_by_default(self):
        model = GeminiInteractions(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        kwargs = model._get_request_kwargs(messages)
        assert "response_format" not in kwargs
