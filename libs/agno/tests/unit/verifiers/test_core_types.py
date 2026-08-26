"""Round-trip tests for the verification field on run outputs, the verification events,
and the unverified run status."""

import json
from pathlib import Path

import pytest

from agno.db.utils import HISTORY_SKIP_STATUSES as DB_HISTORY_SKIP_STATUSES
from agno.db.utils import canonical_run_status
from agno.run.agent import (
    RunEvent,
    RunOutput,
    VerificationCompletedEvent,
    VerificationStartedEvent,
    run_output_event_from_dict,
)
from agno.run.base import HISTORY_SKIP_STATUSES, RunStatus
from agno.run.team import (
    TeamRunEvent,
    TeamRunOutput,
    TeamVerificationCompletedEvent,
    TeamVerificationStartedEvent,
    team_run_output_event_from_dict,
)
from agno.utils.events import (
    create_team_verification_completed_event,
    create_team_verification_started_event,
    create_verification_completed_event,
    create_verification_started_event,
)
from agno.verifiers.types import Verdict, Verification, VerificationAttempt


def make_verification() -> Verification:
    """A two-attempt record exercising every field, including non-JSON verdict data."""
    return Verification(
        status="unverified",
        stop_reason="exhausted",
        baseline_fingerprint="base-fp",
        budget_baseline=1,
        attempts=[
            VerificationAttempt(
                index=0,
                verdicts=[
                    Verdict(passed=False, report="exit 1\nFAILED test_a", name="pytest"),
                    Verdict(passed=True, report="clean", name="lint", data={"path": Path("/tmp/report.txt")}),
                ],
                fingerprint="fp-0",
                compared_against="base-fp",
                noop=False,
                message_index=0,
            ),
            VerificationAttempt(
                index=1,
                verdicts=[Verdict(passed=False, report="exit 1", name="pytest")],
                fingerprint="fp-1",
                compared_against="fp-0-settled",
                noop=True,
                message_index=5,
            ),
        ],
    )


def json_round_trip(payload):
    return json.loads(json.dumps(payload))


class TestRunOutputVerificationRoundTrip:
    def test_round_trip_through_json(self):
        verification = make_verification()
        run = RunOutput(
            run_id="run-1",
            agent_id="agent-1",
            agent_name="Agent",
            session_id="session-1",
            status=RunStatus.unverified,
            verification=verification,
        )

        restored = RunOutput.from_dict(json_round_trip(run.to_dict()))

        assert isinstance(restored.verification, Verification)
        # Verdict data held a Path; to_dict's JSON-safety pass stringifies it, so
        # content equality is asserted on the serialized form (idempotent) rather
        # than the dataclasses.
        assert restored.verification.to_dict() == verification.to_dict()
        assert restored.verification.status == "unverified"
        assert restored.verification.stop_reason == "exhausted"
        assert restored.verification.budget_baseline == 1
        assert restored.verification.baseline_fingerprint == "base-fp"
        assert len(restored.verification.attempts) == 2
        first, second = restored.verification.attempts
        assert first.message_index == 0
        assert first.compared_against == "base-fp"
        assert first.passed is False
        assert second.message_index == 5
        assert second.compared_against == "fp-0-settled"
        assert second.noop is True
        assert restored.verification.passed is False
        assert isinstance(restored.verification.attempts[0].verdicts[1].data["path"], str)

    def test_status_string_equality_after_round_trip(self):
        run = RunOutput(run_id="run-1", agent_id="agent-1", status=RunStatus.unverified)
        restored = RunOutput.from_dict(json_round_trip(run.to_dict()))
        # from_dict keeps the stored string; RunStatus is a str Enum, so equality
        # must hold without assuming the field was rehydrated to the enum.
        assert restored.status == RunStatus.unverified
        assert restored.status == "UNVERIFIED"

    def test_from_dict_tolerates_verification_instance(self):
        verification = make_verification()
        restored = RunOutput.from_dict({"run_id": "run-1", "verification": verification})
        assert restored.verification is verification

    def test_no_verification_stays_none(self):
        run = RunOutput(run_id="run-1", agent_id="agent-1")
        d = run.to_dict()
        assert "verification" not in d
        assert RunOutput.from_dict(json_round_trip(d)).verification is None


class TestTeamRunOutputVerificationRoundTrip:
    def test_round_trip_through_json(self):
        verification = make_verification()
        run = TeamRunOutput(
            run_id="run-1",
            team_id="team-1",
            team_name="Team",
            session_id="session-1",
            status=RunStatus.unverified,
            verification=verification,
        )

        restored = TeamRunOutput.from_dict(json_round_trip(run.to_dict()))

        assert isinstance(restored.verification, Verification)
        assert restored.verification.to_dict() == verification.to_dict()
        assert len(restored.verification.attempts) == 2
        assert restored.verification.attempts[1].message_index == 5
        assert restored.verification.attempts[1].compared_against == "fp-0-settled"
        assert restored.verification.budget_baseline == 1
        assert restored.status == RunStatus.unverified
        assert restored.status == "UNVERIFIED"

    def test_from_dict_tolerates_verification_instance(self):
        verification = make_verification()
        restored = TeamRunOutput.from_dict({"run_id": "run-1", "verification": verification})
        assert restored.verification is verification


AGENT_RUN = RunOutput(run_id="run-1", agent_id="agent-1", agent_name="Agent", session_id="session-1")
TEAM_RUN = TeamRunOutput(run_id="run-1", team_id="team-1", team_name="Team", session_id="session-1")
VERDICT_SUMMARIES = [
    {"name": "pytest", "passed": False, "summary": "exit 1"},
    {"name": "lint", "passed": True, "summary": "clean"},
]


class TestVerificationEventRoundTrip:
    def test_agent_started_event(self):
        event = create_verification_started_event(AGENT_RUN, attempt=2, max_attempts=3)
        assert event.event == RunEvent.verification_started.value

        restored = run_output_event_from_dict(json_round_trip(event.to_dict()))

        assert type(restored) is VerificationStartedEvent
        assert restored.attempt == 2
        assert restored.max_attempts == 3
        assert restored.run_id == "run-1"
        assert restored.agent_id == "agent-1"
        assert restored.session_id == "session-1"

    def test_agent_completed_event(self):
        event = create_verification_completed_event(
            AGENT_RUN,
            attempt=3,
            max_attempts=3,
            passed=False,
            verdicts=VERDICT_SUMMARIES,
            noop=True,
            stop_reason="exhausted",
        )
        assert event.event == RunEvent.verification_completed.value

        restored = run_output_event_from_dict(json_round_trip(event.to_dict()))

        assert type(restored) is VerificationCompletedEvent
        assert restored.attempt == 3
        assert restored.max_attempts == 3
        assert restored.passed is False
        assert restored.verdicts == VERDICT_SUMMARIES
        assert restored.noop is True
        assert restored.stop_reason == "exhausted"
        assert restored.agent_id == "agent-1"

    def test_team_started_event(self):
        event = create_team_verification_started_event(TEAM_RUN, attempt=1, max_attempts=2)
        assert event.event == TeamRunEvent.verification_started.value

        restored = team_run_output_event_from_dict(json_round_trip(event.to_dict()))

        assert type(restored) is TeamVerificationStartedEvent
        assert restored.attempt == 1
        assert restored.max_attempts == 2
        assert restored.team_id == "team-1"
        assert restored.team_name == "Team"
        assert restored.run_id == "run-1"

    def test_team_completed_event(self):
        event = create_team_verification_completed_event(
            TEAM_RUN,
            attempt=2,
            max_attempts=2,
            passed=True,
            verdicts=[{"name": "pytest", "passed": True, "summary": "12 passed"}],
            noop=False,
            stop_reason="passed",
        )
        assert event.event == TeamRunEvent.verification_completed.value

        restored = team_run_output_event_from_dict(json_round_trip(event.to_dict()))

        assert type(restored) is TeamVerificationCompletedEvent
        assert restored.passed is True
        assert restored.verdicts == [{"name": "pytest", "passed": True, "summary": "12 passed"}]
        assert restored.noop is False
        assert restored.stop_reason == "passed"
        assert restored.team_id == "team-1"

    def test_stored_event_reconstructed_via_registry(self):
        # A persisted run's events list holds plain dicts; RunOutput.from_dict must
        # resolve them through the event-type registry, or the whole row is unreadable.
        event = create_verification_completed_event(
            AGENT_RUN, attempt=1, max_attempts=3, passed=False, verdicts=VERDICT_SUMMARIES
        )
        run = RunOutput(run_id="run-1", agent_id="agent-1", status=RunStatus.unverified, events=[event])

        restored = RunOutput.from_dict(json_round_trip(run.to_dict()))

        assert len(restored.events) == 1
        assert type(restored.events[0]) is VerificationCompletedEvent
        assert restored.events[0].verdicts == VERDICT_SUMMARIES
        assert restored.events[0].attempt == 1

    def test_team_stored_event_reconstructed_via_registry(self):
        event = create_team_verification_started_event(TEAM_RUN, attempt=1, max_attempts=2)
        run = TeamRunOutput(run_id="run-1", team_id="team-1", events=[event])

        restored = TeamRunOutput.from_dict(json_round_trip(run.to_dict()))

        assert len(restored.events) == 1
        assert type(restored.events[0]) is TeamVerificationStartedEvent
        assert restored.events[0].max_attempts == 2

    def test_unknown_event_string_still_raises(self):
        with pytest.raises(ValueError):
            run_output_event_from_dict({"event": "VerificationFinished"})

    def test_registration_matrix(self):
        # All four touch points per side: enum member, dataclass, union, registry.
        # A registry or union miss makes persisted runs unreadable.
        from agno.run.agent import RUN_EVENT_TYPE_REGISTRY, RUN_OUTPUT_EVENT_TYPES
        from agno.run.team import TEAM_RUN_EVENT_TYPE_REGISTRY, TEAM_RUN_OUTPUT_EVENT_TYPES

        assert RunEvent.verification_started.value == "VerificationStarted"
        assert RunEvent.verification_completed.value == "VerificationCompleted"
        assert TeamRunEvent.verification_started.value == "TeamVerificationStarted"
        assert TeamRunEvent.verification_completed.value == "TeamVerificationCompleted"

        assert VerificationStartedEvent in RUN_OUTPUT_EVENT_TYPES
        assert VerificationCompletedEvent in RUN_OUTPUT_EVENT_TYPES
        assert TeamVerificationStartedEvent in TEAM_RUN_OUTPUT_EVENT_TYPES
        assert TeamVerificationCompletedEvent in TEAM_RUN_OUTPUT_EVENT_TYPES

        assert RUN_EVENT_TYPE_REGISTRY[RunEvent.verification_started.value] is VerificationStartedEvent
        assert RUN_EVENT_TYPE_REGISTRY[RunEvent.verification_completed.value] is VerificationCompletedEvent
        assert TEAM_RUN_EVENT_TYPE_REGISTRY[TeamRunEvent.verification_started.value] is TeamVerificationStartedEvent
        assert TEAM_RUN_EVENT_TYPE_REGISTRY[TeamRunEvent.verification_completed.value] is TeamVerificationCompletedEvent


class TestUnverifiedStatus:
    def test_not_in_history_skip_statuses(self):
        # The transcript of an unverified run is real work: history builders must keep it.
        assert RunStatus.unverified not in HISTORY_SKIP_STATUSES
        assert RunStatus.unverified.value not in DB_HISTORY_SKIP_STATUSES

    def test_canonical_run_status_round_trip(self):
        assert canonical_run_status("unverified") == "UNVERIFIED"
        assert canonical_run_status("UNVERIFIED") == "UNVERIFIED"
        assert canonical_run_status(RunStatus.unverified) == "UNVERIFIED"
        assert RunStatus("UNVERIFIED") is RunStatus.unverified
