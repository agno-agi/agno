from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, Field

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.culture import CulturalArtifact
from agno.models.base import Model
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import (
    log_debug,
    log_error,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)
from agno.utils.prompts import get_json_output_prompt
from agno.utils.string import parse_response_model_str


@dataclass
class CultureManager:
    """Culture Manager"""

    # Model used for artifact management
    model: Optional[Model] = None
    # The database to store cultural artifacts
    db: Optional[BaseDb] = None

    # ----- db tools ---------
    # If the CultureManager can add artifacts
    add_artifacts: bool = True
    # If the CultureManager can update artifacts
    update_artifacts: bool = True
    # If the CultureManager can delete artifacts
    delete_artifacts: bool = True
    # If the CultureManager can clear artifacts
    clear_artifacts: bool = True

    # ----- internal settings ---------
    # Whether artifacts were updated in the last run of the CultureManager
    artifacts_updated: bool = False
    debug_mode: bool = False

    def __init__(
        self,
        model: Optional[Model] = None,
        db: Optional[BaseDb] = None,
        add_artifacts: bool = True,
        update_artifacts: bool = True,
        delete_artifacts: bool = False,
        clear_artifacts: bool = True,
        debug_mode: bool = False,
    ):
        self.model = model
        if self.model is not None and isinstance(self.model, str):
            raise ValueError("Model must be a Model object, not a string")
        self.db = db
        self.add_artifacts = add_artifacts
        self.update_artifacts = update_artifacts
        self.delete_artifacts = delete_artifacts
        self.clear_artifacts = clear_artifacts
        self.debug_mode = debug_mode
        self._tools_for_model: Optional[List[Dict[str, Any]]] = None
        self._functions_for_model: Optional[Dict[str, Function]] = None

    def get_model(self) -> Model:
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                log_error(e)
                log_error(
                    "Agno uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                )
                exit(1)
            self.model = OpenAIChat(id="gpt-4o")
        return self.model

    def set_log_level(self):
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    def initialize(self, user_id: Optional[str] = None):
        self.set_log_level()

    # -*- Retrieve Artifacts -*-
    def get_all_artifacts(self) -> Optional[List[CulturalArtifact]]:
        """Get all cultural artifacts in the database"""
        if self.db:
            return self.db.get_cultural_artifacts()
        return None

    def get_artifact_by_id(self, id: str) -> Optional[CulturalArtifact]:
        """Get the cultural artifact by id"""
        if self.db:
            return self.db.get_cultural_artifact(id=id)
        return None

    def get_artifacts_by_name(self, name: str) -> Optional[List[CulturalArtifact]]:
        """Get the cultural artifacts by name"""
        if self.db:
            return self.db.get_cultural_artifacts(name=name)
        return None

    # -*- Artifact Management -*-
    def add_artifact(
        self,
        artifact: CulturalArtifact,
    ) -> Optional[str]:
        """Add a cultural artifact
        Args:
            artifact (CulturalArtifact): The artifact to add
        Returns:
            str: The id of the artifact
        """
        if self.db:
            if artifact.id is None:
                from uuid import uuid4

                artifact_id = artifact.id or str(uuid4())
                artifact.id = artifact_id

            if not artifact.updated_at:
                artifact.bump_updated_at()

            self._upsert_db_artifact(artifact=artifact)
            return artifact.id

        else:
            log_warning("CultureDb not provided.")
            return None

    def clear_all_artifacts(self) -> None:
        """Clears all cultural artifacts."""
        if self.db:
            self.db.clear_cultural_artifacts()

    # -*- Create Artifacts -*-
    def create_artifact(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """Creates a cultural artifact from a message or a list of messages"""
        self.set_log_level()

        if self.db is None:
            log_warning("CultureDb not provided.")
            return "Please provide a db to store cultural artifacts"

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        artifacts = self.get_all_artifacts()
        if artifacts is None:
            artifacts = []

        existing_artifacts = [artifact.preview() for artifact in artifacts]
        print("Existing artifacts:")
        print(existing_artifacts)
