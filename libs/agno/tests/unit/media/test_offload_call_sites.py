"""Tests for the call sites that must offload media before a row is written.

Every persist an agent, team or workflow makes has to hand its media to storage
first — the terminal write, the mid-run checkpoints, the background PENDING and
RUNNING rows, and a team's member run rows. A call site that skips it writes the
bytes into the database inline, which is the whole thing offloading exists to avoid.
"""

import asyncio
import copy
import os
import tempfile
from pathlib import Path

import pytest

from agno.media import File, Image
from agno.media.reference import MediaReference
from agno.media.storage.local import LocalMediaStorage
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.utils.agent import scrub_media_from_message
from agno.utils.media_offload import offload_run_media


def test_idless_files_get_distinct_keys():
    """Two id-less Files must not overwrite each other on the same storage key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        f1 = File(content=b"REPORT ALPHA", mime_type="text/plain")
        f2 = File(content=b"REPORT BRAVO", mime_type="text/plain")
        offload_run_media(RunOutput(run_id="r", files=[f1, f2]), storage, "s", "r")

        assert f1.media_reference.storage_key != f2.media_reference.storage_key
        assert storage.download(f1.media_reference.storage_key) == b"REPORT ALPHA"
        assert storage.download(f2.media_reference.storage_key) == b"REPORT BRAVO"


def test_idless_media_gets_id_assigned():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        f = File(content=b"data", mime_type="text/plain")
        offload_run_media(RunOutput(run_id="r", files=[f]), storage, "s", "r")
        assert f.id is not None


def test_media_reference_rebuilt_from_dict():
    """to_dict()/model_validate round-trip yields a MediaReference object, not a dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        img = Image(content=b"hello", id="i1", mime_type="image/png")
        offload_run_media(RunOutput(run_id="r", images=[img]), storage, "s", "r")

        rebuilt = Image.model_validate(img.to_dict())
        assert isinstance(rebuilt.media_reference, MediaReference)
        assert rebuilt.media_reference.storage_key == img.media_reference.storage_key


def test_get_content_bytes_never_reads_a_file_uri():
    """A file:// URL is not a content source: every url reaching _bytes_from_url is
    caller-supplied, so reading one would be an arbitrary-file-read primitive. Local media is
    rehydrated through storage.download() instead."""
    with tempfile.TemporaryDirectory() as tmpdir:
        secret = Path(tmpdir) / "secret.txt"
        secret.write_bytes(b"SECRET")
        target = secret.as_uri()

        for kwargs in ({"url": target}, {"media_reference": _file_uri_ref(target)}):
            img = Image(id="i1", **kwargs)
            with pytest.raises(Exception) as sync_err:
                img.get_content_bytes()
            assert b"SECRET" not in str(sync_err.value).encode()
            with pytest.raises(Exception):
                asyncio.run(img.aget_content_bytes())

        # The offloaded bytes are still retrievable, just through the backend.
        storage = LocalMediaStorage(base_path=tmpdir)
        img = Image(content=b"png-bytes", id="i2", mime_type="image/png")
        offload_run_media(RunOutput(run_id="r", images=[img]), storage, "s", "r")
        rebuilt = Image.model_validate(img.to_dict())
        assert storage.download(rebuilt.media_reference.storage_key) == b"png-bytes"


def _file_uri_ref(uri: str) -> dict:
    return {"media_id": "i1", "storage_key": "k.png", "storage_backend": "local", "url": uri}


def test_external_file_kept_when_scrubbing_with_references():
    """Provider-managed (external) files must survive scrub even without a reference."""
    msg = Message(role="user", content="x")
    # No content bytes: the external handle alone must be what keeps the file.
    msg.files = [File(external={"provider": "gemini", "uri": "files/abc"})]
    scrub_media_from_message(msg, keep_references=True)

    assert msg.files is not None
    assert len(msg.files) == 1
    assert msg.files[0].external is not None


def test_same_id_distinct_content_no_overwrite():
    """Reusing an explicit id with different content must not overwrite (content-addressed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        a = Image(content=b"AAAA", id="dup", mime_type="image/png")
        b = Image(content=b"BBBB", id="dup", mime_type="image/png")
        offload_run_media(RunOutput(run_id="r1", images=[a]), storage, "s", "r1")
        offload_run_media(RunOutput(run_id="r2", images=[b]), storage, "s", "r2")

        assert a.media_reference.storage_key != b.media_reference.storage_key
        assert storage.download(a.media_reference.storage_key) == b"AAAA"
        assert storage.download(b.media_reference.storage_key) == b"BBBB"


def test_per_item_offload_failure_kept_inline():
    """If one item fails to offload, it is kept inline (not silently dropped)."""
    from agno.media.storage.base import MediaStorage
    from agno.utils.agent import scrub_media_from_run_output

    class FlakyStorage(MediaStorage):
        backend_name = "flaky"

        def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None):
            if b"FAIL" in content:
                raise RuntimeError("simulated outage")
            return f"{media_id}.bin"

        def download(self, k):
            return b""

        def get_url(self, k, *, expires_in=3600):
            return "http://x/" + k

        def delete(self, k):
            return True

        def exists(self, k):
            return True

    good = Image(content=b"GOOD", id="g", mime_type="image/png")
    bad = Image(content=b"FAIL", id="b", mime_type="image/png")
    run = RunOutput(run_id="r", messages=[Message(role="user", content="x", images=[good, bad])])
    offload_run_media(run, FlakyStorage(), "s", "r")
    scrub_media_from_run_output(run, keep_references=True)

    ids = {i.id for i in (run.messages[0].images or [])}
    assert ids == {"g", "b"}  # failed item kept inline, not lost


def test_async_storage_on_sync_path_keeps_media_inline():
    """AsyncMediaStorage on a sync run (offload skipped) keeps media inline, not dropped."""
    from agno.agent._run import scrub_run_output_for_storage
    from agno.agent.agent import Agent
    from agno.media.storage.local import AsyncLocalMediaStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = Agent(media_storage=AsyncLocalMediaStorage(base_path=tmpdir), store_media=True)
        run = RunOutput(run_id="r", images=[Image(content=b"IMG", id="i", mime_type="image/png")])
        scrub_run_output_for_storage(agent, run)  # sync path skips offload, must not drop
        assert run.images is not None and len(run.images) == 1


def test_nested_team_keeps_referenced_leaf_media():
    """Leaf media offloaded by the root team must survive nested member scrub."""
    from agno.agent.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.run.team import TeamRunOutput
    from agno.team.team import Team

    leaf = Agent(name="leaf", id="leaf", model=OpenAIResponses(id="gpt-5.5"), store_media=False)
    sub = Team(name="sub", id="sub", members=[leaf], model=OpenAIResponses(id="gpt-5.5"))
    top = Team(
        name="top",
        id="top",
        members=[sub],
        model=OpenAIResponses(id="gpt-5.5"),
        media_storage=LocalMediaStorage(base_path=tempfile.mkdtemp()),
    )

    ref = MediaReference(media_id="leafimg", storage_key="leafimg.png", storage_backend="local", url="file:///x")
    leaf_img = Image(url="file:///x", media_reference=ref, id="leafimg")
    leaf_run = RunOutput(run_id="lr", agent_id="leaf", images=[leaf_img])
    sub_run = TeamRunOutput(run_id="sr", team_id="sub", member_responses=[leaf_run])

    top._scrub_member_responses([sub_run])

    assert leaf_run.images is not None
    assert len(leaf_run.images) == 1
    assert leaf_run.images[0].media_reference is not None


def test_team_save_session_offloads_nothing():
    """Team.save_session offloads sibling runs on deep copies, so the caller's reused
    input media (shared with those runs) keeps its content bytes and stays un-referenced."""
    from agno.db.sqlite import SqliteDb
    from agno.run.agent import RunInput
    from agno.run.team import TeamRunOutput
    from agno.session.team import TeamSession
    from agno.team.team import Team

    with tempfile.TemporaryDirectory() as tmpdir:
        team = Team(
            name="t",
            id="t",
            members=[],
            db=SqliteDb(db_file=os.path.join(tmpdir, "t.db")),
            media_storage=LocalMediaStorage(base_path=os.path.join(tmpdir, "media")),
            store_media=True,
        )
        img = Image(id="shared", mime_type="image/png", content=b"ORIGINAL")
        member_run = RunOutput(run_id="m1", input=RunInput(input_content="hi", images=[img]))
        session = TeamSession(session_id="s1", team_id="t", runs=[TeamRunOutput(run_id="t1"), member_run])

        team.save_session(session=session)

        # Caller's image is untouched: bytes preserved, no reference attached.
        assert img.content == b"ORIGINAL"
        assert getattr(img, "media_reference", None) is None
        # And nothing was uploaded: _cleanup_and_store puts the offloaded copy on the session
        # before the row is written, so an offload here would only re-upload it.
        media_dir = Path(tmpdir) / "media"
        assert not media_dir.exists() or not [f for f in media_dir.rglob("*") if f.is_file()]


def test_refresh_downloads_bytes_when_url_is_empty():
    """A backend that can't produce a usable URL (empty string, e.g. GCS with non-signing
    credentials) must trigger a byte re-read so the model still receives the media."""

    class _EmptyUrlStorage:
        backend_name = "gcs"

        def get_url(self, storage_key, *, expires_in=3600):
            return ""

        def download(self, storage_key):
            return b"DOWNLOADED"

    from agno.utils.media_offload import refresh_message_media_urls

    ref = MediaReference(media_id="m", storage_key="m.png", storage_backend="gcs", mime_type="image/png")
    img = Image(id="m", mime_type="image/png", media_reference=ref)
    message = Message(role="user", content="hi", images=[img])

    refresh_message_media_urls(message, _EmptyUrlStorage())

    assert img.content == b"DOWNLOADED"
    assert img.url is None
    assert img.media_reference.url is None


# ---------------------------------------------------------------------------
# Pre-terminal writes: background PENDING/RUNNING rows and mid-run checkpoints
# ---------------------------------------------------------------------------


def _agent_with_storage(tmpdir, **kwargs):
    from agno.agent.agent import Agent
    from agno.db.sqlite import SqliteDb

    return Agent(
        id="a",
        db=SqliteDb(db_file=os.path.join(tmpdir, "a.db")),
        media_storage=LocalMediaStorage(base_path=os.path.join(tmpdir, "media")),
        store_media=True,
        **kwargs,
    )


def _inline_run(run_id="r1"):
    from agno.run.agent import RunInput

    img = Image(id="i1", mime_type="image/png", content=b"INLINE-IMAGE-BYTES")
    return img, RunOutput(run_id=run_id, agent_id="a", input=RunInput(input_content="hi", images=[img]))


def test_checkpoint_row_is_offloaded():
    """A mid-run checkpoint must persist references, not the inline bytes it would
    otherwise park in the DB for the rest of the run."""
    from agno.agent._run import persist_run_in_session
    from agno.session import AgentSession

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _agent_with_storage(tmpdir)
        live_img, run = _inline_run()
        session = AgentSession(session_id="s1", agent_id="a")

        persist_run_in_session(agent, run, session)

        persisted = session.runs[0].input.images[0]
        assert persisted.media_reference is not None
        assert persisted.content is None
        # The live run keeps its bytes — the model turns still to come need them.
        assert live_img.content == b"INLINE-IMAGE-BYTES"
        assert live_img.media_reference is None


def test_acheckpoint_row_is_offloaded():
    """Async variant of the checkpoint offload."""
    from agno.agent._run import apersist_run_in_session
    from agno.session import AgentSession

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _agent_with_storage(tmpdir)
        live_img, run = _inline_run()
        session = AgentSession(session_id="s1", agent_id="a")

        asyncio.run(apersist_run_in_session(agent, run, session))

        persisted = session.runs[0].input.images[0]
        assert persisted.media_reference is not None
        assert persisted.content is None
        assert live_img.content == b"INLINE-IMAGE-BYTES"


def test_team_checkpoint_row_is_offloaded(monkeypatch):
    """Same for a team's mid-run checkpoint. Asserted on the runs-table write: save_session
    offloads the session blob on its own, so only save_run's payload shows this bug."""
    from agno.db.sqlite import SqliteDb
    from agno.run.agent import RunInput
    from agno.run.team import TeamRunOutput
    from agno.session.team import TeamSession
    from agno.team import _session as team_session_mod
    from agno.team.team import Team

    with tempfile.TemporaryDirectory() as tmpdir:
        team = Team(
            id="t",
            members=[],
            db=SqliteDb(db_file=os.path.join(tmpdir, "t.db")),
            media_storage=LocalMediaStorage(base_path=os.path.join(tmpdir, "media")),
            store_media=True,
        )
        img = Image(id="i1", mime_type="image/png", content=b"INLINE-IMAGE-BYTES")
        run = TeamRunOutput(run_id="r1", team_id="t", input=RunInput(input_content="hi", images=[img]))
        session = TeamSession(session_id="s1", team_id="t")

        saved: list = []
        monkeypatch.setattr(team_session_mod, "save_run", lambda team, run, **kwargs: saved.append(run), raising=False)

        from agno.team._run import _persist_team_run_in_session

        _persist_team_run_in_session(team, run, session)

        assert len(saved) == 1
        persisted = saved[0].input.images[0]
        assert persisted.media_reference is not None
        assert persisted.content is None
        assert img.content == b"INLINE-IMAGE-BYTES"


def test_build_offloaded_storage_copy_leaves_original_intact():
    """The helper the pre-terminal writes use returns an offloaded deep copy and never
    touches the live run; it returns None when there is nothing to offload."""
    from agno.agent.agent import Agent
    from agno.utils.agent import build_offloaded_storage_copy

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        agent = Agent(id="a", media_storage=storage, store_media=True)
        img, run = _inline_run()

        copy_ = build_offloaded_storage_copy(agent, run, "s1")
        assert copy_ is not None and copy_ is not run
        assert copy_.input.images[0].media_reference is not None
        assert copy_.input.images[0].content is None
        assert img.content == b"INLINE-IMAGE-BYTES"
        assert storage.download(copy_.input.images[0].media_reference.storage_key) == b"INLINE-IMAGE-BYTES"

        # store_media off, and no storage configured, both mean "nothing to offload".
        assert build_offloaded_storage_copy(Agent(id="b", media_storage=storage, store_media=False), run, "s1") is None
        assert build_offloaded_storage_copy(Agent(id="c"), run, "s1") is None


def test_build_offloaded_storage_copy_rejects_an_async_backend():
    """The pre-terminal writes go through this helper on the sync path, for an agent and for a
    team alike. Its inline fallback is for a storage failure, so the mismatch is raised before
    it and reaches the caller instead of being written off as one more failed upload."""
    from agno.agent.agent import Agent
    from agno.media.storage.local import AsyncLocalMediaStorage
    from agno.team.team import Team
    from agno.utils.agent import build_offloaded_storage_copy

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = AsyncLocalMediaStorage(base_path=tmpdir)
        _, run = _inline_run()

        for entity in (
            Agent(id="a", media_storage=storage, store_media=True),
            Team(id="t", members=[], media_storage=storage, store_media=True),
        ):
            with pytest.raises(ValueError, match="Cannot use sync run\\(\\) with an AsyncMediaStorage"):
                build_offloaded_storage_copy(entity, run, "s1")

        # store_media off means nothing is offloaded, so the backend is never reached.
        assert build_offloaded_storage_copy(Agent(id="b", media_storage=storage, store_media=False), run, "s1") is None


def test_background_pending_row_is_offloaded(monkeypatch):
    """agent.arun(background=True) writes a PENDING row that stands for the whole run —
    and forever if the process dies first — so it must carry references, not base64."""
    from agno.agent import _run as agent_run
    from agno.agent import _session as agent_session_mod
    from agno.agent import _storage as agent_storage
    from agno.run import RunContext
    from agno.session import AgentSession

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = _agent_with_storage(tmpdir)
        live_img, run = _inline_run()
        saved: list = []

        async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id, user_id=user_id)

        async def fake_asave_session(agent, session):
            return None

        async def fake_asave_run(agent, run, session_id=None, user_id=None, run_index=None):
            saved.append(run)

        async def fake_arun(*args, **kwargs):
            return None

        monkeypatch.setattr(agent_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(agent_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr(agent_session_mod, "asave_session", fake_asave_session)
        monkeypatch.setattr(agent_session_mod, "asave_run", fake_asave_run)
        monkeypatch.setattr(agent_run, "_arun", fake_arun)

        async def go():
            await agent_run._arun_background(
                agent,
                run_response=run,
                run_context=RunContext(run_id="r1", session_id="s1"),
                session_id="s1",
            )
            # Let the spawned task write the RUNNING row too.
            await asyncio.sleep(0.05)

        asyncio.run(go())

        assert len(saved) >= 2  # PENDING + RUNNING
        for row in saved:
            persisted = row.input.images[0]
            assert persisted.media_reference is not None
            assert persisted.content is None
        assert saved[1].status.value == "RUNNING"
        # The live run still has its bytes for the model turns to come.
        assert live_img.content == b"INLINE-IMAGE-BYTES"


def test_team_background_pending_row_is_offloaded(monkeypatch):
    """Team background runs write the same PENDING/RUNNING pair."""
    from agno.db.sqlite import SqliteDb
    from agno.run import RunContext
    from agno.run.agent import RunInput
    from agno.run.team import TeamRunOutput
    from agno.session.team import TeamSession
    from agno.team import _run as team_run
    from agno.team import _session as team_session_mod
    from agno.team import _storage as team_storage
    from agno.team.team import Team

    with tempfile.TemporaryDirectory() as tmpdir:
        team = Team(
            id="t",
            members=[],
            db=SqliteDb(db_file=os.path.join(tmpdir, "t.db")),
            media_storage=LocalMediaStorage(base_path=os.path.join(tmpdir, "media")),
            store_media=True,
        )
        img = Image(id="i1", mime_type="image/png", content=b"INLINE-IMAGE-BYTES")
        run = TeamRunOutput(run_id="r1", team_id="t", input=RunInput(input_content="hi", images=[img]))
        saved: list = []

        async def fake_aread_or_create_session(team, session_id=None, user_id=None):
            return TeamSession(session_id=session_id, user_id=user_id, team_id="t")

        async def fake_asave_session(team, session):
            return None

        async def fake_asave_run(team, run, session_id=None, user_id=None, run_index=None):
            saved.append(run)

        async def fake_arun(*args, **kwargs):
            return None

        monkeypatch.setattr(team_storage, "_aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(team_storage, "_update_metadata", lambda team, session=None: None)
        monkeypatch.setattr(team_session_mod, "asave_session", fake_asave_session)
        monkeypatch.setattr(team_session_mod, "asave_run", fake_asave_run)
        monkeypatch.setattr(team_run, "_arun", fake_arun)

        async def go():
            await team_run._arun_background(
                team,
                run_response=run,
                run_context=RunContext(run_id="r1", session_id="s1"),
                session_id="s1",
            )
            await asyncio.sleep(0.05)

        asyncio.run(go())

        assert len(saved) >= 2
        for row in saved:
            persisted = row.input.images[0]
            assert persisted.media_reference is not None
            assert persisted.content is None
        assert img.content == b"INLINE-IMAGE-BYTES"


# ---------------------------------------------------------------------------
# store_media=False on a Team clears the member data embedded in its row
# ---------------------------------------------------------------------------


def test_scrub_recurses_into_member_responses():
    """Team(store_media=False) drops media from the embedded member runs too — they are
    part of the team's own row."""
    from agno.run.team import TeamRunOutput
    from agno.utils.agent import scrub_media_from_run_output

    member = RunOutput(
        run_id="m1",
        agent_id="m",
        images=[Image(id="mi", mime_type="image/png", content=b"MEMBER-IMAGE")],
        messages=[Message(role="user", content="x", images=[Image(id="mm", content=b"MSG-IMAGE")])],
    )
    team_run = TeamRunOutput(run_id="t1", team_id="t", member_responses=[member])

    scrub_media_from_run_output(team_run, keep_references=False)

    assert member.images is None
    assert member.messages[0].images is None


def test_scrub_member_responses_keeps_offloaded_references():
    """With keep_references=True the member's offloaded pointers survive, so media that
    was moved to storage is not orphaned."""
    from agno.run.team import TeamRunOutput
    from agno.utils.agent import scrub_media_from_run_output

    ref = MediaReference(media_id="mi", storage_key="mi.png", storage_backend="local")
    kept = Image(id="mi", mime_type="image/png", media_reference=ref)
    url_only = Image(id="none", mime_type="image/png", url="https://example.com/x.png")
    member = RunOutput(run_id="m1", agent_id="m", images=[kept, url_only])
    team_run = TeamRunOutput(run_id="t1", team_id="t", member_responses=[member])

    scrub_media_from_run_output(team_run, keep_references=True)

    # The offloaded pointer survives; the url-only placeholder carries no data and goes.
    assert member.images is not None
    assert [i.id for i in member.images] == ["mi"]


def test_isolate_covers_member_responses():
    """Isolation must keep pace with the scrub's recursion: scrubbing an isolated copy
    must not strip media off the live member runs the sibling rows are written from."""
    from agno.run.team import TeamRunOutput
    from agno.utils.agent import isolate_media_scrub_targets, scrub_media_from_run_output

    live_member = RunOutput(
        run_id="m1",
        agent_id="m",
        images=[Image(id="mi", mime_type="image/png", content=b"MEMBER-IMAGE")],
        messages=[Message(role="user", content="x", images=[Image(id="mm", content=b"MSG-IMAGE")])],
    )
    live_run = TeamRunOutput(run_id="t1", team_id="t", member_responses=[live_member])

    storage_copy = copy.copy(live_run)
    isolate_media_scrub_targets(storage_copy)
    scrub_media_from_run_output(storage_copy, keep_references=False)

    assert storage_copy.member_responses[0].images is None
    # Live member run — the source for its own agno_runs row — is untouched.
    assert live_member.images is not None
    assert live_member.images[0].content == b"MEMBER-IMAGE"
    assert live_member.messages[0].images is not None


def test_team_store_media_false_leaves_member_rows_alone():
    """The team's store_media governs the team row. Member rows follow each member's own
    store_media (same per-component rule as store_events and workflow executors), so the
    team's terminal write must not strip the member runs it shares objects with."""
    from agno.agent.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.run.team import TeamRunOutput
    from agno.session.team import TeamSession
    from agno.team._run import _cleanup_and_store
    from agno.team.team import Team

    with tempfile.TemporaryDirectory() as tmpdir:
        member = Agent(id="m", name="m")  # store_media defaults to True
        team = Team(
            id="t",
            members=[member],
            db=SqliteDb(db_file=os.path.join(tmpdir, "t.db")),
            store_media=False,
            store_member_responses=True,
        )
        member_img = Image(id="mi", mime_type="image/png", content=b"MEMBER-IMAGE")
        member_run = RunOutput(run_id="m1", agent_id="m", images=[member_img])
        team_img = Image(id="ti", mime_type="image/png", content=b"TEAM-IMAGE")
        run = TeamRunOutput(run_id="t1", team_id="t", images=[team_img], member_responses=[member_run])
        session = TeamSession(session_id="s1", team_id="t", runs=[member_run])

        _cleanup_and_store(team, run, session)

        # Team row: no media anywhere, including the embedded member data.
        persisted_team_run = next(r for r in session.runs if r.run_id == "t1")
        assert persisted_team_run.images is None
        assert all(m.images is None for m in persisted_team_run.member_responses)
        # The member's own run object is untouched, so its sibling row keeps its media.
        assert member_run.images is not None
        assert member_run.images[0].content == b"MEMBER-IMAGE"


def test_request_media_cannot_carry_a_storage_pointer():
    """A media_reference names an object in the configured bucket, and the media route serves
    any key it finds on a session the caller owns. Honouring one off a request body would let a
    caller name any key the AgentOS credentials can reach, have it persisted onto their own
    session, and read it back — so the OS boundary drops it before reconstruction."""
    import base64

    from agno.os.utils import drop_media_references
    from agno.utils.media import reconstruct_images

    forged = [
        {
            "id": "img-1",
            "content": base64.b64encode(b"CALLER-SUPPLIED").decode(),
            "mime_type": "image/png",
            "media_reference": {
                "media_id": "img-1",
                "storage_key": "totally/unrelated/finance-report.txt",
                "storage_backend": "local",
            },
        }
    ]

    images = reconstruct_images(drop_media_references(copy.deepcopy(forged)))
    assert images[0].media_reference is None
    # The caller's own bytes still come through; only the pointer is refused.
    assert images[0].content == b"CALLER-SUPPLIED"

    # Without the guard the pointer survives verbatim, which is what it protects against.
    leaked = reconstruct_images(copy.deepcopy(forged))
    assert leaked[0].media_reference.storage_key == "totally/unrelated/finance-report.txt"


def test_offload_cache_uploads_once_across_persists():
    """Every persist offloads a fresh deep copy, so the media_reference the last one attached
    is gone and the bytes go up again — a HITL run that pauses three times uploaded its media
    five times. The cache lives on the live run, so the second persist is a no-op."""
    from agno.utils.media_offload import offload_cache_for

    class CountingStorage(LocalMediaStorage):
        uploads = 0

        def upload(self, media_id, content, **kwargs):
            type(self).uploads += 1
            return super().upload(media_id, content, **kwargs)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = CountingStorage(base_path=tmpdir)
        run = RunOutput(run_id="r1", images=[Image(id="i1", mime_type="image/png", content=b"PAUSED-IMAGE")])

        for _ in range(3):
            storage_copy = copy.deepcopy(run)
            offload_run_media(storage_copy, storage, "s1", "r1", cache=offload_cache_for(run))
            assert storage_copy.images[0].media_reference is not None
            assert storage_copy.images[0].content is None

        assert CountingStorage.uploads == 1
        # The cache holds references, never media: the caller's run still has its bytes.
        assert run.images[0].content == b"PAUSED-IMAGE"
        assert run.images[0].media_reference is None


def test_cache_does_not_hand_one_media_kind_another_kinds_object():
    """The cache keyed on the content-addressed id alone, so a File sharing an id and bytes with
    an Image got the Image's reference and its own object was never uploaded."""
    from agno.media import File
    from agno.utils.media_offload import offload_cache_for

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        run = RunOutput(
            run_id="r1",
            images=[Image(id="same", mime_type="image/png", content=b"SHARED")],
            files=[File(id="same", mime_type="text/plain", content=b"SHARED")],
        )
        offload_run_media(run, storage, "s1", "r1", cache=offload_cache_for(run))

        img_ref = run.images[0].media_reference
        file_ref = run.files[0].media_reference
        assert img_ref.media_type == "image"
        assert file_ref.media_type == "file"
        assert img_ref.storage_key != file_ref.storage_key
        assert storage.exists(file_ref.storage_key)


@pytest.mark.asyncio
async def test_pre_terminal_writes_upload_once_under_a_sync_backend_on_arun():
    """The sync-backend branch hands offload_run_media to to_thread by reference, so the cache
    had to travel as a positional argument and did not. Every pre-terminal write — the PENDING
    row, the RUNNING row, each checkpoint — re-uploaded the whole run."""
    from agno.utils.agent import abuild_offloaded_storage_copy

    class CountingStorage(LocalMediaStorage):
        uploads = 0

        def upload(self, media_id, content, **kwargs):
            type(self).uploads += 1
            return super().upload(media_id, content, **kwargs)

    class _Entity:
        store_media = True

        def __init__(self, storage):
            self.media_storage = storage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = CountingStorage(base_path=tmpdir)
        run = RunOutput(run_id="r1", images=[Image(id="i1", mime_type="image/png", content=b"BYTES")])
        entity = _Entity(storage)

        for _ in range(3):
            copy_ = await abuild_offloaded_storage_copy(entity, run, "s1")
            assert copy_.images[0].media_reference is not None

        assert CountingStorage.uploads == 1
        assert run.images[0].content == b"BYTES"


def test_member_run_rows_are_offloaded_with_the_teams_backend():
    """Member runs are written as their own rows by the team, so the team's backend offloads them.

    _cleanup_and_store offloads a deep copy of the team run, which leaves the member runs the
    sibling rows are written from still carrying raw base64. The team row beside them held
    references while the member rows held the bytes.
    """
    import os
    import tempfile

    from agno.db.sqlite import SqliteDb
    from agno.run.agent import RunInput, RunOutput
    from agno.run.team import TeamRunOutput
    from agno.session.team import TeamSession
    from agno.team._run import _persist_member_runs_for_team_run
    from agno.team.team import Team

    with tempfile.TemporaryDirectory() as tmpdir:
        team = Team(
            name="t",
            id="t",
            members=[],
            db=SqliteDb(db_file=os.path.join(tmpdir, "t.db")),
            media_storage=LocalMediaStorage(base_path=os.path.join(tmpdir, "media")),
            store_media=True,
        )
        img = Image(id="member-img", mime_type="image/png", content=b"MEMBERBYTES" * 60)
        member_run = RunOutput(run_id="m1", parent_run_id="t1", input=RunInput(input_content="hi", images=[img]))
        team_run = TeamRunOutput(run_id="t1", team_id="t", member_responses=[member_run])
        session = TeamSession(session_id="s1", team_id="t", runs=[team_run, member_run])
        team.db.upsert_session(session=session)  # the runs table has a foreign key onto it

        _persist_member_runs_for_team_run(team=team, session=session, team_run_id="t1")

        stored = team.db.get_run(run_id="m1")
        assert stored is not None, "member run was not persisted"
        payload = stored if isinstance(stored, dict) else stored.to_dict()
        persisted_image = payload["input"]["images"][0]
        assert persisted_image.get("media_reference") is not None
        assert not persisted_image.get("content")

        # The caller's own object keeps its bytes: offload works on a copy.
        assert img.content == b"MEMBERBYTES" * 60
        assert getattr(img, "media_reference", None) is None
