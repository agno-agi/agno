"""Claude configuration contracts without model calls or an installed SDK."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from agno.agents.claude import ClaudeAgent
from agno.agents.claude import agent as claude_module
from agno.db.sqlite import SqliteDb


@dataclass
class Options:
    model: Optional[str] = None
    system_prompt: Any = None
    cwd: Any = None
    tools: Any = None
    allowed_tools: list = field(default_factory=list)
    disallowed_tools: list = field(default_factory=list)
    permission_mode: Optional[str] = None
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    mcp_servers: dict = field(default_factory=dict)
    setting_sources: Any = None
    strict_mcp_config: bool = False
    skills: Any = None
    plugins: list = field(default_factory=list)
    hooks: dict = field(default_factory=dict)
    extra_args: dict = field(default_factory=dict)
    resume: Optional[str] = None
    session_id: Optional[str] = None
    continue_conversation: bool = False
    fork_session: bool = False
    include_partial_messages: bool = False
    session_store: Any = None
    enable_file_checkpointing: bool = False


@pytest.fixture(autouse=True)
def options_sdk(monkeypatch):
    monkeypatch.setattr(claude_module, "_sdk", lambda: SimpleNamespace(ClaudeAgentOptions=Options))


def test_named_parameters_override_native_options_including_empty_values():
    source = Options(
        model="base-model",
        tools=["Bash"],
        allowed_tools=["Bash"],
        disallowed_tools=["Edit"],
        system_prompt="base prompt",
        strict_mcp_config=True,
        setting_sources=["user"],
        mcp_servers={"server": {"command": "example"}},
        skills="all",
        plugins=[{"type": "local", "path": "."}],
        max_turns=5,
        max_budget_usd=1,
    )
    agent = ClaudeAgent(
        options=source,
        model="named-model",
        tools=[],
        allowed_tools=[],
        disallowed_tools=[],
        system_prompt="",
        strict_mcp_config=False,
        setting_sources=[],
        mcp_servers={},
        skills=[],
        plugins=[],
        max_turns=0,
        max_budget_usd=0,
    )
    resolved = agent._build_options()
    assert resolved.model == "named-model"
    for name in ("tools", "allowed_tools", "disallowed_tools", "setting_sources", "skills", "plugins"):
        assert getattr(resolved, name) == []
    assert resolved.system_prompt == ""
    assert resolved.strict_mcp_config is False
    assert resolved.mcp_servers == {}
    assert resolved.max_turns == resolved.max_budget_usd == 0
    assert source.model == "base-model" and source.tools == ["Bash"]


def test_advanced_options_survive_and_each_run_gets_independent_containers():
    callback = object()
    server = object()
    source = Options(
        model="base-model",
        hooks={"Stop": [callback]},
        mcp_servers={"sdk": {"type": "sdk", "instance": server}},
        plugins=[{"type": "local", "path": "./plugin"}],
        skills=["review"],
        system_prompt={"type": "preset", "preset": "claude_code"},
    )
    agent = ClaudeAgent(options=source)
    first = agent._build_options(streaming=True, resume="native-1")
    second = agent._build_options(streaming=False, resume="native-2")
    assert first.model == second.model == "base-model"
    assert first.resume == "native-1" and second.resume == "native-2"
    assert first.include_partial_messages and not second.include_partial_messages
    assert source.resume is None and not source.include_partial_messages
    assert first.hooks["Stop"][0] is callback
    assert first.mcp_servers["sdk"]["instance"] is server
    first.hooks["Stop"].clear()
    first.mcp_servers["sdk"]["type"] = "changed"
    first.plugins[0]["path"] = "changed"
    assert second.hooks == source.hooks == {"Stop": [callback]}
    assert second.mcp_servers["sdk"]["type"] == source.mcp_servers["sdk"]["type"] == "sdk"
    assert second.plugins == source.plugins == [{"type": "local", "path": "./plugin"}]


def test_named_collections_are_not_mutated():
    tools = ["Read"]
    plugins = [{"type": "local", "path": "./plugin"}]
    agent = ClaudeAgent(tools=tools, plugins=plugins)
    resolved = agent._build_options()
    resolved.tools.append("Bash")
    resolved.plugins[0]["path"] = "changed"
    assert tools == ["Read"]
    assert plugins == [{"type": "local", "path": "./plugin"}]


def test_legacy_dictionary_warns_and_preserves_precedence():
    with pytest.warns(DeprecationWarning, match="options_kwargs"):
        agent = ClaudeAgent(model="named", options_kwargs={"model": "legacy", "tools": []})
    assert agent._build_options().model == "legacy"
    assert agent._build_options().tools == []


def test_ambiguous_or_untyped_options_fail_early():
    with pytest.raises(ValueError, match="not both"):
        ClaudeAgent(options=Options(), options_kwargs={"model": "legacy"})
    with pytest.raises(TypeError, match="ClaudeAgentOptions instance"):
        ClaudeAgent(options={"model": "wrong type"})


@pytest.mark.parametrize(
    "name,value",
    [
        ("resume", "native"),
        ("session_id", "native"),
        ("continue_conversation", True),
        ("fork_session", True),
    ],
)
@pytest.mark.parametrize("legacy", [False, True])
def test_native_session_selection_cannot_override_agno(name, value, legacy):
    with pytest.raises(ValueError, match=f"manages {name}"):
        if legacy:
            with pytest.warns(DeprecationWarning):
                ClaudeAgent(options_kwargs={name: value})
        else:
            ClaudeAgent(options=Options(**{name: value}))


@pytest.mark.parametrize("flag", ["resume", "session-id", "continue", "fork-session", "include-partial-messages"])
def test_raw_cli_flags_cannot_bypass_runtime_configuration(flag):
    with pytest.raises(ValueError, match="manages extra_args"):
        ClaudeAgent(options=Options(extra_args={flag: "value"}))


def test_mutating_native_options_after_construction_still_checks_conflicts():
    source = Options()
    agent = ClaudeAgent(options=source)
    source.resume = "other-session"
    with pytest.raises(ValueError, match="manages resume"):
        agent._build_options(resume="agno-selected")


def test_streaming_defaults_and_conflicts():
    agent = ClaudeAgent(options=Options())
    assert agent._build_options(streaming=True).include_partial_messages is True
    source = Options(include_partial_messages=True)
    agent = ClaudeAgent(options=source)
    assert agent._build_options(streaming=True).include_partial_messages is True
    with pytest.raises(ValueError, match="stream="):
        agent._build_options(streaming=False)
    with pytest.warns(DeprecationWarning):
        legacy = ClaudeAgent(options_kwargs={"include_partial_messages": False})
    with pytest.raises(ValueError, match="stream="):
        legacy._build_options(streaming=True)


def test_typed_session_store_and_checkpointing_preserve_storage_contract(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    store = object()
    custom = ClaudeAgent(id="a", db=db, options=Options(session_store=store))
    assert custom._transcript_store("session") is None
    assert custom._build_options(agno_session_id="session").session_store is store
    checkpointing = ClaudeAgent(id="a", db=db, options=Options(enable_file_checkpointing=True))
    assert checkpointing._transcript_store("session") is None
    assert checkpointing._build_options(agno_session_id="session").session_store is None
    normal = ClaudeAgent(id="a", db=db, options=Options())
    injected = normal._build_options(agno_session_id="session").session_store
    assert injected is not None
    assert normal.options.session_store is None


def test_sdk_is_still_optional_until_needed(monkeypatch):
    def missing_sdk():
        raise ImportError("SDK is not installed")

    monkeypatch.setattr(claude_module, "_sdk", missing_sdk)
    agent = ClaudeAgent(model="example", tools=[])
    with pytest.raises(ImportError, match="SDK is not installed"):
        agent._build_options()
