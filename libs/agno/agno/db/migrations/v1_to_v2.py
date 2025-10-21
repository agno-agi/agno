"""Migration utility to migrate your Agno tables from v1 to v2"""

import gc
import json
from typing import Any, Dict, List, Optional, Union, cast

from sqlalchemy import text

from agno.db.base import BaseDb
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.utils.log import log_error, log_info, log_warning


def convert_v1_metrics_to_v2(metrics_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Convert v1 metrics dictionary to v2 format by mapping old field names to new ones."""
    if not isinstance(metrics_dict, dict):
        return metrics_dict

    # Create a copy to avoid modifying the original
    v2_metrics = metrics_dict.copy()

    # Map v1 field names to v2 field names
    field_mappings = {
        "time": "duration",
        "audio_tokens": "audio_total_tokens",
        "input_audio_tokens": "audio_input_tokens",
        "output_audio_tokens": "audio_output_tokens",
        "cached_tokens": "cache_read_tokens",
    }

    # Fields to remove (deprecated in v2)
    deprecated_fields = ["prompt_tokens", "completion_tokens", "prompt_tokens_details", "completion_tokens_details"]

    # Apply field mappings
    for old_field, new_field in field_mappings.items():
        if old_field in v2_metrics:
            v2_metrics[new_field] = v2_metrics.pop(old_field)

    # Remove deprecated fields
    for field in deprecated_fields:
        v2_metrics.pop(field, None)

    return v2_metrics


def convert_any_metrics_in_data(data: Any) -> Any:
    """Recursively find and convert any metrics dictionaries and handle v1 to v2 field conversion."""
    if isinstance(data, dict):
        # First apply v1 to v2 field conversion (handles extra_data extraction, thinking/reasoning_content consolidation, etc.)
        data = convert_v1_fields_to_v2(data)

        # Check if this looks like a metrics dictionary
        if _is_metrics_dict(data):
            return convert_v1_metrics_to_v2(data)

        # Otherwise, recursively process all values
        converted_dict = {}
        for key, value in data.items():
            # Special handling for 'metrics' keys - always convert their values
            if key == "metrics" and isinstance(value, dict):
                converted_dict[key] = convert_v1_metrics_to_v2(value)
            else:
                converted_dict[key] = convert_any_metrics_in_data(value)
        return converted_dict

    elif isinstance(data, list):
        return [convert_any_metrics_in_data(item) for item in data]

    else:
        # Not a dict or list, return as-is
        return data


def _is_metrics_dict(data: Dict[str, Any]) -> bool:
    """Check if a dictionary looks like a metrics dictionary based on common field names."""
    if not isinstance(data, dict):
        return False

    # Common metrics field names (both v1 and v2)
    metrics_indicators = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "time",
        "duration",
        "audio_tokens",
        "audio_total_tokens",
        "audio_input_tokens",
        "audio_output_tokens",
        "cached_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "prompt_tokens",
        "completion_tokens",
        "time_to_first_token",
        "provider_metrics",
        "additional_metrics",
    }

    # Deprecated v1 fields that are strong indicators this is a metrics dict
    deprecated_v1_indicators = {"time", "audio_tokens", "cached_tokens", "prompt_tokens", "completion_tokens"}

    # If we find any deprecated v1 field, it's definitely a metrics dict that needs conversion
    if any(field in data for field in deprecated_v1_indicators):
        return True

    # Otherwise, if the dict has at least 2 metrics-related fields, consider it a metrics dict
    matching_fields = sum(1 for field in data.keys() if field in metrics_indicators)
    return matching_fields >= 2


def convert_session_data_comprehensively(session_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Comprehensively convert session data from v1 to v2 format, including metrics conversion and field mapping."""
    if not session_data:
        return session_data

    # Use the recursive converter to handle all v1 to v2 conversions (metrics, field mapping, extra_data extraction, etc.)
    return convert_any_metrics_in_data(session_data)


def safe_get_runs_from_memory(memory_data: Any) -> Any:
    """Safely extract runs data from memory field, handling various data types."""
    if memory_data is None:
        return None

    runs: Any = []

    # If memory_data is a string, try to parse it as JSON
    if isinstance(memory_data, str):
        try:
            memory_dict = json.loads(memory_data)
            if isinstance(memory_dict, dict):
                runs = memory_dict.get("runs")
        except (json.JSONDecodeError, AttributeError):
            # If JSON parsing fails, memory_data might just be a string value
            return None

    # If memory_data is already a dict, access runs directly
    elif isinstance(memory_data, dict):
        runs = memory_data.get("runs")

    for run in runs or []:
        # Adjust fields mapping for Agent sessions
        if run.get("agent_id") is not None:
            if run.get("team_id") is not None:
                run.pop("team_id")
            if run.get("team_session_id") is not None:
                run["session_id"] = run.pop("team_session_id")
                if run.get("event"):
                    run["events"] = [run.pop("event")]

        # Adjust fields mapping for Team sessions
        if run.get("team_id") is not None:
            if run.get("agent_id") is not None:
                run.pop("agent_id")
            if member_responses := run.get("member_responses"):
                for response in member_responses:
                    if response.get("agent_id") is not None and response.get("team_id") is not None:
                        response.pop("team_id")
                    if response.get("agent_id") is not None and response.get("team_session_id") is not None:
                        response["session_id"] = response.pop("team_session_id")
                run["member_responses"] = member_responses

    return runs


def convert_v1_media_to_v2(media_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert v1 media objects to v2 format."""
    if not isinstance(media_data, dict):
        return media_data

    # Create a copy to avoid modifying the original
    v2_media = media_data.copy()

    # Add id if missing (required in v2)
    if "id" not in v2_media or v2_media["id"] is None:
        from uuid import uuid4

        v2_media["id"] = str(uuid4())

    # Handle VideoArtifact → Video conversion
    if "eta" in v2_media or "length" in v2_media:
        # Convert length to duration if it's numeric
        length = v2_media.pop("length", None)
        if length and isinstance(length, (int, float)):
            v2_media["duration"] = length
        elif length and isinstance(length, str):
            try:
                v2_media["duration"] = float(length)
            except ValueError:
                pass  # Keep as is if not convertible

    # Handle AudioArtifact → Audio conversion
    if "base64_audio" in v2_media:
        # Map base64_audio to content
        base64_audio = v2_media.pop("base64_audio", None)
        if base64_audio:
            v2_media["content"] = base64_audio

    # Handle AudioResponse content conversion (base64 string to bytes if needed)
    if "transcript" in v2_media and "content" in v2_media:
        content = v2_media.get("content")
        if content and isinstance(content, str):
            # Try to decode base64 content to bytes for v2
            try:
                import base64

                v2_media["content"] = base64.b64decode(content)
            except Exception:
                # If not valid base64, keep as string
                pass

    # Ensure format and mime_type are set appropriately
    if "format" in v2_media and "mime_type" not in v2_media:
        format_val = v2_media["format"]
        if format_val:
            # Set mime_type based on format for common types
            mime_type_map = {
                "mp4": "video/mp4",
                "mov": "video/quicktime",
                "avi": "video/x-msvideo",
                "webm": "video/webm",
                "mp3": "audio/mpeg",
                "wav": "audio/wav",
                "ogg": "audio/ogg",
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
            }
            if format_val.lower() in mime_type_map:
                v2_media["mime_type"] = mime_type_map[format_val.lower()]

    return v2_media


def convert_v1_fields_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert v1 fields to v2 format with proper field mapping and extraction."""
    if not isinstance(data, dict):
        return data

    # Create a copy to avoid modifying the original
    v2_data = data.copy()

    # Fields that should be completely ignored/removed in v2
    deprecated_fields = {
        "team_session_id",  # RunOutput v1 field, removed in v2
        "formatted_tool_calls",  # RunOutput v1 field, removed in v2
        "event",  # Remove event field
        "events",  # Remove events field
        # Add other deprecated fields here as needed
    }

    # Extract and map fields from extra_data before removing it
    extra_data = v2_data.get("extra_data")
    if extra_data and isinstance(extra_data, dict):
        # Map extra_data fields to their v2 locations
        if "add_messages" in extra_data:
            v2_data["additional_input"] = extra_data["add_messages"]
        if "references" in extra_data:
            v2_data["references"] = extra_data["references"]
        if "reasoning_steps" in extra_data:
            v2_data["reasoning_steps"] = extra_data["reasoning_steps"]
        if "reasoning_content" in extra_data:
            # reasoning_content from extra_data also goes to reasoning_content
            v2_data["reasoning_content"] = extra_data["reasoning_content"]
        if "reasoning_messages" in extra_data:
            v2_data["reasoning_messages"] = extra_data["reasoning_messages"]

    # Handle thinking and reasoning_content consolidation
    # Both thinking and reasoning_content from v1 should become reasoning_content in v2
    thinking = v2_data.get("thinking")
    reasoning_content = v2_data.get("reasoning_content")

    # Consolidate thinking and reasoning_content into reasoning_content
    if thinking and reasoning_content:
        # Both exist, combine them (thinking first, then reasoning_content)
        v2_data["reasoning_content"] = f"{thinking}\n{reasoning_content}"
    elif thinking and not reasoning_content:
        # Only thinking exists, move it to reasoning_content
        v2_data["reasoning_content"] = thinking
    # If only reasoning_content exists, keep it as is

    # Remove thinking field since it's now consolidated into reasoning_content
    if "thinking" in v2_data:
        del v2_data["thinking"]

    # Handle media object conversions
    media_fields = ["images", "videos", "audio", "response_audio"]
    for field in media_fields:
        if field in v2_data and v2_data[field]:
            if isinstance(v2_data[field], list):
                # Handle list of media objects
                v2_data[field] = [
                    convert_v1_media_to_v2(item) if isinstance(item, dict) else item for item in v2_data[field]
                ]
            elif isinstance(v2_data[field], dict):
                # Handle single media object
                v2_data[field] = convert_v1_media_to_v2(v2_data[field])

    # Remove extra_data after extraction
    if "extra_data" in v2_data:
        del v2_data["extra_data"]

    # Remove other deprecated fields
    for field in deprecated_fields:
        v2_data.pop(field, None)

    return v2_data


def migrate(
    db: BaseDb,
    v1_db_schema: str,
    agent_sessions_table_name: Optional[str] = None,
    team_sessions_table_name: Optional[str] = None,
    workflow_sessions_table_name: Optional[str] = None,
    memories_table_name: Optional[str] = None,
    batch_size: int = 5000,
):
    """Given a database connection and table/collection names, parse and migrate the content to corresponding v2 tables/collections.

    Args:
        db: The database to migrate (PostgresDb, MySQLDb, SqliteDb, or MongoDb)
        v1_db_schema: The schema of the v1 tables (leave empty for SQLite and MongoDB)
        agent_sessions_table_name: The name of the agent sessions table/collection. If not provided, agent sessions will not be migrated.
        team_sessions_table_name: The name of the team sessions table/collection. If not provided, team sessions will not be migrated.
        workflow_sessions_table_name: The name of the workflow sessions table/collection. If not provided, workflow sessions will not be migrated.
        memories_table_name: The name of the memories table/collection. If not provided, memories will not be migrated.
        batch_size: Number of records to process in each batch (default: 5000)
    """
    if agent_sessions_table_name:
        migrate_table_in_batches(
            db=db,
            v1_db_schema=v1_db_schema,
            v1_table_name=agent_sessions_table_name,
            v1_table_type="agent_sessions",
            batch_size=batch_size,
        )

    if team_sessions_table_name:
        migrate_table_in_batches(
            db=db,
            v1_db_schema=v1_db_schema,
            v1_table_name=team_sessions_table_name,
            v1_table_type="team_sessions",
            batch_size=batch_size,
        )

    if workflow_sessions_table_name:
        migrate_table_in_batches(
            db=db,
            v1_db_schema=v1_db_schema,
            v1_table_name=workflow_sessions_table_name,
            v1_table_type="workflow_sessions",
            batch_size=batch_size,
        )

    if memories_table_name:
        migrate_table_in_batches(
            db=db,
            v1_db_schema=v1_db_schema,
            v1_table_name=memories_table_name,
            v1_table_type="memories",
            batch_size=batch_size,
        )


def migrate_table_in_batches(
    db: BaseDb,
    v1_db_schema: str,
    v1_table_name: str,
    v1_table_type: str,
    batch_size: int = 5000,
):
    log_info(f"Starting migration of table {v1_table_name} (type: {v1_table_type}) with batch size {batch_size}")

    total_migrated = 0
    batch_count = 0

    for batch_content in get_table_content_in_batches(db, v1_db_schema, v1_table_name, batch_size):
        batch_count += 1
        batch_size_actual = len(batch_content)
        log_info(f"Processing batch {batch_count} with {batch_size_actual} records from table {v1_table_name}")

        # Parse the content into the new format
        memories: List[UserMemory] = []
        sessions: Union[List[AgentSession], List[TeamSession], List[WorkflowSession]] = []

        if v1_table_type == "agent_sessions":
            sessions = parse_agent_sessions(batch_content)
        elif v1_table_type == "team_sessions":
            sessions = parse_team_sessions(batch_content)
        elif v1_table_type == "workflow_sessions":
            sessions = parse_workflow_sessions(batch_content)
        elif v1_table_type == "memories":
            memories = parse_memories(batch_content)
        else:
            raise ValueError(f"Invalid table type: {v1_table_type}")

        # Insert the batch into the new table
        if v1_table_type in ["agent_sessions", "team_sessions", "workflow_sessions"]:
            if sessions:
                # Clear any existing scoped session state for SQL databases to prevent transaction conflicts
                if hasattr(db, "Session"):
                    db.Session.remove()  # type: ignore

                db.upsert_sessions(sessions, preserve_updated_at=True)  # type: ignore
                total_migrated += len(sessions)
                log_info(f"Bulk upserted {len(sessions)} sessions in batch {batch_count}")

        elif v1_table_type == "memories":
            if memories:
                # Clear any existing scoped session state for SQL databases to prevent transaction conflicts
                if hasattr(db, "Session"):
                    db.Session.remove()  # type: ignore

                db.upsert_memories(memories, preserve_updated_at=True)
                total_migrated += len(memories)
                log_info(f"Bulk upserted {len(memories)} memories in batch {batch_count}")

        log_info(f"Completed batch {batch_count}: migrated {batch_size_actual} records")

        # Explicit cleanup to free memory before next batch
        del batch_content
        if v1_table_type in ["agent_sessions", "team_sessions", "workflow_sessions"]:
            del sessions
        elif v1_table_type == "memories":
            del memories

        # Force garbage collection to return memory to OS
        # This is necessary because Python's memory allocator retains memory after large operations
        # See: https://github.com/sqlalchemy/sqlalchemy/issues/4616
        gc.collect()

    log_info(f"✅ Migration completed for table {v1_table_name}: {total_migrated} total records migrated")


def get_table_content_in_batches(db: BaseDb, db_schema: str, table_name: str, batch_size: int = 5000):
    """Get table content in batches to avoid memory issues with large tables"""
    try:
        if type(db).__name__ == "MongoDb":
            from agno.db.mongo.mongo import MongoDb

            db = cast(MongoDb, db)

            # MongoDB implementation with cursor and batching
            collection = db.database[table_name]
            cursor = collection.find({}).batch_size(batch_size)

            batch = []
            for doc in cursor:
                # Convert ObjectId to string for compatibility
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                batch.append(doc)

                if len(batch) >= batch_size:
                    yield batch
                    batch = []

            # Yield remaining items
            if batch:
                yield batch
        else:
            # SQL database implementations (PostgresDb, MySQLDb, SqliteDb)
            if type(db).__name__ == "PostgresDb":
                from agno.db.postgres.postgres import PostgresDb

                db = cast(PostgresDb, db)

            elif type(db).__name__ == "MySQLDb":
                from agno.db.mysql.mysql import MySQLDb

                db = cast(MySQLDb, db)

            elif type(db).__name__ == "SqliteDb":
                from agno.db.sqlite.sqlite import SqliteDb

                db = cast(SqliteDb, db)

            else:
                raise ValueError(f"Invalid database type: {type(db).__name__}")

            offset = 0
            while True:
                # Create a new session for each batch to avoid transaction conflicts
                with db.Session() as sess:
                    # Handle empty schema by omitting the schema prefix (needed for SQLite)
                    if db_schema and db_schema.strip():
                        sql_query = f"SELECT * FROM {db_schema}.{table_name} LIMIT {batch_size} OFFSET {offset}"
                    else:
                        sql_query = f"SELECT * FROM {table_name} LIMIT {batch_size} OFFSET {offset}"

                    result = sess.execute(text(sql_query))
                    batch = [row._asdict() for row in result]

                    if not batch:
                        break

                    yield batch
                    offset += batch_size

                    # If batch is smaller than batch_size, we've reached the end
                    if len(batch) < batch_size:
                        break

    except Exception as e:
        log_error(f"Error getting batched content from table/collection {table_name}: {e}")
        return


def get_all_table_content(db, db_schema: str, table_name: str) -> list[dict[str, Any]]:
    """Get all content from the given table/collection (legacy method kept for backward compatibility)

    WARNING: This method loads all data into memory and should not be used for large tables.
    Use get_table_content_in_batches() for large datasets.
    """
    log_warning(
        f"Loading entire table {table_name} into memory. Consider using get_table_content_in_batches() for large tables, or if you experience any complication."
    )

    all_content = []
    for batch in get_table_content_in_batches(db, db_schema, table_name):
        all_content.extend(batch)
    return all_content


def parse_agent_sessions(v1_content: List[Dict[str, Any]]) -> List[AgentSession]:
    """Parse v1 Agent sessions into v2 Agent sessions and Memories"""
    sessions_v2 = []

    for item in v1_content:
        session = {
            "agent_id": item.get("agent_id"),
            "agent_data": item.get("agent_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": convert_session_data_comprehensively(item.get("session_data")),
            "metadata": convert_any_metrics_in_data(item.get("extra_data")),
            "runs": convert_any_metrics_in_data(safe_get_runs_from_memory(item.get("memory"))),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }

        try:
            agent_session = AgentSession.from_dict(session)
        except Exception as e:
            log_error(f"Error parsing agent session: {e}. This is the complete session that failed: {session}")
            continue

        if agent_session is not None:
            sessions_v2.append(agent_session)

    return sessions_v2


def parse_team_sessions(v1_content: List[Dict[str, Any]]) -> List[TeamSession]:
    """Parse v1 Team sessions into v2 Team sessions and Memories"""
    sessions_v2 = []

    for item in v1_content:
        session = {
            "team_id": item.get("team_id"),
            "team_data": item.get("team_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": convert_session_data_comprehensively(item.get("session_data")),
            "metadata": convert_any_metrics_in_data(item.get("extra_data")),
            "runs": convert_any_metrics_in_data(safe_get_runs_from_memory(item.get("memory"))),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        try:
            team_session = TeamSession.from_dict(session)
        except Exception as e:
            log_error(f"Error parsing team session: {e}. This is the complete session that failed: {session}")
            continue

        if team_session is not None:
            sessions_v2.append(team_session)

    return sessions_v2


def parse_workflow_sessions(v1_content: List[Dict[str, Any]]) -> List[WorkflowSession]:
    """Parse v1 Workflow sessions into v2 Workflow sessions"""
    sessions_v2 = []

    for item in v1_content:
        session = {
            "workflow_id": item.get("workflow_id"),
            "workflow_data": item.get("workflow_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": convert_session_data_comprehensively(item.get("session_data")),
            "metadata": convert_any_metrics_in_data(item.get("extra_data")),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            # Workflow v2 specific fields
            "workflow_name": item.get("workflow_name"),
            "runs": convert_any_metrics_in_data(item.get("runs")),
        }
        try:
            workflow_session = WorkflowSession.from_dict(session)
        except Exception as e:
            log_error(f"Error parsing workflow session: {e}. This is the complete session that failed: {session}")
            continue

        if workflow_session is not None:
            sessions_v2.append(workflow_session)

    return sessions_v2


def parse_memories(v1_content: List[Dict[str, Any]]) -> List[UserMemory]:
    """Parse v1 Memories into v2 Memories"""
    memories_v2 = []

    for item in v1_content:
        memory = {
            "memory_id": item.get("memory_id"),
            "memory": item.get("memory"),
            "input": item.get("input"),
            "updated_at": item.get("updated_at"),
            "agent_id": item.get("agent_id"),
            "team_id": item.get("team_id"),
            "user_id": item.get("user_id"),
        }
        memories_v2.append(UserMemory.from_dict(memory))

    return memories_v2
