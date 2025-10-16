from dataclasses import asdict
from datetime import date, datetime, timezone
from textwrap import dedent
from typing import List, Literal, Optional, Sequence

from surrealdb import RecordID

from agno.db.base import SessionType
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import Session
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

TableType = Literal[
    "agents",
    "evals",
    "knowledge",
    "memories",
    "metrics",
    "sessions",
    "teams",
    "users",
    "workflows",
]


def deserialize_record_id(record: dict, agno_field: str, surreal_field: Optional[str] = None) -> dict:
    if surreal_field is None:
        surreal_field = agno_field
    x = record.get(surreal_field)
    if isinstance(x, RecordID):
        record[agno_field] = x.id
        if agno_field != surreal_field:
            del record[surreal_field]
    return record


def surrealize_dates(record: dict) -> dict:
    copy = record.copy()
    for key, value in copy.items():
        if isinstance(value, date):
            copy[key] = datetime.combine(value, datetime.min.time()).replace(tzinfo=timezone.utc)
        elif key in ["created_at", "updated_at"] and isinstance(value, (int, float)):
            copy[key] = datetime.fromtimestamp(value).replace(tzinfo=timezone.utc)
        elif key in ["created_at", "updated_at"] and isinstance(value, str):
            # Handle ISO string format - convert back to datetime object for SurrealDB
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                copy[key] = dt
            except ValueError:
                # If it's not a valid ISO format, leave it as is
                pass
        elif key in ["created_at", "updated_at"] and value is None:
            # Set current time for None datetime fields
            copy[key] = datetime.now(timezone.utc)
        elif isinstance(value, datetime):
            copy[key] = value.replace(tzinfo=timezone.utc)
    return copy


def desurrealize_dates(record: dict) -> dict:
    copy = record.copy()
    for key, value in copy.items():
        if isinstance(value, datetime):
            copy[key] = int(value.timestamp())
    return copy


def serialize_session(session: Session, table_names: dict[TableType, str]) -> dict:
    _dict = session.to_dict()

    if session.session_id is not None:
        _dict["id"] = RecordID(table_names["sessions"], session.session_id)
        del _dict["session_id"]

    if isinstance(session, AgentSession):
        _dict["agent"] = RecordID(table_names["agents"], session.agent_id)
        del _dict["agent_id"]
    elif isinstance(session, TeamSession):
        _dict["team"] = RecordID(table_names["teams"], session.team_id)
        del _dict["team_id"]
    elif isinstance(session, WorkflowSession):
        _dict["workflow"] = RecordID(table_names["workflows"], session.workflow_id)
        del _dict["workflow_id"]

    # surrealize dates
    _dict = surrealize_dates(_dict)

    return _dict


def desurrealize_session(session_raw: dict, session_type: Optional[SessionType] = None) -> dict:
    session_raw = deserialize_record_id(session_raw, "session_id", "id")
    if session_type == SessionType.AGENT:
        session_raw = deserialize_record_id(session_raw, "agent_id", "agent")
    elif session_type == SessionType.TEAM:
        session_raw = deserialize_record_id(session_raw, "team_id", "team")
    elif session_type == SessionType.WORKFLOW:
        session_raw = deserialize_record_id(session_raw, "workflow_id", "workflow")

    session_raw = desurrealize_dates(session_raw)

    if session_raw.get("agent_id"):
        session_raw["session_type"] = SessionType.AGENT
    elif session_raw.get("team_id"):
        session_raw["session_type"] = SessionType.TEAM
    elif session_raw.get("workflow_id"):
        session_raw["session_type"] = SessionType.WORKFLOW

    return session_raw


def deserialize_session(session_type: SessionType, session_raw: dict) -> Optional[Session]:
    session_raw = desurrealize_session(session_raw, session_type)

    if session_type == SessionType.AGENT:
        return AgentSession.from_dict(session_raw)
    elif session_type == SessionType.TEAM:
        return TeamSession.from_dict(session_raw)
    elif session_type == SessionType.WORKFLOW:
        return WorkflowSession.from_dict(session_raw)
    else:
        raise ValueError(f"Invalid session type: {session_type}")


def deserialize_sessions(session_type: SessionType, sessions_raw: List[dict]) -> List[Session]:
    return [x for x in [deserialize_session(session_type, x) for x in sessions_raw] if x is not None]


def get_session_type(session: Session) -> SessionType:
    if isinstance(session, AgentSession):
        return SessionType.AGENT
    elif isinstance(session, TeamSession):
        return SessionType.TEAM
    elif isinstance(session, WorkflowSession):
        return SessionType.WORKFLOW
    else:
        raise ValueError(f"Invalid session instance: {type(session)}")


def desurrealize_user_memory(memory_raw: dict) -> dict:
    copy = memory_raw.copy()

    copy = deserialize_record_id(copy, "memory_id", "id")
    copy = deserialize_record_id(copy, "user_id", "user")
    copy = deserialize_record_id(copy, "agent_id", "agent")
    copy = deserialize_record_id(copy, "team_id", "team")
    copy = deserialize_record_id(copy, "workflow_id", "workflow")

    # TODO: is this ok? or should we cast datetimes to int? Like in desurrealize_session
    # copy = desurrealize_dates(copy)
    updated_at = copy.get("updated_at")
    if not isinstance(updated_at, str):
        copy["updated_at"] = str(updated_at)

    return copy


def deserialize_user_memory(memory_raw: dict) -> UserMemory:
    return UserMemory.from_dict(desurrealize_user_memory(memory_raw))


def deserialize_user_memories(memories_raw: Sequence[dict]) -> List[UserMemory]:
    return [deserialize_user_memory(x) for x in memories_raw]


def serialize_user_memory(memory: UserMemory, memory_table_name: str, user_table_name: str) -> dict:
    dict_ = asdict(memory)
    if memory.memory_id is not None:
        dict_["id"] = RecordID(memory_table_name, memory.memory_id)
        del dict_["memory_id"]
    if memory.user_id is not None:
        dict_["user"] = RecordID(user_table_name, memory.user_id)
        del dict_["user_id"]

    # surrealize dates
    dict_ = surrealize_dates(dict_)

    return dict_


def deserialize_knowledge_row(knowledge_row_raw: dict) -> KnowledgeRow:
    copy = knowledge_row_raw.copy()

    copy = deserialize_record_id(copy, "id")
    copy = desurrealize_dates(copy)

    return KnowledgeRow.model_validate(copy)


def serialize_knowledge_row(knowledge_row: KnowledgeRow, knowledge_table_name: str) -> dict:
    dict_ = knowledge_row.model_dump()
    if knowledge_row.id is not None:
        dict_["id"] = RecordID(knowledge_table_name, knowledge_row.id)

    # surrealize dates
    dict_ = surrealize_dates(dict_)

    return dict_


def desurrealize_eval_run_record(eval_run_record_raw: dict) -> dict:
    copy = eval_run_record_raw.copy()

    copy = deserialize_record_id(copy, "run_id", "id")
    copy = deserialize_record_id(copy, "agent_id", "agent")
    copy = deserialize_record_id(copy, "team_id", "team")
    copy = deserialize_record_id(copy, "workflow_id", "workflow")

    return copy


def deserialize_eval_run_record(eval_run_record_raw: dict) -> EvalRunRecord:
    return EvalRunRecord.model_validate(desurrealize_eval_run_record(eval_run_record_raw))


def serialize_eval_run_record(eval_run_record: EvalRunRecord, table_names: dict[TableType, str]) -> dict:
    dict_ = eval_run_record.model_dump()
    if eval_run_record.run_id is not None:
        dict_["id"] = RecordID(table_names["evals"], eval_run_record.run_id)
        del dict_["run_id"]
    if eval_run_record.agent_id is not None:
        dict_["agent"] = RecordID(table_names["agents"], eval_run_record.agent_id)
        del dict_["agent_id"]
    if eval_run_record.team_id is not None:
        dict_["team"] = RecordID(table_names["teams"], eval_run_record.team_id)
        del dict_["team_id"]
    if eval_run_record.workflow_id is not None:
        dict_["workflow"] = RecordID(table_names["workflows"], eval_run_record.workflow_id)
        del dict_["workflow_id"]
    return dict_


def get_schema(table_type: TableType, table_name: str) -> str:
    define_table = f"DEFINE TABLE {table_name} SCHEMALESS;"
    if table_type == "memories":
        return dedent(f"""
            {define_table}
            DEFINE FIELD OVERWRITE updated_at ON {table_name} TYPE datetime VALUE time::now();
            """)
    elif table_type == "knowledge":
        return dedent(f"""
            {define_table}
            DEFINE FIELD OVERWRITE created_at ON {table_name} TYPE datetime VALUE time::now();
            DEFINE FIELD OVERWRITE updated_at ON {table_name} TYPE datetime VALUE time::now();
            """)
    elif table_type == "sessions":
        return dedent(f"""
            {define_table}
            DEFINE FIELD OVERWRITE created_at ON {table_name} TYPE datetime VALUE time::now();
            DEFINE FIELD OVERWRITE updated_at ON {table_name} TYPE datetime VALUE time::now();
            """)
    else:
        return define_table
