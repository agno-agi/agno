"""Live PostgreSQL coverage for the v2.9 schedule migration."""

import time
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agno.db.migrations.versions import v2_9_0
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.schemas.scheduler import ScheduleNameConflictError


def _manual_claim_schedule(schedule_id: str) -> dict:
    return {
        "id": schedule_id,
        "name": schedule_id,
        "method": "POST",
        "endpoint": "/external",
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": int(time.time()) + 9999,
        "created_at": int(time.time()),
    }



def _force_schedule_row(db, schedule_id, **cols):
    """Rig lock/run state directly at the table: update_schedule guards these columns."""
    table = db._get_table(table_type="schedules")
    with db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == schedule_id).values(**cols))


async def _aforce_schedule_row(db, schedule_id, **cols):
    table = await db._get_table(table_type="schedules")
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(table.update().where(table.c.id == schedule_id).values(**cols))

def _assert_sync_stale_manual_recovery(db: PostgresDb) -> None:
    schedule = _manual_claim_schedule(f"manual-{uuid.uuid4().hex}")
    now = int(time.time())
    future = now + 9999
    db.create_schedule(schedule)
    try:
        db.trigger_schedule(schedule["id"])
        abandoned = db.claim_due_schedule("dead-worker")
        assert abandoned is not None and abandoned["manual_trigger_claimed"] is True

        stale_fence = now - 600
        _force_schedule_row(db, schedule["id"], locked_at=stale_fence)
        with patch("agno.db.postgres.postgres.time.time", return_value=stale_fence):
            renewed_at = db.renew_schedule_claim(
                schedule["id"],
                worker_id="dead-worker",
                locked_at=stale_fence,
            )
        assert renewed_at == stale_fence + 1
        assert not db.release_schedule(schedule["id"], worker_id="dead-worker", locked_at=stale_fence)

        _force_schedule_row(db, schedule["id"], locked_at=now - 600, next_run_at=now - 1)
        recovered = db.claim_due_schedule("recovery-worker")
        assert recovered is not None
        assert recovered["pending_trigger_count"] == 0
        assert recovered["manual_trigger_claimed"] is True
        assert not db.release_schedule(
            schedule["id"],
            worker_id=abandoned["locked_by"],
            locked_at=abandoned["locked_at"],
        )
        assert db.release_schedule(
            schedule["id"],
            worker_id=recovered["locked_by"],
            locked_at=recovered["locked_at"],
        )

        cron_claim = db.claim_due_schedule("cron-worker")
        assert cron_claim is not None and cron_claim["manual_trigger_claimed"] is False
        assert db.release_schedule(
            schedule["id"],
            next_run_at=future,
            worker_id=cron_claim["locked_by"],
            locked_at=cron_claim["locked_at"],
        )
        assert db.claim_due_schedule("extra-worker") is None
    finally:
        db.delete_schedule(schedule["id"])


def test_postgres_schedule_migration_is_reversible_and_preserves_legacy_rows(
    postgres_db_real: PostgresDb,
) -> None:
    schema = postgres_db_real.db_schema
    table_name = postgres_db_real.schedules_table_name
    runs_table_name = postgres_db_real.schedule_runs_table_name
    qualified_table = f'"{schema}"."{table_name}"'
    qualified_runs_table = f'"{schema}"."{runs_table_name}"'

    with postgres_db_real.Session() as session, session.begin():
        session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        session.execute(text(f"DROP TABLE IF EXISTS {qualified_runs_table} CASCADE"))
        session.execute(text(f"DROP TABLE IF EXISTS {qualified_table} CASCADE"))
        session.execute(
            text(
                f"""
                CREATE TABLE {qualified_table} (
                    id VARCHAR PRIMARY KEY NOT NULL,
                    name VARCHAR NOT NULL,
                    description VARCHAR,
                    method VARCHAR NOT NULL,
                    endpoint VARCHAR NOT NULL,
                    payload JSON,
                    cron_expr VARCHAR NOT NULL,
                    timezone VARCHAR NOT NULL,
                    timeout_seconds BIGINT NOT NULL,
                    max_retries BIGINT NOT NULL,
                    retry_delay_seconds BIGINT NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    next_run_at BIGINT,
                    locked_by VARCHAR,
                    locked_at BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT
                )
                """
            )
        )
        session.execute(
            text(
                f"""
                INSERT INTO {qualified_table} (
                    id, name, method, endpoint, cron_expr, timezone,
                    timeout_seconds, max_retries, retry_delay_seconds,
                    enabled, created_at
                ) VALUES
                    ('legacy-1', 'legacy-one', 'POST', '/external', '0 9 * * *', 'UTC', 3600, 0, 60, true, 1),
                    ('legacy-2', 'legacy-two', 'POST', '/external', '0 10 * * *', 'UTC', 3600, 0, 60, true, 1)
                """
            )
        )

    assert v2_9_0.up(postgres_db_real, "schedules", table_name) is True

    with postgres_db_real.Session() as session:
        columns = {
            row.column_name
            for row in session.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table_name
                    """
                ),
                {"schema": schema, "table_name": table_name},
            )
        }
        legacy_row = session.execute(
            text(
                f"""
                SELECT managed_by, owner_actor_id, target_type, target_id
                FROM {qualified_table}
                WHERE id = 'legacy-1'
                """
            )
        ).one()
        indexes = {
            row.indexname
            for row in session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = :schema AND tablename = :table_name
                    """
                ),
                {"schema": schema, "table_name": table_name},
            )
        }

    assert set(v2_9_0._V2_9_COLUMNS).issubset(columns)
    assert tuple(legacy_row) == (None, None, None, None)
    assert {
        f"{table_name}_uq_generic_name",
        f"{table_name}_uq_studio_owner_name",
    }.issubset(indexes)

    with pytest.raises(IntegrityError):
        with postgres_db_real.Session() as session, session.begin():
            session.execute(
                text(
                    f"""
                    INSERT INTO {qualified_table} (
                        id, name, method, endpoint, cron_expr, timezone,
                        timeout_seconds, max_retries, retry_delay_seconds,
                        enabled, created_at
                    ) VALUES (
                        'duplicate-name', 'legacy-one', 'POST', '/external',
                        '0 11 * * *', 'UTC', 3600, 0, 60, true, 1
                    )
                    """
                )
            )

    duplicate_schedule = {
        "id": "adapter-duplicate-name",
        "name": "legacy-one",
        "method": "POST",
        "endpoint": "/external",
        "cron_expr": "0 11 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "created_at": 1,
    }
    with pytest.raises(ScheduleNameConflictError, match="legacy-one"):
        postgres_db_real.create_schedule(duplicate_schedule)
    with pytest.raises(ScheduleNameConflictError, match="legacy-one"):
        postgres_db_real.update_schedule("legacy-2", name="legacy-one")

    with postgres_db_real.Session() as session, session.begin():
        session.execute(
            text(
                f"""
                UPDATE {qualified_table}
                SET managed_by = 'studio',
                    owner_actor_id = 'actor-1',
                    target_type = 'agent',
                    target_id = 'private-agent',
                    payload = '{{"message": "private prompt"}}'
                WHERE id = 'legacy-2'
                """
            )
        )
        session.execute(
            text(
                f"""
                CREATE TABLE {qualified_runs_table} (
                    id VARCHAR PRIMARY KEY NOT NULL,
                    schedule_id VARCHAR NOT NULL REFERENCES {qualified_table}(id) ON DELETE CASCADE,
                    input JSON,
                    output JSON
                )
                """
            )
        )
        session.execute(
            text(
                f"""
                INSERT INTO {qualified_runs_table} (id, schedule_id, input, output)
                VALUES (
                    'studio-run',
                    'legacy-2',
                    '{{"message": "private prompt"}}',
                    '{{"content": "private response"}}'
                )
                """
            )
        )

    with pytest.raises(ValueError, match="Cannot remove Studio schedule provenance"):
        v2_9_0.down(postgres_db_real, "schedules", table_name)

    with postgres_db_real.Session() as session, session.begin():
        protected_schedule = session.execute(
            text(f"SELECT managed_by, owner_actor_id, payload FROM {qualified_table} WHERE id = 'legacy-2'")
        ).one()
        protected_run = session.execute(
            text(f"SELECT input, output FROM {qualified_runs_table} WHERE id = 'studio-run'")
        ).one()
        columns_after_refusal = {
            row.column_name
            for row in session.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table_name
                    """
                ),
                {"schema": schema, "table_name": table_name},
            )
        }
        indexes_after_refusal = {
            row.indexname
            for row in session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = :schema AND tablename = :table_name
                    """
                ),
                {"schema": schema, "table_name": table_name},
            )
        }
        session.execute(text(f"DELETE FROM {qualified_table} WHERE id = 'legacy-2'"))

    assert tuple(protected_schedule[:2]) == ("studio", "actor-1")
    assert protected_schedule.payload == {"message": "private prompt"}
    assert protected_run.input == {"message": "private prompt"}
    assert protected_run.output == {"content": "private response"}
    assert set(v2_9_0._V2_9_COLUMNS).issubset(columns_after_refusal)
    assert {
        f"{table_name}_uq_generic_name",
        f"{table_name}_uq_studio_owner_name",
    }.issubset(indexes_after_refusal)

    assert v2_9_0.down(postgres_db_real, "schedules", table_name) is True

    with postgres_db_real.Session() as session, session.begin():
        columns_after = {
            row.column_name
            for row in session.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table_name
                    """
                ),
                {"schema": schema, "table_name": table_name},
            )
        }
        indexes_after = {
            row.indexname
            for row in session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = :schema AND tablename = :table_name
                    """
                ),
                {"schema": schema, "table_name": table_name},
            )
        }
        session.execute(
            text(
                f"""
                INSERT INTO {qualified_table} (
                    id, name, method, endpoint, cron_expr, timezone,
                    timeout_seconds, max_retries, retry_delay_seconds,
                    enabled, created_at
                ) VALUES (
                    'duplicate-after-down', 'legacy-one', 'POST', '/external',
                    '0 12 * * *', 'UTC', 3600, 0, 60, true, 1
                )
                """
            )
        )

    assert set(v2_9_0._V2_9_COLUMNS).isdisjoint(columns_after)
    assert f"{table_name}_uq_generic_name" not in indexes_after
    assert f"{table_name}_uq_studio_owner_name" not in indexes_after


def test_postgres_stale_manual_claim_is_recovered_exactly_once(postgres_db_real: PostgresDb) -> None:
    _assert_sync_stale_manual_recovery(postgres_db_real)


@pytest.mark.asyncio
async def test_async_postgres_stale_manual_claim_is_recovered_exactly_once() -> None:
    schema = f"test_schedule_async_{uuid.uuid4().hex[:8]}"
    db = AsyncPostgresDb(
        db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai",
        db_schema=schema,
    )
    schedule = _manual_claim_schedule(f"manual-{uuid.uuid4().hex}")
    now = int(time.time())
    future = now + 9999
    try:
        await db.create_schedule(schedule)
        await db.trigger_schedule(schedule["id"])
        abandoned = await db.claim_due_schedule("dead-worker")
        assert abandoned is not None and abandoned["manual_trigger_claimed"] is True

        stale_fence = now - 600
        await _aforce_schedule_row(db, schedule["id"], locked_at=stale_fence)
        with patch("agno.db.postgres.async_postgres.time.time", return_value=stale_fence):
            renewed_at = await db.renew_schedule_claim(
                schedule["id"],
                worker_id="dead-worker",
                locked_at=stale_fence,
            )
        assert renewed_at == stale_fence + 1
        assert not await db.release_schedule(schedule["id"], worker_id="dead-worker", locked_at=stale_fence)

        await _aforce_schedule_row(db, schedule["id"], locked_at=now - 600, next_run_at=now - 1)
        recovered = await db.claim_due_schedule("recovery-worker")
        assert recovered is not None
        assert recovered["pending_trigger_count"] == 0
        assert recovered["manual_trigger_claimed"] is True
        assert not await db.release_schedule(
            schedule["id"],
            worker_id=abandoned["locked_by"],
            locked_at=abandoned["locked_at"],
        )
        assert await db.release_schedule(
            schedule["id"],
            worker_id=recovered["locked_by"],
            locked_at=recovered["locked_at"],
        )

        cron_claim = await db.claim_due_schedule("cron-worker")
        assert cron_claim is not None and cron_claim["manual_trigger_claimed"] is False
        assert await db.release_schedule(
            schedule["id"],
            next_run_at=future,
            worker_id=cron_claim["locked_by"],
            locked_at=cron_claim["locked_at"],
        )
        assert await db.claim_due_schedule("extra-worker") is None
    finally:
        async with db.db_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await db.close()
