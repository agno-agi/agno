"""Unit tests for Env, EnvTask, and the two fingerprints (offline)."""

import logging
import pathlib
from contextlib import contextmanager

import pytest

from agno.agent import Agent
from agno.environments import Env, EnvFingerprintError, EnvTask
from agno.environments.env import _policy_fingerprint_of as policy_fingerprint_of
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


def _env(**overrides) -> Env:
    settings = {
        "name": "arithmetic",
        "tasks": (EnvTask(input="What is 2+2?", expected=4),),
        "scorer": CodeScorer(exact_match),
        "agent": Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=[search_tool]),
    }
    settings.update(overrides)
    return Env(**settings)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_fingerprint_sensitivity():
    base = _env()
    base_env_fp = base.env_fingerprint()
    base_policy_fp = base.policy_fingerprint()

    # Environment edits flip env_fingerprint only.
    env_edits = [
        _env(tasks=(EnvTask(input="What is 3+3?", expected=4),)),  # task input
        _env(tasks=(EnvTask(input="What is 2+2?", expected=5),)),  # expected value
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
    env = _env(tasks=(EnvTask(input="q", expected=object()),))
    with pytest.raises(EnvFingerprintError):
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

    stub_env = Env(
        name="degrades",
        tasks=(EnvTask(input="q", expected=object()),),
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
    # EnvFingerprintError too, or the runner's catch-and-degrade is incomplete: a
    # functools.partial tool has no __name__ and would otherwise escape as a raw
    # AttributeError and crash the run at fingerprint time.
    import functools

    def helper(query: str, depth: int) -> str:
        return query

    partial_tool = functools.partial(helper, depth=2)
    env = _env(agent=Agent(model=OpenAIChat(id="gpt-5-mini"), instructions="Answer tersely.", tools=[partial_tool]))
    with pytest.raises(EnvFingerprintError):
        env.env_fingerprint()


def test_env_matches_rejects_none():
    good = _env()
    bad = _env(tasks=(EnvTask(input="q", expected=object()),))  # fingerprint degrades to None
    assert good.env_matches(bad) is False
    assert bad.env_matches(good) is False
    assert bad.env_matches(bad) is False  # None == None must NOT match
    assert good.env_matches(_env()) is True


def test_policy_fingerprint_reads_the_live_model():
    fingerprint = policy_fingerprint_of(OpenAIChat(id="gpt-5-mini", temperature=0.7))
    assert fingerprint != policy_fingerprint_of(OpenAIChat(id="gpt-5-mini", temperature=0.8))
    assert fingerprint == policy_fingerprint_of(OpenAIChat(id="gpt-5-mini", temperature=0.7))


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
    # first time an Env or EnvTask sat in a set (metadata is a mapping).
    env = _env()
    task = EnvTask(input="q", metadata={"difficulty": "hard"})
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
    tasks = EnvTask.from_jsonl(path)
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
    tasks = await EnvTask.afrom_jsonl(path)
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
        EnvTask.from_jsonl(path)
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
