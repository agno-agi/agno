"""Super Agent with compaction on: a long conversation is folded into a summary, and what Super Agent
depends on each turn still works after the fold."""

import json
import re

import pytest

from agno.compaction import Compaction
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.models.response import ModelResponse
from agno.os import OSManager
from agno.os.manager.finished_work import FINISHED_WORK_LABEL, READ_TOOLS, finished_work_gate
from agno.os.manager.linked_work import _HEADER
from agno.run.authorization import FINISHED_WORK_REPORT_REFUSAL
from agno.tools import tool
from tests.unit.os import test_super_agent_finished_work as finished_work_tests
from tests.unit.os.test_super_agent_finished_work import (
    CHAT,
    Chat,
    System,
    marked,
    quick,  # noqa: F401
    scenario,
)

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

PAD = "pad " * 1_500
# Above Super Agent's system prompt and tools, and a few turns of PAD.
THRESHOLD = 12_000


class Recorded(Chat):
    """Super Agent's scripted model, keeping every request in full."""

    def __init__(self):
        super().__init__()
        self.requests: list = []

    def invoke(self, messages, tools=None, **kwargs):
        self.requests.append(list(messages))
        return super().invoke(messages, tools=tools, **kwargs)


class Summarizer:
    id = "summarizer"

    def __init__(self):
        self.asked: list = []

    def response(self, messages, **kwargs):
        self.asked.append(messages[-1].content)
        return ModelResponse(content="SUMMARY OF THE EARLIER TURNS")

    async def aresponse(self, messages, **kwargs):
        return self.response(messages)


@tool
def big_report() -> str:
    """Return a report too long to keep in the conversation."""
    return "\n".join(f"row {i}: the quarterly figure is {i * 7}" for i in range(4_000))


@pytest.fixture(params=[False, True], ids=["in-memory", "durable-queue"])
def system(request, tmp_path, monkeypatch):
    monkeypatch.setattr(finished_work_tests, "Chat", Recorded)
    compaction = Compaction(compact_at_tokens=THRESHOLD, uncompacted_runs=2, model=Summarizer())
    value = System(tmp_path, queue=request.param, compaction=compaction, tools=[big_report])
    yield value
    value.close()


def rows(system):
    return system.db.get_compactions_for_session(CHAT)


def archived(system):
    return "\n".join(row["archived_messages"] or "" for row in rows(system))


def summaries(request):
    return [m for m in request if m.role == "user" and str(m.content).startswith(SUMMARY_PREFIX)]


def notes(request):
    """The linked-work notes in one request: each an unstored user message of its own."""
    return [m for m in request if m.role == "user" and not m.from_history and str(m.content).startswith(_HEADER)]


async def talk_until_folded(system, start=0, limit=30):
    """The person keeps talking until the conversation is compacted once more."""
    before = len(rows(system))
    for i in range(start, start + limit):
        await system.say(f"Detail {i}: keep this in mind. {PAD}")
        if len(rows(system)) > before:
            return i + 1
    raise AssertionError("The conversation was never compacted")


# ----------------------------------------------------------------- the setting


def test_compaction_is_off_by_default(tmp_path):
    assert OSManager().compaction is None
    system = System(tmp_path)
    try:
        assert system.os.manager.compaction is None
    finally:
        system.close()


@pytest.mark.parametrize("setting", [True, "threshold"])
def test_the_setting_reaches_super_agent_and_not_platform_builder(tmp_path, setting):
    compaction = Compaction(compact_at_tokens=THRESHOLD) if setting == "threshold" else True
    system = System(tmp_path, compaction=compaction)
    try:
        team = system.os.manager
        team.initialize_team()
        assert isinstance(team.compaction, Compaction)
        assert team.compaction.compact_at_tokens == (THRESHOLD if setting == "threshold" else None)
        assert team.compaction.on_context_overflow is (setting is True)
        assert team.compaction.model is team.model
        assert all(getattr(member, "compaction", None) is None for member in team.members)
    finally:
        system.close()


def test_a_long_conversation_with_super_agent_is_folded_and_stays_searchable(system):
    async def steps():
        await system.say(f"The staging database is on port 5532 and the release owner is Priya. {PAD}")
        await talk_until_folded(system)
        await system.say("What port was it?", ("search_compacted_history", {"pattern": "staging database"}))
        return system.chat.requests[-1], system.chat.runs[-1]["offered"], system.turns()[-1]

    request, offered, turn = scenario(steps)
    assert len(summaries(request)) == 1
    assert "port 5532" in archived(system)
    assert "search_compacted_history" in offered
    # The search ran against this conversation's stored turns and found the exact words.
    assert "port 5532" in turn["run_data"]["content"] and "Priya" in turn["run_data"]["content"]


# ----------------------------------------------------------------- the linked-work note


def test_the_linked_work_note_is_still_sent_after_a_compaction_and_is_never_stored_with_it(system):
    async def steps():
        run_id = await system.start()
        await talk_until_folded(system)
        await system.say("Anything running?")
        return run_id, system.chat.requests[-1]

    run_id, request = scenario(steps)
    assert len(summaries(request)) == 1
    (note,) = notes(request)
    assert run_id in note.content
    # The note sits right before the person's message, after the summary and the kept turns.
    assert request[-2] is note and request[-1].content == "Anything running?"
    assert request.index(summaries(request)[0]) < request.index(note)
    # It is state for one turn: no fold summarized it or stored it.
    summarizer = system.os.manager.compaction.model
    assert _HEADER not in archived(system) and not any(_HEADER in asked for asked in summarizer.asked)


# ----------------------------------------------------------------- finished-work reports


def test_search_compacted_history_is_a_read_a_finished_work_report_may_make():
    assert "search_compacted_history" in READ_TOOLS
    assert (
        finished_work_gate("search_compacted_history", lambda pattern: "found", {"pattern": "x"}, marked()) == "found"
    )
    assert finished_work_gate("compact", lambda: "ran", {}, marked()) == FINISHED_WORK_REPORT_REFUSAL


def test_a_finished_work_report_after_a_compaction_is_given_the_summary_and_reports_as_before(system):
    async def steps():
        run_id = await system.start()
        await talk_until_folded(system)
        folds = len(rows(system))
        sent_before = len(system.chat.requests)
        system.chat.scripts.append(
            [("check_background_run", {"run_id": run_id}), ("search_compacted_history", {"pattern": "Detail 0"})]
        )
        await system.finish()
        return run_id, folds, system.chat.requests[sent_before], system.chat.runs[-1], system.reports_stored()

    run_id, folds, request, report_run, reports = scenario(steps)
    assert folds >= 1
    # The report was started by AgentOS, and was sent the folded conversation, not a blank one.
    assert len(summaries(request)) == 1
    assert request[-1].content.startswith(FINISHED_WORK_LABEL)
    assert f"run {run_id}" in request[-1].content
    assert "search_compacted_history" in report_run["offered"]
    (report,) = reports
    assert report["status"] == "COMPLETED"
    reply = report["run_data"]["content"]
    assert '"status": "COMPLETED"' in reply
    # It read the stored turns, which is a read: the gate let it through.
    assert FINISHED_WORK_REPORT_REFUSAL not in reply and "Detail 0: keep this in mind." in reply


def test_a_finished_work_report_is_folded_like_any_other_turn_and_the_conversation_carries_on(system):
    async def steps():
        run_id = await system.start()
        system.chat.scripts.append([("check_background_run", {"run_id": run_id})])
        await system.finish()
        assert len(system.reports_stored()) == 1
        await talk_until_folded(system)
        # Fold again, so the report is behind the cut whatever the first fold kept.
        await talk_until_folded(system, start=100)
        await system.say("Thanks")
        return system.chat.requests[-1], system.turns()

    request, turns = scenario(steps)
    assert FINISHED_WORK_LABEL in archived(system)
    assert len(summaries(request)) == 1
    assert not any(str(m.content).startswith(FINISHED_WORK_LABEL) for m in request)
    assert turns[-1]["status"] == "COMPLETED"
    # The report is still in the stored conversation, as it was.
    assert len(system.reports_stored()) == 1


# ----------------------------------------------------------------- offloaded tool results


def test_an_offloaded_tool_result_can_still_be_read_after_its_turn_is_folded(system):
    async def steps():
        first = await system.say("Get the report", ("big_report", {}))
        envelope = first.tools[0].result
        result_id = re.search(r'<result id="([^"]+)"', envelope).group(1)
        await talk_until_folded(system)
        await talk_until_folded(system, start=100)
        folded = system.chat.requests[-1]
        await system.say("Read it back", ("read_result", {"result_id": result_id, "end_line": 3}))
        return result_id, folded, system.turns()[-1]

    result_id, request, turn = scenario(steps)
    (summary,) = summaries(request)
    # The envelope left the context with its turn. Its id did not: the summary carries it.
    assert not any(m.role == "tool" and result_id in str(m.content) for m in request)
    assert f"read_result(id): {result_id}" in summary.content
    assert "row 0: the quarterly figure is 0" in turn["run_data"]["content"]
    # The stored payload was never part of the archive: the envelope is what was folded.
    assert "row 2000:" not in archived(system)


def test_the_stored_turns_are_untouched_by_a_compaction(system):
    async def steps():
        await system.say(f"First message. {PAD}")
        turns = await talk_until_folded(system)
        return turns, system.turns()

    turns, stored = scenario(steps)
    assert len(stored) == turns + 1
    assert json.dumps(stored[0]["run_data"]["input"]).count("First message.") == 1
    assert all(SUMMARY_PREFIX not in json.dumps(row["run_data"].get("input")) for row in stored)
