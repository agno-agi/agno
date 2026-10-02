"""Run finalization must clean up member-run mappings.

spawn-style delegation registers child runs via register_member_run; without a
cleanup_member_runs sibling at run finalization the mappings outlive the run,
until the cancellation manager's TTL — or forever with ttl_seconds=None. These
tests drive real run()/arun() calls with an offline model and assert the
mappings are gone afterwards, mirroring Teams' finalization behaviour.
"""

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.cancel import (
    aget_member_run_ids,
    aregister_member_run,
    get_member_run_ids,
    register_member_run,
)


class _OfflineModel(Model):
    """Minimal offline model: canned text response, no network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self._response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs):
        return self._response

    async def ainvoke(self, *args, **kwargs):
        return self._response

    def invoke_stream(self, *args, **kwargs):
        yield self._response

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._response
        return

    def _parse_provider_response(self, response, **kwargs):
        return self._response

    def _parse_provider_response_delta(self, response):
        return self._response


def test_run_cleans_up_registered_member_runs():
    agent = Agent(name="Parent", model=_OfflineModel())
    run_id = "run-member-cleanup-sync"
    register_member_run(run_id, "child-1")
    assert get_member_run_ids(run_id) == {"child-1"}

    agent.run("hi", run_id=run_id)

    assert get_member_run_ids(run_id) == set()


async def test_arun_cleans_up_registered_member_runs():
    agent = Agent(name="Parent", model=_OfflineModel())
    run_id = "run-member-cleanup-async"
    await aregister_member_run(run_id, "child-1")
    assert await aget_member_run_ids(run_id) == {"child-1"}

    await agent.arun("hi", run_id=run_id)

    assert await aget_member_run_ids(run_id) == set()
