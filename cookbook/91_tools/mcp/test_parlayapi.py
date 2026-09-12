"""Offline checks for the cookbook's actual MCP connection and tool boundary."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "parlayapi_example", Path(__file__).with_name("parlayapi.py")
)
assert spec and spec.loader
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def test_default_ignores_keys_and_origin(monkeypatch):
    monkeypatch.setenv("PARLAYAPI_KEY", "private-sentinel")
    monkeypatch.setenv("PARLAY_API_KEY", "alias-sentinel")
    monkeypatch.setenv("PARLAYAPI_BASE_URL", "https://example.invalid")
    tools = example.make_tools()
    assert tools.server_params.env == {
        "PARLAYAPI_BASE_URL": "https://parlay-api.com",
        "PARLAYAPI_KEY": "",
        "PARLAY_API_KEY": "",
    }
    assert tools.include_tools == example.DISCOVERY_TOOLS


def test_private_requires_explicit_key(monkeypatch):
    monkeypatch.delenv("PARLAYAPI_KEY", raising=False)
    monkeypatch.delenv("PARLAY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="requires your own"):
        example.make_tools(private=True)
    monkeypatch.setenv("PARLAY_API_KEY", "test-only-sentinel")
    tools = example.make_tools(private=True)
    assert tools.server_params.env["PARLAYAPI_KEY"] == "test-only-sentinel"
    assert set(tools.include_tools) == set(
        example.DISCOVERY_TOOLS + example.PRIVATE_TOOLS
    )


def test_server_version_change_requires_review(monkeypatch):
    monkeypatch.setattr(example, "version", lambda name: "999.0.0")
    with pytest.raises(ValueError, match="reviewed tool allowlist"):
        example.make_tools()


@pytest.mark.parametrize("private", [False, True])
def test_actual_stdio_discovery_without_network_or_model(
    tmp_path, monkeypatch, private
):
    # The actual published server runs in a child with TCP connection attempts blocked.
    (tmp_path / "sitecustomize.py").write_text(
        "import socket\n"
        "def blocked(*args, **kwargs):\n"
        "    raise RuntimeError('Network forbidden in MCP discovery test')\n"
        "socket.socket.connect = blocked\n"
        "socket.socket.connect_ex = blocked\n"
    )
    monkeypatch.setenv("PARLAYAPI_KEY", "test-only-sentinel")
    tools = example.make_tools(private=private)
    tools.server_params.env["PYTHONPATH"] = str(tmp_path)

    async def check():
        async with tools:
            names = set(tools.functions)
            assert names == set(
                example.DISCOVERY_TOOLS + (example.PRIVATE_TOOLS if private else [])
            )
            assert not names.intersection(
                {
                    "parlayapi_signup",
                    "parlayapi_magic_link",
                    "parlayapi_checkout_link",
                    "parlayapi_set_bettable_books",
                }
            )
            for function in tools.functions.values():
                assert "test-only-sentinel" not in str(function.to_dict())

    asyncio.run(check())


def test_optional_agent_configuration_without_model_call(monkeypatch):
    from agno.agent import Agent

    captured = []

    async def inspect_only(agent, message):
        captured.append(message)
        assert agent.model.id == "gpt-5.6-luna"
        assert agent.model.max_retries == 0
        assert agent.tool_call_limit == 2
        assert agent.telemetry is False
        assert set(agent.tools[0].functions) == set(example.DISCOVERY_TOOLS)

    monkeypatch.setattr(Agent, "aprint_response", inspect_only)
    asyncio.run(example.run_example("Describe public metadata only."))
    assert captured == ["Describe public metadata only."]
