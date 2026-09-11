import pytest

from agno.api.api import api as agno_api

TELEMETRY_ENTRY_POINTS = ("post_in_background", "apost_in_background")


def refuse_telemetry_post(route: str, payload: dict) -> None:
    """Stand in for every telemetry entry point and fail the test that reached one.

    A plain function, not a closure, so the guard's own tests can recognise it by
    identity rather than by the message it happens to raise.
    """
    pytest.fail(f"an integration test posted telemetry to {route}; build the entity with telemetry=False")


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


@pytest.fixture(autouse=True, scope="package")
def no_outbound_telemetry():
    """Fail any test in this directory that reaches the telemetry endpoint.

    These suites call a real model, so the network is already in play and a stray
    telemetry post is easy to miss. Setting telemetry=False on one builder only fixes
    the builder someone noticed; this catches every entity built here, including the
    ones written later, and the AgentOS launch post the app lifespan makes.

    Package scope, not function scope, because a module-scoped fixture that performs the
    run is set up before any function-scoped guard exists, and that is exactly where the
    expensive run lives. Not session scope either: the patch would then outlive this
    directory and, since pytest collects it before its siblings, break every later suite
    that posts telemetry on purpose.

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
