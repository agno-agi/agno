"""Attachments on a ``sandbox=`` agent: the canonical wire the queue stores, and what the coordinator receives.

The harness is the single validation point for Python callers, HTTP and the queue worker, so these tests drive
``_harness.submission`` / ``_execution`` and the public ``arun`` with only the coordinator replaced by a recorder.
"""

import json

import pytest

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.exceptions import InputCheckError, UnsupportedMediaError
from agno.media import Audio, File, Image
from agno.run.concurrency import worker_managed_execution
from agno.sandbox import _harness
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from agno.sandbox.media import MAX_MEDIA_BYTES, decode_media, encode_media

SANDBOX_ENV = {"AGNO_SANDBOX_TEST_RUNTIME": "1"}


def _agent(cls=FixtureAgent):
    return cls(sandbox=DockerSandbox("img:none", env=SANDBOX_ENV))


def _media():
    return dict(images=[Image(content=b"png", format="png")], files=[File(content=b"abc", filename="a.txt")])


def test_python_media_becomes_the_canonical_json_wire_in_the_run_options():
    agent = _agent()
    options = _harness.submission(agent, "hello", agent._media_kwargs(**_media()))
    assert options["media"] == encode_media(**_media())
    assert json.loads(json.dumps(options)) == options


@pytest.mark.parametrize("cls", [FixtureAgent, ClaudeAgent, CodexAgent])
def test_every_sandboxable_harness_accepts_images_and_files_and_refuses_the_rest(cls):
    agent = _agent(cls)
    assert "media" in _harness.submission(agent, "hello", agent._media_kwargs(**_media()))
    with pytest.raises(UnsupportedMediaError):
        agent._media_kwargs(audio=[Audio(content=b"audio")])


def test_queue_wire_is_accepted_and_revalidated_when_the_worker_replays_it():
    agent = _agent()
    wire = encode_media(**_media())
    assert _harness.submission(agent, "hello", {"media": wire})["media"] == wire
    # A direct caller handing over a damaged wire gets a plain input error; the queue's permanent failure is below.
    with pytest.raises(ValueError, match="filename"):
        _harness.submission(agent, "hello", {"media": [{**wire[0], "name": "../escape"}]})


def test_the_whole_runtime_request_limit_counts_the_attachments():
    agent = _agent()
    full = {"files": [File(content=b"a" * MAX_MEDIA_BYTES, filename="full.bin")]}
    _harness.submission(agent, "x", {"media": full})
    with pytest.raises(ValueError, match="exceeds"):
        _harness.submission(agent, "x" * 400_000, {"media": full})


def test_a_local_file_is_read_at_submission_and_survives_removal_of_its_source(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"local bytes")
    agent = _agent()
    options = _harness.submission(agent, "hello", {"media": {"files": [File(filepath=path)]}})
    path.unlink()
    (file,) = decode_media(options["media"])["files"]
    assert file.content == b"local bytes" and file.filename == "notes.txt"
    assert str(tmp_path) not in json.dumps(options)


def test_the_coordinator_is_called_with_decoded_attachments_and_text_only_calls_are_unchanged():
    agent = _agent()
    wire = encode_media(**_media())
    execution = _harness._execution(agent, "hello", {"media": wire, "run_id": "r"})
    assert [image.content for image in execution["images"]] == [b"png"]
    assert [file.content for file in execution["files"]] == [b"abc"]
    text_only = _harness._execution(agent, "hello", {"run_id": "r"})
    assert "images" not in text_only and "files" not in text_only


class _Recorder:
    def __init__(self):
        self.calls = []

    async def arun(self, session_id, **execution):
        from agno.run.agent import RunOutput
        from agno.run.base import RunStatus

        self.calls.append(execution)
        return RunOutput(run_id=execution["run_id"], session_id=session_id, status=RunStatus.completed, content="ok")

    async def astream(self, session_id, **execution):
        self.calls.append(execution)
        if False:
            yield None


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_public_arun_forwards_attachments_to_the_coordinator(monkeypatch, stream):
    agent, recorder = _agent(), _Recorder()
    monkeypatch.setattr(_harness, "coordinator", lambda _: recorder)
    if stream:
        async for _ in agent.arun("hello", stream=True, session_id="s", run_id="r", **_media()):
            pass
    else:
        await agent.arun("hello", session_id="s", run_id="r", **_media())
    (execution,) = recorder.calls
    assert [image.content for image in execution["images"]] == [b"png"]
    assert [file.filename for file in execution["files"]] == ["a.txt"]


@pytest.mark.asyncio
async def test_invalid_attachments_fail_before_the_coordinator_is_reached(monkeypatch):
    agent, recorder = _agent(), _Recorder()
    monkeypatch.setattr(_harness, "coordinator", lambda _: recorder)
    with pytest.raises(ValueError):
        await agent.arun("hello", session_id="s", run_id="r", files=[File(url="https://example.com/a.txt")])
    assert recorder.calls == []


# --- the pending run row ---------------------------------------------------------------------------------------
# The store refuses to claim a run whose input differs from the row accepted for it, so the pending row has to carry
# exactly the attachments the coordinator will write when the run starts. The queue hands the hook the wire its
# ticket holds, both when the request is accepted and when the worker ensures the row at claim.


class _Store:
    def __init__(self):
        self.prepared = []

    async def aprepare(self, run):
        self.prepared.append(run)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_media", [True, False])
async def test_the_pending_row_carries_the_same_input_the_coordinator_writes_at_claim(monkeypatch, with_media):
    from types import SimpleNamespace

    from agno.run.agent import RunInput

    agent = _agent()
    wire = encode_media(images=[Image(content=b"png", format="png")], files=[File(content=b"abc", filename="a.txt")])
    store = _Store()
    monkeypatch.setattr(_harness, "coordinator", lambda _: SimpleNamespace(store=store))
    pending = await _harness.aprepare_pending_run(agent, "r", "s", None, "hello", wire if with_media else None)
    claimed = RunInput(input_content="hello", **decode_media(wire if with_media else []))
    assert pending.input.to_dict() == claimed.to_dict()
    assert store.prepared[0]["input"] == claimed.to_dict()
    assert bool(pending.input.files) is with_media


@pytest.mark.parametrize("stream", [False, True])
def test_the_synchronous_public_run_forwards_attachments_too(monkeypatch, stream):
    agent, recorder = _agent(), _Recorder()
    monkeypatch.setattr(_harness, "coordinator", lambda _: recorder)
    result = agent.run("hello", stream=stream, session_id="s", run_id="r", **_media())
    if stream:
        list(result)
    (execution,) = recorder.calls
    assert [file.content for file in execution["files"]] == [b"abc"]


# --- a ticket that cannot be replayed ---------------------------------------------------------------------------
# Retrying cannot cure a damaged wire, so the worker must fail it once and write the reason on the run. The
# claim-time "ensure the run row" step only retries, so the pending-row hook must not raise for such a ticket.


@pytest.mark.parametrize(
    "damage",
    [
        lambda wire: wire[0].update(name="../escape"),
        lambda wire: wire[0].update(content="not base64!"),
        lambda wire: wire[0].update(host_path="/etc/passwd"),
        lambda wire: wire.append("not an object"),
    ],
)
def test_a_damaged_wire_is_a_permanent_input_failure_for_the_worker(damage):
    agent = _agent()
    wire = encode_media(files=[File(content=b"abc", filename="a.txt")])
    damage(wire)
    with worker_managed_execution("r", "w", 1):
        with pytest.raises(InputCheckError):
            _harness._execution(agent, "hello", {"media": wire, "run_id": "r"})
    # Outside a queue worker the same wire is an ordinary caller error, not a replayed ticket.
    with pytest.raises(ValueError):
        _harness._execution(agent, "hello", {"media": wire, "run_id": "r"})


NOT_A_WIRE_LIST = ["oops", 5, True, {"images": ["x"]}, "", 0, False, {}]


@pytest.mark.parametrize("stored", NOT_A_WIRE_LIST, ids=repr)
def test_a_stored_value_that_is_not_a_wire_list_is_a_permanent_input_failure_for_the_worker(stored):
    # A ticket only ever stores the wire list, so any other stored value (including a falsy one that would otherwise
    # read as "no attachments" and run the turn without them) is damage that a retry cannot cure.
    agent = _agent()
    with worker_managed_execution("r", "w", 1):
        with pytest.raises(InputCheckError):
            _harness._execution(agent, "hello", {"media": stored, "run_id": "r"})


@pytest.mark.parametrize("stored", ["oops", 5, True, {"images": ["x"]}], ids=repr)
def test_the_same_values_stay_an_ordinary_caller_error_outside_a_queue_worker(stored):
    with pytest.raises(ValueError):
        _harness._execution(_agent(), "hello", {"media": stored, "run_id": "r"})


@pytest.mark.parametrize("stored", [None, []], ids=repr)
def test_null_and_empty_stored_media_are_text_only_for_the_worker(stored):
    with worker_managed_execution("r", "w", 1):
        execution = _harness._execution(_agent(), "hello", {"media": stored, "run_id": "r"})
    assert "images" not in execution and "files" not in execution


@pytest.mark.asyncio
@pytest.mark.parametrize("row_exists", [True, False])
async def test_the_pending_row_hook_does_not_raise_for_a_ticket_that_cannot_be_replayed(monkeypatch, row_exists):
    from types import SimpleNamespace

    agent = _agent()
    wire = encode_media(files=[File(content=b"abc", filename="a.txt")])
    wire[0]["name"] = "../escape"
    store = _Store()
    accepted = object()

    async def aget_run_output(run_id, session_id, user_id=None):
        return accepted if row_exists else None

    monkeypatch.setattr(agent, "aget_run_output", aget_run_output)
    monkeypatch.setattr(_harness, "coordinator", lambda _: SimpleNamespace(store=store))
    result = await _harness.aprepare_pending_run(agent, "r", "s", None, "hello", wire)
    if row_exists:
        # The row the accepted request wrote is left alone; rewriting it would be refused as a different input.
        assert result is accepted and store.prepared == []
    else:
        # No row to fail onto: a text-only one gives the failure a run to land on.
        assert result.input.input_content == "hello" and not result.input.files and len(store.prepared) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image",
    [
        Image(content=b"\x89PNG\r\n\x1a\nfixture"),  # no format: taken from the byte signature
        Image(content=b"\xff\xd8\xff\xe0fixture", mime_type="image/jpeg"),
        Image(content=b"GIF89afixture", format="gif"),
    ],
    ids=["png-signature", "jpeg-mime-only", "gif-format"],
)
async def test_the_pending_row_matches_the_coordinators_input_for_images_given_without_a_format(monkeypatch, image):
    # The image's wire name is derived from its format, so re-encoding the rebuilt image at claim time must give the
    # same wire the ticket holds; otherwise the store would refuse the claim as a different input.
    from types import SimpleNamespace

    from agno.run.agent import RunInput

    agent = _agent()
    wire = _harness.submission(agent, "hello", {"media": {"images": [image]}})["media"]
    store = _Store()
    monkeypatch.setattr(_harness, "coordinator", lambda _: SimpleNamespace(store=store))
    pending = await _harness.aprepare_pending_run(agent, "r", "s", None, "hello", wire)
    rebuilt = decode_media(wire)
    claimed = RunInput(input_content="hello", **decode_media(encode_media(images=rebuilt["images"])))
    assert encode_media(images=rebuilt["images"]) == wire
    assert pending.input.to_dict() == claimed.to_dict()
