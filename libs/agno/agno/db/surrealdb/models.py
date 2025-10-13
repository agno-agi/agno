import datetime
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

TableType = Literal["sessions", "memories", "users", "knowledge", "evals", "agents", "teams", "workflows"]


def deserialize_record_id(record: dict, agno_field: str, surreal_field: Optional[str] = None) -> dict:
    if surreal_field is None:
        surreal_field = agno_field
    x = record.get(surreal_field)
    if isinstance(x, RecordID):
        record[agno_field] = x.id
        if agno_field != surreal_field:
            del record[surreal_field]
    return record


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
    return _dict


def deserialize_session(session_type: SessionType, session_raw: dict) -> Optional[Session]:
    # session_raw = deserialize_session_json_fields(session_raw)

    session_raw = deserialize_record_id(session_raw, "session_id", "id")
    session_raw = deserialize_record_id(session_raw, "agent_id", "agent")
    session_raw = deserialize_record_id(session_raw, "team_id", "team")
    session_raw = deserialize_record_id(session_raw, "workflow_id", "workflow")

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

    updated_at = copy.get("updated_at")
    if not isinstance(updated_at, str):
        copy["updated_at"] = str(updated_at)

    return copy


def deserialize_user_memory(memory_raw: dict) -> UserMemory:
    return UserMemory.from_dict(desurrealize_user_memory(memory_raw))


def deserialize_user_memories(memories_raw: Sequence[dict]) -> List[UserMemory]:
    return [deserialize_user_memory(desurrealize_user_memory(x)) for x in memories_raw]


def serialize_user_memory(memory: UserMemory, memory_table_name: str, user_table_name: str) -> dict:
    dict_ = memory.to_dict()
    if memory.memory_id is not None:
        dict_["id"] = RecordID(memory_table_name, memory.memory_id)
        del dict_["memory_id"]
    if memory.user_id is not None:
        dict_["user"] = RecordID(user_table_name, memory.user_id)
        del dict_["user_id"]
    return dict_


def deserialize_knowledge_row(knowledge_row_raw: dict) -> KnowledgeRow:
    copy = knowledge_row_raw.copy()

    # - id
    copy = deserialize_record_id(copy, "id")

    # - created_at
    created_at = copy.get("created_at")
    if created_at and isinstance(created_at, datetime.datetime):
        copy["created_at"] = int(created_at.timestamp())

    # - updated_at
    updated_at = copy.get("updated_at")
    if updated_at and isinstance(updated_at, datetime.datetime):
        copy["updated_at"] = int(updated_at.timestamp())

    # return
    return KnowledgeRow.model_validate(copy)


def serialize_knowledge_row(knowledge_row: KnowledgeRow, knowledge_table_name: str) -> dict:
    dict_ = knowledge_row.to_dict()
    if knowledge_row.id is not None:
        dict_["id"] = RecordID(knowledge_table_name, knowledge_row.id)
    return dict_


def desurealize_eval_run_record(eval_run_record_raw: dict) -> dict:
    copy = eval_run_record_raw.copy()

    copy = deserialize_record_id(copy, "run_id", "id")
    copy = deserialize_record_id(copy, "agent_id", "agent")
    copy = deserialize_record_id(copy, "team_id", "team")
    copy = deserialize_record_id(copy, "workflow_id", "workflow")

    return copy


def deserialize_eval_run_record(eval_run_record_raw: dict) -> EvalRunRecord:
    return EvalRunRecord.model_validate(desurealize_eval_run_record(eval_run_record_raw))


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
            DEFINE FIELD OVERWRITE created_at ON {table_name} TYPE datetime VALUE time::now() READONLY;
            DEFINE FIELD OVERWRITE updated_at ON {table_name} TYPE datetime VALUE time::now();
            """)
    else:
        return define_table
