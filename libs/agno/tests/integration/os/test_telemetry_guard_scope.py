"""The interfaces telemetry guard must not outlive the directory that installs it.

pytest collects the interfaces package before the modules beside it, so a guard held for
the whole session is still patched in here. It refuses with pytest.fail, which raises
outside the `except Exception` every telemetry call site uses, and so takes down the
AgentOS lifespan of suites that post telemetry on purpose. This module has no AG-UI
content of its own; it exists to catch that regression.
"""

from agno.api.api import api as agno_api


def test_telemetry_is_not_patched_outside_the_interfaces_directory():
    assert agno_api.post_in_background.__module__.startswith("agno."), (
        "the interfaces telemetry guard is still installed here; scope it to its own directory"
    )
