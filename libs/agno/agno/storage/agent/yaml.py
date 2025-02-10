import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Union

import yaml

from agno.storage.agent.base import AgentStorage
from agno.storage.agent.session import AgentSession
from agno.utils.log import logger


class YamlAgentStorage(AgentStorage):
    def __init__(self, dir_path: Union[str, Path]):
        self.dir_path = Path(dir_path)
        self.dir_path.mkdir(parents=True, exist_ok=True)

    def serialize(self, data: dict) -> str:
        return yaml.dump(data, default_flow_style=False)

    def deserialize(self, data: str) -> dict:
        return yaml.safe_load(data)

    def create(self) -> None:
        """Create the storage if it doesn't exist."""
        if not self.dir_path.exists():
            self.dir_path.mkdir(parents=True, exist_ok=True)

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """Read an AgentSession from storage."""
        try:
            with open(self.dir_path / f"{session_id}.yaml", "r", encoding="utf-8") as f:
                data = self.deserialize(f.read())
                if user_id and data["user_id"] != user_id:
                    return None
                return AgentSession.from_dict(data)
        except FileNotFoundError:
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[str]:
        """Get all session IDs, optionally filtered by user_id and/or agent_id."""
        session_ids = []
        for file in self.dir_path.glob("*.yaml"):
            with open(file, "r", encoding="utf-8") as f:
                data = self.deserialize(f.read())
                if (not user_id or data["user_id"] == user_id) and (not agent_id or data["agent_id"] == agent_id):
                    session_ids.append(data["session_id"])
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[AgentSession]:
        """Get all sessions, optionally filtered by user_id and/or agent_id."""
        sessions = []
        for file in self.dir_path.glob("*.yaml"):
            with open(file, "r", encoding="utf-8") as f:
                data = self.deserialize(f.read())
                if (not user_id or data["user_id"] == user_id) and (not agent_id or data["agent_id"] == agent_id):
                    _agent_session = AgentSession.from_dict(data)
                    if _agent_session is not None:
                        sessions.append(_agent_session)
        return sessions

    def upsert(self, session: AgentSession) -> Optional[AgentSession]:
        """Insert or update an AgentSession in storage."""
        try:
            data = asdict(session)
            data["updated_at"] = int(time.time())
            if "created_at" not in data:
                data["created_at"] = data["updated_at"]

            with open(self.dir_path / f"{session.session_id}.yaml", "w", encoding="utf-8") as f:
                f.write(self.serialize(data))
            return session
        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None):
        """Delete a session from storage."""
        if session_id is None:
            return
        try:
            (self.dir_path / f"{session_id}.yaml").unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Drop all sessions from storage."""
        for file in self.dir_path.glob("*.yaml"):
            file.unlink()

    def upgrade_schema(self) -> None:
        """Upgrade the schema of the storage."""
        pass
