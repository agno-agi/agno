"""TTL bounds on the in-memory cancellation manager.

cancel_run stores intent even for run ids that never start
(cancel-before-start), and only a completing run calls cleanup_run, so on a
long-lived process the intent dict is only bounded by the TTL. These tests pin
that bound and its parity with the Redis manager's TTL contract, so swapping
managers does not change semantics.
"""

from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

DAY = 60 * 60 * 24


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_manager(ttl_seconds: float = DAY) -> tuple[InMemoryRunCancellationManager, FakeClock]:
    manager = InMemoryRunCancellationManager(ttl_seconds=ttl_seconds)
    clock = FakeClock()
    manager._clock = clock
    return manager, clock


class TestTtlDefaults:
    def test_default_ttl_matches_redis_manager(self):
        assert InMemoryRunCancellationManager.DEFAULT_TTL_SECONDS == DAY
        assert InMemoryRunCancellationManager.DEFAULT_TTL_SECONDS == RedisRunCancellationManager.DEFAULT_TTL_SECONDS
        assert InMemoryRunCancellationManager().ttl_seconds == DAY

    def test_ttl_none_disables_expiry(self):
        manager = InMemoryRunCancellationManager(ttl_seconds=None)
        clock = FakeClock()
        manager._clock = clock
        manager.cancel_run("run-1")
        clock.advance(1000 * DAY)
        assert manager.is_cancelled("run-1") is True


class TestCancelBeforeStartWithTtl:
    def test_intent_survives_within_ttl(self):
        manager, clock = make_manager()
        assert manager.cancel_run("future-run") is False
        clock.advance(DAY - 1)
        manager.register_run("future-run")
        assert manager.is_cancelled("future-run") is True

    def test_intent_expires_after_ttl(self):
        manager, clock = make_manager()
        manager.cancel_run("never-started")
        clock.advance(DAY + 1)
        assert manager.is_cancelled("never-started") is False
        assert manager._cancelled_runs == {}

    def test_reused_id_is_not_insta_cancelled_after_expiry(self):
        """A legitimate run that reuses an id after the intent expired runs normally."""
        manager, clock = make_manager()
        manager.cancel_run("reused-id")
        clock.advance(DAY + 1)
        manager.register_run("reused-id")
        assert manager.is_cancelled("reused-id") is False

    def test_expired_intents_are_purged_on_unrelated_access(self):
        """The dict stays bounded even when the stale ids are never queried again."""
        manager, clock = make_manager()
        for i in range(50):
            manager.cancel_run(f"junk-{i}")
        clock.advance(DAY + 1)
        manager.cancel_run("fresh")
        assert set(manager._cancelled_runs) == {"fresh"}


class TestTtlRefreshParity:
    def test_cancel_refreshes_ttl(self):
        manager, clock = make_manager()
        manager.cancel_run("run-1")
        clock.advance(0.9 * DAY)
        assert manager.cancel_run("run-1") is True
        clock.advance(0.9 * DAY)
        assert manager.is_cancelled("run-1") is True

    def test_register_does_not_refresh_ttl(self):
        manager, clock = make_manager()
        manager.register_run("run-1")
        clock.advance(0.5 * DAY)
        manager.register_run("run-1")
        clock.advance(0.6 * DAY)
        assert "run-1" not in manager.get_active_runs()

    def test_register_does_not_extend_cancel_intent(self):
        manager, clock = make_manager()
        manager.cancel_run("run-1")
        clock.advance(0.9 * DAY)
        manager.register_run("run-1")
        clock.advance(0.2 * DAY)
        assert manager.is_cancelled("run-1") is False

    def test_registered_run_expiry_fails_open(self):
        """A run older than the TTL is not spuriously cancelled, and a cancel
        after expiry reports unregistered but still stores intent."""
        manager, clock = make_manager()
        manager.register_run("long-run")
        clock.advance(DAY + 1)
        assert manager.is_cancelled("long-run") is False
        assert manager.cancel_run("long-run") is False
        assert manager.is_cancelled("long-run") is True

    def test_refresh_does_not_shield_older_siblings_from_purge(self):
        """A refreshed entry must move behind its unexpired peers, or the
        front-of-dict purge would stop at it and never reach expired ones."""
        manager, clock = make_manager()
        manager.cancel_run("refreshed")
        clock.advance(0.1 * DAY)
        manager.cancel_run("stale")
        clock.advance(0.4 * DAY)
        manager.cancel_run("refreshed")
        clock.advance(0.7 * DAY)
        assert manager.get_active_runs() == {"refreshed": True}
        assert "stale" not in manager._cancelled_runs

    def test_member_refresh_does_not_shield_older_teams_from_purge(self):
        manager, clock = make_manager()
        manager.register_member_run("team-refreshed", "member-1")
        clock.advance(0.1 * DAY)
        manager.register_member_run("team-stale", "member-2")
        clock.advance(0.4 * DAY)
        manager.register_member_run("team-refreshed", "member-3")
        clock.advance(0.7 * DAY)
        assert manager.get_member_run_ids("team-refreshed") == {"member-1", "member-3"}
        assert "team-stale" not in manager._member_runs

    def test_purge_preserves_unexpired_entries(self):
        manager, clock = make_manager()
        manager.cancel_run("old")
        clock.advance(0.5 * DAY)
        manager.register_run("mid")
        clock.advance(0.3 * DAY)
        manager.cancel_run("new")
        clock.advance(0.3 * DAY)
        assert manager.get_active_runs() == {"mid": False, "new": True}


class TestMemberRunTtl:
    def test_member_runs_expire(self):
        manager, clock = make_manager()
        manager.register_member_run("team-run", "member-1")
        clock.advance(DAY + 1)
        assert manager.get_member_run_ids("team-run") == set()
        assert manager._member_runs == {}

    def test_member_registration_refreshes_ttl(self):
        manager, clock = make_manager()
        manager.register_member_run("team-run", "member-1")
        clock.advance(0.9 * DAY)
        manager.register_member_run("team-run", "member-2")
        clock.advance(0.6 * DAY)
        assert manager.get_member_run_ids("team-run") == {"member-1", "member-2"}
        clock.advance(0.5 * DAY)
        assert manager.get_member_run_ids("team-run") == set()


class TestAsyncVariants:
    async def test_async_cancel_before_start_expires(self):
        manager, clock = make_manager()
        assert await manager.acancel_run("future-run") is False
        await manager.aregister_run("future-run")
        assert await manager.ais_cancelled("future-run") is True
        clock.advance(DAY + 1)
        assert await manager.ais_cancelled("future-run") is False
        assert manager._cancelled_runs == {}

    async def test_async_cancel_refreshes_and_register_does_not(self):
        manager, clock = make_manager()
        await manager.acancel_run("cancelled")
        await manager.aregister_run("registered")
        clock.advance(0.9 * DAY)
        assert await manager.acancel_run("cancelled") is True
        await manager.aregister_run("registered")
        clock.advance(0.9 * DAY)
        assert await manager.aget_active_runs() == {"cancelled": True}

    async def test_async_member_runs_expire(self):
        manager, clock = make_manager()
        await manager.aregister_member_run("team-run", "member-1")
        clock.advance(DAY + 1)
        assert await manager.aget_member_run_ids("team-run") == set()
        assert manager._member_runs == {}
