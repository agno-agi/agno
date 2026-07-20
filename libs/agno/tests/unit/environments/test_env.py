"""Unit tests for Environment, Task, and the two fingerprints (offline)."""

import logging
import pathlib
from contextlib import contextmanager

import pytest

from agno.agent import Agent
from agno.environments import Environment, FingerprintError, Task
from agno.environments.environment import _ENV_FINGERPRINT_VERSION
from agno.environments.environment import _policy_fingerprint_of as policy_fingerprint_of
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.scorer import CodeScorer, JudgeScorer


def exact_match(run, expected):
    return run.content == expected


def loose_match(run, expected):
    return str(run.content) == str(expected)


def search_tool(query: str) -> str:
    """Find things."""
    return query


def search_tool_redocumented(query: str) -> str:
    """Find things carefully, with sources."""
    return query


# from_callable keys the schema on __name__: same declared tool, edited docstring.
search_tool_redocumented.__name__ = "search_tool"


@contextmanager
def _capture_agno_warnings():
    """caplog can miss the agno logger's records depending on its configuration; a
    handler attached directly to the logger cannot."""
    records = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("agno")
    handler = _Collector(level=logging.WARNING)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _env(**overrides) -> Environment:
    settings = {
        "name": "arithmetic",
        "tasks": (Task(input="What is 2+2?", expected=4),),
        "scorer": CodeScorer(exact_match),
        "agent": Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=[search_tool]),
    }
    settings.update(overrides)
    return Environment(**settings)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_fingerprint_sensitivity():
    base = _env()
    base_env_fp = base.env_fingerprint()
    base_policy_fp = base.policy_fingerprint()

    # Environment edits flip env_fingerprint only.
    env_edits = [
        _env(tasks=(Task(input="What is 3+3?", expected=4),)),  # task input
        _env(tasks=(Task(input="What is 2+2?", expected=5),)),  # expected value
        _env(scorer=JudgeScorer(OpenAIChat(id="gpt-5-mini"), "Is it right?")),  # scorer identity
        _env(
            agent=Agent(
                model=OpenAIChat(id="gpt-5-mini"),
                instructions="Answer tersely.",
                tools=[search_tool_redocumented],  # tool docstring
            )
        ),
    ]
    for edited in env_edits:
        assert edited.env_fingerprint() != base_env_fp
        assert edited.policy_fingerprint() == base_policy_fp

    # Policy edits flip policy_fingerprint only. Temperature is the canary for a
    # to_dict-based wrong build: Model.to_dict drops sampling params, so a build
    # hashing to_dict passes the other two and fails here.
    policy_edits = [
        OpenAIChat(id="gpt-5"),
        OpenAIChat(id="gpt-5-mini", base_url="https://proxy.example.com/v1"),
        OpenAIChat(id="gpt-5-mini", temperature=0.2),
    ]
    for edited_model in policy_edits:
        edited = _env(agent=Agent(model=edited_model, instructions="Answer tersely.", tools=[search_tool]))
        assert edited.policy_fingerprint() != base_policy_fp
        assert edited.env_fingerprint() == base_env_fp


def test_fingerprint_is_model_independent():
    # Two Envs differing only in model hash the same env_fingerprint. Catches a
    # reintroduced parse_tools call, whose strict-mode mutation depends on the model.
    one = _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=[search_tool]))
    two = _env(agent=Agent(model=OpenAIChat(id="gpt-5"), instructions="Answer tersely.", tools=[search_tool]))
    assert one.env_fingerprint() == two.env_fingerprint()


def test_model_level_prompt_is_env_not_policy():
    # system_prompt/instructions on the MODEL are prompt-shaped: they flip the env
    # fingerprint (like agent instructions) and leave the policy fingerprint alone.
    plain = _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=[search_tool]))
    prompted = _env(
        agent=Agent(
            model=OpenAIChat(id="gpt-5-mini", system_prompt="You are a pirate."),
            instructions="Answer tersely.",
            tools=[search_tool],
        )
    )
    assert prompted.env_fingerprint() != plain.env_fingerprint()
    assert prompted.policy_fingerprint() == plain.policy_fingerprint()


def test_tool_choice_is_env_not_policy():
    # tool_choice shapes which of the declared tools the model may call, so two envs
    # with identical tools but different tool_choice are different environments -- and
    # it is a prompt/request-shaping field, not model sampling identity.
    auto = _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), tools=[search_tool], tool_choice="auto"))
    none = _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), tools=[search_tool], tool_choice="none"))
    assert auto.env_fingerprint() != none.env_fingerprint()
    assert auto.policy_fingerprint() == none.policy_fingerprint()


def test_fingerprint_does_not_mutate_agent():
    env = _env()
    before = env.agent.__dict__.get("_tool_instructions")
    env.env_fingerprint()
    assert env.agent.__dict__.get("_tool_instructions") == before


def test_flagship_example_fingerprints_clean():
    # The headline example -- a CodeScorer over a file-defined function -- must
    # exercise the fingerprint feature that sells it: non-None, and function edits
    # flip it.
    with_exact = _env(scorer=CodeScorer(exact_match))
    with_loose = _env(scorer=CodeScorer(loose_match))
    assert with_exact.env_fingerprint() is not None
    assert with_exact.env_fingerprint() != with_loose.env_fingerprint()


def test_fingerprint_rejects_unserializable_expected():
    env = _env(tasks=(Task(input="q", expected=object()),))
    with pytest.raises(FingerprintError):
        env.env_fingerprint()

    # The other half of the contract: the rollout runner catches, stamps None, and
    # warns -- the run itself completes.
    import asyncio

    from agno.environments import arun_rollouts
    from agno.scorer import Score

    class StubFingerprintAgent:
        model = None

        async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
            from agno.run.agent import RunOutput
            from agno.run.base import RunStatus

            yield RunOutput(content="ok", status=RunStatus.completed)

    stub_env = Environment(
        name="degrades",
        tasks=(Task(input="q", expected=object()),),
        scorer=CodeScorer(lambda run, expected: Score(value=1.0, passed=True)),
        agent=lambda: StubFingerprintAgent(),
    )
    with _capture_agno_warnings() as records:
        result = asyncio.run(arun_rollouts(stub_env, k=1))
    assert result.env_fingerprint is None
    assert result.pass_rate == 1.0
    # The warn is part of the contract: degradation must be loud, not silent.
    assert any("env_fingerprint degraded to None" in record.getMessage() for record in records)


def test_fingerprint_component_failures_become_env_fingerprint_error():
    # Exceptions raised while BUILDING the payload must surface as
    # FingerprintError too, or the runner's catch-and-degrade is incomplete: a
    # functools.partial tool has no __name__ and would otherwise escape as a raw
    # AttributeError and crash the run at fingerprint time.
    import functools

    def helper(query: str, depth: int) -> str:
        return query

    partial_tool = functools.partial(helper, depth=2)
    env = _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=[partial_tool]))
    with pytest.raises(FingerprintError):
        env.env_fingerprint()


def test_env_matches_rejects_none():
    good = _env()
    bad = _env(tasks=(Task(input="q", expected=object()),))  # fingerprint degrades to None
    assert good.env_matches(bad) is False
    assert bad.env_matches(good) is False
    assert bad.env_matches(bad) is False  # None == None must NOT match
    assert good.env_matches(_env()) is True


def test_policy_fingerprint_reads_the_live_model():
    fingerprint = policy_fingerprint_of(OpenAIChat(id="gpt-5-mini", temperature=0.7))
    assert fingerprint != policy_fingerprint_of(OpenAIChat(id="gpt-5-mini", temperature=0.8))
    assert fingerprint == policy_fingerprint_of(OpenAIChat(id="gpt-5-mini", temperature=0.7))


# ---------------------------------------------------------------------------
# Prompt-shaping agent fields (envfp2): each changes the rendered system prompt or
# run input, so each must flip env_fingerprint while leaving policy_fingerprint alone.
# Before envfp2 every pair below hashed IDENTICALLY -- the under-invalidation this fixes.
# ---------------------------------------------------------------------------


def _prompt_agent(**overrides) -> Agent:
    return Agent(model=OpenAIChat(id="gpt-5-mini"), **overrides)


# (label, base kwargs, edited kwargs) -- the two agents differ in exactly one field.
_PROMPT_FIELD_EDITS = [
    ("additional_context", {"additional_context": "Cite sources."}, {"additional_context": "Be terse."}),
    ("expected_output", {"expected_output": "a number"}, {"expected_output": "a sentence"}),
    ("role", {"role": "teacher"}, {"role": "examiner"}),
    ("markdown", {"markdown": False}, {"markdown": True}),
    ("add_datetime_to_context", {"add_datetime_to_context": False}, {"add_datetime_to_context": True}),
    ("add_location_to_context", {"add_location_to_context": False}, {"add_location_to_context": True}),
    (
        "add_session_state_to_context",
        {"add_session_state_to_context": False},
        {"add_session_state_to_context": True},
    ),
    (
        "add_name_to_context",
        {"name": "Bot", "add_name_to_context": False},
        {"name": "Bot", "add_name_to_context": True},
    ),
    (
        "name (with add_name_to_context on)",
        {"name": "Alice", "add_name_to_context": True},
        {"name": "Bob", "add_name_to_context": True},
    ),
    (
        "additional_input (dict)",
        {"additional_input": [{"role": "user", "content": "one"}]},
        {"additional_input": [{"role": "user", "content": "two"}]},
    ),
    (
        "additional_input (Message)",
        {"additional_input": [Message(role="user", content="one")]},
        {"additional_input": [Message(role="user", content="two")]},
    ),
]


@pytest.mark.parametrize(
    "label, base_kwargs, edited_kwargs", _PROMPT_FIELD_EDITS, ids=[e[0] for e in _PROMPT_FIELD_EDITS]
)
def test_prompt_shaping_field_flips_env_fingerprint(label, base_kwargs, edited_kwargs):
    base = _env(agent=_prompt_agent(**base_kwargs))
    edited = _env(agent=_prompt_agent(**edited_kwargs))
    # The environment changed (prompt/input differs), so the env fingerprint must too.
    assert edited.env_fingerprint() != base.env_fingerprint()
    # ...but the model is untouched, so it is an environment change, not a policy one.
    assert edited.policy_fingerprint() == base.policy_fingerprint()


def test_add_name_to_context_gates_the_name():
    # With the flag off, agent.name never reaches the prompt, so a rename must NOT
    # invalidate: hashing name unconditionally would spuriously flag cosmetic renames.
    flag_off = _env(agent=_prompt_agent(name="Alice"))
    renamed_off = _env(agent=_prompt_agent(name="Bob"))
    assert flag_off.env_fingerprint() == renamed_off.env_fingerprint()

    # With the flag on, the name is in the prompt, so a rename must invalidate.
    flag_on = _env(agent=_prompt_agent(name="Alice", add_name_to_context=True))
    renamed_on = _env(agent=_prompt_agent(name="Bob", add_name_to_context=True))
    assert flag_on.env_fingerprint() != renamed_on.env_fingerprint()


def test_add_datetime_to_context_is_reproducible():
    # add_datetime_to_context injects wall-clock time into the prompt. The fingerprint
    # hashes the FLAG, not the rendered time, so repeated calls on the same agent are
    # stable -- the timestamp must not leak into the hash.
    import time

    env = _env(agent=_prompt_agent(add_datetime_to_context=True))
    first = env.env_fingerprint()
    time.sleep(1.1)  # cross a whole-second boundary; a leaked timestamp would change here
    assert env.env_fingerprint() == first


def test_additional_input_message_hashes_stably():
    # Two agents with semantically identical Message input must hash the same. A raw
    # Message carries a fresh id and a wall-clock created_at on every construction;
    # those volatile fields are stripped before hashing.
    one = _env(agent=_prompt_agent(additional_input=[Message(role="user", content="hello")]))
    two = _env(agent=_prompt_agent(additional_input=[Message(role="user", content="hello")]))
    assert one.env_fingerprint() == two.env_fingerprint()


class _OldFormatResult:
    """Stand-in for a result whose env_fingerprint was written by the pre-version format
    (a bare sha256, no 'envfp2:' prefix)."""

    def __init__(self, fingerprint):
        self._fingerprint = fingerprint

    def env_fingerprint(self):
        return self._fingerprint


def test_env_fingerprint_carries_version_prefix():
    fingerprint = _env().env_fingerprint()
    assert fingerprint.startswith(f"{_ENV_FINGERPRINT_VERSION}:")


def test_cross_version_fingerprints_do_not_match():
    # A version bump must make old fingerprints refuse to compare, even if the raw hash
    # underneath is byte-identical: the prefix is what env_matches sees, so a bare
    # (pre-version) hash never equals the prefixed one. Refusing to compare is the safe
    # behavior -- a false "same environment" is exactly what the fingerprint exists to
    # prevent.
    env = _env()
    new_fingerprint = env.env_fingerprint()
    bare_hash = new_fingerprint.split(":", 1)[1]  # simulate the old format: hash without prefix
    assert env.env_matches(_OldFormatResult(bare_hash)) is False
    # Same version and hash still matches -- the prefix does not break normal equality.
    assert env.env_matches(_OldFormatResult(new_fingerprint)) is True


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_env_agent_validation():
    _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini")))  # live agent accepted
    _env(agent=lambda: Agent(model=OpenAIChat(id="gpt-5-mini")))  # factory accepted

    from agno.team.team import Team

    with pytest.raises(TypeError, match="team release"):
        _env(agent=Team(members=[Agent(id="member")]))

    # A Team subclass IS a Team: the deferral message follows isinstance, not the
    # class name, and still names the received type.
    class MyTeam(Team):
        pass

    with pytest.raises(TypeError, match="team release") as excinfo:
        _env(agent=MyTeam(members=[Agent(id="member")]))
    assert "MyTeam" in str(excinfo.value)
    with pytest.raises(TypeError, match="str"):
        _env(agent="my-agent")
    with pytest.raises(TypeError, match="OpenAIChat"):
        _env(agent=OpenAIChat(id="gpt-5-mini"))


def test_team_agent_hybrid_rejected():
    # A class subclassing BOTH Team and Agent is a Team: the Team check runs before
    # the Agent accept, in construction and in factory-product validation alike.
    from agno.team.team import Team

    class Hybrid(Team, Agent):
        pass

    hybrid = Hybrid(members=[Agent(id="member")])
    with pytest.raises(TypeError, match="team release"):
        _env(agent=hybrid)
    with pytest.raises(TypeError, match="team release"):
        _env(agent=lambda: hybrid).env_fingerprint()


def test_duplicate_declared_task_ids_rejected():
    with pytest.raises(ValueError, match="duplicate task id"):
        _env(tasks=(Task(input="a", id="dup"), Task(input="b", id="dup")))


def test_factory_product_validated():
    # The Team exclusion cannot be bypassed by wrapping the Team in a lambda: the
    # factory product is validated where it is first materialized.
    from agno.team.team import Team

    team = Team(members=[Agent(id="member")])
    env = _env(agent=lambda: team)  # construction cannot see through the callable
    with pytest.raises(TypeError, match="team release"):
        env.env_fingerprint()
    with pytest.raises(TypeError, match="must return an Agent"):
        _env(agent=lambda: "not an agent").env_fingerprint()


def test_fingerprint_order_insensitive_for_nameless_dict_tools():
    # Provider-builtin dict tools carry no "name" key; without a content tiebreak
    # they would all sort under "" and leak declaration order into env_fingerprint.
    def _with_tools(tools):
        return _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=tools))

    dict_a = {"type": "file_search"}
    dict_b = {"type": "web_search_preview"}
    assert _with_tools([dict_a, dict_b]).env_fingerprint() == _with_tools([dict_b, dict_a]).env_fingerprint()
    # A different builtin set still flips the hash.
    assert _with_tools([dict_a, dict_b]).env_fingerprint() != _with_tools([dict_a]).env_fingerprint()


def test_env_not_silently_unhashable():
    # eq=False keeps identity hashing: the auto-generated __hash__ would raise the
    # first time an Environment or Task sat in a set (metadata is a mapping).
    env = _env()
    task = Task(input="q", metadata={"difficulty": "hard"})
    assert {env, task}


# ---------------------------------------------------------------------------
# from_jsonl
# ---------------------------------------------------------------------------


def test_from_jsonl_roundtrip(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text(
        '{"input": "What is 2+2?", "expected": 4}\n'
        '{"input": "Name the capital of France.", "expected": "Paris", "id": "capitals-1"}\n'
        '{"input": "Hard one.", "metadata": {"difficulty": "hard"}}\n',
        encoding="utf-8",
    )
    tasks = Task.from_jsonl(path)
    assert len(tasks) == 3
    assert tasks[0].input == "What is 2+2?"
    assert tasks[0].expected == 4
    assert tasks[0].id is None
    assert tasks[1].id == "capitals-1"
    assert tasks[2].expected is None
    assert tasks[2].metadata == {"difficulty": "hard"}


async def test_afrom_jsonl_matches_sync(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"input": "What is 2+2?", "expected": 4}\n', encoding="utf-8")
    tasks = await Task.afrom_jsonl(path)
    assert len(tasks) == 1
    assert tasks[0].input == "What is 2+2?"
    assert tasks[0].expected == 4


def test_from_jsonl_rejects_unknown_keys(tmp_path):
    # An "expected_output" column (AccuracyEval's name) must not silently yield
    # expected=None on every task, which under a None-tolerant scorer greens
    # everything.
    path = tmp_path / "tasks.jsonl"
    path.write_text(
        '{"input": "ok"}\n{"input": "bad", "expected_output": "4"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        Task.from_jsonl(path)
    assert "line 2" in str(excinfo.value)
    assert "expected_output" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Import direction (the half deferred from R2)
# ---------------------------------------------------------------------------


def test_dependency_direction_environments():
    import agno
    from tests.unit.environments.test_engine import _direct_imports, _imports_of

    agno_root = pathlib.Path(agno.__file__).parent
    environments_dir = agno_root / "environments"

    # environments imports scorer (its engine is internal to the package)...
    assert _imports_of(environments_dir, "agno.scorer") != []
    # ...and nothing outside the package imports environments.
    outside = [
        f"{path}:{lineno}"
        for path, lineno, target in _direct_imports(agno_root)
        if (target == "agno.environments" or target.startswith("agno.environments."))
        and environments_dir not in path.parents
    ]
    assert outside == []
