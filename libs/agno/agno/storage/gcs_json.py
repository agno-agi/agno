import json
import time
from typing import Any, List, Literal, Optional

from agno.storage.json import JsonStorage, Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import logger

try:
    from google.cloud import storage as gcs
except ImportError:
    raise ImportError("`google-cloud-storage` not installed. Please install it with `pip install google-cloud-storage`")


class GCSJsonStorage(JsonStorage):
    """
    A Cloud-based JSON storage for agent sessions that stores session (memory) data
    in a GCS bucket. This class derives from JsonStorage and replaces local
    file system operations with Cloud Storage operations. The GCS client and bucket
    are initialized once in the constructor and then reused for all subsequent operations.

    Parameters:
      - bucket_name: The GCS bucket name (must be provided).
      - prefix: The GCS folder path prefix). See (Flat Namespace)[https://cloud.google.com/storage/docs/objects#flat-namespace] in GCS docs for details.
      - mode: One of "agent", "team", or "workflow". Defaults to "agent".
      - project: Optional; the GCP project ID. Defaults to current Google Cloud's project (set with `gcloud init`).
      - location: Optional; the GCP location for the bucket. Default's to current project's location.
      - credentials: Optional credentials object; if not provided, defaults will be used.
    """

    def __init__(
        self,
        bucket_name: str,
        prefix: Optional[str] = "",
        mode: Optional[Literal["agent", "team", "workflow"]] = "agent",
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials: Optional[Any] = None,
    ):
        # Call Storage's __init__ directly to bypass the folder creation logic in JsonStorage.
        Storage.__init__(self, mode=mode)
        self.bucket_name = bucket_name
        if prefix is not None and prefix != "" and not prefix.endswith("/"):
            prefix += "/"
        self.prefix = prefix
        self.project = project
        self.location = location

        # Initialize the GCS client once; if STORAGE_EMULATOR_HOST is set, it will be used automatically.
        self.client = gcs.Client(project=self.project, credentials=credentials)
        self.bucket = self.client.bucket(self.bucket_name)

    def _get_blob_path(self, session_id: str) -> str:
        """Returns the blob path for a given session."""
        return f"{self.prefix}{session_id}.json"

    def create(self) -> None:
        """
        Creates the bucket if it doesn't exist
        The client and bucket are already stored in self.
        """
        try:
            self.bucket = self.client.create_bucket(self.bucket_name, self.location, self.project)
            logger.info(f"Bucket {self.bucket_name} created successfully.")
        except Exception as e:
            # If the bucket already exists, check for conflict (HTTP 409) and continue.
            if hasattr(e, "code") and e.code == 409:
                logger.info(f"Bucket {self.bucket_name} already exists.")
            else:
                logger.error(f"Failed to create bucket {self.bucket_name}: {e}")
                raise

    def serialize(self, data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, indent=4)

    def deserialize(self, data: str) -> dict:
        return json.loads(data)

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """
        Reads a session JSON blob from the GCS bucket and returns a Session object.
        If the blob is not found, returns None.
        """
        blob = self.bucket.blob(self._get_blob_path(session_id))
        try:
            data_str = blob.download_as_bytes().decode("utf-8")
            data = self.deserialize(data_str)
        except Exception as e:
            # If the error indicates that the blob was not found (404), return None.
            if "404" in str(e):
                return None
            logger.error(f"Error reading session {session_id} from GCS: {e}")
            return None

        if user_id and data.get("user_id") != user_id:
            return None

        if self.mode == "agent":
            return AgentSession.from_dict(data)
        elif self.mode == "team":
            return TeamSession.from_dict(data)
        elif self.mode == "workflow":
            return WorkflowSession.from_dict(data)
        return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """
        Lists all session IDs stored in the bucket.
        """
        session_ids = []
        for blob in self.client.list_blobs(self.bucket, prefix=self.prefix):
            if blob.name.endswith(".json"):
                session_ids.append(blob.name.replace(".json", ""))
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """
        Retrieves all sessions stored in the bucket.
        """
        sessions: List[Session] = []
        for blob in self.client.list_blobs(self.bucket, prefix=self.prefix):
            if blob.name.endswith(".json"):
                try:
                    data_str = blob.download_as_bytes().decode("utf-8")
                    data = self.deserialize(data_str)

                    if user_id and data.get("user_id") != user_id:
                        continue
                    session: Optional[Session] = None
                    if self.mode == "agent":
                        session = AgentSession.from_dict(data)
                    elif self.mode == "team":
                        session = TeamSession.from_dict(data)
                    elif self.mode == "workflow":
                        session = WorkflowSession.from_dict(data)
                    if session is not None:
                        sessions.append(session)
                except Exception as e:
                    logger.error(f"Error reading session from blob {blob.name}: {e}")
                    continue
        return sessions

    def get_recent_sessions(
        self,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = 2,
    ) -> List[Session]:
        """Get the last N sessions, ordered by created_at descending.

        Args:
            num_history_sessions: Number of most recent sessions to return
            user_id: Filter by user ID
            entity_id: Filter by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of most recent sessions
        """
        sessions: List[Session] = []
        # List of (created_at, data) tuples for sorting
        session_data: List[tuple[int, dict]] = []

        try:
            # Get all blobs with the specified prefix
            for blob in self.client.list_blobs(self.bucket, prefix=self.prefix):
                if not blob.name.endswith(".json"):
                    continue

                try:
                    data_str = blob.download_as_bytes().decode("utf-8")
                    data = self.deserialize(data_str)

                    # Apply filters
                    if user_id and data.get("user_id") != user_id:
                        continue

                    # Store with created_at for sorting
                    created_at = data.get("created_at", 0)
                    session_data.append((created_at, data))

                except Exception as e:
                    logger.error(f"Error reading session from blob {blob.name}: {e}")
                    continue

            # Sort by created_at descending and take only num_history_sessions
            session_data.sort(key=lambda x: x[0], reverse=True)
            if limit is not None:
                session_data = session_data[:limit]

            # Convert filtered and sorted data to Session objects
            for _, data in session_data:
                session: Optional[Session] = None
                if self.mode == "agent":
                    session = AgentSession.from_dict(data)
                elif self.mode == "team":
                    session = TeamSession.from_dict(data)
                elif self.mode == "workflow":
                    session = WorkflowSession.from_dict(data)

                if session is not None:
                    sessions.append(session)

        except Exception as e:
            logger.error(f"Error getting last {limit} sessions: {e}")

        return sessions

    def upsert(self, session: Session) -> Optional[Session]:
        """
        Inserts or updates a session JSON blob in the GCS bucket.
        """
        blob = self.bucket.blob(self._get_blob_path(session.session_id))
        try:
            data = session.to_dict()
            data["updated_at"] = int(time.time())
            if "created_at" not in data:
                data["created_at"] = data["updated_at"]
            json_data = self.serialize(data)
            blob.upload_from_string(json_data, content_type="application/json")
            return session
        except Exception as e:
            logger.error(f"Error upserting session {session.session_id}: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None):
        """
        Deletes a session JSON blob from the GCS bucket.
        """
        if session_id is None:
            return
        blob = self.bucket.blob(self._get_blob_path(session_id))
        try:
            blob.delete()
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")

    def drop(self) -> None:
        """
        Deletes all session JSON blobs from the bucket.
        """
        prefix = ""
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            try:
                blob.delete()
            except Exception as e:
                logger.error(f"Error deleting blob {blob.name}: {e}")

    def upgrade_schema(self) -> None:
        """
        Schema upgrade is not implemented.
        """
        pass
