import json
import time
from dataclasses import asdict
from typing import List, Literal, Optional

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_info, logger

try:
    import redis
except ImportError:
    raise ImportError("`redis` not installed. Please install it using `pip install redis`")


class RedisStorage(Storage):
    def __init__(
        self,
        prefix: str,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        mode: Optional[Literal["agent", "team", "workflow"]] = "agent",
    ):
        """
        Initialize Redis storage for sessions.

        Args:
            prefix (str): Prefix for Redis keys to namespace the sessions
            host (str): Redis host address
            port (int): Redis port number
            db (int): Redis database number
            password (Optional[str]): Redis password if authentication is required
            mode (Optional[Literal["agent", "team", "workflow"]]): Storage mode
        """
        super().__init__(mode)
        self.prefix = prefix
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,  # Automatically decode responses to str
        )
        log_debug(f"Created RedisStorage with prefix: '{self.prefix}'")

    def _get_key(self, session_id: str) -> str:
        """Generate Redis key for a session."""
        return f"{self.prefix}:{session_id}"

    def serialize(self, data: dict) -> str:
        """Serialize data to JSON string."""
        return json.dumps(data, ensure_ascii=False)

    def deserialize(self, data: str) -> dict:
        """Deserialize JSON string to dict."""
        return json.loads(data)

    def create(self) -> None:
        """
        Create storage if it doesn't exist.
        For Redis, we don't need to create anything as it's schema-less.
        """
        # Test connection
        try:
            self.redis_client.ping()
            log_debug("Redis connection successful")
        except redis.ConnectionError as e:
            logger.error(f"Could not connect to Redis: {e}")
            raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """Read a Session from Redis."""
        try:
            data = self.redis_client.get(self._get_key(session_id))
            if data is None:
                return None

            session_data = self.deserialize(data)  # type: ignore
            if user_id and session_data.get("user_id") != user_id:
                return None

            if self.mode == "agent":
                return AgentSession.from_dict(session_data)
            elif self.mode == "team":
                return TeamSession.from_dict(session_data)
            elif self.mode == "workflow":
                return WorkflowSession.from_dict(session_data)

        except Exception as e:
            logger.error(f"Error reading session: {e}")
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """Get all session IDs, optionally filtered by user_id and/or entity_id."""
        session_ids = []
        try:
            # Get all keys matching the prefix pattern
            pattern = f"{self.prefix}:*"
            for key in self.redis_client.scan_iter(match=pattern):
                data = self.deserialize(self.redis_client.get(key))  # type: ignore

                if user_id or entity_id:
                    if user_id and entity_id:
                        if self.mode == "agent" and data["agent_id"] == entity_id and data["user_id"] == user_id:
                            session_ids.append(data["session_id"])
                        elif self.mode == "team" and data["team_id"] == entity_id and data["user_id"] == user_id:
                            session_ids.append(data["session_id"])
                        elif (
                            self.mode == "workflow" and data["workflow_id"] == entity_id and data["user_id"] == user_id
                        ):
                            session_ids.append(data["session_id"])
                    elif user_id and data["user_id"] == user_id:
                        session_ids.append(data["session_id"])
                    elif entity_id:
                        if self.mode == "agent" and data["agent_id"] == entity_id:
                            session_ids.append(data["session_id"])
                        elif self.mode == "team" and data["team_id"] == entity_id:
                            session_ids.append(data["session_id"])
                        elif self.mode == "workflow" and data["workflow_id"] == entity_id:
                            session_ids.append(data["session_id"])
                else:
                    # No filters applied, add all session_ids
                    session_ids.append(data["session_id"])

        except Exception as e:
            logger.error(f"Error getting session IDs: {e}")

        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """Get all sessions, optionally filtered by user_id and/or entity_id."""
        sessions: List[Session] = []
        try:
            pattern = f"{self.prefix}:*"
            for key in self.redis_client.scan_iter(match=pattern):
                data = self.deserialize(self.redis_client.get(key))  # type: ignore

                if user_id or entity_id:
                    _session: Optional[Session] = None

                    if user_id and entity_id:
                        if self.mode == "agent" and data["agent_id"] == entity_id and data["user_id"] == user_id:
                            _session = AgentSession.from_dict(data)
                        elif self.mode == "team" and data["team_id"] == entity_id and data["user_id"] == user_id:
                            _session = TeamSession.from_dict(data)
                        elif (
                            self.mode == "workflow" and data["workflow_id"] == entity_id and data["user_id"] == user_id
                        ):
                            _session = WorkflowSession.from_dict(data)
                    elif user_id and data["user_id"] == user_id:
                        if self.mode == "agent":
                            _session = AgentSession.from_dict(data)
                        elif self.mode == "team":
                            _session = TeamSession.from_dict(data)
                        elif self.mode == "workflow":
                            _session = WorkflowSession.from_dict(data)
                    elif entity_id:
                        if self.mode == "agent" and data["agent_id"] == entity_id:
                            _session = AgentSession.from_dict(data)
                        elif self.mode == "team" and data["team_id"] == entity_id:
                            _session = TeamSession.from_dict(data)
                        elif self.mode == "workflow" and data["workflow_id"] == entity_id:
                            _session = WorkflowSession.from_dict(data)

                    if _session:
                        sessions.append(_session)
                else:
                    _session = None
                    # No filters applied, add all sessions
                    if self.mode == "agent":
                        _session = AgentSession.from_dict(data)
                    elif self.mode == "team":
                        _session = TeamSession.from_dict(data)
                    elif self.mode == "workflow":
                        _session = WorkflowSession.from_dict(data)
                    if _session:
                        sessions.append(_session)

        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")

        return sessions

    def upsert(self, session: Session) -> Optional[Session]:
        """Insert or update a Session in Redis."""
        try:
            data = asdict(session)
            data["updated_at"] = int(time.time())
            if "created_at" not in data:
                data["created_at"] = data["updated_at"]

            key = self._get_key(session.session_id)
            self.redis_client.set(key, self.serialize(data))
            return session
        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None):
        """Delete a session from Redis."""
        if session_id is None:
            return
        try:
            key = self._get_key(session_id)
            self.redis_client.delete(key)
            log_debug(f"Deleted session: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """Drop all sessions from storage."""
        try:
            pattern = f"{self.prefix}:*"
            for key in self.redis_client.scan_iter(match=pattern):
                self.redis_client.delete(key)
            log_info(f"Dropped all sessions with prefix: {self.prefix}")
        except Exception as e:
            logger.error(f"Error dropping sessions: {e}")

    def upgrade_schema(self) -> None:
        """
        Upgrade the schema of the storage.
        For Redis, this is a no-op as it's schema-less.
        """
        pass
