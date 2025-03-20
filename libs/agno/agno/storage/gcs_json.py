import os
import json
import time
from typing import List, Literal, Optional, Any
from pathlib import Path

from agno.storage.json import JsonStorage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import logger

try:
    from google.cloud import storage as gcs
except ImportError:
    raise ImportError("`google-cloud-storage` not installed. Please install it with `pip install google-cloud-storage`")


class GCSJsonStorage(JsonStorage):
    """
    A Cloud-based JSON storage for agent sessions that stores session (memory) data
    in a GCS bucket. This class derives from Agno's JsonStorage and replaces local
    file system operations with Cloud Storage operations. The GCS client and bucket
    are initialized once in the constructor and then reused for all subsequent operations.

    Parameters:
      - mode: Either "agent" or "workflow".
      - bucket_name: The GCS bucket name (must be provided).
      - project: The GCP project ID (must be provided).
      - credentials: Optional credentials object; if not provided, defaults will be used.
    """

    def __init__(
        self,
        mode: Optional[Literal["agent", "workflow"]] = "agent",
        bucket_name: str = None,
        project: str = None,
        credentials: Optional[Any] = None,
    ):
        # Pass a dummy directory to the parent's constructor, as it's not used.
        super().__init__(dir_path="dummy", mode=mode)
        if not bucket_name:
            raise ValueError("bucket_name must be provided")
        if not project:
            raise ValueError("project must be provided")
        self.bucket_name = bucket_name
        self.project = project

        # Initialize the GCS client once; if STORAGE_EMULATOR_HOST is set, it will be used automatically.
        self.client = gcs.Client(project=self.project, credentials=credentials)
        self.bucket = self.client.bucket(self.bucket_name)

    def _get_blob_path(self, session_id: str) -> str:
        """Returns the blob path for a given session."""
        return f"{session_id}.json"

    def create(self) -> None:
        """
        Creates the bucket if it doesn't exist, using a default location of "US".
        The client and bucket are already stored in self.
        """
        try:
            # Attempt to create the bucket. If it exists, a Conflict error should be raised.
            self.bucket = self.client.create_bucket(self.bucket_name, location="US")
            logger.info(f"Bucket {self.bucket_name} created successfully.")
        except Exception as e:
            # If the bucket already exists, check for conflict (HTTP 409)
            if hasattr(e, 'code') and e.code == 409:
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
        """
        blob = self.bucket.blob(self._get_blob_path(session_id))
        try:
            data_str = blob.download_as_bytes().decode("utf-8")
            data = self.deserialize(data_str)
        except Exception as e:
            logger.error(f"Error reading session {session_id} from GCS: {e}")
            return None

        if user_id and data.get("user_id") != user_id:
            return None

        if self.mode == "agent":
            return AgentSession.from_dict(data)
        elif self.mode == "workflow":
            return WorkflowSession.from_dict(data)
        return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """
        Lists all session IDs stored in the bucket.
        """
        session_ids = []
        prefix = ""
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            if blob.name.endswith(".json"):
                session_ids.append(blob.name.replace(".json", ""))
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """
        Retrieves all sessions stored in the bucket.
        """
        sessions: List[Session] = []
        prefix = ""
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            if blob.name.endswith(".json"):
                try:
                    data_str = blob.download_as_bytes().decode("utf-8")
                    data = self.deserialize(data_str)
                    if user_id and data.get("user_id") != user_id:
                        continue
                    if self.mode == "agent":
                        session = AgentSession.from_dict(data)
                    elif self.mode == "workflow":
                        session = WorkflowSession.from_dict(data)
                    else:
                        session = None
                    if session:
                        sessions.append(session)
                except Exception as e:
                    logger.error(f"Error reading session from blob {blob.name}: {e}")
                    continue
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
