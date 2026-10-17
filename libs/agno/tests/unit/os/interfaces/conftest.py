import pytest

from agno.api.api import api as agno_api

TELEMETRY_ENTRY_POINTS = ("post_in_background", "apost_in_background")


def refuse_telemetry_post(route: str, payload: dict) -> None:
    """Stand in for every telemetry entry point and fail the test that reached one.

    A plain function, not a closure, so the guard's own tests can recognise it by
    identity rather than by the message it happens to raise.
    """
    pytest.fail(f"a unit test posted telemetry to {route}; build the entity with telemetry=False")


def install_telemetry_guard(target=agno_api):
    """Put the guard on every telemetry entry point and return the undo.

    The undo removes the attributes this added rather than writing back what
    ``getattr`` returned, which would be a bound method and would stay on this
    process-wide instance for good, shadowing the class attribute for every later
    test in the run.
    """
    previous = {name: vars(target).get(name, ...) for name in TELEMETRY_ENTRY_POINTS}
    for name in TELEMETRY_ENTRY_POINTS:
        setattr(target, name, refuse_telemetry_post)

    def undo() -> None:
        for name, value in previous.items():
            if value is ...:
                delattr(target, name)
            else:
                setattr(target, name, value)

    return undo


@pytest.fixture(autouse=True)
def no_outbound_telemetry():
    """Fail any test in this directory that reaches the telemetry endpoint.

    A unit test must not touch the network. Adding telemetry=False to one builder only
    fixes the builder someone noticed; this catches every entity built here, including
    the ones written later, and it has to sit in the conftest rather than in one module
    or the sibling interface suites are left unguarded.

    Both entry points are covered. The async one currently delegates to the sync one, so
    guarding it changes nothing today, and that is the point: nothing about the delegation
    is promised, and a guard that depends on it would be disarmed by an ordinary edit.

    Every telemetry path funnels through these two on the calling thread, and each call
    site wraps it in `except Exception` so telemetry can never change a run's outcome.
    pytest.fail raises outside that hierarchy, so the failure reaches the test instead of
    being logged and dropped.
    """
    undo = install_telemetry_guard()
    try:
        yield
    finally:
        undo()
