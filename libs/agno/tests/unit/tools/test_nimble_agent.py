import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agno.tools.nimble_agent import NimbleAgentTools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_run(status="queued", run_id="task_run_abc", agent_id="wsa_123", error=None):
    run = Mock()
    run.id = run_id
    run.web_search_agent_id = agent_id
    run.status = status
    run.is_active = status in ("queued", "running")
    run.effort = "low"
    run.error = error
    return run


def make_result(result_dict):
    result = Mock()
    result.to_dict.return_value = result_dict
    return result


def completed_result_dict(confidence="high", with_citation=True, content="Python 3.13 is the current stable release."):
    citations = [{"url": "https://www.python.org/downloads/", "title": "Downloads"}] if with_citation else []
    return {
        "run": {
            "id": "task_run_abc",
            "web_search_agent_id": "wsa_123",
            "status": "completed",
            "effort": "low",
            "interaction_id": "int_1",
        },
        "output": {
            "type": "text",
            "content": content,
            "trust": {
                "confidence": confidence,
                "reasoning": "Based on the official python.org downloads page.",
                "sources": [
                    {
                        "url": "https://www.python.org/downloads/",
                        "title": "Downloads",
                        "type": "primary",
                        "source_category": "official",
                        "extract_template_name": None,
                    }
                ],
                "claims": [
                    {
                        "callout": 1,
                        "confidence": confidence,
                        "reasoning": "stated release",
                        "excerpts": ["Python 3.13"],
                        "citations": citations,
                    }
                ],
            },
        },
    }


def rate_limit_error():
    req = httpx.Request("POST", "https://sdk.nimbleway.com/v2/agents/wsa_123/runs")
    resp = httpx.Response(429, headers={"retry-after": "5"}, request=req)
    from nimble_python import RateLimitError

    return RateLimitError("rate limited", response=resp, body=None)


def status_error(cls_name, code):
    from nimble_python import AuthenticationError, ConflictError, NotFoundError, PermissionDeniedError

    cls = {
        "auth": AuthenticationError,
        "forbidden": PermissionDeniedError,
        "not_found": NotFoundError,
        "conflict": ConflictError,
    }[cls_name]
    req = httpx.Request("GET", "https://sdk.nimbleway.com/v2/agents/wsa_123/runs/task_run_abc")
    resp = httpx.Response(code, request=req)
    return cls("boom", response=resp, body=None)


@pytest.fixture
def mock_nimble():
    with patch("agno.tools.nimble_agent.Nimble") as mock_client:
        yield mock_client


@pytest.fixture
def tools(mock_nimble):
    return NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_with_api_key(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890")
    assert t.api_key == "test-key-1234567890"
    assert t.poll_interval_seconds == 10.0


def test_poll_interval_is_configurable_for_test_only_override(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890", poll_interval_seconds=0.1)
    assert t.poll_interval_seconds == 0.1


def test_init_with_env_vars(mock_nimble):
    with patch.dict("os.environ", {"NIMBLE_API_KEY": "env-key-123456", "NIMBLE_AGENT_ID": "wsa_env"}):
        t = NimbleAgentTools()
        assert t.api_key == "env-key-123456"
        assert t.agent_id == "wsa_env"


def test_init_missing_key_logs_and_no_client(mock_nimble):
    with patch.dict("os.environ", {}, clear=True):
        t = NimbleAgentTools()
        assert t._sync_client is None


def test_init_registers_sync_and_async_tools(tools):
    sync_names = list(tools.functions.keys())
    async_names = list(tools.async_functions.keys())
    for name in (
        "start_agent_run",
        "get_agent_run_status",
        "get_agent_run_result",
        "list_agents",
        "list_agent_templates",
    ):
        assert name in sync_names
        assert name in async_names


def test_start_tool_schema_exposes_identity_and_run_controls(tools):
    function = tools.functions["start_agent_run"]
    function.process_entrypoint()
    properties = function.parameters["properties"]
    assert set(
        (
            "agent_id",
            "agent_name",
            "use_case",
            "skill",
            "input_data",
            "output_schema",
            "sources",
            "enable_events",
        )
    ).issubset(properties)
    assert properties["use_case"]["enum"] == ["research", "enrichment", "dataset_building"]
    assert {"array", "object"}.issubset({item["type"] for item in properties["input_data"]["anyOf"]})


def test_discovery_can_be_disabled(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890", enable_discovery=False)
    assert "list_agents" not in t.functions
    assert "list_agent_templates" not in t.functions
    assert "start_agent_run" in t.functions


def test_run_lifecycle_can_be_disabled(mock_nimble):
    # Discovery-only mode: no billable run tool is exposed to the model at all.
    t = NimbleAgentTools(api_key="test-key-1234567890", enable_run_lifecycle=False)
    for name in ("start_agent_run", "get_agent_run_status", "get_agent_run_result"):
        assert name not in t.functions
        assert name not in t.async_functions
    assert "list_agents" in t.functions


@pytest.mark.parametrize("effort", ["low", "medium", "high", "x-high", "max"])
def test_supported_effort_override_is_preserved(mock_nimble, effort):
    t = NimbleAgentTools(api_key="test-key-1234567890", effort=effort)
    assert t.effort == effort


def test_effort_defaults_to_server_selected_default(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890")
    assert t.effort is None


@pytest.mark.parametrize("effort", ["turbo"])
def test_unknown_effort_is_rejected(mock_nimble, effort):
    with pytest.raises(ValueError, match="omit it"):
        NimbleAgentTools(api_key="test-key-1234567890", effort=effort)


# ---------------------------------------------------------------------------
# X-Client-Source attribution (real client, no network)
# ---------------------------------------------------------------------------


def test_x_client_source_header_is_agno():
    # Uses the real nimble_python client (construction makes no network call).
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    assert t._sync_client is not None
    assert t._sync_client.default_headers.get("X-Client-Source") == "agno"


def test_async_client_also_sends_agno_source():
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    async_client = t._get_async_client()
    assert async_client.default_headers.get("X-Client-Source") == "agno"


# ---------------------------------------------------------------------------
# Billing safety: a run creation is billable and not idempotent, so it must be
# attempted exactly once. These drive the real client through a mock transport
# and count HTTP attempts, rather than asserting on a mocked SDK method.
# ---------------------------------------------------------------------------


def _counting_client(status_code, attempts):
    from nimble_python import Nimble

    def handler(request):
        attempts.append(request)
        return httpx.Response(status_code, json={"detail": "boom"})

    return Nimble(
        api_key="test-key-1234567890",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("status_code", [408, 409, 429, 500, 502, 503])
def test_start_agent_run_makes_exactly_one_http_attempt(status_code):
    """A billable create is never retried, whatever the server says."""
    attempts = []
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    t._sync_client = _counting_client(status_code, attempts)
    json.loads(t.start_agent_run("q"))
    assert len(attempts) == 1


@pytest.mark.parametrize("status_code", [429, 500])
def test_generic_route_create_also_makes_exactly_one_http_attempt(status_code):
    """The no-agent_id route is equally billable and equally un-retried."""
    attempts = []
    t = NimbleAgentTools(api_key="test-key-1234567890")
    t._sync_client = _counting_client(status_code, attempts)
    json.loads(t.start_agent_run("q"))
    assert len(attempts) == 1


def _transport_failure_client(exc, attempts):
    from nimble_python import Nimble

    def handler(request):
        attempts.append(request)
        raise exc

    return Nimble(
        api_key="test-key-1234567890",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("timed out")],
)
def test_unconfirmed_create_says_do_not_resubmit_and_how_to_reconcile(exc):
    """A create that never got an answer may already have been billed.

    "Try again" here would buy a second run, so the guidance has to forbid
    resubmission and tell the model how to find out what happened.
    """
    attempts = []
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    t._sync_client = _transport_failure_client(exc, attempts)
    out = json.loads(t.start_agent_run("q"))

    assert len(attempts) == 1, "an unconfirmed create must never be retried"
    assert out["code"] == "connection_error_unconfirmed"
    message = out["error"].lower()
    assert "do not resubmit" in message
    assert "may still have been created and billed" in message
    # Reconciliation must be actionable, not just a warning.
    assert "list_agents" in message and "get_agent_run_status" in message


@pytest.mark.parametrize("status_code", [500, 503])
def test_unconfirmed_create_covers_server_errors_too(status_code):
    """A 5xx leaves the same question open as a timeout: did the run start?"""
    attempts = []
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    t._sync_client = _counting_client(status_code, attempts)
    out = json.loads(t.start_agent_run("q"))
    assert len(attempts) == 1
    assert out["code"] == "connection_error_unconfirmed"


@pytest.mark.parametrize("status_code", [401, 404, 422])
def test_rejected_create_is_not_reported_as_unconfirmed(status_code):
    """A 4xx answers the question -- nothing ran -- so it keeps its own code."""
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    t._sync_client = _counting_client(status_code, [])
    out = json.loads(t.start_agent_run("q"))
    assert out["code"] != "connection_error_unconfirmed"


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("timed out")],
)
def test_safe_reads_still_say_try_again(exc):
    """Reads are idempotent, so the old retry guidance is still correct there."""
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123", max_read_retries=0)
    t._sync_client = _transport_failure_client(exc, [])
    out = json.loads(t.get_agent_run_status("task_run_abc"))
    assert out["code"] == "connection_error"
    assert "do not resubmit" not in out["error"].lower()


async def test_unconfirmed_create_guidance_is_the_same_on_the_async_path():
    from nimble_python import AsyncNimble

    def handler(request):
        raise httpx.ReadTimeout("timed out")

    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    t._async_client = AsyncNimble(
        api_key="test-key-1234567890",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    out = json.loads(await t.astart_agent_run("q"))
    assert out["code"] == "connection_error_unconfirmed"
    assert "do not resubmit" in out["error"].lower()


def test_safe_reads_keep_a_bounded_retry_budget():
    """Reads are idempotent, so they may retry - but only up to max_read_retries."""
    attempts = []
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123", max_read_retries=2)
    t._sync_client = _counting_client(500, attempts)
    json.loads(t.get_agent_run_status("task_run_abc"))
    assert len(attempts) == 3  # the initial attempt plus two retries


# ---------------------------------------------------------------------------
# SDK contract (real client, no network)
#
# The lifecycle tests mock the client, so a Mock accepts any method name and any
# keyword. These assert against the real SDK so a renamed method or a dropped
# parameter fails here instead of only in production.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr_path,required_params",
    [
        # Generic route: no agent_id needed; Nimble provisions one and returns its id.
        (
            "agents.run",
            {
                "input",
                "effort",
                "enable_events",
                "agent_name",
                "use_case",
                "skill",
                "input_data",
                "output_schema",
                "sources",
            },
        ),
        # Persistent route: run against an existing agent.
        (
            "agents.runs.create",
            {
                "agent_id",
                "input",
                "effort",
                "enable_events",
                "agent_name",
                "use_case",
                "skill",
                "input_data",
                "output_schema",
                "sources",
            },
        ),
        ("agents.runs.get", {"run_id", "agent_id"}),
        ("agents.runs.result", {"run_id", "agent_id"}),
        ("agents.list", {"limit"}),
        ("agents.templates.list", {"limit"}),
    ],
)
def test_sdk_exposes_the_methods_and_parameters_this_toolkit_calls(attr_path, required_params):
    import inspect
    from functools import reduce

    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    for client in (t._sync_client, t._get_async_client()):
        method = reduce(getattr, attr_path.split("."), client)
        params = set(inspect.signature(method).parameters)
        assert required_params.issubset(params), (
            f"{type(client).__name__}.{attr_path} is missing {required_params - params}"
        )


def test_accepted_effort_tiers_match_the_sdk_exactly():
    """The toolkit validates effort against a hardcoded set; keep it tied to the SDK.

    If nimble-python adds, renames, or removes a tier, this fails here rather than
    silently rejecting a valid tier or forwarding one the API no longer accepts.
    The SDK annotates with PEP 563 strings, so resolve them before reading Literals.
    """
    import typing
    from functools import reduce

    from agno.tools.nimble_agent import SUPPORTED_EFFORTS

    def literal_values(annotation):
        if typing.get_origin(annotation) is typing.Literal:
            return set(typing.get_args(annotation))
        return set().union(*(literal_values(arg) for arg in typing.get_args(annotation)), set())

    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
    for client in (t._sync_client, t._get_async_client()):
        for attr_path in ("agents.run", "agents.runs.create"):
            method = reduce(getattr, attr_path.split("."), client)
            func = getattr(method, "__func__", method)
            hints = typing.get_type_hints(func)
            assert literal_values(hints["effort"]) == SUPPORTED_EFFORTS, (
                f"{type(client).__name__}.{attr_path} effort tiers drifted from the toolkit's allow-list"
            )


# ---------------------------------------------------------------------------
# start_agent_run
# ---------------------------------------------------------------------------


def test_start_agent_run_happy_path(tools):
    tools._sync_client.agents.runs.create.return_value = make_run(status="queued")
    out = json.loads(tools.start_agent_run("What is the latest Python release?"))
    assert out["run_id"] == "task_run_abc"
    assert out["agent_id"] == "wsa_123"
    assert out["status"] == "queued"
    assert out["poll_after_seconds"] == 10.0
    tools._sync_client.agents.runs.create.assert_called_once_with(
        "wsa_123",
        input="What is the latest Python release?",
        enable_events=False,
    )


def test_start_agent_run_never_retries_the_post(tools):
    tools._sync_client.agents.runs.create.return_value = make_run()
    tools.start_agent_run("q")
    # The write goes through the base client (max_retries=0), never the retrying reader.
    tools._sync_client.with_options.assert_not_called()


def test_start_agent_run_without_agent_auto_provisions(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890")
    t._sync_client.agents.run.return_value = make_run()
    out = json.loads(t.start_agent_run("q"))
    # The generic route returns the agent id Nimble provisioned, paired with the run id.
    assert out["agent_id"] == "wsa_123"
    assert out["run_id"] == "task_run_abc"
    t._sync_client.agents.run.assert_called_once_with(
        input="q",
        enable_events=False,
    )
    # The per-agent route must not be used when no agent is configured.
    t._sync_client.agents.runs.create.assert_not_called()


def test_start_agent_run_create_or_reuse_by_name(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890")
    t._sync_client.agents.run.return_value = make_run()
    out = json.loads(
        t.start_agent_run(
            "q",
            agent_name="agno-researcher",
            use_case="research",
            skill="Use primary sources.",
        )
    )
    assert out["agent_id"] == "wsa_123"
    assert t._sync_client.agents.run.call_args.kwargs["agent_name"] == "agno-researcher"
    assert t._sync_client.agents.run.call_args.kwargs["use_case"] == "research"
    assert t._sync_client.agents.run.call_args.kwargs["skill"] == "Use primary sources."
    assert "extra_body" not in t._sync_client.agents.run.call_args.kwargs


def test_start_agent_run_generic_route_forwards_structured_controls(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890")
    t._sync_client.agents.run.return_value = make_run()
    input_data = [{"company": "Nimble"}]
    output_schema = {"type": "object"}
    sources = {"prioritize": "Official sources"}
    t.start_agent_run(
        "q",
        use_case="dataset_building",
        input_data=input_data,
        output_schema=output_schema,
        sources=sources,
        enable_events=True,
    )
    t._sync_client.agents.run.assert_called_once_with(
        input="q",
        enable_events=True,
        use_case="dataset_building",
        input_data=input_data,
        output_schema=output_schema,
        sources=sources,
    )


def test_start_agent_run_forwards_all_existing_agent_overrides(tools):
    tools._sync_client.agents.runs.create.return_value = make_run()
    input_data = [{"company": "Nimble"}]
    output_schema = {"type": "object"}
    sources = {"prioritize": "Official sources"}
    tools.start_agent_run(
        "q",
        use_case="enrichment",
        skill="Fill missing fields.",
        input_data=input_data,
        output_schema=output_schema,
        sources=sources,
        enable_events=True,
    )
    tools._sync_client.agents.runs.create.assert_called_once_with(
        "wsa_123",
        input="q",
        enable_events=True,
        use_case="enrichment",
        skill="Fill missing fields.",
        input_data=input_data,
        output_schema=output_schema,
        sources=sources,
    )


def test_start_agent_run_forwards_explicit_effort_override(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890", effort="x-high")
    t._sync_client.agents.run.return_value = make_run()
    t.start_agent_run("q")
    t._sync_client.agents.run.assert_called_once_with(
        input="q",
        effort="x-high",
        enable_events=False,
    )


def test_start_agent_run_promotes_gated_max_without_creating(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890", effort="max")
    out = json.loads(t.start_agent_run("q"))
    assert out["code"] == "effort_tier_coming_soon"
    assert "custom budget" in out["error"]
    assert "https://www.nimbleway.com/contact" in out["error"]
    t._sync_client.agents.run.assert_not_called()
    t._sync_client.agents.runs.create.assert_not_called()


def test_start_agent_run_rejects_two_identity_modes(tools):
    out = json.loads(tools.start_agent_run("q", agent_name="also-set"))
    assert out["code"] == "invalid_identity"
    tools._sync_client.agents.runs.create.assert_not_called()
    tools._sync_client.post.assert_not_called()


def test_start_agent_run_requires_query(tools):
    out = json.loads(tools.start_agent_run("   "))
    assert "error" in out


def test_start_agent_run_missing_key(mock_nimble):
    with patch.dict("os.environ", {}, clear=True):
        t = NimbleAgentTools(agent_id="wsa_123")
        out = json.loads(t.start_agent_run("q"))
        assert "error" in out


def test_start_agent_run_rate_limited(tools):
    tools._sync_client.agents.runs.create.side_effect = rate_limit_error()
    out = json.loads(tools.start_agent_run("q"))
    assert out["code"] == "rate_limited"
    assert out["retry_after"] == "5"


# ---------------------------------------------------------------------------
# get_agent_run_status
# ---------------------------------------------------------------------------


def test_get_status_running(tools):
    tools._sync_client.with_options.return_value.agents.runs.get.return_value = make_run(status="running")
    out = json.loads(tools.get_agent_run_status("task_run_abc"))
    assert out["status"] == "running"
    assert out["is_active"] is True
    tools._sync_client.with_options.assert_called_with(max_retries=2)


def test_get_status_failed_includes_error(tools):
    err = Mock()
    err.message = "the run failed"
    tools._sync_client.with_options.return_value.agents.runs.get.return_value = make_run(status="failed", error=err)
    out = json.loads(tools.get_agent_run_status("task_run_abc"))
    assert out["status"] == "failed"
    assert out["error"] == "the run failed"


# ---------------------------------------------------------------------------
# get_agent_run_result
# ---------------------------------------------------------------------------


def test_result_not_ready_when_active(tools):
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="running")
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert out["state"] == "not_ready"
    assert out["status"] == "running"
    assert out["poll_after_seconds"] == 10.0
    # Must not fetch the result while the run is active.
    reader.agents.runs.result.assert_not_called()


def test_result_completed_grounded(tools):
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="completed")
    reader.agents.runs.result.return_value = make_result(completed_result_dict())
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert out["state"] == "completed"
    assert out["output"]["type"] == "text"
    assert out["output"]["usability"] == "grounded"
    assert out["output"]["trust"]["source_count"] == 1
    assert out["output"]["trust"]["claims"][0]["citation_urls"] == ["https://www.python.org/downloads/"]


def test_result_completed_degraded_when_uncited(tools):
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="completed")
    reader.agents.runs.result.return_value = make_result(completed_result_dict(confidence="low", with_citation=False))
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert out["output"]["usability"] == "degraded"


def test_result_failed(tools):
    err = Mock()
    err.message = "boom"
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="failed", error=err)
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert out["state"] == "failed"
    assert out["error"] == "boom"
    reader.agents.runs.result.assert_not_called()


def test_result_cancelled(tools):
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="cancelled")
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert out["state"] == "cancelled"


def test_result_conflict_maps_to_not_ready(tools):
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="completed")
    reader.agents.runs.result.side_effect = status_error("conflict", 409)
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert out["state"] == "not_ready"


def test_result_content_is_truncated(mock_nimble):
    t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123", max_content_chars=20)
    reader = t._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="completed")
    reader.agents.runs.result.return_value = make_result(completed_result_dict(content="A" * 500))
    out = json.loads(t.get_agent_run_result("task_run_abc"))
    assert len(out["output"]["content"]) == 20


def test_result_redacts_credential_shapes(tools):
    reader = tools._sync_client.with_options.return_value
    reader.agents.runs.get.return_value = make_run(status="completed")
    # Synthetic credential shapes assembled from fragments, so the test source has
    # no contiguous secret-shaped literal; the tool must still redact them at runtime.
    leaked = "token " + "nvapi-" + "abcdefgh1234567890 and " + "a" * 40
    reader.agents.runs.result.return_value = make_result(completed_result_dict(content=leaked))
    out = json.loads(tools.get_agent_run_result("task_run_abc"))
    assert "nvapi-" not in out["output"]["content"]
    assert "<redacted>" in out["output"]["content"]


# ---------------------------------------------------------------------------
# Exception mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "err,code",
    [
        (status_error("auth", 401), "unauthorized"),
        (status_error("forbidden", 403), "forbidden"),
        (status_error("not_found", 404), "not_found"),
    ],
)
def test_status_error_mapping(tools, err, code):
    tools._sync_client.with_options.return_value.agents.runs.get.side_effect = err
    out = json.loads(tools.get_agent_run_status("task_run_abc"))
    assert out["code"] == code


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_list_agents(tools):
    resp = Mock()
    resp.to_dict.return_value = {
        "items": [
            {
                "id": "wsa_1",
                "agent_name": "researcher",
                "display_name": "Researcher",
                "use_case": "research",
                "skill": None,
                "is_active": True,
            }
        ],
        "total": 1,
    }
    tools._sync_client.with_options.return_value.agents.list.return_value = resp
    out = json.loads(tools.list_agents())
    assert out["total"] == 1
    assert out["agents"][0]["id"] == "wsa_1"
    assert out["agents"][0]["agent_name"] == "researcher"


@pytest.mark.parametrize("requested,expected", [(5, 5), (100000, 100), (0, 1), (-3, 1), ("nope", 20)])
def test_discovery_limit_is_clamped(tools, requested, expected):
    reader = tools._sync_client.with_options.return_value
    resp = Mock()
    resp.to_dict.return_value = {"items": [], "total": 0}
    reader.agents.list.return_value = resp
    tools.list_agents(limit=requested)
    reader.agents.list.assert_called_once_with(limit=expected)


def test_discovery_redacts_credentials_in_agent_and_template_skill(tools):
    """skill is free-form account-authored text, the likeliest place a key is sitting."""
    leaked = "use " + "nvapi-" + "abcdefgh1234567890 then " + "b" * 40
    agents_resp, templates_resp = Mock(), Mock()
    agents_resp.to_dict.return_value = {
        "items": [{"id": "wsa_1", "agent_name": "researcher", "skill": leaked}],
        "total": 1,
    }
    templates_resp.to_dict.return_value = {
        "items": [{"template_name": "company_research", "skill": leaked, "description": leaked}],
        "total": 1,
    }
    reader = tools._sync_client.with_options.return_value
    reader.agents.list.return_value = agents_resp
    reader.agents.templates.list.return_value = templates_resp

    agent_skill = json.loads(tools.list_agents())["agents"][0]["skill"]
    template = json.loads(tools.list_agent_templates())["templates"][0]
    for value in (agent_skill, template["skill"], template["description"]):
        assert "nvapi-" not in value
        assert "b" * 40 not in value
        assert "<redacted>" in value


@pytest.mark.parametrize(
    "field,limit",
    [("agent_name", 200), ("display_name", 200), ("use_case", 100), ("skill", 500), ("id", 200)],
)
def test_discovery_bounds_each_agent_field(tools, field, limit):
    resp = Mock()
    resp.to_dict.return_value = {"items": [{field: "z" * 5000}], "total": 1}
    tools._sync_client.with_options.return_value.agents.list.return_value = resp
    assert len(json.loads(tools.list_agents())["agents"][0][field]) == limit


@pytest.mark.parametrize(
    "field,limit",
    [("template_name", 200), ("display_name", 200), ("use_case", 100), ("skill", 500), ("description", 300)],
)
def test_discovery_bounds_each_template_field(tools, field, limit):
    resp = Mock()
    resp.to_dict.return_value = {"items": [{field: "z" * 5000}], "total": 1}
    tools._sync_client.with_options.return_value.agents.templates.list.return_value = resp
    assert len(json.loads(tools.list_agent_templates())["templates"][0][field]) == limit


def test_discovery_keeps_missing_fields_null_rather_than_empty_strings(tools):
    resp = Mock()
    resp.to_dict.return_value = {"items": [{"id": "wsa_1"}], "total": 1}
    tools._sync_client.with_options.return_value.agents.list.return_value = resp
    agent = json.loads(tools.list_agents())["agents"][0]
    assert agent["skill"] is None
    assert agent["display_name"] is None


def test_list_agent_templates(tools):
    resp = Mock()
    resp.to_dict.return_value = {
        "items": [
            {
                "template_name": "company_research",
                "display_name": "Company Research",
                "use_case": "research",
                "skill": None,
                "description": "x",
            }
        ],
        "total": 1,
    }
    tools._sync_client.with_options.return_value.agents.templates.list.return_value = resp
    out = json.loads(tools.list_agent_templates())
    assert out["templates"][0]["template_name"] == "company_research"


# ---------------------------------------------------------------------------
# Async variants
# ---------------------------------------------------------------------------


async def test_astart_agent_run_happy_path(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        mock_async.return_value.agents.runs.create = AsyncMock(return_value=make_run(status="queued"))
        out = json.loads(await t.astart_agent_run("q"))
        assert out["run_id"] == "task_run_abc"
        assert out["status"] == "queued"


async def test_astart_agent_run_without_agent_auto_provisions(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890")
        mock_async.return_value.agents.run = AsyncMock(return_value=make_run())
        out = json.loads(await t.astart_agent_run("q", agent_name="agno-researcher"))
        assert out["agent_id"] == "wsa_123"
        assert out["run_id"] == "task_run_abc"
        call = mock_async.return_value.agents.run.call_args
        assert call.kwargs["input"] == "q"
        assert call.kwargs["agent_name"] == "agno-researcher"
        assert "extra_body" not in call.kwargs


async def test_astart_agent_run_promotes_gated_max_without_creating(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", effort="max")
        out = json.loads(await t.astart_agent_run("q"))
        assert out["code"] == "effort_tier_coming_soon"
        assert "https://www.nimbleway.com/contact" in out["error"]
        mock_async.return_value.agents.run.assert_not_called()
        mock_async.return_value.agents.runs.create.assert_not_called()


async def test_aget_result_not_ready(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        reader = mock_async.return_value.with_options.return_value
        reader.agents.runs.get = AsyncMock(return_value=make_run(status="running"))
        reader.agents.runs.result = AsyncMock()
        out = json.loads(await t.aget_agent_run_result("task_run_abc"))
        assert out["state"] == "not_ready"
        reader.agents.runs.result.assert_not_called()


async def test_astart_agent_run_never_retries_the_post(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        mock_async.return_value.agents.runs.create = AsyncMock(return_value=make_run())
        await t.astart_agent_run("q")
        # The async write must go through the base client (max_retries=0), never the reader.
        mock_async.return_value.with_options.assert_not_called()


async def test_astart_agent_run_rate_limited(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        mock_async.return_value.agents.runs.create = AsyncMock(side_effect=rate_limit_error())
        out = json.loads(await t.astart_agent_run("q"))
        assert out["code"] == "rate_limited"


async def test_aget_agent_run_status_running(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        reader = mock_async.return_value.with_options.return_value
        reader.agents.runs.get = AsyncMock(return_value=make_run(status="running"))
        out = json.loads(await t.aget_agent_run_status("task_run_abc"))
        assert out["status"] == "running"
        mock_async.return_value.with_options.assert_called_with(max_retries=2)


async def test_aget_result_completed_grounded(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        reader = mock_async.return_value.with_options.return_value
        reader.agents.runs.get = AsyncMock(return_value=make_run(status="completed"))
        reader.agents.runs.result = AsyncMock(return_value=make_result(completed_result_dict()))
        out = json.loads(await t.aget_agent_run_result("task_run_abc"))
        assert out["state"] == "completed"
        assert out["output"]["usability"] == "grounded"


async def test_aget_result_failed(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        err = Mock()
        err.message = "boom"
        reader = mock_async.return_value.with_options.return_value
        reader.agents.runs.get = AsyncMock(return_value=make_run(status="failed", error=err))
        reader.agents.runs.result = AsyncMock()
        out = json.loads(await t.aget_agent_run_result("task_run_abc"))
        assert out["state"] == "failed"
        assert out["error"] == "boom"
        reader.agents.runs.result.assert_not_called()


async def test_alist_agents_async(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        resp = Mock()
        resp.to_dict.return_value = {"items": [{"id": "wsa_1", "agent_name": "researcher"}], "total": 1}
        mock_async.return_value.with_options.return_value.agents.list = AsyncMock(return_value=resp)
        out = json.loads(await t.alist_agents())
        assert out["agents"][0]["id"] == "wsa_1"
        assert out["total"] == 1


async def test_astatus_error_mapping_async(mock_nimble):
    with patch("agno.tools.nimble_agent.AsyncNimble") as mock_async:
        t = NimbleAgentTools(api_key="test-key-1234567890", agent_id="wsa_123")
        reader = mock_async.return_value.with_options.return_value
        reader.agents.runs.get = AsyncMock(side_effect=status_error("not_found", 404))
        out = json.loads(await t.aget_agent_run_status("task_run_abc"))
        assert out["code"] == "not_found"
