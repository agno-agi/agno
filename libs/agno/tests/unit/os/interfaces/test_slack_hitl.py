import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("slack_sdk", reason="slack_sdk not installed")

from agno.models.response import ToolExecution
from agno.os.interfaces.slack import hitl, security
from agno.os.interfaces.slack.context import EventContext
from agno.os.interfaces.slack.executor import DecisionRefused
from agno.os.interfaces.slack.ids import (
    ACTION_CHECK_STATUS,
    ACTION_ROW_APPROVE,
    ACTION_ROW_REJECT,
    ACTION_SUBMIT,
    encode_admin_approval_button_value,
    encode_row_button_value,
    encode_submit_button_value,
    row_block_id,
)
from agno.os.interfaces.slack.pause import post_pause_card
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunContinuedEvent,
    RunErrorEvent,
    RunPausedEvent,
)
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement

from .conftest import make_async_client_mock, make_ctx

OWNER = "U123"
SESSION_ID = "agent-1:C123:111.222"


def _make_requirement(req_id: str = "r1", **tool_overrides: Any) -> RunRequirement:
    defaults = {"tool_name": "delete_file", "tool_args": {"path": "/tmp/demo.txt"}, "requires_confirmation": True}
    defaults.update(tool_overrides)
    return RunRequirement(tool_execution=ToolExecution(**defaults), id=req_id)


def _paused_run(requirements: List[RunRequirement], user_id: str = OWNER, status: Any = RunStatus.paused) -> Mock:
    return Mock(
        run_id="run-1",
        session_id=SESSION_ID,
        user_id=user_id,
        status=status,
        active_requirements=requirements,
        content="",
    )


def _make_entity(run_output: Any = None) -> AsyncMock:
    entity = AsyncMock()
    entity.id = "agent-1"
    entity.name = "Test Agent"
    entity.db = None
    entity.aget_session = AsyncMock(return_value=None)
    entity.aget_run_output = AsyncMock(return_value=run_output)
    return entity


def _submit_payload(
    blocks: List[Dict[str, Any]],
    user: str = OWNER,
    awaiting_ts: Optional[str] = "await-1",
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": user},
        "channel": {"id": "C123"},
        "message": {"ts": "222.333", "thread_ts": "111.222", "blocks": blocks},
        "state": {"values": {}},
        "actions": [
            {
                "action_id": ACTION_SUBMIT,
                "block_id": "pause:run-1",
                "value": encode_submit_button_value("run-1", awaiting_ts, owner),
            }
        ],
    }


def _approved_blocks() -> List[Dict[str, Any]]:
    return [{"type": "section", "block_id": row_block_id("r1", "confirmation", decided="approve")}]


def _row_payload(action_id: str, user: str = OWNER) -> Dict[str, Any]:
    return {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": user},
        "channel": {"id": "C123"},
        "message": {
            "ts": "222.333",
            "thread_ts": "111.222",
            "blocks": [
                {
                    "type": "card",
                    "block_id": "rowact:r1:confirmation",
                    "title": {"type": "mrkdwn", "text": "*delete_file*"},
                    "body": {"type": "mrkdwn", "text": "path=/tmp/demo.txt"},
                    "actions": [],
                }
            ],
        },
        "actions": [{"action_id": action_id, "value": encode_row_button_value("r1", "run-1", "await-1", OWNER)}],
    }


def _check_status_payload(user: str = OWNER, awaiting_ts: Optional[str] = "await-1") -> Dict[str, Any]:
    return {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": user},
        "channel": {"id": "C123"},
        "message": {
            "ts": "222.333",
            "thread_ts": "111.222",
            "blocks": [
                {
                    "type": "card",
                    "block_id": "admin_approval:r1",
                    "title": {"text": "*deploy_schema*"},
                    "body": {"text": "Args: table=users"},
                }
            ],
        },
        "actions": [
            {
                "action_id": ACTION_CHECK_STATUS,
                "value": encode_admin_approval_button_value("appr-1", "r1", "run-1", awaiting_ts, OWNER),
            }
        ],
    }


class FakeContinue:
    """Stands in for executor.continue_run: records each call and accepts like the pipeline does."""

    def __init__(self, result: bool = True, refuse: bool = False, gate: Optional[asyncio.Event] = None):
        self.result = result
        self.refuse = refuse
        self.gate = gate
        self.calls: List[Dict[str, Any]] = []

    async def __call__(
        self, event_context, client, ctx, requirements, *, decisions=None, on_accepted=None, clicker=None
    ) -> bool:
        self.calls.append(
            {"event_context": event_context, "requirements": requirements, "decisions": decisions, "clicker": clicker}
        )
        if self.refuse:
            # A refusal carries no text; the card says it is no longer active
            raise DecisionRefused()
        if on_accepted is not None:
            await on_accepted()
        if self.gate is not None:
            await self.gate.wait()
        return self.result


def _ephemerals(client: AsyncMock) -> List[str]:
    return [c.kwargs["text"] for c in client.chat_postEphemeral.call_args_list]


class TestSubmit:
    @pytest.mark.asyncio
    async def test_submit_approval_continues_run(self):
        requirement = _make_requirement()
        entity = _make_entity(_paused_run([requirement]))
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

        entity.aget_run_output.assert_awaited_with(run_id="run-1", session_id=SESSION_ID)
        assert requirement.confirmation is True
        assert len(fake.calls) == 1
        assert fake.calls[0]["requirements"] == [requirement]
        assert fake.calls[0]["event_context"].owner == OWNER
        client.chat_delete.assert_awaited_once_with(channel="C123", ts="await-1")
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_submit_skips_required_approval_tools(self):
        regular_req = _make_requirement(req_id="r1")
        required_req = _make_requirement(req_id="r2", approval_type="required", approval_id="appr-1")
        entity = _make_entity(_paused_run([regular_req, required_req]))
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(
                _submit_payload(_approved_blocks()), make_async_client_mock(), make_ctx(agent=entity)
            )

        assert regular_req.confirmation is True
        assert required_req.confirmation is None
        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_two_concurrent_submits_continue_once(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        gate = asyncio.Event()
        fake = FakeContinue(gate=gate)

        with patch.object(hitl, "continue_run", new=fake):
            first = asyncio.create_task(hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx))
            while not fake.calls:
                await asyncio.sleep(0)
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)
            gate.set()
            await first

        assert len(fake.calls) == 1
        assert _ephemerals(client) == [hitl._ALREADY_SUBMITTED_MESSAGE]
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_invalid_submit_then_valid_submit_continues_once(self):
        requirement = _make_requirement()
        entity = _make_entity(_paused_run([requirement]))
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()
        undecided = [{"type": "section", "block_id": row_block_id("r1", "confirmation")}]

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(undecided), client, ctx)
            assert fake.calls == []
            assert "Please fix the following" in _ephemerals(client)[0]
            # The awaiting indicator stays while the card is still live
            client.chat_delete.assert_not_awaited()
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

        assert len(fake.calls) == 1
        assert requirement.confirmation is True

    @pytest.mark.asyncio
    async def test_approval_write_failure_releases_claim_and_retry_succeeds(self):
        first = _make_requirement(req_id="r1", approval_type="required", approval_id="appr-1")
        second = _make_requirement(req_id="r2", approval_type="required", approval_id="appr-2")
        entity = _make_entity(_paused_run([first, second]))
        rows = {"appr-1": {"status": "pending"}, "appr-2": {"status": "pending"}}
        entity.db = Mock()
        entity.db.get_approval = Mock(side_effect=lambda approval_id: rows[approval_id])
        writes = {"appr-2": [False, True]}

        async def resolve(db, approval_id, status, **kwargs):
            # appr-1 is written once and then reads as already resolved; appr-2 fails on the first write
            if rows[approval_id]["status"] != "pending":
                return None
            if approval_id in writes and not writes[approval_id].pop(0):
                return None
            rows[approval_id] = {"status": status}
            return rows[approval_id]

        decisions = []
        for req_id in ("r1", "r2"):
            decision = Mock(requirement_id=req_id, approved=True, rejected_note=None)
            decision.input_values = decision.external_result = decision.feedback_selections = None
            decisions.append(decision)
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()

        with (
            patch.object(hitl, "continue_run", new=fake),
            patch.object(hitl, "parse_submit_payload", return_value=(decisions, [])),
            patch.object(hitl, "aresolve_approval", new=resolve),
        ):
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)
            assert fake.calls == []
            assert _ephemerals(client) == [hitl.APPROVAL_NOT_RECORDED_MESSAGE]
            client.chat_update.assert_not_awaited()
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

        assert len(fake.calls) == 1
        assert rows == {"appr-1": {"status": "approved"}, "appr-2": {"status": "approved"}}

    @pytest.mark.asyncio
    async def test_conflicting_resolved_approval_is_refused(self):
        requirement = _make_requirement(approval_type="required", approval_id="appr-1")
        entity = _make_entity(_paused_run([requirement]))
        entity.db = Mock()
        entity.db.get_approval = Mock(return_value={"status": "rejected"})
        decision = Mock(requirement_id="r1", approved=True, rejected_note=None)
        decision.input_values = decision.external_result = decision.feedback_selections = None
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()

        with (
            patch.object(hitl, "continue_run", new=fake),
            patch.object(hitl, "parse_submit_payload", return_value=([decision], [])),
            patch.object(hitl, "aresolve_approval", new=AsyncMock(return_value=None)),
        ):
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

        assert fake.calls == []
        assert _ephemerals(client) == [hitl._NO_LONGER_ACTIVE_MESSAGE]
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_run_no_longer_paused_releases_claim(self):
        requirement = _make_requirement()
        entity = _make_entity()
        paused = _paused_run([requirement])
        completed = _paused_run([requirement], status=RunStatus.completed)
        # Paused on the first read (owner check), continued elsewhere by the read after the claim
        entity.aget_run_output = AsyncMock(side_effect=[paused, completed])
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

        assert fake.calls == []
        assert _ephemerals(client) == [hitl._NO_LONGER_ACTIVE_MESSAGE]
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_continue_failure_marks_card_could_not_resume(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        blocks = _approved_blocks() + [{"type": "input", "block_id": "x"}]

        with patch.object(hitl, "continue_run", new=FakeContinue(result=False)):
            await hitl.handle_submit(_submit_payload(blocks), client, ctx)

        texts = [c.kwargs["text"] for c in client.chat_update.call_args_list]
        assert texts == ["Submitted", "Could not resume"]
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_unexpected_continue_error_marks_card_could_not_resume(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        blocks = _approved_blocks() + [{"type": "input", "block_id": "x"}]

        async def broken(event_context, client, ctx, requirements, *, decisions=None, on_accepted=None, clicker=None):
            await on_accepted()
            raise RuntimeError("boom")

        with patch.object(hitl, "continue_run", new=broken):
            await hitl.handle_submit(_submit_payload(blocks), client, ctx)

        texts = [c.kwargs["text"] for c in client.chat_update.call_args_list]
        assert texts == ["Submitted", "Could not resume"]
        client.chat_postMessage.assert_awaited()
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "111.222"
        client.assistant_threads_setStatus.assert_awaited_with(channel_id="C123", thread_ts="111.222", status="")
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_refused_native_decision_leaves_card_live(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        blocks = _approved_blocks() + [{"type": "input", "block_id": "x"}]
        fake = FakeContinue(refuse=True)

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(blocks), client, ctx)

        assert len(fake.calls) == 1
        assert _ephemerals(client) == [hitl._NO_LONGER_ACTIVE_MESSAGE]
        client.chat_update.assert_not_awaited()
        client.chat_delete.assert_not_awaited()
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_remote_entity_without_run_output_gets_ephemeral(self):
        entity = Mock(spec=["arun", "acontinue_run", "id"])
        entity.id = "agent-1"
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

        assert fake.calls == []
        assert _ephemerals(client) == [hitl._REMOTE_MESSAGE]


class TestWhoMayDecide:
    @pytest.mark.parametrize("entity_type", ["agent", "team", "external"])
    @pytest.mark.parametrize("action", ["approve", "reject", "submit", "check_status"])
    @pytest.mark.asyncio
    async def test_only_owner_or_approver_decides(self, entity_type: str, action: str):
        requirement = _make_requirement(approval_type="required", approval_id="appr-1")
        entity = _make_entity(_paused_run([requirement]))
        entity.db = Mock()
        entity.db.get_approval = Mock(return_value={"id": "appr-1", "status": "approved"})
        ctx = make_ctx(agent=None, team=entity) if entity_type == "team" else make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()
        payloads = {
            "approve": (hitl.handle_row_approve, _row_payload(ACTION_ROW_APPROVE, user="U999")),
            "reject": (hitl.handle_row_reject, _row_payload(ACTION_ROW_REJECT, user="U999")),
            "submit": (hitl.handle_submit, _submit_payload(_approved_blocks(), user="U999")),
            "check_status": (hitl.handle_check_status, _check_status_payload(user="U999")),
        }
        handler, payload = payloads[action]

        with patch.object(hitl, "continue_run", new=fake):
            await handler(payload, client, ctx)

        assert fake.calls == []
        assert _ephemerals(client) == [hitl._NOT_ALLOWED_MESSAGE]
        client.chat_update.assert_not_awaited()
        client.chat_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approver_may_decide(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        ctx = make_ctx(agent=entity, approvers=["U777"])
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(_approved_blocks(), user="U777"), make_async_client_mock(), ctx)

        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_parked_event_context_owner_is_used(self):
        entity = _make_entity(_paused_run([_make_requirement()], user_id="someone@example.com"))
        ctx = make_ctx(agent=entity)
        parked = EventContext(
            run_id="run-1",
            session_id=SESSION_ID,
            channel="C123",
            thread_ts="111.222",
            message_ts="111.222",
            owner="U555",
            user_id="someone@example.com",
            entity_id="agent-1",
        )
        ctx.runs.park_paused(parked)
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(_approved_blocks(), user="U555"), make_async_client_mock(), ctx)

        assert len(fake.calls) == 1
        assert fake.calls[0]["event_context"] is parked

    @pytest.mark.asyncio
    async def test_card_owner_survives_restart(self):
        requirement = _make_requirement()
        run_output = _paused_run([requirement], user_id="test@example.com")
        # The card is posted by the process that started the run
        poster = make_async_client_mock()
        poster.chat_postMessage = AsyncMock(return_value={"ts": "222.333"})
        await post_pause_card(poster, run_output, "C123", "111.222", "await-1", owner=OWNER)
        posted_blocks = poster.chat_postMessage.call_args.kwargs["blocks"]
        row = next(b for b in posted_blocks if b.get("block_id", "").startswith("rowact:r1:confirmation"))
        approve_value = row["actions"][0]["value"]

        # A new process: empty registry, and Slack identity lookups fail, so only the card names the owner
        ctx = make_ctx(agent=_make_entity(run_output), resolve_user_identity=True)
        assert ctx.runs.find_run("run-1") is None
        client = make_async_client_mock()
        client.users_info = AsyncMock(side_effect=Exception("users.info unavailable"))
        client.users_lookupByEmail = AsyncMock(side_effect=Exception("users.lookupByEmail unavailable"))
        payload = _row_payload(ACTION_ROW_APPROVE)
        payload["message"]["blocks"] = posted_blocks
        payload["actions"][0]["value"] = approve_value
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_row_approve(payload, client, ctx)

        assert len(fake.calls) == 1
        assert fake.calls[0]["event_context"].owner == OWNER
        assert fake.calls[0]["event_context"].user_id == "test@example.com"
        assert requirement.confirmation is True

    @pytest.mark.asyncio
    async def test_card_without_owner_resolves_owner_by_identity(self):
        # A card posted before the owner was written on it: the clicker's own email matches the run's user
        entity = _make_entity(_paused_run([_make_requirement()], user_id="test@example.com"))
        ctx = make_ctx(agent=entity, resolve_user_identity=True)
        client = make_async_client_mock()
        client.users_lookupByEmail = AsyncMock(return_value={"ok": True, "user": {"id": OWNER}})
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_submit(_submit_payload(_approved_blocks(), user=OWNER), client, ctx)

        assert len(fake.calls) == 1


class TestRestoredAuthority:
    @pytest.mark.asyncio
    async def test_click_after_registry_clear_restores_owner_authority(self):
        entity = _make_entity(_paused_run([_make_requirement()], user_id="principal-1"))
        ctx = make_ctx(agent=entity, users={OWNER: "principal-1"})
        authority = object()
        authorize = AsyncMock(return_value=authority)
        fake = FakeContinue()

        with (
            patch.object(hitl, "continue_run", new=fake),
            patch.object(security, "resolve_principal_authorization", new=authorize),
        ):
            await hitl.handle_submit(_submit_payload(_approved_blocks(), owner=OWNER), make_async_client_mock(), ctx)

        authorize.assert_awaited_once_with(ctx.app, "principal-1", "agents", "agent-1")
        assert len(fake.calls) == 1
        assert fake.calls[0]["event_context"].authority is authority
        assert fake.calls[0]["clicker"] == OWNER

    @pytest.mark.asyncio
    async def test_refused_authority_posts_ephemeral_without_claim(self):
        entity = _make_entity(_paused_run([_make_requirement()], user_id="principal-1"))
        ctx = make_ctx(agent=entity, users={OWNER: "principal-1"})
        client = make_async_client_mock()
        fake = FakeContinue()

        with (
            patch.object(hitl, "continue_run", new=fake),
            patch.object(
                security,
                "resolve_principal_authorization",
                new=AsyncMock(side_effect=PermissionError("User is disabled")),
            ),
        ):
            await hitl.handle_submit(_submit_payload(_approved_blocks(), owner=OWNER), client, ctx)

        assert fake.calls == []
        assert _ephemerals(client) == ["Not run: User is disabled"]
        assert ctx.runs.claim_run("run-1") is True


class TestRowActions:
    @pytest.mark.asyncio
    async def test_row_reject_shows_reason_and_submit(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        client = make_async_client_mock()

        await hitl.handle_row_reject(_row_payload(ACTION_ROW_REJECT), client, make_ctx(agent=entity))

        call = client.chat_update.call_args
        assert call.kwargs["text"] == "Rejection pending"
        assert any(b.get("type") == "actions" for b in call.kwargs["blocks"])

    @pytest.mark.asyncio
    async def test_last_row_approve_submits_once(self):
        requirement = _make_requirement()
        entity = _make_entity(_paused_run([requirement]))
        ctx = make_ctx(agent=entity)
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_row_approve(_row_payload(ACTION_ROW_APPROVE), make_async_client_mock(), ctx)

        assert len(fake.calls) == 1
        assert requirement.confirmation is True


class TestAdminApproval:
    @pytest.mark.asyncio
    async def test_check_status_pending_updates_card(self):
        entity = _make_entity(_paused_run([_make_requirement(approval_type="required", approval_id="appr-1")]))
        entity.db = Mock()
        entity.db.get_approval = Mock(return_value={"id": "appr-1", "status": "pending"})
        client = make_async_client_mock()

        await hitl.handle_check_status(_check_status_payload(), client, make_ctx(agent=entity))

        entity.db.get_approval.assert_called_once_with("appr-1")
        assert client.chat_update.call_args.kwargs["text"] == "Status: pending"

    @pytest.mark.asyncio
    async def test_check_status_no_db_returns_pending(self):
        entity = _make_entity(_paused_run([_make_requirement()]))
        client = make_async_client_mock()

        await hitl.handle_check_status(_check_status_payload(), client, make_ctx(agent=entity))

        assert client.chat_update.call_args.kwargs["text"] == "Status: pending"

    @pytest.mark.asyncio
    async def test_check_status_approved_resumes_run(self):
        requirement = _make_requirement(approval_type="required", approval_id="appr-1")
        entity = _make_entity(_paused_run([requirement]))
        entity.db = Mock()
        entity.db.get_approval = Mock(return_value={"id": "appr-1", "status": "approved"})
        client = make_async_client_mock()
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_check_status(_check_status_payload(), client, make_ctx(agent=entity))

        assert requirement.confirmation is True
        assert len(fake.calls) == 1
        client.chat_delete.assert_awaited_once_with(channel="C123", ts="await-1")
        update = client.chat_update.call_args
        assert update.kwargs["text"] == "Approved"
        card = next(b for b in update.kwargs["blocks"] if b.get("type") == "card")
        assert card["actions"] == []
        assert card["subtext"]["text"] == ":white_check_mark: Approved"

    @pytest.mark.asyncio
    async def test_admin_rejection_resumes_with_rejection(self):
        requirement = _make_requirement(approval_type="required", approval_id="appr-1")
        entity = _make_entity(_paused_run([requirement]))
        entity.db = Mock()
        entity.db.get_approval = Mock(
            return_value={"id": "appr-1", "status": "rejected", "resolution_data": {"note": "not today"}}
        )
        client = make_async_client_mock()
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_check_status(_check_status_payload(), client, make_ctx(agent=entity))

        assert len(fake.calls) == 1
        assert requirement.confirmation is False
        assert requirement.confirmation_note == "not today"
        assert client.chat_update.call_args.kwargs["text"] == "Status: rejected"

    @pytest.mark.asyncio
    async def test_check_status_without_matching_requirement_does_not_continue(self):
        other = _make_requirement(req_id="r9", approval_type="required", approval_id="appr-9")
        entity = _make_entity(_paused_run([other]))
        entity.db = Mock()
        entity.db.get_approval = Mock(return_value={"id": "appr-1", "status": "approved"})
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()
        fake = FakeContinue()

        with patch.object(hitl, "continue_run", new=fake):
            await hitl.handle_check_status(_check_status_payload(), client, ctx)

        assert fake.calls == []
        assert _ephemerals(client) == [hitl._NO_LONGER_ACTIVE_MESSAGE]
        assert other.confirmation is None
        assert ctx.runs.claim_run("run-1") is True

    @pytest.mark.asyncio
    async def test_check_again_never_deletes_thread_root(self):
        requirement = _make_requirement(approval_type="required", approval_id="appr-1")
        entity = _make_entity(_paused_run([requirement]))
        entity.db = Mock()
        entity.db.get_approval = Mock(return_value={"id": "appr-1", "status": "pending"})
        ctx = make_ctx(agent=entity)
        client = make_async_client_mock()

        # The card was posted without an awaiting indicator
        await hitl.handle_check_status(_check_status_payload(awaiting_ts=None), client, ctx)
        refreshed = client.chat_update.call_args.kwargs["blocks"]
        button_value = next(b for b in refreshed if b.get("type") == "card")["actions"][0]["value"]
        payload = _check_status_payload(awaiting_ts=None)
        payload["actions"][0]["value"] = button_value

        entity.db.get_approval = Mock(return_value={"id": "appr-1", "status": "approved"})
        with patch.object(hitl, "continue_run", new=FakeContinue()):
            await hitl.handle_check_status(payload, client, ctx)

        assert "111.222" not in button_value
        client.chat_delete.assert_not_awaited()


def _sse(event: Any) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.to_dict())}\n\n"


def _native_run(requirements: List[RunRequirement], native_state: Dict[str, Any]) -> Mock:
    run_output = _paused_run(requirements)
    run_output.metadata = {"native_hitl": native_state}
    run_output.events = []
    return run_output


def _native_entity(run_output: Any) -> AsyncMock:
    entity = _make_entity(run_output)
    entity.id = "agent-1"
    entity._uses_native_hitl = True
    entity.hitl_timeout = 5
    return entity


def _native_client() -> tuple:
    # The reply streams through the chat.*Stream Web API calls; the client stands in for the stream
    client = make_async_client_mock()
    client.chat_startStream = AsyncMock(return_value={"ok": True, "ts": "333.444"})
    client.chat_appendStream = AsyncMock(return_value={"ok": True})
    client.chat_stopStream = AsyncMock(return_value={"ok": True})
    client.chat_postMessage = AsyncMock(return_value={"ts": "555.666"})
    return client, client


def _input_blocks() -> List[Dict[str, Any]]:
    return _approved_blocks() + [{"type": "input", "block_id": "x"}]


def _appended_text(client: AsyncMock) -> str:
    calls = (
        client.chat_startStream.call_args_list
        + client.chat_appendStream.call_args_list
        + client.chat_stopStream.call_args_list
    )
    return "".join(
        chunk["text"] for c in calls for chunk in c.kwargs.get("chunks") or [] if chunk.get("type") == "markdown_text"
    )


def _pause_cards(client: AsyncMock) -> List[Any]:
    return [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("blocks")]


class TestSandboxNativeApprovals:
    """A live native run (sandboxed Claude Code or Codex) is answered through the run row, never the ticket gate."""

    @pytest.mark.asyncio
    async def test_live_native_decision_skips_gate_and_streams_tail(self):
        run_output = _native_run([_make_requirement()], {"pending": ["nr-1"]})
        entity = _native_entity(run_output)
        submitted = Mock(metadata={"native_hitl": {"decisions": {"nr-1": {"allow": True}}}}, events=[])
        client, stream = _native_client()
        order: List[str] = []

        async def deliver(*args: Any, **kwargs: Any):
            order.append("delivered")
            return submitted, 3

        async def frozen(**kwargs: Any):
            order.append(kwargs["text"])

        client.chat_update = AsyncMock(side_effect=frozen)

        async def tail(run_id: str, from_index: Optional[int] = None):
            assert from_index == 3
            yield _sse(RunContinuedEvent(run_id="run-1", external_agent_request_id="nr-1"))
            yield _sse(RunContentEvent(run_id="run-1", content="Created the file."))
            yield _sse(RunCompletedEvent(run_id="run-1", content="Created the file."))

        gate = AsyncMock(side_effect=AssertionError("a live native decision never reaches the ticket gate"))
        with (
            patch("agno.os.interfaces.slack.executor.adeliver_native_decisions", new=deliver),
            patch("agno.os.interfaces.slack.executor.queued_run_tail_streamer", new=tail),
            patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", new=gate),
        ):
            await hitl.handle_submit(_submit_payload(_input_blocks()), client, make_ctx(agent=entity))

        gate.assert_not_awaited()
        entity.acontinue_run.assert_not_called()
        assert order == ["delivered", "Submitted"]
        assert "Created the file." in _appended_text(stream)
        client.chat_stopStream.assert_awaited()
        assert _pause_cards(client) == []

    @pytest.mark.asyncio
    async def test_refused_native_decision_posts_ephemeral_and_keeps_card(self):
        entity = _native_entity(_native_run([_make_requirement()], {"pending": ["nr-1"]}))
        client, stream = _native_client()
        refuse = AsyncMock(side_effect=ValueError("Run was already continued or is no longer paused"))

        with patch("agno.os.interfaces.slack.executor.adeliver_native_decisions", new=refuse):
            await hitl.handle_submit(_submit_payload(_input_blocks()), client, make_ctx(agent=entity))

        assert _ephemerals(client) == [hitl._NO_LONGER_ACTIVE_MESSAGE]
        client.chat_update.assert_not_awaited()
        client.chat_startStream.assert_not_awaited()
        entity.acontinue_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_native_run_that_is_not_live_gets_no_continue(self):
        # The native execution ended in ERROR (computer lost, or timed out): nothing is delivered or continued
        run_output = _native_run([_make_requirement()], {"pending": ["nr-1"]})
        run_output.status = RunStatus.error
        entity = _native_entity(run_output)
        client, _ = _native_client()
        gate = AsyncMock()
        deliver = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.executor.adeliver_native_decisions", new=deliver),
            patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", new=gate),
        ):
            await hitl.handle_submit(_submit_payload(_input_blocks()), client, make_ctx(agent=entity))

        assert _ephemerals(client) == [hitl._NO_LONGER_ACTIVE_MESSAGE]
        gate.assert_not_awaited()
        deliver.assert_not_awaited()
        entity.acontinue_run.assert_not_called()
        client.chat_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_native_repause_posts_new_card(self):
        entity = _native_entity(_native_run([_make_requirement()], {"pending": ["nr-1"]}))
        submitted = Mock(metadata={"native_hitl": {"decisions": {"nr-1": {"allow": True}}}}, events=[])
        client, _ = _native_client()
        second = _make_requirement(req_id="r2", tool_name="git_push", tool_args={"branch": "main"})

        async def tail(run_id: str, from_index: Optional[int] = None):
            yield _sse(RunContinuedEvent(run_id="run-1", external_agent_request_id="nr-1"))
            yield _sse(RunPausedEvent(run_id="run-1", requirements=[second]))

        with (
            patch(
                "agno.os.interfaces.slack.executor.adeliver_native_decisions",
                new=AsyncMock(return_value=(submitted, 0)),
            ),
            patch("agno.os.interfaces.slack.executor.queued_run_tail_streamer", new=tail),
        ):
            await hitl.handle_submit(_submit_payload(_input_blocks()), client, make_ctx(agent=entity))

        cards = _pause_cards(client)
        assert len(cards) == 1
        assert "r2" in json.dumps(cards[0].kwargs["blocks"])
        assert "git_push" in json.dumps(cards[0].kwargs["blocks"])

    @pytest.mark.parametrize("ending", ["completed", "error"])
    @pytest.mark.asyncio
    async def test_untracked_tail_skips_first_leg_replay(self, ending: str):
        first = _make_requirement()
        entity = _native_entity(_native_run([first], {"pending": ["nr-1"]}))
        submitted = Mock(metadata={"native_hitl": {"decisions": {"nr-1": {"allow": True}}}}, events=[])
        client, stream = _native_client()

        async def tail_stored(*args: Any, **kwargs: Any):
            # A sandboxed row stores its events only at the end, so the tail replays the first leg
            yield RunContentEvent(run_id="run-1", content="Asking first.")
            yield RunPausedEvent(run_id="run-1", requirements=[first])
            if ending == "error":
                yield RunErrorEvent(run_id="run-1", content="The sandbox went away")
                return
            yield RunContinuedEvent(run_id="run-1", external_agent_request_id="nr-1")
            yield RunContentEvent(run_id="run-1", content="Second leg.")
            yield RunCompletedEvent(run_id="run-1", content="Second leg.")

        with (
            patch(
                "agno.os.interfaces.slack.executor.adeliver_native_decisions",
                new=AsyncMock(return_value=(submitted, None)),
            ),
            patch("agno.os.interfaces.slack.executor.tail_stored", new=tail_stored),
        ):
            await hitl.handle_submit(_submit_payload(_input_blocks()), client, make_ctx(agent=entity))

        assert _pause_cards(client) == []
        assert "Asking first." not in _appended_text(stream)
        if ending == "completed":
            assert "Second leg." in _appended_text(stream)
        else:
            assert "The sandbox went away" in _appended_text(stream)
