from typing import Sequence

from surrealdb import RecordID

from agno.db.base import SessionType
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import deserialize_session_json_fields
from agno.session import Session
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


def serialize_session(session: Session) -> dict:
    _dict = session.to_dict()
    if isinstance(session, AgentSession):
        _dict["agent"] = RecordID("agent", session.agent_id)
    elif isinstance(session, TeamSession):
        _dict["team"] = RecordID("team", session.team_id)
    elif isinstance(session, WorkflowSession):
        _dict["workflow"] = RecordID("workflow", session.workflow_id)
    return _dict


def deserialize_session(session_type: SessionType, session_raw: dict) -> Session | None:
    session_raw = deserialize_session_json_fields(session_raw)
    if session_type == SessionType.AGENT:
        session_raw["agent"] = RecordID("agent", session_raw.get("agent_id"))
        return AgentSession.from_dict(session_raw)
    elif session_type == SessionType.TEAM:
        session_raw["team"] = RecordID("team", session_raw.get("team_id"))
        return TeamSession.from_dict(session_raw)
    elif session_type == SessionType.WORKFLOW:
        session_raw["workflow"] = RecordID("workflow", session_raw.get("workflow_id"))
        return WorkflowSession.from_dict(session_raw)
    else:
        raise ValueError(f"Invalid session type: {session_type}")


def deserialize_sessions(session_type: SessionType, sessions_raw: list[dict]) -> list[Session]:
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


def deserialize_user_memory(memory_raw: dict) -> UserMemory:
    return UserMemory.from_dict(memory_raw)


def deserialize_user_memories(memories_raw: Sequence[dict]) -> list[UserMemory]:
    return [UserMemory.from_dict(x) for x in memories_raw]


def serialize_user_memory(memory: UserMemory) -> dict:
    return memory.to_dict()


def deserialize_knowledge_row(knowledge_row_raw: dict) -> KnowledgeRow:
    return KnowledgeRow.model_validate(knowledge_row_raw)


def serialize_knowledge_row(knowledge_row: KnowledgeRow) -> dict:
    return knowledge_row.to_dict()


def deserialize_eval_run_record(eval_run_record_raw: dict) -> EvalRunRecord:
    return EvalRunRecord.model_validate(eval_run_record_raw)


def serialize_eval_run_record(eval_run_record: EvalRunRecord) -> dict:
    _dict = eval_run_record.model_dump()
    return _dict
