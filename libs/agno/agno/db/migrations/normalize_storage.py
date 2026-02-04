"""
Migration utility to convert v2.4 JSONB session storage to v2.5 normalized tables.

This migration reads existing sessions with JSONB `runs` column and:
1. Creates entries in the normalized `agno_runs` table
2. Creates entries in the normalized `agno_messages` table
3. Optionally clears the `runs` JSONB column to free up space

Usage:
    from agno.db.migrations.normalize_storage import migrate_to_normalized_storage

    # Migrate all sessions
    migrate_to_normalized_storage(db)

    # Migrate with options
    migrate_to_normalized_storage(
        db,
        batch_size=100,
        clear_jsonb_runs=True,
        dry_run=False,
    )
"""

import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.log import log_debug, log_error, log_info, log_warning


def migrate_to_normalized_storage(
    db: Any,
    batch_size: int = 100,
    clear_jsonb_runs: bool = False,
    dry_run: bool = False,
    session_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Migrate session data from JSONB `runs` column to normalized tables.

    Args:
        db: The database instance (PostgresDb).
        batch_size: Number of sessions to process per batch.
        clear_jsonb_runs: If True, clear the `runs` JSONB column after migration.
        dry_run: If True, only report what would be migrated without making changes.
        session_ids: Optional list of specific session IDs to migrate.
                    If None, all sessions will be migrated.

    Returns:
        Dictionary with migration statistics:
        - sessions_processed: Number of sessions processed
        - runs_migrated: Number of runs migrated
        - messages_migrated: Number of messages migrated
        - errors: List of error messages
        - duration_seconds: Total migration time
    """
    start_time = time.time()

    stats = {
        "sessions_processed": 0,
        "runs_migrated": 0,
        "messages_migrated": 0,
        "errors": [],
        "duration_seconds": 0,
    }

    # Check if db supports normalized storage
    if not hasattr(db, "upsert_run") or not hasattr(db, "upsert_messages"):
        error_msg = "Database does not support normalized storage methods"
        log_error(error_msg)
        stats["errors"].append(error_msg)
        return stats

    log_info(f"Starting migration to normalized storage (dry_run={dry_run})")

    try:
        # Get sessions to migrate
        sessions = _get_sessions_to_migrate(db, session_ids, batch_size)

        for session_dict in sessions:
            try:
                result = _migrate_session(
                    db=db,
                    session_dict=session_dict,
                    clear_jsonb_runs=clear_jsonb_runs,
                    dry_run=dry_run,
                )
                stats["sessions_processed"] += 1
                stats["runs_migrated"] += result["runs"]
                stats["messages_migrated"] += result["messages"]

                if stats["sessions_processed"] % 10 == 0:
                    log_info(
                        f"Progress: {stats['sessions_processed']} sessions, "
                        f"{stats['runs_migrated']} runs, "
                        f"{stats['messages_migrated']} messages"
                    )

            except Exception as e:
                error_msg = f"Error migrating session {session_dict.get('session_id')}: {e}"
                log_error(error_msg)
                stats["errors"].append(error_msg)

    except Exception as e:
        error_msg = f"Migration failed: {e}"
        log_error(error_msg)
        stats["errors"].append(error_msg)

    stats["duration_seconds"] = time.time() - start_time

    log_info(
        f"Migration completed in {stats['duration_seconds']:.2f}s: "
        f"{stats['sessions_processed']} sessions, "
        f"{stats['runs_migrated']} runs, "
        f"{stats['messages_migrated']} messages, "
        f"{len(stats['errors'])} errors"
    )

    return stats


def _get_sessions_to_migrate(
    db: Any,
    session_ids: Optional[List[str]] = None,
    batch_size: int = 100,
) -> List[Dict[str, Any]]:
    """Get sessions that need to be migrated."""
    try:
        from sqlalchemy import select, text

        # Get the sessions table
        table = db._get_table(table_type="sessions")
        if table is None:
            return []

        with db.Session() as sess:
            # Build query
            stmt = select(table)

            # Filter by specific session IDs if provided
            if session_ids:
                stmt = stmt.where(table.c.session_id.in_(session_ids))

            # Only get sessions that have runs in JSONB
            # This is a PostgreSQL-specific check for non-empty JSONB
            stmt = stmt.where(
                text("runs IS NOT NULL AND runs != 'null'::jsonb AND runs != '[]'::jsonb")
            )

            # Order by created_at for consistent processing
            stmt = stmt.order_by(table.c.created_at.asc())

            result = sess.execute(stmt).fetchall()
            return [dict(row._mapping) for row in result]

    except Exception as e:
        log_error(f"Error getting sessions to migrate: {e}")
        return []


def _migrate_session(
    db: Any,
    session_dict: Dict[str, Any],
    clear_jsonb_runs: bool = False,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Migrate a single session's runs to normalized storage."""
    result = {"runs": 0, "messages": 0}

    session_id = session_dict.get("session_id")
    runs = session_dict.get("runs")

    if not runs or not isinstance(runs, list):
        log_debug(f"Session {session_id} has no runs to migrate")
        return result

    log_debug(f"Migrating session {session_id} with {len(runs)} runs")

    for run_order, run_dict in enumerate(runs):
        try:
            run_id = run_dict.get("run_id") or str(uuid4())

            if not dry_run:
                # Persist the run
                run_dict["run_order"] = run_order
                db.upsert_run(
                    run_id=run_id,
                    session_id=session_id,
                    run_data=run_dict,
                )

                # Persist messages (excluding history messages)
                messages = run_dict.get("messages", [])
                if messages:
                    # Filter out history messages
                    non_history_messages = [
                        m for m in messages
                        if not m.get("from_history", False)
                    ]
                    if non_history_messages:
                        db.upsert_messages(run_id=run_id, messages=non_history_messages)
                        result["messages"] += len(non_history_messages)

            result["runs"] += 1

        except Exception as e:
            log_warning(f"Error migrating run {run_dict.get('run_id')} in session {session_id}: {e}")

    # Clear JSONB runs column if requested
    if clear_jsonb_runs and not dry_run and result["runs"] > 0:
        _clear_session_runs(db, session_id)

    return result


def _clear_session_runs(db: Any, session_id: str) -> bool:
    """Clear the runs JSONB column for a session after migration."""
    try:
        from sqlalchemy import update

        table = db._get_table(table_type="sessions")
        if table is None:
            return False

        with db.Session() as sess, sess.begin():
            stmt = (
                update(table)
                .where(table.c.session_id == session_id)
                .values(runs=None)
            )
            sess.execute(stmt)
            log_debug(f"Cleared JSONB runs for session {session_id}")
            return True

    except Exception as e:
        log_error(f"Error clearing JSONB runs for session {session_id}: {e}")
        return False


def estimate_migration(db: Any) -> Dict[str, Any]:
    """
    Estimate the scope of migration without making changes.

    Args:
        db: The database instance.

    Returns:
        Dictionary with estimates:
        - total_sessions: Number of sessions to migrate
        - estimated_runs: Estimated number of runs
        - estimated_messages: Estimated number of messages
        - estimated_storage_savings_mb: Estimated storage savings in MB
    """
    try:
        from sqlalchemy import func, select, text

        table = db._get_table(table_type="sessions")
        if table is None:
            return {"error": "Sessions table not found"}

        with db.Session() as sess:
            # Count sessions with runs
            count_stmt = (
                select(func.count())
                .select_from(table)
                .where(text("runs IS NOT NULL AND runs != 'null'::jsonb AND runs != '[]'::jsonb"))
            )
            total_sessions = sess.execute(count_stmt).scalar() or 0

            # Sample some sessions to estimate runs/messages
            sample_stmt = (
                select(table)
                .where(text("runs IS NOT NULL AND runs != 'null'::jsonb AND runs != '[]'::jsonb"))
                .limit(10)
            )
            sample_sessions = sess.execute(sample_stmt).fetchall()

            total_runs = 0
            total_messages = 0
            total_history_messages = 0

            for row in sample_sessions:
                session_dict = dict(row._mapping)
                runs = session_dict.get("runs", [])
                if runs:
                    total_runs += len(runs)
                    for run in runs:
                        messages = run.get("messages", [])
                        total_messages += len(messages)
                        total_history_messages += sum(
                            1 for m in messages if m.get("from_history", False)
                        )

            # Extrapolate to all sessions
            if sample_sessions:
                sample_count = len(sample_sessions)
                avg_runs = total_runs / sample_count
                avg_messages = total_messages / sample_count
                avg_history = total_history_messages / sample_count

                estimated_runs = int(avg_runs * total_sessions)
                estimated_messages = int(avg_messages * total_sessions)
                estimated_history = int(avg_history * total_sessions)

                # Estimate storage savings (history messages won't be duplicated)
                # Assume average message size of 1KB
                estimated_savings_mb = (estimated_history * 1024) / (1024 * 1024)
            else:
                estimated_runs = 0
                estimated_messages = 0
                estimated_savings_mb = 0

            return {
                "total_sessions": total_sessions,
                "estimated_runs": estimated_runs,
                "estimated_messages": estimated_messages,
                "estimated_storage_savings_mb": round(estimated_savings_mb, 2),
            }

    except Exception as e:
        log_error(f"Error estimating migration: {e}")
        return {"error": str(e)}


def verify_migration(db: Any, session_id: str) -> Dict[str, Any]:
    """
    Verify that a session was migrated correctly.

    Args:
        db: The database instance.
        session_id: The session ID to verify.

    Returns:
        Dictionary with verification results:
        - session_found: Whether the session exists
        - jsonb_runs_count: Number of runs in JSONB column
        - normalized_runs_count: Number of runs in normalized table
        - normalized_messages_count: Number of messages in normalized table
        - match: Whether counts match (excluding history messages)
    """
    try:
        # Get session from JSONB
        table = db._get_table(table_type="sessions")
        if table is None:
            return {"error": "Sessions table not found"}

        from sqlalchemy import select

        with db.Session() as sess:
            stmt = select(table).where(table.c.session_id == session_id)
            result = sess.execute(stmt).fetchone()

            if not result:
                return {"session_found": False}

            session_dict = dict(result._mapping)
            jsonb_runs = session_dict.get("runs", []) or []
            jsonb_runs_count = len(jsonb_runs)

            # Count non-history messages in JSONB
            jsonb_messages_count = 0
            for run in jsonb_runs:
                messages = run.get("messages", [])
                jsonb_messages_count += sum(
                    1 for m in messages if not m.get("from_history", False)
                )

        # Get normalized counts
        normalized_runs = db.get_runs(session_id=session_id)
        normalized_runs_count = len(normalized_runs)

        normalized_messages = db.get_messages(session_id=session_id)
        normalized_messages_count = len(normalized_messages)

        return {
            "session_found": True,
            "jsonb_runs_count": jsonb_runs_count,
            "jsonb_messages_count": jsonb_messages_count,
            "normalized_runs_count": normalized_runs_count,
            "normalized_messages_count": normalized_messages_count,
            "runs_match": jsonb_runs_count == normalized_runs_count,
            "messages_match": jsonb_messages_count == normalized_messages_count,
        }

    except Exception as e:
        log_error(f"Error verifying migration for session {session_id}: {e}")
        return {"error": str(e)}
