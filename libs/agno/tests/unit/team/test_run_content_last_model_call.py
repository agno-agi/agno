"""Team run content is the last model call's text, not every call's text glued together."""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.team.team import Team
from tests.unit.agent.test_run_content_last_model_call import (
    MODE_IDS,
    MODES,
    NARRATED_SCRIPT,
    ScriptedModel,
    add_to_cart,
    assert_last_call_text,
    run_in_mode,
)


@pytest.mark.parametrize("stream,use_async", MODES, ids=MODE_IDS)
def test_team_content_is_last_model_call_text(stream: bool, use_async: bool):
    team = Team(members=[], model=ScriptedModel(NARRATED_SCRIPT), tools=[add_to_cart], db=InMemoryDb())
    output, events = run_in_mode(team, stream, use_async)
    assert_last_call_text(output, events, stream)
