import asyncio
from unittest.mock import Mock, patch

import pytest

from agno.os.interfaces.slack import runs as runs_module
from agno.os.interfaces.slack.runs import SlackRuns

from .conftest import make_event_context


class TestTaskSet:
    @pytest.mark.asyncio
    async def test_spawn_keeps_a_reference_until_done(self):
        runs = SlackRuns()
        gate = asyncio.Event()
        task = runs.spawn(gate.wait())
        assert task in runs._tasks
        gate.set()
        await task
        await asyncio.sleep(0)
        assert task not in runs._tasks

    @pytest.mark.asyncio
    async def test_aclose_drains_then_cancels(self):
        runs = SlackRuns()
        finished = runs.spawn(asyncio.sleep(0.01))
        hanging = runs.spawn(asyncio.sleep(60))
        await runs.aclose(timeout=0.1)
        assert finished.done() and not finished.cancelled()
        assert hanging.cancelled()


class TestRunIndex:
    def test_register_keeps_the_first_event_context_of_a_run(self):
        runs = SlackRuns()
        first, second = make_event_context(run_id="r1"), make_event_context(run_id="r1")
        runs.register(first)
        runs.register(second)
        assert runs.find_run("r1") is first

    def test_find_by_stream_message_returns_the_owning_event_context(self):
        runs = SlackRuns()
        a, b = make_event_context(run_id="ra"), make_event_context(run_id="rb")
        runs.register(a)
        runs.register(b)
        runs.attach_ts("rb", "200.1")
        runs.attach_ts("rb", "300.1")
        assert runs.find("C1", "100.1", ["300.1"]) == [b]
        assert b.streaming_message_ts == ["200.1", "300.1"]

    def test_find_by_unknown_stream_message_is_empty(self):
        runs = SlackRuns()
        runs.register(make_event_context(run_id="r1"))
        assert runs.find("C1", "100.1", ["999.1"]) == []

    def test_find_without_ts_returns_running_runs_not_parked(self):
        runs = SlackRuns()
        running, parked = make_event_context(run_id="ra"), make_event_context(run_id="rb")
        runs.register(running)
        runs.register(parked)
        runs.attach_ts("rb", "200.1")
        runs.park_paused(parked, card_ts="250.1")
        assert runs.find("C1", "100.1", []) == [running]
        # A parked run is still found by its own stream message
        assert runs.find("C1", "100.1", ["200.1"]) == [parked]
        assert runs.parked_cards("rb") == ("250.1", None)

    def test_find_is_per_thread(self):
        runs = SlackRuns()
        runs.register(make_event_context(run_id="ra", thread_ts="100.1"))
        runs.register(make_event_context(run_id="rb", thread_ts="200.1"))
        assert [t.run_id for t in runs.find("C1", "200.1")] == ["rb"]

    def test_unregister_forgets_the_event_context(self):
        runs = SlackRuns()
        runs.register(make_event_context(run_id="r1"))
        runs.mark_started("r1")
        runs.unregister("r1")
        assert runs.find_run("r1") is None
        assert not runs.is_started("r1")

    def test_register_unparks_a_continued_run(self):
        runs = SlackRuns()
        event_context = make_event_context(run_id="r1")
        runs.register(event_context)
        runs.park_paused(event_context)
        assert runs.is_parked("r1")
        runs.register(event_context)
        assert not runs.is_parked("r1")
        assert runs.find_run("r1") is event_context

    def test_rekey_moves_everything_to_the_live_id(self):
        runs = SlackRuns()
        event_context = make_event_context(run_id="local")
        runs.register(event_context)
        runs.mark_started("local")
        stream = Mock()
        runs.set_stream("local", stream)
        runs.rekey("local", "remote")
        assert event_context.run_id == "remote"
        # The old id stays an alias, so a redelivery of the message finds the live event context
        assert runs.find_run("local") is event_context
        assert runs.find_run("remote") is event_context
        assert runs.is_started("remote")
        assert runs.stream_for("remote") is stream
        runs.unregister("remote")
        assert runs.find("C1", "100.1") == []
        assert runs.find_run("local") is None


class TestTtls:
    def test_stop_expires_and_park_stays_until_the_run_continues(self):
        fake_time = Mock()
        fake_time.monotonic.return_value = 1000.0
        with patch.object(runs_module, "time", fake_time):
            runs = SlackRuns()
            event_context = make_event_context(run_id="r1")
            runs.register(event_context)
            runs.park_paused(event_context, card_ts="250.1")
            runs.record_stop("r1")
            assert runs.is_parked("r1") and runs.was_stopped("r1")
            assert not runs.was_stopped("r2")
            fake_time.monotonic.return_value = 1000.0 + SlackRuns.TTL_SECONDS + 1
            assert not runs.was_stopped("r1")
            # An approval card older than the TTL can still be stopped, and is frozen at shutdown
            assert runs.find_run("r1") is event_context
            assert runs.parked() == [event_context]
            assert runs.parked_cards("r1") == ("250.1", None)

    def test_parked_runs_are_bounded(self):
        with patch.object(runs_module.LookupCache, "LOOKUP_MAX_ENTRIES", 2):
            runs = SlackRuns()
            for run_id in ("r1", "r2", "r3"):
                runs.park_paused(make_event_context(run_id=run_id), card_ts=f"{run_id}.card")
            assert [event_context.run_id for event_context in runs.parked()] == ["r2", "r3"]
            assert runs.parked_cards("r1") == (None, None)

    def test_thread_start_markers_are_bounded(self):
        with patch.object(runs_module.LookupCache, "LOOKUP_MAX_ENTRIES", 2):
            runs = SlackRuns()
            for ts in ("1.0", "2.0", "3.0"):
                runs.mark_thread_started("C1", ts)
            assert runs.take_thread_started("C1", "1.0") is False
            assert runs.take_thread_started("C1", "3.0") is True
            assert runs.take_thread_started("C1", "3.0") is False


class TestClaims:
    def test_claim_is_exclusive_until_released(self):
        runs = SlackRuns()
        assert runs.claim_run("r1") is True
        assert runs.claim_run("r1") is False
        runs.release_run("r1")
        assert runs.claim_run("r1") is True
