"""A StudioTools preview run records the version it previewed.

``run_*(version=N)`` previews an exact stored version, drafts included. The
run is continuable, and every continuation surface re-resolves the component
from the version stamped on the run at start. Without that stamp a paused
draft preview resumes on the PUBLISHED version, so an approved tool call is
executed against a config that never had the tool -- it is dropped in silence.

The REST preview routes already stamp; these pin the six toolkit entrypoints
(three component types x sync/async) to the same rule, and pin the other half
of it: an UNPINNED run stays unstamped, or every dispatch would freeze on
whatever was live when it started.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Iterator, Optional

import pytest

from agno.agent.agent import Agent
from agno.db.schemas.scheduler import (
    COMPONENT_VERSION_METADATA_KEY,
    DISPATCH_CHAIN_METADATA_KEY,
    DISPATCH_DEPTH_METADATA_KEY,
)
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.registry import Registry
from agno.run import RunContext
from agno.team.team import Team
from agno.tools.studio import StudioTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    """Offline model answering with a canned string that names its version."""

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._resp()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._resp()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._resp()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._resp()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp()


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-preview-db", db_file=str(tmp_path / "preview.db"))


@pytest.fixture
def models():
    return ScriptedModel("model-v1", "answer from v1"), ScriptedModel("model-v2", "answer from v2")


@pytest.fixture
def registry(db, models):
    return Registry(name="Preview Registry", dbs=[db], models=list(models))


@pytest.fixture
def studio(registry, db, models):
    model_v1, model_v2 = models

    member = Agent(id="member", name="Member", model=model_v1, instructions="member")
    member.save(db=db, stage="published")

    Agent(id="pv-agent", name="PV Agent", model=model_v1, instructions="v1").save(db=db, stage="published")
    Agent(id="pv-agent", name="PV Agent", model=model_v2, instructions="v2").save(db=db, stage="draft")

    Team(id="pv-team", name="PV Team", model=model_v1, members=[member], instructions="v1").save(
        db=db, stage="published"
    )
    Team(id="pv-team", name="PV Team", model=model_v2, members=[member], instructions="v2").save(db=db, stage="draft")

    Workflow(id="pv-flow", name="PV Flow", steps=[Step(name="s", agent=member)]).save(db=db, stage="published")
    Workflow(id="pv-flow", name="PV Flow", steps=[Step(name="s", agent=member)]).save(db=db, stage="draft")

    return StudioTools(registry=registry, db=db)


def _payload(raw: str) -> Dict[str, Any]:
    out = json.loads(raw)
    return out.get("data") if out.get("ok") else out


def _stored_metadata(db, session_id: str, run_id: str, session_type: str) -> Optional[Dict[str, Any]]:
    session = db.get_session(session_id=session_id, session_type=session_type)
    for run in session.runs or []:
        run_dict = run if isinstance(run, dict) else run.to_dict()
        if run_dict.get("run_id") == run_id:
            return run_dict.get("metadata")
    raise AssertionError(f"run {run_id} not found on session {session_id}")


def _stamp(db, payload: Dict[str, Any], session_type: str) -> Optional[int]:
    metadata = _stored_metadata(db, payload["session_id"], payload["run_id"], session_type)
    # Assert on the key, never on the dict: the workflow path already persists
    # an empty metadata dict where the agent path persists None.
    return (metadata or {}).get(COMPONENT_VERSION_METADATA_KEY)


SURFACES = [
    ("run_agent", "pv-agent", "agent"),
    ("run_team", "pv-team", "team"),
    ("run_workflow", "pv-flow", "workflow"),
]


class TestPinnedPreviewRunsCarryTheStamp:
    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_sync_preview_stamps_the_pinned_version(self, studio, db, tool_name, component_id, session_type):
        payload = _payload(getattr(studio, tool_name)(component_id, "hi", version=2))
        assert _stamp(db, payload, session_type) == 2

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_async_preview_stamps_the_pinned_version(self, studio, db, tool_name, component_id, session_type):
        payload = _payload(asyncio.run(getattr(studio, f"a{tool_name}")(component_id, "hi", version=2)))
        assert _stamp(db, payload, session_type) == 2

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_published_version_pin_is_stamped_too(self, studio, db, tool_name, component_id, session_type):
        # v1 happens to be live, but the caller asked for an exact version and
        # the run must stay on it even after the pointer moves.
        payload = _payload(getattr(studio, tool_name)(component_id, "hi", version=1))
        assert _stamp(db, payload, session_type) == 1


class TestUnpinnedRunsStayUnstamped:
    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_no_version_means_no_stamp(self, studio, db, tool_name, component_id, session_type):
        payload = _payload(getattr(studio, tool_name)(component_id, "hi"))
        assert _stamp(db, payload, session_type) is None

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_no_version_means_no_stamp_async(self, studio, db, tool_name, component_id, session_type):
        payload = _payload(asyncio.run(getattr(studio, f"a{tool_name}")(component_id, "hi")))
        assert _stamp(db, payload, session_type) is None


class TestTheStampNeedsNoServerStack:
    """The toolkit ships without the server extras, so the stamp writer must
    not drag ``agno.os`` (and with it fastapi/starlette) into a preview run."""

    def test_the_stamp_is_written_without_fastapi_installed(self):
        import subprocess
        import sys as _sys
        import textwrap

        script = textwrap.dedent(
            """
            import sys

            class Blocker:
                BLOCKED = ("fastapi", "starlette")

                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".")[0] in self.BLOCKED:
                        raise ImportError(fullname + " is not installed")
                    return None

            sys.meta_path.insert(0, Blocker())
            from agno.tools.studio import StudioTools

            print(StudioTools._version_stamp(2)["agno_component_version"])
            print(StudioTools._version_stamp(None))
            assert "agno.os.utils" not in sys.modules
            """
        )
        result = subprocess.run(
            [_sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": ":".join(p for p in _sys.path if p), "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["2", "{}"], result.stdout


class TestTheStampDrivesContinuation:
    def test_a_draft_preview_resumes_on_the_draft(self, studio, db):
        from agno.os.utils import stamped_component_version

        payload = _payload(studio.run_agent("pv-agent", "hi", version=2))
        assert payload["content"] == "answer from v2"

        session = db.get_session(session_id=payload["session_id"], session_type="agent")
        run = next(r for r in (session.runs or []) if getattr(r, "run_id", None) == payload["run_id"])
        # This is the reader every continue/resume surface re-resolves from.
        assert stamped_component_version(run) == 2


def _chained_context(*chain: str) -> RunContext:
    return RunContext(
        run_id="caller-run",
        session_id="caller-sess",
        metadata={DISPATCH_CHAIN_METADATA_KEY: list(chain), DISPATCH_DEPTH_METADATA_KEY: len(chain)},
    )


class TestDispatchesCarryTheChain:
    """These are real runs, not stubs: the lineage must survive the whole
    resolve -> run -> persist path and land on the stored child run row, or a
    nested run has no signal that it is nested and the cycle guard reads an
    empty lineage on every hop."""

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_a_dispatched_run_row_records_its_chain(self, studio, db, tool_name, component_id, session_type):
        payload = _payload(getattr(studio, tool_name)(component_id, "hi"))
        metadata = _stored_metadata(db, payload["session_id"], payload["run_id"], session_type) or {}
        assert metadata.get(DISPATCH_CHAIN_METADATA_KEY) == [f"{session_type}:{component_id}"]
        assert metadata.get(DISPATCH_DEPTH_METADATA_KEY) == 1

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_a_pinned_preview_carries_chain_and_stamp_together(self, studio, db, tool_name, component_id, session_type):
        payload = _payload(getattr(studio, tool_name)(component_id, "hi", version=2))
        metadata = _stored_metadata(db, payload["session_id"], payload["run_id"], session_type) or {}
        assert metadata.get(DISPATCH_CHAIN_METADATA_KEY) == [f"{session_type}:{component_id}"]
        assert metadata.get(DISPATCH_DEPTH_METADATA_KEY) == 1
        assert metadata.get(COMPONENT_VERSION_METADATA_KEY) == 2

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_an_async_pinned_preview_carries_chain_and_stamp_together(
        self, studio, db, tool_name, component_id, session_type
    ):
        # The async pinned branch is separate code dispatching component.arun
        # directly; without this, it could stop threading the lineage while
        # every refusal test stays green (refusals fire before the run).
        payload = _payload(asyncio.run(getattr(studio, f"a{tool_name}")(component_id, "hi", version=2)))
        metadata = _stored_metadata(db, payload["session_id"], payload["run_id"], session_type) or {}
        assert metadata.get(DISPATCH_CHAIN_METADATA_KEY) == [f"{session_type}:{component_id}"]
        assert metadata.get(DISPATCH_DEPTH_METADATA_KEY) == 1
        assert metadata.get(COMPONENT_VERSION_METADATA_KEY) == 2

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_a_pinned_preview_registers_for_cancel_cascade(self, studio, db, tool_name, component_id, session_type):
        # The pinned branch is the dispatch path that bypasses the runner's
        # run tools, so its registration must be pinned separately or an
        # escaped preview run is unstoppable from the caller's cancel_run.
        from agno.run.cancel import get_member_run_ids

        context = RunContext(run_id="cascade-parent", session_id="caller-sess")
        payload = _payload(getattr(studio, tool_name)(component_id, "hi", version=2, _agno_run_context=context))
        assert payload["run_id"] in get_member_run_ids("cascade-parent")

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_an_async_pinned_preview_registers_for_cancel_cascade(
        self, studio, db, tool_name, component_id, session_type
    ):
        from agno.run.cancel import get_member_run_ids

        context = RunContext(run_id="cascade-parent-async", session_id="caller-sess")
        payload = _payload(
            asyncio.run(getattr(studio, f"a{tool_name}")(component_id, "hi", version=2, _agno_run_context=context))
        )
        assert payload["run_id"] in get_member_run_ids("cascade-parent-async")

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_the_stored_chain_composes_into_a_refusal(self, studio, db, tool_name, component_id, session_type):
        # The loop the guard exists for: run, read back the chain exactly as a
        # nested run's tools would see it, dispatch the same component again.
        payload = _payload(getattr(studio, tool_name)(component_id, "hi"))
        metadata = _stored_metadata(db, payload["session_id"], payload["run_id"], session_type)
        nested_context = RunContext(run_id="nested-run", session_id="nested-sess", metadata=dict(metadata or {}))

        out = json.loads(getattr(studio, tool_name)(component_id, "hi again", _agno_run_context=nested_context))
        # Unversioned runs go through the embedded runner, whose errors pass
        # through as {"error": <message>} rather than the studio envelope.
        assert f"{session_type}:{component_id}" in out["error"]
        assert "already running" in out["error"]


class TestPinnedPreviewsAreGuardedToo:
    """run_*(version=N) dispatches the component directly rather than through
    the runner's run tools, so an unguarded preview would be the one door left
    open to unbounded self-dispatch."""

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_sync_preview_refuses_a_cycle(self, studio, db, tool_name, component_id, session_type):
        out = json.loads(
            getattr(studio, tool_name)(
                component_id, "hi", version=2, _agno_run_context=_chained_context(f"{session_type}:{component_id}")
            )
        )
        assert out["ok"] is False
        assert out["error"]["code"] == "dispatch_refused"
        assert "already running" in out["error"]["message"]

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_async_preview_refuses_a_cycle(self, studio, db, tool_name, component_id, session_type):
        out = json.loads(
            asyncio.run(
                getattr(studio, f"a{tool_name}")(
                    component_id,
                    "hi",
                    version=2,
                    _agno_run_context=_chained_context(f"{session_type}:{component_id}"),
                )
            )
        )
        assert out["ok"] is False
        assert out["error"]["code"] == "dispatch_refused"

    @pytest.mark.parametrize("tool_name,component_id,session_type", SURFACES)
    def test_preview_refuses_past_the_depth_cap(self, studio, db, tool_name, component_id, session_type):
        out = json.loads(
            getattr(studio, tool_name)(
                component_id, "hi", version=2, _agno_run_context=_chained_context("team:o1", "agent:o2")
            )
        )
        assert out["ok"] is False
        assert out["error"]["code"] == "dispatch_refused"


class TestSelfDispatchOnceOnThePinnedPath:
    """The version-pinned branch dispatches directly, bypassing the runner's
    run tools; the opt-in must behave identically there or version=N becomes
    the door where "once" silently means "always" (or "never")."""

    def test_a_pinned_self_preview_runs_once_then_refuses(self, studio, registry, db):
        once_studio = StudioTools(registry=registry, db=db, self_dispatch="once")
        caller = type("W", (), {"id": "pv-agent"})()

        first = _payload(once_studio.run_agent("pv-agent", "hi", version=2, _agno_agent=caller))
        assert first["content"] == "answer from v2"
        metadata = _stored_metadata(db, first["session_id"], first["run_id"], "agent") or {}
        assert metadata.get(DISPATCH_CHAIN_METADATA_KEY) == ["agent:pv-agent"]
        assert metadata.get(DISPATCH_DEPTH_METADATA_KEY) == 1

        nested = RunContext(run_id="nested-run", session_id="nested-sess", metadata=dict(metadata))
        out = json.loads(
            once_studio.run_agent("pv-agent", "hi again", version=2, _agno_run_context=nested, _agno_agent=caller)
        )
        assert out["ok"] is False
        assert out["error"]["code"] == "dispatch_refused"

    def test_the_default_still_refuses_the_first_pinned_self_preview(self, studio, db):
        caller = type("W", (), {"id": "pv-agent"})()
        out = json.loads(studio.run_agent("pv-agent", "hi", version=2, _agno_agent=caller))
        assert out["ok"] is False
        assert out["error"]["code"] == "dispatch_refused"
