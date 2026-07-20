"""TinkerModel against fake sampling clients.

The `tinker` SDK is not installed in this environment and no TINKER_API_KEY is set;
every test here injects fakes through the constructor seams. The fakes deliberately
replay the SHAPES the real SDK returns -- in particular a parts-list message, which is
what a thinking model actually produces -- because a str-only assumption passes an
offline suite and breaks on the first live sample.
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts, to_sft_jsonl
from agno.environments.environment import _env_fingerprint_of, _policy_fingerprint_of
from agno.models.message import Message
from agno.models.tinker import TinkerModel
from agno.scorer import CodeScorer

ANSWER = "an old silent pond\na frog jumps in\nsplash, silence again"
THINKING = "Let me count the syllables: 5, 7, 5."


class FakeSequence:
    def __init__(self, tokens):
        self.tokens = tokens


class FakeSampleResponse:
    def __init__(self, tokens):
        self.sequences = [FakeSequence(tokens)]


class FakeFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class FakeSamplingClient:
    """Records every sample call so the request params are assertable."""

    def __init__(self, *, tokens=(1, 2, 3), assert_off_thread=None):
        self.calls = []
        self._tokens = list(tokens)
        self._assert_off_thread = assert_off_thread

    def sample(self, *, prompt, num_samples, sampling_params):
        if self._assert_off_thread is not None:
            # The whole point of the async path: a seconds-long network call must not
            # run on the event-loop thread.
            assert threading.current_thread() is not self._assert_off_thread, (
                "sample() ran on the event-loop thread; concurrent attempts would serialize"
            )
        self.calls.append({"prompt": prompt, "num_samples": num_samples, "params": sampling_params})
        return FakeFuture(FakeSampleResponse(self._tokens))

    def get_tokenizer(self):
        return "fake-tokenizer"


class FakeSamplingParams:
    def __init__(self, *, max_tokens, temperature, seed, stop):
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed
        self.stop = stop


class FakeRenderer:
    """Mirrors the real renderer contract, including the parts-list response shape."""

    def __init__(self, *, message=None, termination="stop_sequence"):
        self._message = message if message is not None else {"role": "assistant", "content": ANSWER}
        self._termination = termination
        self.prompts = []

    def build_generation_prompt(self, messages):
        self.prompts.append(messages)
        return {"prompt_for": messages}

    def get_stop_sequences(self):
        return ["<|im_end|>"]

    def parse_response(self, tokens):
        return self._message, self._termination


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    """Inject the SDK at the module boundary, not over the unit under test.

    Deliberately NOT a monkeypatch of `TinkerModel._sampling_params`: that would
    replace the only code that builds the sampling request, and the sampling-params
    test would then be asserting against its own re-implementation. Stubbing
    `sys.modules["tinker"]` leaves the production method running.
    """
    import sys

    monkeypatch.setitem(
        sys.modules,
        "tinker",
        SimpleNamespace(types=SimpleNamespace(SamplingParams=FakeSamplingParams)),
    )


def _model(**kwargs):
    kwargs.setdefault("sampling_client", FakeSamplingClient())
    kwargs.setdefault("renderer", FakeRenderer())
    kwargs.setdefault("base_model", "Qwen/Qwen3.6-35B-A3B")
    return TinkerModel(**kwargs)


def _messages():
    return [Message(role="user", content="the sea")]


# ---------------------------------------------------------------------------
# Shape: all six abstract methods, and the stream path the engine actually uses
# ---------------------------------------------------------------------------


def test_tinker_model_implements_stream_methods():
    # The engine consumes every subject through arun(stream=True), which reaches
    # ainvoke_stream. An unimplemented stream method would raise on every rollout and
    # leave every attempt unscored -- a pass rate over zero, silently.
    model = _model()

    assert model.invoke(messages=_messages()).content == ANSWER
    assert asyncio.run(model.ainvoke(messages=_messages())).content == ANSWER

    sync_chunks = list(model.invoke_stream(messages=_messages()))
    assert len(sync_chunks) == 1 and sync_chunks[0].content == ANSWER

    async def collect():
        return [chunk async for chunk in model.ainvoke_stream(messages=_messages())]

    async_chunks = asyncio.run(collect())
    assert len(async_chunks) == 1 and async_chunks[0].content == ANSWER

    # The parse pair are pass-throughs because _sample returns a complete response.
    sentinel = object()
    assert model._parse_provider_response(sentinel) is sentinel
    assert model._parse_provider_response_delta(sentinel) is sentinel


def _haiku_env(model):
    return Environment(
        name="tinker-haiku",
        agent=Agent(model=model),
        tasks=(Task(id="sea", input="the sea"),),
        scorer=CodeScorer(three_lines),
    )


def three_lines(run, expected):
    return run.content is not None and len(run.content.strip().split("\n")) == 3


def test_rollout_through_tinker_model_completes_via_stream():
    result = run_rollouts(_haiku_env(_model()), k=2)

    assert result.n_scored == 2  # scored, not errored
    assert result.n_unscored == 0
    assert result.pass_rate == 1.0


# ---------------------------------------------------------------------------
# Content: byte-for-byte, with reasoning split out
# ---------------------------------------------------------------------------


def test_tinker_model_content_is_raw_reasoning_split():
    # A str-content message passes straight through: no scrub, no fence or whitespace
    # munging. The display-only cleanup in the consumer must not migrate here.
    raw = f"  {ANSWER}  \n"
    model = _model(renderer=FakeRenderer(message={"role": "assistant", "content": raw}))

    response = model.invoke(messages=_messages())

    assert response.content == raw  # byte-for-byte, whitespace included
    assert response.reasoning_content is None


def test_tinker_model_parses_parts_content():
    # The shape a thinking model really returns: the qwen3 renderer rewrites parsed
    # content into typed parts. Note the keys differ -- TextPart carries "text",
    # ThinkingPart carries "thinking".
    parts_message = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": THINKING},
            {"type": "text", "text": "an old silent pond\n"},
            {"type": "text", "text": "a frog jumps in\nsplash, silence again"},
        ],
    }
    model = _model(renderer=FakeRenderer(message=parts_message))

    response = model.invoke(messages=_messages())

    # Text parts concatenate byte-for-byte, in order, with no separator.
    assert response.content == ANSWER
    assert response.reasoning_content == THINKING
    assert THINKING not in response.content  # reasoning never leaks into the answer


def test_tinker_model_export_fidelity(tmp_path):
    # The data path: what the model emitted is what lands in the training file.
    parts_message = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": THINKING},
            {"type": "text", "text": ANSWER},
        ],
    }
    model = _model(renderer=FakeRenderer(message=parts_message))
    result = run_rollouts(_haiku_env(model), k=2)

    path = tmp_path / "train.jsonl"
    report = to_sft_jsonl(result, path)

    assert report.n_written == 2
    written = path.read_text(encoding="utf-8")
    import json as json_module

    for line in [row for row in written.split("\n") if row.strip()]:
        assistant = json_module.loads(line)["messages"][-1]
        assert assistant["role"] == "assistant"
        assert assistant["content"] == ANSWER  # unscrubbed
        assert THINKING not in assistant["content"]  # reasoning is not trained


# ---------------------------------------------------------------------------
# Sampling parameters
# ---------------------------------------------------------------------------


def test_tinker_model_sampling_params():
    # Three load-bearing rules: temperature above zero, the renderer's stop sequences,
    # a max_tokens budget covering the think block -- and NO constant seed across
    # attempts. A fixed seed makes all k attempts identical, every task unanimous, the
    # learning zone empty by construction, and the loop converges having trained
    # nothing. No offline assertion on a single call can catch that, so this asserts
    # across attempts.
    client = FakeSamplingClient()
    model = _model(sampling_client=client)

    run_rollouts(_haiku_env(model), k=4)

    assert len(client.calls) == 4
    for call in client.calls:
        params = call["params"]
        assert params.temperature > 0
        assert params.stop == ["<|im_end|>"]
        assert params.max_tokens == 2000
        assert params.seed is None  # never a fixed seed across attempts
        assert call["num_samples"] == 1

    assert {call["params"].seed for call in client.calls} == {None}

    # An explicitly requested seed is still honoured -- it is opt-in, not the default.
    seeded = _model(sampling_client=FakeSamplingClient(), seed=7)
    seeded.invoke(messages=_messages())
    assert seeded._sampling_client.calls[0]["params"].seed == 7


def test_tinker_model_async_sample_off_loop_thread():
    async def drive():
        loop_thread = threading.current_thread()
        client = FakeSamplingClient(assert_off_thread=loop_thread)
        model = _model(sampling_client=client)
        chunks = [chunk async for chunk in model.ainvoke_stream(messages=_messages())]
        assert chunks[0].content == ANSWER
        # And the plain async door too.
        await model.ainvoke(messages=_messages())
        return client

    client = asyncio.run(drive())
    assert len(client.calls) == 2


def test_tinker_model_unclean_sample_errors_the_attempt():
    # A cut-off sample is a fragment, not an answer: it must surface as an errored
    # (unscored) attempt rather than be scored as a wrong one.
    model = _model(renderer=FakeRenderer(termination="length"))

    result = run_rollouts(_haiku_env(model), k=2)

    assert result.n_scored == 0
    assert result.n_unscored == 2
    assert result.pass_rate is None


# ---------------------------------------------------------------------------
# Fingerprints -- the identity the whole before/after rests on
# ---------------------------------------------------------------------------


def test_tinker_model_policy_diverges_env_matches():
    # Base and tuned must differ in POLICY and agree on ENVIRONMENT. Get the first
    # wrong and diff.policy_changed reads False while the pass rate rises; get the
    # second wrong and diff() raises MismatchError instead of measuring.
    base = TinkerModel(
        base_model="Qwen/Qwen3.6-35B-A3B",
        sampling_client=FakeSamplingClient(),
        renderer=FakeRenderer(),
    )
    tuned = TinkerModel(
        base_model="Qwen/Qwen3.6-35B-A3B",
        model_path="tinker://checkpoint/run-1",
        sampling_client=FakeSamplingClient(),
        renderer=FakeRenderer(),
    )

    assert base.id == "Qwen/Qwen3.6-35B-A3B"
    assert tuned.id == "Qwen/Qwen3.6-35B-A3B@tinker://checkpoint/run-1"
    assert base.provider == tuned.provider == "Tinker"
    assert base.name == tuned.name == "Qwen/Qwen3.6-35B-A3B"

    base_policy = _policy_fingerprint_of(base)
    tuned_policy = _policy_fingerprint_of(tuned)
    assert base_policy is not None and tuned_policy is not None
    assert base_policy != tuned_policy

    # Model-level prompt fields stay None, so the env fingerprint is unmoved by the
    # model swap.
    assert base.system_prompt is None and base.instructions is None
    assert tuned.system_prompt is None and tuned.instructions is None

    agent = Agent(model=base)
    env = Environment(
        name="fp",
        agent=agent,
        tasks=(Task(id="sea", input="the sea"),),
        scorer=CodeScorer(three_lines),
    )
    base_env = _env_fingerprint_of(env, agent, model=base)
    tuned_env = _env_fingerprint_of(env, agent, model=tuned)
    assert base_env is not None
    assert base_env == tuned_env


def test_tinker_model_injected_client_stays_private():
    # The sampling client must not reach the identity payload: it is not policy, and a
    # live client is not serializable.
    model = _model()
    assert "sampling_client" not in vars(model)
    assert "renderer" not in vars(model)
    assert "_sampling_client" in vars(model)

    from agno.scorer._model import model_identity_payload

    payload = model_identity_payload(model)
    assert "unserializable_params" not in payload
    assert payload["id"] == "Qwen/Qwen3.6-35B-A3B"
    assert payload["provider"] == "Tinker"
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == 2000


def test_tinker_model_sdk_imports_stay_lazy():
    # The offline contract: this module must import with the SDK uninstalled, which is
    # only true while every tinker import sits inside a function body. Asserted
    # structurally so a later consistency pass cannot "fix" it back to the
    # module-level try/except convention every other adapter uses.
    import ast
    import inspect

    import agno.models.tinker.tinker as module

    tree = ast.parse(inspect.getsource(module))
    module_level = []
    for node in tree.body:  # top level only -- nested function bodies are not walked
        if isinstance(node, ast.Import):
            module_level += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module_level.append(node.module or "")

    offenders = [name for name in module_level if name.split(".")[0] in ("tinker", "tinker_cookbook")]
    assert offenders == [], f"SDK imported at module level: {offenders}"

    # And the imports really are present somewhere -- the adapter is not a stub.
    source = inspect.getsource(module)
    assert "import tinker" in source
    assert "from tinker_cookbook" in source
