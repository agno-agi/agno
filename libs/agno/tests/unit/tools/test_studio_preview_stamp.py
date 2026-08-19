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
from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.registry import Registry
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

    return StudioTools(registry=registry, db=db, teams=True, workflows=True)


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

            print(StudioTools._version_stamp(2)["metadata"]["agno_component_version"])
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
