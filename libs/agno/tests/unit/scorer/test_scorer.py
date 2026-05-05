"""Unit tests for agno.scorer: Score, CodeScorer, and the package-level rules."""

import ast
import importlib.util
import pathlib
import subprocess
import sys

import pytest

from agno.run.agent import RunOutput
from agno.scorer import CodeScorer, FingerprintError, Score, Scorer, ToolCallScorer


def _run(content="x"):
    return RunOutput(content=content)


# ---------------------------------------------------------------------------
# Architectural rules
# ---------------------------------------------------------------------------


def test_scorer_does_not_import_eval_or_environments():
    # The one architectural rule: scorer imports neither eval nor environments,
    # because both import it. Inspected as direct imports in the package's own
    # modules (module-level and function-level both): the transitive closure through
    # agno.agent unavoidably contains agno.eval.base, so it cannot be the assertion.
    import agno.scorer

    package_dir = pathlib.Path(agno.scorer.__file__).parent
    forbidden = ("agno.eval", "agno.environments")
    offenders = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                targets = [node.module]
            for target in targets:
                if any(target == pkg or target.startswith(pkg + ".") for pkg in forbidden):
                    offenders.append(f"{path.name}:{node.lineno}: imports {target}")
    assert not offenders, offenders


def test_scorer_and_suite_import_cleanly_in_fresh_interpreters():
    # eval imports scorer at module scope (the allowed direction; suite.py needs
    # real Score/Scorer names so get_type_hints resolves over Case/CaseResult), and
    # importing any scorer submodule executes the whole package __init__ -- judge.py
    # included, which builds on agno.agent. That is safe exactly as long as
    # agno.agent never imports agno.eval.suite back; a fresh interpreter per entry
    # point catches that cycle the moment it becomes real, where in-process test
    # imports would mask it.
    for entry in ("import agno.scorer", "import agno.eval.suite"):
        result = subprocess.run(
            [sys.executable, "-c", entry],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"{entry!r} failed in a fresh interpreter:\n{result.stderr}"


def test_no_lowercase_status_literals():
    # RunStatus subclasses str with UPPERCASE values, so `run.status == "completed"`
    # is silently always false -- and mypy accepts the comparison as overlapping.
    # An AST walk is the only thing catching it. Scope is agno/scorer only: in
    # agno/environments, StopReason values are deliberately lowercase and comparing
    # them to lowercase strings is correct code.
    import agno.scorer

    lowercase_status_words = {"pending", "running", "completed", "paused", "cancelled", "error", "regenerated"}
    package_dir = pathlib.Path(agno.scorer.__file__).parent
    offenders = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            # Membership tests against literal collections: flag the elements too.
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and isinstance(comparator, (ast.List, ast.Tuple, ast.Set)):
                    operands.extend(comparator.elts)
            for operand in operands:
                if (
                    isinstance(operand, ast.Constant)
                    and isinstance(operand.value, str)
                    and operand.value in lowercase_status_words
                ):
                    offenders.append(f"{path.name}:{node.lineno}: comparison against {operand.value!r}")
    assert not offenders, offenders


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


def test_score_rejects_out_of_range():
    with pytest.raises(ValueError, match="must be in"):
        Score(value=1.4, passed=True)
    with pytest.raises(ValueError, match="must be in"):
        Score(value=-0.1, passed=False)
    # The endpoints themselves are valid.
    Score(value=0.0, passed=False)
    Score(value=1.0, passed=True)


# ---------------------------------------------------------------------------
# CodeScorer
# ---------------------------------------------------------------------------


def test_code_scorer_threshold_boundary():
    # A float equal to pass_threshold passes (>=).
    at_threshold = CodeScorer(lambda run, expected: 0.5).score(_run())
    assert at_threshold.value == 0.5
    assert at_threshold.passed is True
    below = CodeScorer(lambda run, expected: 0.49).score(_run())
    assert below.passed is False

    # A bool bypasses the threshold entirely: with an unreachable threshold, a float
    # 1.0 fails but True still passes.
    unreachable = CodeScorer(lambda run, expected: True, pass_threshold=1.5)
    assert unreachable.score(_run()).passed is True
    assert unreachable.score(_run()).value == 1.0
    float_one = CodeScorer(lambda run, expected: 1.0, pass_threshold=1.5)
    assert float_one.score(_run()).passed is False

    # A returned Score is used verbatim, threshold not consulted.
    verbatim = Score(value=0.2, passed=True, reason="verbatim")
    assert CodeScorer(lambda run, expected: verbatim).score(_run()) is verbatim


def test_code_scorer_out_of_range_float_raises():
    # A scorer written against a 1-10 mental model fails loudly, not silently green.
    with pytest.raises(ValueError, match="must be in"):
        CodeScorer(lambda run, expected: 7.0).score(_run())


async def test_code_scorer_awaits_coroutine_functions():
    async def check(run, expected):
        return run.content == expected

    result = await CodeScorer(check).ascore(_run("yes"), "yes")
    assert result.passed is True


class _AsyncCallable:
    async def __call__(self, run, expected):
        return run.content == expected


async def test_code_scorer_ascore_awaits_async_callable_objects():
    # iscoroutinefunction is False for the instance; the dispatch must look at __call__.
    result = await CodeScorer(_AsyncCallable()).ascore(_run("yes"), "yes")
    assert result.passed is True


def test_code_scorer_score_awaits_async_callable_objects():
    assert CodeScorer(_AsyncCallable()).score(_run("yes"), "yes").passed is True


def test_code_scorer_accepts_int_returns():
    # 0/1 from comparison-style functions are common; ints are treated as floats.
    assert CodeScorer(lambda run, expected: 1).score(_run()).passed is True
    assert CodeScorer(lambda run, expected: 0).score(_run()).passed is False
    with pytest.raises(ValueError, match="must be in"):
        CodeScorer(lambda run, expected: 2).score(_run())


def test_code_scorer_digest_stable_and_sensitive():
    def scorer_a(run, expected):
        return run.content == expected

    def scorer_b(run, expected):
        return run.content != expected

    # The __name__ attribute must not be the discriminator: with the names aligned,
    # only a source-based digest still tells these apart.
    scorer_b.__name__ = scorer_a.__name__

    # Same function, hashed twice: stable (source-based, no memory addresses).
    assert CodeScorer(scorer_a).digest() == CodeScorer(scorer_a).digest()
    # A different body flips the digest.
    assert CodeScorer(scorer_a).digest() != CodeScorer(scorer_b).digest()
    # The same function with a different pass_threshold grades differently, so it
    # must flip the digest -- otherwise two environments that pass and fail the same
    # score would share an env_fingerprint.
    assert CodeScorer(scorer_a, pass_threshold=0.5).digest() != CodeScorer(scorer_a, pass_threshold=0.8).digest()
    assert CodeScorer(scorer_a, pass_threshold=0.5).digest() == CodeScorer(scorer_a, pass_threshold=0.5).digest()
    # A callable without retrievable source raises FingerprintError.
    with pytest.raises(FingerprintError):
        CodeScorer(len).digest()


def test_code_scorer_digest_stable_across_processes():
    # A digest embedding anything process-local -- a repr with a memory address --
    # would report "environment drifted" forever between two identical envs.
    fixture_dir = pathlib.Path(__file__).parent
    spec = importlib.util.spec_from_file_location("digest_fixture", fixture_dir / "digest_fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    local_digest = CodeScorer(module.fixture_scorer).digest()

    code = (
        f"import sys; sys.path.insert(0, {str(fixture_dir)!r}); "
        "from digest_fixture import fixture_scorer; "
        "from agno.scorer import CodeScorer; "
        "print(CodeScorer(fixture_scorer).digest())"
    )
    remote = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert local_digest == remote.stdout.strip()


# ---------------------------------------------------------------------------
# The protocol and the sync twins
# ---------------------------------------------------------------------------


def test_all_scorers_have_sync_score():
    from types import SimpleNamespace

    from agno.scorer import JudgeScorer
    from agno.scorer.judge import BinaryJudgeResponse

    code_scorer = CodeScorer(lambda run, expected: True)
    tool_scorer = ToolCallScorer(["search"])
    from agno.models.openai import OpenAIChat

    judge_scorer = JudgeScorer(OpenAIChat(id="gpt-5-mini"), "Is it correct?")
    judge_scorer._evaluator = SimpleNamespace(
        run=lambda prompt, stream=False: SimpleNamespace(content=BinaryJudgeResponse(passed=True, reason="ok"))
    )

    assert code_scorer.score(_run()).passed is True
    assert tool_scorer.score(_run()).passed is False
    assert judge_scorer.score(_run()).passed is True

    # A third-party scorer implementing only ascore also satisfies the protocol.
    class AscoreOnly:
        async def ascore(self, run, expected=None):
            return Score(value=1.0, passed=True)

    for scorer in (code_scorer, tool_scorer, judge_scorer, AscoreOnly()):
        assert isinstance(scorer, Scorer)
