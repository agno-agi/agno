"""StreamedContent builds the content of a user-written generator from what it yields."""

from pydantic import BaseModel

from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput, ToolCallStartedEvent
from agno.run.streamed import StreamedContent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent


def content_of(*items) -> object:
    streamed = StreamedContent()
    for item in items:
        streamed.add(item)
    return streamed.get()


def test_deltas_are_joined_when_the_run_result_never_arrives():
    deltas = [RunContentEvent(run_id="r1", content="Let me check."), RunContentEvent(run_id="r1", content="Final.")]
    assert content_of(*deltas) == "Let me check.Final."


def test_completed_event_replaces_the_deltas_of_its_run():
    items = [
        RunContentEvent(run_id="r1", content="Let me check."),
        ToolCallStartedEvent(run_id="r1", content="add_to_cart()"),
        RunContentEvent(run_id="r1", content="Final."),
        RunCompletedEvent(run_id="r1", content="Final."),
    ]
    assert content_of(*items) == "Final."


def test_run_output_replaces_the_deltas_of_its_run():
    items = [RunContentEvent(run_id="r1", content="Let me check."), RunOutput(run_id="r1", content="Final.")]
    assert content_of(*items) == "Final."
    # Both the completed event and the run output arriving counts the run once
    assert content_of(*items, RunCompletedEvent(run_id="r1", content="Final.")) == "Final."


def test_plain_items_and_other_runs_keep_their_place():
    items = [
        "Header: ",
        RunContentEvent(run_id="r1", content="narration"),
        RunCompletedEvent(run_id="r1", content="First."),
        " | ",
        RunContentEvent(run_id="r2", content="Second, streamed."),
    ]
    assert content_of(*items) == "Header: First. | Second, streamed."


def test_team_result_replaces_what_its_members_streamed():
    items = [
        TeamRunContentEvent(run_id="team", content="I'll ask."),
        RunContentEvent(run_id="member", parent_run_id="team", content="Member narration."),
        RunCompletedEvent(run_id="member", parent_run_id="team", content="Member final."),
        TeamRunContentEvent(run_id="team", content="Team final."),
        TeamRunCompletedEvent(run_id="team", content="Team final."),
    ]
    assert content_of(*items) == "Team final."
    # Without the team's result, each run's text stays where it was streamed
    assert content_of(*items[:-1]) == "I'll ask.Member final.Team final."


def test_structured_content_is_returned_as_is():
    class Answer(BaseModel):
        name: str

    answer = Answer(name="x")
    assert content_of(RunContentEvent(run_id="r1", content=answer)) is answer
    assert content_of(RunContentEvent(run_id="r1", content="draft"), RunOutput(run_id="r1", content=answer)) is answer


def test_nothing_streamed_is_empty_content():
    assert content_of() == ""
