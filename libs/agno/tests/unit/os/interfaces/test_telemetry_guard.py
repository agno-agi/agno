"""The conftest telemetry guard, checked from inside the directory it covers.

The guard used to sit in one interface module, which left every sibling suite here free
to post telemetry from a unit test. Nothing in those suites posts on purpose, so they
pass either way and cannot say whether the guard is armed. This says it.

Each entry point is recognised by identity before it is called. Calling one to find out
whether it is guarded is the regression itself: on the run where the guard is missing,
that call is a telemetry post from a unit test.
"""

import pytest

from agno.api.api import Api
from agno.api.api import api as agno_api

from .conftest import TELEMETRY_ENTRY_POINTS, install_telemetry_guard, refuse_telemetry_post


@pytest.mark.parametrize("entry_point", TELEMETRY_ENTRY_POINTS)
def test_the_guard_stands_on_every_telemetry_entry_point(entry_point):
    assert getattr(agno_api, entry_point) is refuse_telemetry_post


def test_the_guard_refuses_a_telemetry_post():
    assert agno_api.post_in_background is refuse_telemetry_post

    with pytest.raises(pytest.fail.Exception, match="posted telemetry"):
        agno_api.post_in_background("agent-run", {})


async def test_the_guard_refuses_an_async_telemetry_post():
    """The async entry point is public and awaited from event-loop code. It delegates to
    the sync one today, so nothing here depends on it continuing to."""
    assert agno_api.apost_in_background is refuse_telemetry_post

    with pytest.raises(pytest.fail.Exception, match="posted telemetry"):
        await agno_api.apost_in_background("agent-run", {})


def test_the_undo_leaves_the_instance_reading_its_class_again():
    """Writing back what ``getattr`` returned pins a bound method on the instance, which
    then answers every later call however the class changes. The telemetry client is a
    module-level singleton, so a pin put there outlives this directory."""

    class ApiUnderTest(Api):
        pass

    target = ApiUnderTest()
    undo = install_telemetry_guard(target)
    assert target.post_in_background is refuse_telemetry_post
    undo()

    for name in TELEMETRY_ENTRY_POINTS:
        assert name not in vars(target)

    ApiUnderTest.post_in_background = lambda self, route, payload: "from the class"
    assert target.post_in_background("agent-run", {}) == "from the class"
