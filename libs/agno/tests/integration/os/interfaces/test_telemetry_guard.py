"""The conftest telemetry guard, checked from inside the directory it covers.

Every other suite here passes whether or not the guard is installed, because none of
them posts telemetry on purpose. So the guard's own properties, that it stands on every
telemetry entry point and that it is armed early enough for the module-scoped fixture
that performs the expensive run, need saying out loud. None of them needs a model or the
network.

Each entry point is recognised by identity, and before anything is called. Calling one
to find out whether it is guarded is the regression itself: on the run where the guard
is missing or installed too late, that call is a telemetry post to the live endpoint.
"""

import pytest

from agno.api.api import Api
from agno.api.api import api as agno_api

from .conftest import TELEMETRY_ENTRY_POINTS, install_telemetry_guard, refuse_telemetry_post


@pytest.fixture(scope="module")
def hook_seen_by_a_module_fixture(request):
    """Record the telemetry hook as a module-scoped fixture finds it.

    The runs in this directory are performed by fixtures at this scope, which are set up
    before any function-scoped fixture exists. A guard installed later than this would
    miss exactly the calls worth catching, so the scope is what gives this fixture its
    point and is asserted rather than assumed.
    """
    assert request.scope == "module"
    return agno_api.post_in_background


@pytest.mark.parametrize("entry_point", TELEMETRY_ENTRY_POINTS)
def test_the_guard_stands_on_every_telemetry_entry_point(entry_point):
    assert getattr(agno_api, entry_point) is refuse_telemetry_post


def test_the_guard_refuses_a_telemetry_post():
    assert agno_api.post_in_background is refuse_telemetry_post

    with pytest.raises(pytest.fail.Exception, match="posted telemetry"):
        agno_api.post_in_background("os-launch", {})


async def test_the_guard_refuses_an_async_telemetry_post():
    """The async entry point is public and awaited from event-loop code. It delegates to
    the sync one today, so nothing here depends on it continuing to."""
    assert agno_api.apost_in_background is refuse_telemetry_post

    with pytest.raises(pytest.fail.Exception, match="posted telemetry"):
        await agno_api.apost_in_background("os-launch", {})


def test_the_guard_is_armed_before_a_module_scoped_fixture_is_set_up(hook_seen_by_a_module_fixture):
    assert hook_seen_by_a_module_fixture is refuse_telemetry_post


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
