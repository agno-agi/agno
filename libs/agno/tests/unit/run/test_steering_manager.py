"""The in-memory steering manager: when input is accepted, and that accepted input is never lost."""

import threading

import pytest

from agno.models.message import Message
from agno.run.steering import RunSteering, _to_messages, steer_run
from agno.run.steering_management import InMemoryRunSteeringManager


def _msg(text: str) -> Message:
    return Message(role="user", content=text)


def test_input_is_refused_before_the_run_opens_its_inbox():
    manager = InMemoryRunSteeringManager()
    assert manager.steer("run-1", [_msg("hello")]) is False


def test_open_run_accepts_input_and_take_returns_it_in_order():
    manager = InMemoryRunSteeringManager()
    manager.open_run("run-1")
    assert manager.steer("run-1", [_msg("first")]) is True
    assert manager.steer("run-1", [_msg("second")]) is True

    assert [m.content for m in manager.take("run-1")] == ["first", "second"]
    assert manager.take("run-1") == []


def test_take_or_close_returns_pending_input_and_keeps_accepting():
    manager = InMemoryRunSteeringManager()
    manager.open_run("run-1")
    manager.steer("run-1", [_msg("wait, one more thing")])

    assert [m.content for m in manager.take_or_close("run-1")] == ["wait, one more thing"]
    # The loop makes another request, so the run must still accept input
    assert manager.steer("run-1", [_msg("and another")]) is True


def test_take_or_close_with_nothing_pending_refuses_later_input():
    manager = InMemoryRunSteeringManager()
    manager.open_run("run-1")

    assert manager.take_or_close("run-1") == []
    assert manager.steer("run-1", [_msg("too late")]) is False


def test_every_accepted_steer_is_taken_when_a_steer_races_the_close():
    """A steer racing the finishing loop is either taken or refused, never accepted and dropped."""
    manager = InMemoryRunSteeringManager()
    for trial in range(500):
        run_id = f"run-{trial}"
        manager.open_run(run_id)
        accepted = []
        start = threading.Barrier(2)

        def user(run_id=run_id, accepted=accepted, start=start):
            start.wait()
            if manager.steer(run_id, [_msg("racing")]):
                accepted.append(run_id)

        thread = threading.Thread(target=user)
        thread.start()
        start.wait()
        taken = manager.take_or_close(run_id)
        thread.join()
        # If input was taken the loop answers it and tries to finish again
        taken += manager.take_or_close(run_id)
        assert len(taken) == len(accepted)
        assert manager.steer(run_id, [_msg("after close")]) is False


def test_take_or_close_on_an_unknown_run_returns_nothing():
    manager = InMemoryRunSteeringManager()
    assert manager.take_or_close("never-opened") == []


def test_release_keeps_undelivered_input_for_the_next_leg():
    manager = InMemoryRunSteeringManager()
    manager.open_run("run-1")
    manager.steer("run-1", [_msg("arrived while the batch paused")])

    manager.release_run("run-1")
    # Paused: refuses new input, keeps what it accepted
    assert manager.steer("run-1", [_msg("while paused")]) is False

    manager.open_run("run-1")
    assert [m.content for m in manager.take("run-1")] == ["arrived while the batch paused"]


def test_release_with_nothing_pending_forgets_the_run():
    manager = InMemoryRunSteeringManager()
    manager.open_run("run-1")
    manager.release_run("run-1")
    assert "run-1" not in manager._inboxes


def test_released_input_expires_after_ttl():
    now = [1000.0]
    manager = InMemoryRunSteeringManager(ttl_seconds=10)
    manager._clock = lambda: now[0]
    manager.open_run("abandoned")
    manager.steer("abandoned", [_msg("never continued")])
    manager.release_run("abandoned")

    now[0] += 11
    manager.open_run("another-run")
    assert "abandoned" not in manager._inboxes


def test_an_open_inbox_never_expires():
    now = [1000.0]
    manager = InMemoryRunSteeringManager(ttl_seconds=10)
    manager._clock = lambda: now[0]
    manager.open_run("long-run")

    now[0] += 1_000_000
    manager.open_run("another-run")
    assert manager.steer("long-run", [_msg("still running")]) is True


@pytest.mark.asyncio
async def test_async_methods_share_state_with_sync_methods():
    manager = InMemoryRunSteeringManager()
    await manager.aopen_run("run-1")
    assert manager.steer("run-1", [_msg("from a thread")]) is True
    assert await manager.asteer("run-1", [_msg("from the loop")]) is True
    assert [m.content for m in await manager.atake_or_close("run-1")] == ["from a thread", "from the loop"]
    assert await manager.atake_or_close("run-1") == []
    assert await manager.asteer("run-1", [_msg("closed")]) is False


def test_steering_input_normalization():
    assert _to_messages("hi")[0].role == "user"
    message = Message(role="user", content="as-is")
    assert _to_messages(message) == [message]
    with pytest.raises(ValueError):
        _to_messages("   ")
    with pytest.raises(TypeError):
        _to_messages(42)  # type: ignore[arg-type]


def test_run_steering_handle_survives_a_failing_backend():
    class _Broken(InMemoryRunSteeringManager):
        def take(self, run_id):
            raise ConnectionError("backend down")

    steering = RunSteering("run-1", manager=_Broken())
    steering.open()
    assert steering.take() == []


def test_module_level_steer_run_refuses_unknown_runs():
    assert steer_run("no-such-run", "hello") is False
