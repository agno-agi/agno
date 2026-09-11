"""Workflow media-storage offload tests (LocalMediaStorage + real SQLite)."""

import copy
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from agno.db.base import BaseDb
from agno.db.sqlite import SqliteDb
from agno.media import File, Image
from agno.media.reference import MediaReference
from agno.media.storage.local import LocalMediaStorage
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def _echo_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content="processed", images=step_input.images or [])


def _image_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content="rendered", images=[Image(content=b"\x89PNG-fake" * 4000, id="nested-img")])


def _max_str_len(obj) -> int:
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return max([0] + [_max_str_len(v) for v in obj.values()])
    if isinstance(obj, list):
        return max([0] + [_max_str_len(v) for v in obj])
    return 0


class CountingLocalStorage(LocalMediaStorage):
    """LocalMediaStorage that records every upload it is asked to perform."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uploads: list = []

    def upload(self, media_id, content, **kwargs):
        key = super().upload(media_id, content, **kwargs)
        self.uploads.append(key)
        return key


class DurableUrlLocalStorage(LocalMediaStorage):
    """LocalMediaStorage that addresses a key with a durable link, as a public bucket or a CDN does."""

    def get_url(self, storage_key: str, *, expires_in=None) -> str:
        return f"https://cdn.example.com/media/{storage_key}"


class UnportedSqliteDb(SqliteDb):
    """SQLite adapter as it looks before the runs-table port: no upsert_run of its own.

    Stands in for ValkeyDb, which raises NotImplementedError from the base class and keeps
    every run on the session row via a bare ``Session.to_dict()`` — recorded here so the
    test can read what would have been written.
    """

    upsert_run = BaseDb.upsert_run

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_rows: dict = {}

    def upsert_session(self, session, deserialize=True):
        self.session_rows[session.session_id] = session.to_dict()
        return super().upsert_session(session, deserialize=deserialize)


class PortedSqliteDb(UnportedSqliteDb):
    """The same adapter once it gains a runs store."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_rows: dict = {}

    def upsert_run(self, run, session_id, user_id=None, run_index=None):  # type: ignore[override]
        self.run_rows[run.run_id] = run.to_dict()


def test_workflow_offloads_media_and_keeps_db_small():
    with tempfile.TemporaryDirectory() as tmp:
        media_dir = f"{tmp}/media"
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[_echo_step],
            media_storage=LocalMediaStorage(base_path=media_dir),
            store_media=True,
        )

        img_bytes = b"\x89PNG-fake" * 4000  # ~36 KB -> obvious if base64-inlined
        img = Image(content=img_bytes, id="wf-img", mime_type="image/png")
        out = wf.run(input="hi", images=[img], session_id="s1")

        assert str(out.status) == "RunStatus.completed"
        # caller's input image is not mutated by offload
        assert img.content == img_bytes
        # object offloaded to disk
        offloaded = [f for f in Path(media_dir).iterdir() if not f.name.endswith(".meta.json")]
        assert len(offloaded) >= 1

        # persisted run rows carry a reference, not a base64 blob (runs live in
        # the runs table since the sessions-table denormalization)
        con = sqlite3.connect(f"{tmp}/wf.db")
        rows = con.execute("SELECT run_data FROM wf_sessions_runs WHERE session_id='s1'").fetchall()
        con.close()
        assert rows
        assert any("media_reference" in row[0] for row in rows)
        for (run_data,) in rows:
            assert _max_str_len(json.loads(run_data)) < 5000  # no base64 image inline


def _container_steps():
    """Every step type that wraps its children in a container StepOutput."""
    return {
        "loop": Loop(
            steps=[Step(name="l1", executor=_image_step)],
            max_iterations=1,
            end_condition=lambda outputs: True,
            name="lp",
        ),
        "condition": Condition(
            evaluator=lambda step_input: True,
            steps=[Step(name="c1", executor=_image_step)],
            name="cond",
        ),
        "router": Router(
            selector=lambda step_input: [Step(name="r1", executor=_image_step)],
            choices=[Step(name="r1", executor=_image_step)],
            name="rt",
        ),
        "parallel": Parallel(
            Step(name="p1", executor=_image_step),
            Step(name="p2", executor=_image_step),
            name="par",
        ),
    }


@pytest.mark.parametrize("container", list(_container_steps()))
def test_workflow_offloads_media_nested_in_container_steps(container):
    """Media produced inside Loop/Condition/Router/Parallel hangs off StepOutput.steps."""
    step = _container_steps()[container]
    with tempfile.TemporaryDirectory() as tmp:
        media_dir = f"{tmp}/media"
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[step],
            media_storage=LocalMediaStorage(base_path=media_dir),
        )
        wf.run(input="hi", session_id="s1")

        con = sqlite3.connect(f"{tmp}/wf.db")
        rows = con.execute("SELECT run_data FROM wf_sessions_runs WHERE session_id='s1'").fetchall()
        con.close()
        assert rows
        for (run_data,) in rows:
            assert _max_str_len(json.loads(run_data)) < 5000
        assert "media_reference" in rows[0][0]


@pytest.mark.parametrize("container", list(_container_steps()))
def test_workflow_scrubs_media_nested_in_container_steps(container):
    """store_media=False must drop nested media too, not just the top-level step outputs."""
    step = _container_steps()[container]
    with tempfile.TemporaryDirectory() as tmp:
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[step],
            store_media=False,
        )
        out = wf.run(input="hi", session_id="s1")

        con = sqlite3.connect(f"{tmp}/wf.db")
        rows = con.execute("SELECT run_data FROM wf_sessions_runs WHERE session_id='s1'").fetchall()
        con.close()
        assert rows
        for (run_data,) in rows:
            assert _max_str_len(json.loads(run_data)) < 5000
        # the run handed back to the caller still carries its media
        assert out.step_results


def test_sync_workflow_run_rejects_an_async_backend():
    """The persist is guarded, so the offload's own raise would reach the caller as a warning
    and a run whose media stayed inline. run() reports the mismatch up front instead."""
    from agno.media.storage.local import AsyncLocalMediaStorage

    with tempfile.TemporaryDirectory() as tmp:
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[Step(name="s1", executor=_image_step)],
            media_storage=AsyncLocalMediaStorage(base_path=f"{tmp}/media"),
        )
        with pytest.raises(ValueError, match="Cannot use sync run\\(\\) with an AsyncMediaStorage"):
            wf.run(input="hi", session_id="s1")

        with pytest.raises(ValueError, match="Cannot use sync continue_run\\(\\) with an AsyncMediaStorage"):
            wf.continue_run(run_id="r1", session_id="s1")


def test_sync_workflow_run_allows_an_async_backend_when_store_media_is_off():
    """With store_media off nothing is offloaded, so the backend is never reached and the
    configuration is not a mismatch."""
    from agno.media.storage.local import AsyncLocalMediaStorage

    with tempfile.TemporaryDirectory() as tmp:
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[Step(name="s1", executor=_image_step)],
            media_storage=AsyncLocalMediaStorage(base_path=f"{tmp}/media"),
            store_media=False,
        )
        assert wf.run(input="hi", session_id="s1").step_results


async def test_async_workflow_offloads_with_async_storage_on_sync_db():
    """arun() + AsyncMediaStorage must still offload when the database adapter is synchronous."""
    from agno.media.storage.local import AsyncLocalMediaStorage

    with tempfile.TemporaryDirectory() as tmp:
        media_dir = f"{tmp}/media"
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[Step(name="s1", executor=_image_step)],
            media_storage=AsyncLocalMediaStorage(base_path=media_dir),
        )
        await wf.arun(input="hi", session_id="s1")

        assert [f for f in Path(media_dir).iterdir() if not f.name.endswith(".meta.json")]
        con = sqlite3.connect(f"{tmp}/wf.db")
        rows = con.execute("SELECT run_data FROM wf_sessions_runs WHERE session_id='s1'").fetchall()
        con.close()
        assert rows
        assert "media_reference" in rows[0][0]
        for (run_data,) in rows:
            assert _max_str_len(json.loads(run_data)) < 5000


def _turn_image_step(step_input: StepInput) -> StepOutput:
    """One distinct image per turn, so a repeat upload of the same object is visible."""
    turn = str(step_input.input)
    return StepOutput(content="ok", images=[Image(content=b"\x89PNG-turn" * 4000 + turn.encode(), id=f"img-{turn}")])


def test_workflow_uploads_each_media_object_once():
    """save_session and save_run both offloaded, so every object was uploaded twice."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = CountingLocalStorage(base_path=f"{tmp}/media")
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[Step(name="s1", executor=_turn_image_step)],
            media_storage=storage,
        )
        for turn in range(1, 6):
            wf.run(input=str(turn), session_id="s1")

        assert len(set(storage.uploads)) == 5
        assert len(storage.uploads) == 5


def test_workflow_uploads_once_on_an_adapter_without_a_runs_table():
    """The un-ported adapter needs the session pass, and only the session pass.

    Its upsert_run raises NotImplementedError, so the per-run offload would upload bytes
    that no row ever references.
    """
    with tempfile.TemporaryDirectory() as tmp:
        storage = CountingLocalStorage(base_path=f"{tmp}/media")
        db = UnportedSqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions")
        wf = Workflow(
            name="wf",
            id="wf",
            db=db,
            steps=[Step(name="s1", executor=_turn_image_step)],
            media_storage=storage,
        )
        for turn in range(1, 6):
            wf.run(input=str(turn), session_id="s1")

        assert len(storage.uploads) == 5
        # the runs the session row carries are the offloaded copies, not base64
        row = db.session_rows["s1"]
        assert row["runs"]
        assert _max_str_len(row) < 5000
        assert "media_reference" in json.dumps(row)

        # no runs table was ever written, so the per-run offload would have been wasted
        con = sqlite3.connect(f"{tmp}/wf.db")
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        con.close()
        assert "wf_sessions_runs" not in tables


def test_session_pass_follows_upsert_run_support(monkeypatch):
    """An adapter that gains upsert_run flips to the per-run pass with no further change."""
    calls = []
    original = Workflow._offload_workflow_session_media

    def counted(self, session):
        calls.append(type(self.db).__name__)
        return original(self, session)

    monkeypatch.setattr(Workflow, "_offload_workflow_session_media", counted)

    with tempfile.TemporaryDirectory() as tmp:

        def build(db, media_dir):
            return Workflow(
                name="wf",
                id="wf",
                db=db,
                steps=[Step(name="s1", executor=_turn_image_step)],
                media_storage=CountingLocalStorage(base_path=f"{tmp}/{media_dir}"),
            )

        unported = build(UnportedSqliteDb(db_file=f"{tmp}/a.db", session_table="a_sessions"), "media_a")
        assert unported._db_persists_runs_separately() is False
        unported.run(input="1", session_id="s1")
        assert calls == ["UnportedSqliteDb"]

        ported_db = PortedSqliteDb(db_file=f"{tmp}/b.db", session_table="b_sessions")
        ported = build(ported_db, "media_b")
        assert ported._db_persists_runs_separately() is True
        ported.run(input="1", session_id="s2")
        assert calls == ["UnportedSqliteDb"]
        assert len(ported_db.run_rows) == 1


async def test_async_workflow_uploads_each_media_object_once():
    """Same double upload on the arun() path, via asave_session + asave_run."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = CountingLocalStorage(base_path=f"{tmp}/media")
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[Step(name="s1", executor=_turn_image_step)],
            media_storage=storage,
        )
        for turn in range(1, 4):
            await wf.arun(input=str(turn), session_id="s1")

        assert len(storage.uploads) == 3


def test_image_artifact_conversion_keeps_the_storage_key_stable():
    """Dropping id/mime_type on conversion re-stored identical bytes under a new uuid each run."""
    from agno.utils.media_offload import _offload_single_media

    with tempfile.TemporaryDirectory() as tmp:
        storage = CountingLocalStorage(base_path=f"{tmp}/media")
        step = Step(name="s1", executor=_echo_step)
        artifact = Image(content=b"\x89PNG-artifact" * 100, id="artifact-img", mime_type="image/png")

        for _ in range(5):
            converted = step._convert_image_artifacts_to_images([artifact])[0]
            assert converted.id == artifact.id
            assert converted.mime_type == artifact.mime_type
            _offload_single_media(converted, storage, "s1", "image")

        assert len(set(storage.uploads)) == 1


def test_video_and_audio_artifact_conversion_keeps_ids():
    """Same conversion loss on the video and audio paths."""
    from agno.media import Audio, Video

    step = Step(name="s1", executor=_echo_step)
    video = Video(content=b"video-bytes", id="vid-1", format="mp4", mime_type="video/mp4")
    audio = Audio(content=b"audio-bytes", id="aud-1", format="mp3", mime_type="audio/mpeg")

    converted_video = step._convert_video_artifacts_to_videos([video])[0]
    assert (converted_video.id, converted_video.mime_type, converted_video.format) == ("vid-1", "video/mp4", "mp4")

    converted_audio = step._convert_audio_artifacts_to_audio([audio])[0]
    assert (converted_audio.id, converted_audio.mime_type, converted_audio.format) == ("aud-1", "audio/mpeg", "mp3")


def test_workflow_step_conversion_keeps_offloaded_media():
    """An offloaded image has no url, filepath or content — only its reference. The artifact
    converters checked those three fields and dropped anything else, so a step handed media the
    backend was holding perfectly well passed nothing to its executor."""
    step = Step(name="s", executor=lambda step_input: "ok")
    ref = MediaReference(media_id="img-1", storage_key="agno/img-1-abc.png", storage_backend="local")
    offloaded = Image(media_reference=ref, id="img-1", mime_type="image/png")
    assert offloaded.url is None and offloaded.filepath is None and offloaded.content is None

    converted = step._convert_image_artifacts_to_images([offloaded])

    assert len(converted) == 1
    assert converted[0].media_reference is ref
    assert converted[0].id == "img-1"


def test_step_media_storage_falls_back_to_the_workflow_but_never_overrides():
    """A workflow's backend covers a step whose executor has none — the same parent-covers-child
    rule the write side already follows. An executor with its own backend keeps it: redirecting
    its objects to the parent's bucket would be worse than the gap this closes."""
    from agno.agent.agent import Agent

    with tempfile.TemporaryDirectory() as tmpdir:
        parent_storage = LocalMediaStorage(base_path=os.path.join(tmpdir, "parent"))
        own_storage = LocalMediaStorage(base_path=os.path.join(tmpdir, "own"))

        bare = Step(name="bare", executor=Agent(id="a"))
        assert bare._resolve_media_storage(parent_storage) is parent_storage

        configured = Step(name="configured", executor=Agent(id="b", media_storage=own_storage))
        assert configured._resolve_media_storage(parent_storage) is own_storage
        assert configured._resolve_media_storage(None) is own_storage

        assert bare._resolve_media_storage(None) is None


def test_step_conversion_reads_offloaded_bytes_back():
    """Passing the reference through is not enough: on a private bucket it carries no url, so
    the executor would receive an image with nothing in it. The resolved backend reads the
    bytes back for the model turn while the stored row keeps only the pointer."""
    from agno.agent.agent import Agent
    from agno.run.agent import RunOutput
    from agno.utils.media_offload import offload_run_media

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        img = Image(id="i1", mime_type="image/png", content=b"STORED-BYTES")
        run = RunOutput(run_id="r1", images=[img])
        offload_run_media(run, storage, "s1")

        offloaded = run.images[0]
        assert offloaded.content is None and offloaded.url is None

        step = Step(name="s", executor=Agent(id="a"))
        step_input = StepInput(input="hi", images=[offloaded])
        step._rehydrate_step_input_media(step_input, storage)
        converted = step._convert_image_artifacts_to_images(step_input.images)

        assert converted[0].content == b"STORED-BYTES"
        assert converted[0].media_reference is offloaded.media_reference


def test_step_conversion_rejects_an_async_backend():
    """Rehydration is sync here and reads through a blocking download an AsyncMediaStorage does
    not have. Reporting the mismatch is the point: warning past it would hand the executor an
    image with nothing in it."""
    from agno.agent.agent import Agent
    from agno.media.storage.local import AsyncLocalMediaStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        ref = MediaReference(media_id="i1", storage_key="i1.png", storage_backend="local")
        offloaded = Image(id="i1", mime_type="image/png", media_reference=ref)

        step = Step(name="s", executor=Agent(id="a"))
        step_input = StepInput(input="hi", images=[offloaded])
        with pytest.raises(ValueError, match="Cannot use sync run\\(\\) with an AsyncMediaStorage"):
            step._rehydrate_step_input_media(step_input, AsyncLocalMediaStorage(base_path=tmpdir))


async def test_async_step_execution_reads_offloaded_bytes_back_from_an_async_backend():
    """The async twin of the raise above: arun() awaits the read on its own loop before the
    sync converters run in a thread, so an async backend's media still reaches the executor."""
    from agno.agent.agent import Agent
    from agno.media.storage.local import AsyncLocalMediaStorage
    from agno.run.agent import RunOutput
    from agno.utils.media_offload import aoffload_run_media

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = AsyncLocalMediaStorage(base_path=tmpdir)
        img = Image(id="i1", mime_type="image/png", content=b"ASYNC-STORED-BYTES")
        await aoffload_run_media(RunOutput(run_id="r1", images=[img]), storage, "s1")

        offloaded = copy.deepcopy(img)
        assert offloaded.content is None and offloaded.url is None

        step = Step(name="s", executor=Agent(id="a"))
        step_input = StepInput(input="hi", images=[offloaded])
        await step._arehydrate_step_input_media(step_input, storage)

        # The async backend is read here, so the sync converters only convert.
        converted = step._convert_image_artifacts_to_images(step_input.images)
        assert converted[0].content == b"ASYNC-STORED-BYTES"
        assert converted[0].media_reference is offloaded.media_reference


async def test_async_step_execution_rehydrates_a_sync_backend():
    """A sync backend is read back too; _arehydrate keeps its blocking download off the loop."""
    from agno.agent.agent import Agent
    from agno.run.agent import RunOutput
    from agno.utils.media_offload import offload_run_media

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        img = Image(id="i1", mime_type="image/png", content=b"SYNC-STORED-BYTES")
        offload_run_media(RunOutput(run_id="r1", images=[img]), storage, "s1")

        offloaded = copy.deepcopy(img)
        step = Step(name="s", executor=Agent(id="a"))
        step_input = StepInput(input="hi", images=[offloaded])

        await step._arehydrate_step_input_media(step_input, storage)

        assert offloaded.content == b"SYNC-STORED-BYTES"


def test_workflow_no_media_storage_unchanged():
    """Without media_storage, behavior is unchanged (media stays inline)."""
    with tempfile.TemporaryDirectory() as tmp:
        wf = Workflow(
            name="wf2",
            id="wf2",
            db=SqliteDb(db_file=f"{tmp}/wf2.db", session_table="wf2_sessions"),
            steps=[_echo_step],
        )
        img = Image(content=b"\x89PNG-bytes" * 100, id="i", mime_type="image/png")
        out = wf.run(input="hi", images=[img], session_id="s1")
        assert str(out.status) == "RunStatus.completed"


def test_offload_reaches_media_parked_on_step_requirements():
    """A paused HITL run keeps the prepared input and the output under review on
    ``step_requirements``, which is where a row sits for as long as the human takes."""
    from agno.run.workflow import WorkflowRunOutput
    from agno.utils.media_offload import offload_workflow_media
    from agno.workflow.types import StepRequirement

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        parked_input = Image(content=b"INPUT-BYTES", id="req-in", mime_type="image/png")
        parked_output = File(content=b"OUTPUT-BYTES", id="req-out", mime_type="text/plain")
        nested = StepOutput(step_name="child", files=[File(content=b"NESTED", id="req-nested")])

        run = WorkflowRunOutput(run_id="r", workflow_id="w")
        run.step_requirements = [
            StepRequirement(
                step_id="s1",
                step_input=StepInput(input="go", images=[parked_input]),
                step_output=StepOutput(step_name="under-review", files=[parked_output], steps=[nested]),
            )
        ]

        offload_workflow_media(run, storage, "sess")

        for media in (parked_input, parked_output, nested.files[0]):
            assert media.media_reference is not None, f"{media.id} was left inline"
            assert media.content is None
            assert storage.exists(media.media_reference.storage_key)


async def test_errored_stream_persists_with_an_async_backend_on_a_sync_db():
    """The sync branch raised inside save_run and the guard swallowed it, losing the run."""
    from agno.media.storage.local import AsyncLocalMediaStorage
    from agno.run.base import RunStatus
    from agno.run.workflow import WorkflowRunOutput

    with tempfile.TemporaryDirectory() as tmp:
        wf = Workflow(
            name="wf",
            id="wf",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[Step(name="s1", executor=_image_step)],
            media_storage=AsyncLocalMediaStorage(base_path=f"{tmp}/media"),
        )
        session = wf.read_or_create_session(session_id="s1", user_id=None)
        run = WorkflowRunOutput(run_id="r1", workflow_id="wf", session_id="s1", status=RunStatus.error)

        await wf._apersist_errored_run_stream(session=session, run=run)

        stored = wf.get_run(run_id="r1", session_id="s1")
        assert stored is not None
        assert stored.status == RunStatus.error


def test_nested_workflow_reads_the_parents_offloaded_media():
    """workflow_media_storage was threaded through the nested executors and never used, so an
    inner step received a reference with no bytes behind it."""
    from agno.utils.media_offload import _offload_single_media

    seen: dict = {}

    def inspect(step_input: StepInput) -> StepOutput:
        image = (step_input.images or [None])[0]
        doc = (step_input.files or [None])[0]
        seen["content"] = image.content if image is not None else None
        seen["file_content"] = doc.content if doc is not None else None
        return StepOutput(content="ok")

    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalMediaStorage(base_path=f"{tmp}/media")
        inner = Workflow(name="inner", id="inner", steps=[Step(name="inspect", executor=inspect)])
        outer = Workflow(
            name="outer",
            id="outer",
            db=SqliteDb(db_file=f"{tmp}/wf.db", session_table="wf_sessions"),
            steps=[inner],
            media_storage=storage,
        )

        offloaded = Image(content=b"NESTED-BYTES", id="img", mime_type="image/png")
        _offload_single_media(offloaded, storage, "s1", "image")
        doc = File(content=b"NESTED-FILE", id="doc", mime_type="text/plain", filename="r.txt")
        _offload_single_media(doc, storage, "s1", "file")
        assert offloaded.content is None and doc.content is None

        outer.run(input="hi", images=[offloaded], files=[doc], session_id="s1")

        assert seen["content"] == b"NESTED-BYTES"
        # files are forwarded across the boundary too, so they have to be readable as well
        assert seen["file_content"] == b"NESTED-FILE"


def test_a_function_step_reads_offloaded_media():
    """A function step receives offloaded media with its bytes read back, not content=None."""
    from agno.utils.media_offload import _offload_single_media

    seen: dict = {}

    def probe(step_input: StepInput) -> StepOutput:
        seen["image"] = (step_input.images or [None])[0]
        seen["file"] = (step_input.files or [None])[0]
        return StepOutput(content="ok")

    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalMediaStorage(base_path=f"{tmp}/media")
        img = Image(content=b"FN-IMAGE", id="i", mime_type="image/png")
        doc = File(content=b"FN-FILE", id="d", mime_type="text/plain", filename="r.txt")
        _offload_single_media(img, storage, "s1", "image")
        _offload_single_media(doc, storage, "s1", "file")

        wf = Workflow(
            name="w",
            id="w",
            db=SqliteDb(db_file=f"{tmp}/w.db", session_table="w_sessions"),
            steps=[Step(name="probe", executor=probe)],
            media_storage=storage,
        )
        wf.run(input="hi", images=[img], files=[doc], session_id="s1")

        assert seen["image"].content == b"FN-IMAGE"
        assert seen["file"].content == b"FN-FILE"


@pytest.mark.parametrize("nested", [False, True], ids=["top_level", "nested_workflow"])
def test_a_function_step_reads_offloaded_media_behind_a_durable_url(nested):
    """A backend whose get_url is a durable link leaves that link on the offloaded media, and the
    function step still receives the bytes."""
    from agno.utils.media_offload import _offload_single_media

    seen: dict = {}

    def probe(step_input: StepInput) -> StepOutput:
        seen["image"] = (step_input.images or [None])[0]
        return StepOutput(content="ok")

    with tempfile.TemporaryDirectory() as tmp:
        storage = DurableUrlLocalStorage(base_path=f"{tmp}/media")
        img = Image(content=b"URL-BACKED", id="i", mime_type="image/png")
        _offload_single_media(img, storage, "s1", "image")
        assert img.url and img.content is None

        leaf = Step(name="probe", executor=probe)
        steps = [Workflow(name="inner", id="inner", steps=[leaf])] if nested else [leaf]
        wf = Workflow(
            name="w",
            id="w",
            db=SqliteDb(db_file=f"{tmp}/w.db", session_table="w_sessions"),
            steps=steps,
            media_storage=storage,
        )
        wf.run(input="hi", images=[img], session_id="s1")

        assert seen["image"].content == b"URL-BACKED"
