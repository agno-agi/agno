"""Unit tests for the shared durable-continue seam helper.

acontinue_via_queue is the one path all four seams (HTTP agents/teams/
workflows + WS continue-workflow) go through: outcome mapping, component-
identity verification, and the PAUSED -> PENDING stream reopen live here, so
the seams cannot diverge on them. Cancellation intent is deliberately NEVER
cleared by the seam (see TestAcceptSideEffects).
"""

import pytest
import pytest_asyncio

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker, acontinue_via_queue


def make_job(job_id: str = "r1", stream: bool = False) -> dict:
    payload = {"input": "hello", "kwargs": {}}
    if stream:
        payload["stream"] = True
    return QueuedJob(
        id=job_id,
        component_type="workflow",
        component_id="wf-1",
        session_id="s1",
        payload=payload,
    ).to_dict()


@pytest_asyncio.fixture(autouse=True)
async def _clean_cancellation_intent():
    """The seam contract deliberately leaves cancellation intent in place
    (nothing auto-cleans anymore), and the process-global manager outlives
    each test - without this, intent for the shared 'r1' run id leaks into
    other suites and cancels their runs."""
    yield
    from agno.run.cancel import acleanup_run

    await acleanup_run("r1")


def make_worker(store: InMemoryQueueStore) -> QueueWorker:
    return QueueWorker(
        store=store,
        resolve_component=lambda t, i: None,
        config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
        worker_id="seam-test-worker",
    )


async def _pause(store: InMemoryQueueStore, job_id: str = "r1", stream: bool = False) -> None:
    await store.enqueue_job(make_job(job_id, stream=stream))
    claimed = await store.claim_job("w1")
    assert await store.complete_job(job_id, "w1", claimed["attempt"], "paused")


class TestOutcomeMapping:
    @pytest.mark.asyncio
    async def test_no_ticket_returns_none_for_detached_fallback(self):
        worker = make_worker(InMemoryQueueStore())
        assert await acontinue_via_queue(worker, "ghost", {}) is None

    @pytest.mark.asyncio
    async def test_paused_ticket_accepts(self):
        store = InMemoryQueueStore()
        await _pause(store)
        result = await acontinue_via_queue(make_worker(store), "r1", {"step_requirements": [{"step_id": "s"}]})
        assert result["outcome"] == "queued"
        assert result["job"]["payload"]["continue"] == {"step_requirements": [{"step_id": "s"}]}

    @pytest.mark.asyncio
    async def test_queued_after_continue_attaches(self):
        store = InMemoryQueueStore()
        await _pause(store)
        worker = make_worker(store)
        await acontinue_via_queue(worker, "r1", {"a": 1})
        result = await acontinue_via_queue(worker, "r1", {"a": 2})
        assert result["outcome"] == "attach"

    @pytest.mark.asyncio
    async def test_queued_fresh_submission_returns_none(self):
        """A queued ticket with no continue block is a not-yet-executed
        submission: continuing it is a state error the detached path reports;
        the seam must NOT attach a continue response to it."""
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job())
        assert await acontinue_via_queue(make_worker(store), "r1", {}) is None

    @pytest.mark.asyncio
    async def test_running_ticket_is_settling(self):
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job())
        await store.claim_job("w1")
        result = await acontinue_via_queue(make_worker(store), "r1", {})
        assert result["outcome"] == "settling"

    @pytest.mark.asyncio
    async def test_terminal_ticket_returns_none(self):
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job())
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        assert await acontinue_via_queue(make_worker(store), "r1", {}) is None

    @pytest.mark.asyncio
    async def test_cancelled_ticket_returns_none_not_resurrect(self):
        """Cancel-while-paused then continue: the ticket is terminal, the
        durable path declines, and the detached path's own not-paused check
        reports the state - the run is never silently resurrected."""
        store = InMemoryQueueStore()
        await _pause(store)
        assert await store.cancel_job("r1")
        assert await acontinue_via_queue(make_worker(store), "r1", {}) is None


class TestComponentIdentity:
    @pytest.mark.asyncio
    async def test_cross_component_continue_declines_the_durable_path(self):
        """harshsinha03 review: an agent's paused ticket continued through
        the TEAMS endpoint reached the CAS - the ticket got a team-shaped
        requirements block and the worker resolved the pending approval as
        rejected while the caller got a 202. The helper must verify the
        ticket belongs to the component the caller is continuing through;
        mismatches fall to the detached path, whose own run lookup reports
        not-found honestly."""
        store = InMemoryQueueStore()
        await _pause(store)  # ticket: component_type=workflow, component_id=wf-1
        worker = make_worker(store)

        wrong_type = await acontinue_via_queue(worker, "r1", {"a": 1}, component_type="team", component_id="wf-1")
        assert wrong_type is None
        wrong_id = await acontinue_via_queue(worker, "r1", {"a": 1}, component_type="workflow", component_id="other")
        assert wrong_id is None
        assert (await store.get_job("r1"))["status"] == "paused", "no CAS may fire on a mismatched ticket"

        matching = await acontinue_via_queue(worker, "r1", {"a": 1}, component_type="workflow", component_id="wf-1")
        assert matching is not None and matching["outcome"] == "queued"


class TestAcceptSideEffects:
    @pytest.mark.asyncio
    async def test_accept_never_touches_cancellation_intent(self):
        """The seam does NOT clear cancellation intent - every automatic
        deletion scheme had a delayed-cleanup window that could erase a
        newer legitimate cancel. Stale intent survives the accept: the leg
        will cancel visibly at its first checkpoint, and the operator
        remedy is requeue with clear_cancellation=true."""
        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await _pause(store)
        await aregister_run("r1")
        await acancel_run("r1")
        assert await ais_cancelled("r1")
        result = await acontinue_via_queue(make_worker(store), "r1", {})
        assert result["outcome"] == "queued"
        assert await ais_cancelled("r1"), "the seam must never delete cancellation intent"

    @pytest.mark.asyncio
    async def test_stream_status_flipped_to_pending_on_accept(self):
        """PAUSED is tail-terminal: without the flip, a tail attached between
        accept and claim replays the settled pause and closes."""
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            await _pause(store, stream=True)
            await stream.register_run("r1", RunStatus.pending)
            await stream.complete_run("r1", RunStatus.paused)
            assert await stream.get_run_status("r1") == RunStatus.paused

            result = await acontinue_via_queue(make_worker(store), "r1", {})
            assert result["outcome"] == "queued"
            assert await stream.get_run_status("r1") == RunStatus.pending
        finally:
            es_mod._event_stream = original

    @pytest.mark.asyncio
    async def test_pending_flip_never_overwrites_a_terminal_status(self):
        """Codex P1: a fast worker can claim and finish the whole leg between
        the CAS and the flip - PENDING must not overwrite its terminal
        status, or tails wait on a finished run. The flip is conditional on
        the status still being PAUSED."""
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            await _pause(store, stream=True)
            await stream.register_run("r1", RunStatus.pending)
            await stream.complete_run("r1", RunStatus.paused)

            # Simulate the racing worker: the leg completes the instant the
            # ticket becomes claimable (i.e. during continue_job)
            original_continue = store.continue_job

            async def continue_then_finish(job_id, continue_payload):
                result = await original_continue(job_id, continue_payload)
                await stream.complete_run(job_id, RunStatus.completed)
                return result

            store.continue_job = continue_then_finish  # type: ignore[method-assign]
            result = await acontinue_via_queue(make_worker(store), "r1", {})
            assert result["outcome"] == "queued"
            assert await stream.get_run_status("r1") == RunStatus.completed, (
                "the racing worker's terminal status must survive the flip"
            )
        finally:
            es_mod._event_stream = original

    @pytest.mark.asyncio
    async def test_stream_mismatch_refused_before_the_cas(self):
        """Codex P1: a stream-continue of a non-streaming submission must be
        refused BEFORE the CAS - refusing after it tells the client the
        continuation was rejected while a worker executes it anyway."""
        store = InMemoryQueueStore()
        await _pause(store, stream=False)
        result = await acontinue_via_queue(make_worker(store), "r1", {"a": 1}, stream_requested=True)
        assert result["outcome"] == "stream_mismatch"
        ticket = await store.get_job("r1")
        assert ticket["status"] == "paused", "the refusal must leave no accepted continuation behind"
        assert "continue" not in (ticket.get("payload") or {})
        # A matching non-stream continue still accepts afterwards
        result = await acontinue_via_queue(make_worker(store), "r1", {"a": 1})
        assert result["outcome"] == "queued"

    @pytest.mark.asyncio
    async def test_tail_floor_captured_before_acceptance(self):
        """Codex P1: the tail floor must pre-date the CAS - read after it, a
        fast worker's first continuation events inflate the count and the
        tail silently skips the start of the continuation output."""
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:

            class _Evt:
                def __init__(self, name: str) -> None:
                    self.event = name

                def to_dict(self) -> dict:
                    return {"event": self.event}

            store = InMemoryQueueStore()
            await _pause(store, stream=True)
            await stream.register_run("r1", RunStatus.pending)
            for _ in range(3):  # leg-1 events, settled at the pause
                await stream.add_event("r1", _Evt("LegOne"))
            pre_count = await stream.get_event_count("r1")

            # Racing worker: continuation events land the instant the ticket
            # becomes claimable
            original_continue = store.continue_job

            async def continue_then_publish(job_id, continue_payload):
                result = await original_continue(job_id, continue_payload)
                await stream.add_event(job_id, _Evt("LegTwoFirst"))
                await stream.add_event(job_id, _Evt("LegTwoSecond"))
                return result

            store.continue_job = continue_then_publish  # type: ignore[method-assign]
            result = await acontinue_via_queue(make_worker(store), "r1", {})
            assert result["outcome"] == "queued"
            assert result["tail_from"] == pre_count - 1, (
                "the floor must be the pre-accept index, not one inflated by the racing leg"
            )
        finally:
            es_mod._event_stream = original

    @pytest.mark.asyncio
    async def test_delayed_cleanup_cannot_erase_a_newer_cancel(self):
        """Review-round-4 P1, the exact race - now closed STRUCTURALLY: the
        seam performs no cleanup at all, so however delayed the accepting
        request is, a legitimate cancel landing after the claim always
        survives."""
        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await _pause(store)
        await aregister_run("r1")
        await acancel_run("r1")  # stale intent from the paused stretch (token A)

        original_continue = store.continue_job

        async def continue_then_claim_and_cancel(job_id, continue_payload):
            # Everything the reviewer's race needs happens "during" the CAS
            # window from the accepting request's point of view: the ticket
            # is claimed and a NEW legitimate cancel lands (token B) before
            # the delayed cleanup runs
            result = await original_continue(job_id, continue_payload)
            await store.claim_job("w-fast")
            await acancel_run(job_id)  # legitimate cancel of the claimed leg
            return result

        store.continue_job = continue_then_claim_and_cancel  # type: ignore[method-assign]
        result = await acontinue_via_queue(make_worker(store), "r1", {})
        assert result["outcome"] == "queued"
        assert await ais_cancelled("r1"), "the delayed token-scoped cleanup must NOT erase the newer legitimate cancel"

    @pytest.mark.asyncio
    async def test_no_pre_cas_intent_means_no_cleanup_at_all(self):
        """A cancel arriving right after acceptance is legitimate by
        definition and must survive untouched (the seam never cleans)."""
        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await _pause(store)

        original_continue = store.continue_job

        async def continue_then_cancel(job_id, continue_payload):
            result = await original_continue(job_id, continue_payload)
            await aregister_run(job_id)
            await acancel_run(job_id)  # lands right after acceptance
            return result

        store.continue_job = continue_then_cancel  # type: ignore[method-assign]
        result = await acontinue_via_queue(make_worker(store), "r1", {})
        assert result["outcome"] == "queued"
        assert await ais_cancelled("r1"), "a cancel arriving after acceptance must survive untouched"

    @pytest.mark.asyncio
    async def test_attach_loser_never_clears_intent(self):
        """The CAS loser (double-click / stale reader) must not touch
        cancellation state: an intent registered against the winner's leg
        survives the loser's attach."""
        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await _pause(store)
        worker = make_worker(store)
        assert (await acontinue_via_queue(worker, "r1", {"a": 1}))["outcome"] == "queued"
        # A cancel now targets the accepted continuation
        await aregister_run("r1")
        await acancel_run("r1")

        result = await acontinue_via_queue(worker, "r1", {"a": 2})
        assert result["outcome"] == "attach"
        assert await ais_cancelled("r1"), "the losing continue must not erase the cancel aimed at the winner's leg"

    @pytest.mark.asyncio
    async def test_attach_uses_winners_persisted_tail_boundary(self):
        """Review-round-2 P2: by attach time the accepted leg may already be
        publishing; a recomputed floor would skip its early events for the
        attacher. The winner's boundary is persisted in the ticket payload
        at CAS time and every attacher reads THAT."""
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        class _Evt:
            def __init__(self, name: str) -> None:
                self.event = name

            def to_dict(self) -> dict:
                return {"event": self.event}

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            await _pause(store, stream=True)
            await stream.register_run("r1", RunStatus.pending)
            for _ in range(3):
                await stream.add_event("r1", _Evt("LegOne"))

            worker = make_worker(store)
            accepted = await acontinue_via_queue(worker, "r1", {"a": 1})
            assert accepted["outcome"] == "queued"
            winner_floor = accepted["tail_from"]
            assert accepted["job"]["payload"]["continue"]["tail_from"] == winner_floor

            # The claimed leg starts publishing before the double-click lands
            await stream.add_event("r1", _Evt("LegTwoFirst"))
            await stream.add_event("r1", _Evt("LegTwoSecond"))

            attached = await acontinue_via_queue(worker, "r1", {"a": 2})
            assert attached["outcome"] == "attach"
            assert attached["tail_from"] == winner_floor, (
                "the attacher must start from the accepted click's boundary, not skip the leg's early events"
            )
        finally:
            es_mod._event_stream = original

    def _requeue_endpoint(self, store):
        from types import SimpleNamespace

        from agno.os.routers.job_queue.router import get_queue_router

        router = get_queue_router(os=SimpleNamespace(), settings=SimpleNamespace(os_security_key=None))  # type: ignore[arg-type]
        endpoint = next(r.endpoint for r in router.routes if getattr(r, "path", "") == "/queue/jobs/{job_id}/requeue")
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(queue_worker=make_worker(store))),
            state=SimpleNamespace(),
        )
        return endpoint, request

    @pytest.mark.asyncio
    async def test_requeue_preserves_intent_unless_operator_clears(self):
        """Intent clearing is an EXPLICIT operator action, never automatic:
        a plain requeue leaves recorded intent alone (the re-driven attempt
        re-cancels visibly); clear_cancellation=true is the deliberate
        human override for requeueing a previously cancelled job."""
        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom")  # -> failed
        await aregister_run("r1")
        await acancel_run("r1")

        endpoint, request = self._requeue_endpoint(store)
        result = await endpoint(request, "r1")
        assert result["status"] == "queued"
        assert await ais_cancelled("r1"), "a plain requeue must not touch recorded intent"

        # Re-drive once more, this time with the explicit override
        reclaimed = await store.claim_job("w1")
        await store.retry_or_fail_job("r1", "w1", reclaimed["attempt"], "boom again")
        result = await endpoint(request, "r1", clear_cancellation=True)
        assert result["status"] == "queued"
        assert not await ais_cancelled("r1"), "clear_cancellation=true is the operator's explicit clear"

    @pytest.mark.asyncio
    async def test_rejected_requeue_never_touches_intent(self):
        """Review-round-3 P1 regression: requeueing a RUNNING (non-requeueable)
        job must not erase the cancellation intent aimed at that attempt."""
        from fastapi import HTTPException

        from agno.run.cancel import acancel_run, ais_cancelled, aregister_run

        store = InMemoryQueueStore()
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")  # running
        await aregister_run("r1")
        await acancel_run("r1")  # legitimate cancel of the running attempt

        endpoint, request = self._requeue_endpoint(store)
        with pytest.raises(HTTPException) as exc:
            await endpoint(request, "r1")
        assert exc.value.status_code == 400
        assert await ais_cancelled("r1"), "a rejected requeue must leave the running attempt's cancel intact"

    @pytest.mark.asyncio
    async def test_post_cas_attach_uses_winners_persisted_boundary(self):
        """Review-round-3 P2: two callers both read paused; the loser's CAS
        returns attach AFTER its own floor was recomputed - possibly past the
        winner-leg's first events. The loser must adopt the boundary the
        winner persisted into the ticket, not its own."""
        store = InMemoryQueueStore()
        await _pause(store, stream=True)

        original_continue = store.continue_job

        async def losing_continue(job_id, continue_payload):
            # Simulate the race: the winner's CAS landed first (boundary 3
            # persisted); this caller's CAS finds queued and attaches
            await original_continue(job_id, {"a": "winner", "tail_from": 3})
            return await original_continue(job_id, continue_payload)

        store.continue_job = losing_continue  # type: ignore[method-assign]
        result = await acontinue_via_queue(make_worker(store), "r1", {"a": "loser"})
        assert result["outcome"] == "attach"
        assert result["tail_from"] == 3, "the loser must adopt the winner's persisted boundary"

    @pytest.mark.asyncio
    async def test_non_stream_submission_does_not_touch_stream_status(self):
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            await _pause(store, stream=False)
            result = await acontinue_via_queue(make_worker(store), "r1", {})
            assert result["outcome"] == "queued"
            assert await stream.get_run_status("r1") is None, "non-stream runs have no stream view to touch"
        finally:
            es_mod._event_stream = original


class TestContinueStreamEventsPrecedence:
    @pytest.mark.asyncio
    async def test_kwargs_stream_events_hoisted_into_continue_block(self):
        """The CONTINUE request's stream_events must reach the worker: the
        HTTP doors sweep it into continue_payload['kwargs'], where
        _continuation_kwargs strips it as reserved - the seam hoists it to
        the top of the continue block, which wins over the submit payload."""
        store = InMemoryQueueStore()
        await _pause(store)
        result = await acontinue_via_queue(
            make_worker(store), "r1", {"updated_tools": [], "kwargs": {"stream_events": False}}
        )
        assert result["outcome"] == "queued"
        stored = (await store.get_job("r1"))["payload"]["continue"]
        assert stored["stream_events"] is False, "the continue request's choice must be persisted for the worker"

    @pytest.mark.asyncio
    async def test_explicit_top_level_value_is_not_clobbered(self):
        store = InMemoryQueueStore()
        await _pause(store)
        result = await acontinue_via_queue(
            make_worker(store), "r1", {"stream_events": True, "kwargs": {"stream_events": False}}
        )
        assert result["outcome"] == "queued"
        stored = (await store.get_job("r1"))["payload"]["continue"]
        assert stored["stream_events"] is True
