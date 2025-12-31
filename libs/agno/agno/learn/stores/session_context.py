"""
Session Context Store
=====================
Storage backend for Session Context learning type.

Ported from SessionSummaryManager with adaptations for LearningMachine.
"""

import json
from copy import deepcopy
from textwrap import dedent
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, Field

from agno.learn.config import SessionContextConfig
from agno.learn.schemas import DefaultSessionContext
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_warning


class SessionSummaryExtractionResponse(BaseModel):
    """Response model for summary-only extraction."""
    summary: str = Field(..., description="Brief summary of the session")


class SessionPlanningExtractionResponse(BaseModel):
    """Response model for full planning extraction."""
    summary: str = Field(..., description="Brief summary of the session")
    goal: Optional[str] = Field(None, description="User's goal for this session")
    plan: Optional[List[str]] = Field(None, description="Steps to achieve the goal")
    progress: Optional[List[str]] = Field(None, description="Completed steps")


class SessionContextStore:
    """Storage backend for Session Context learning type.

    Handles retrieval, storage, and extraction of session context.
    Context is stored per session_id and is replaced (not appended)
    on each extraction.

    Args:
        db: Database connection for storage.
        config: SessionContextConfig with settings.
    """

    def __init__(
        self,
        db,
        config: Optional[SessionContextConfig] = None,
    ):
        self.db = db
        self.config = config or SessionContextConfig()
        self.schema: Type[BaseModel] = config.schema if config and config.schema else DefaultSessionContext

    def get(self, session_id: str) -> Optional[BaseModel]:
        """Retrieve session context by session_id.

        Args:
            session_id: The unique session identifier.

        Returns:
            Session context as schema instance, or None if not found.
        """
        if not self.db:
            log_warning("SessionContextStore: No database configured")
            return None

        try:
            result = self.db.get_learning(
                learning_type="session_context",
                session_id=session_id,
            )

            if result and result.get("content"):
                content = result["content"]
                if isinstance(content, str):
                    content = json.loads(content)
                return self.schema.model_validate(content)

            return None

        except Exception as e:
            log_error(f"Error retrieving session context: {e}")
            return None

    async def aget(self, session_id: str) -> Optional[BaseModel]:
        """Async version of get."""
        if not self.db:
            log_warning("SessionContextStore: No database configured")
            return None

        try:
            if hasattr(self.db, 'aget_learning'):
                result = await self.db.aget_learning(
                    learning_type="session_context",
                    session_id=session_id,
                )
            else:
                result = self.db.get_learning(
                    learning_type="session_context",
                    session_id=session_id,
                )

            if result and result.get("content"):
                content = result["content"]
                if isinstance(content, str):
                    content = json.loads(content)
                return self.schema.model_validate(content)

            return None

        except Exception as e:
            log_error(f"Error retrieving session context: {e}")
            return None

    def save(self, session_id: str, context: BaseModel) -> None:
        """Save or replace session context.

        Note: Session context is replaced, not appended.

        Args:
            session_id: The unique session identifier.
            context: The context data to save.
        """
        if not self.db:
            log_warning("SessionContextStore: No database configured")
            return

        try:
            content = context.model_dump() if hasattr(context, 'model_dump') else context.dict()

            self.db.upsert_learning(
                id=f"session_context_{session_id}",
                learning_type="session_context",
                session_id=session_id,
                content=content,
            )
            log_debug(f"Saved session context for session_id: {session_id}")

        except Exception as e:
            log_error(f"Error saving session context: {e}")

    async def asave(self, session_id: str, context: BaseModel) -> None:
        """Async version of save."""
        if not self.db:
            log_warning("SessionContextStore: No database configured")
            return

        try:
            content = context.model_dump() if hasattr(context, 'model_dump') else context.dict()

            if hasattr(self.db, 'aupsert_learning'):
                await self.db.aupsert_learning(
                    id=f"session_context_{session_id}",
                    learning_type="session_context",
                    session_id=session_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=f"session_context_{session_id}",
                    learning_type="session_context",
                    session_id=session_id,
                    content=content,
                )
            log_debug(f"Saved session context for session_id: {session_id}")

        except Exception as e:
            log_error(f"Error saving session context: {e}")

    def extract_and_save(
        self,
        session_id: str,
        messages: List[Message],
        model: Model,
        enable_planning: bool = False,
    ) -> Optional[BaseModel]:
        """Extract session context from messages and save.

        Args:
            session_id: The unique session identifier.
            messages: Conversation messages to analyze.
            model: LLM model for extraction.
            enable_planning: If True, extract goal/plan/progress too.

        Returns:
            Extracted context, or None if extraction failed.
        """
        log_debug("SessionContextStore: Extracting session context from messages")

        # Skip if no meaningful messages
        if not self._has_meaningful_messages(messages):
            log_debug("No meaningful messages to summarize")
            return None

        # Build extraction prompt
        extraction_messages = self._build_extraction_prompt(
            session_id=session_id,
            messages=messages,
            enable_planning=enable_planning,
        )

        try:
            model_copy = deepcopy(model)
            response_format = self._get_response_format(model_copy, enable_planning)

            response = model_copy.response(
                messages=extraction_messages,
                response_format=response_format,
            )

            # Parse response
            context = self._parse_extraction_response(
                response=response,
                model=model_copy,
                session_id=session_id,
                enable_planning=enable_planning,
            )

            if context:
                self.save(session_id, context)

            return context

        except Exception as e:
            log_error(f"Error in session context extraction: {e}")
            return None

    async def aextract_and_save(
        self,
        session_id: str,
        messages: List[Message],
        model: Model,
        enable_planning: bool = False,
    ) -> Optional[BaseModel]:
        """Async version of extract_and_save."""
        log_debug("SessionContextStore: Extracting session context from messages (async)")

        if not self._has_meaningful_messages(messages):
            log_debug("No meaningful messages to summarize")
            return None

        extraction_messages = self._build_extraction_prompt(
            session_id=session_id,
            messages=messages,
            enable_planning=enable_planning,
        )

        try:
            model_copy = deepcopy(model)
            response_format = self._get_response_format(model_copy, enable_planning)

            response = await model_copy.aresponse(
                messages=extraction_messages,
                response_format=response_format,
            )

            context = self._parse_extraction_response(
                response=response,
                model=model_copy,
                session_id=session_id,
                enable_planning=enable_planning,
            )

            if context:
                await self.asave(session_id, context)

            return context

        except Exception as e:
            log_error(f"Error in session context extraction: {e}")
            return None

    def _has_meaningful_messages(self, messages: List[Message]) -> bool:
        """Check if there are meaningful messages to summarize."""
        for msg in messages:
            if msg.role in ["user", "assistant"]:
                content = msg.get_content_string() if hasattr(msg, 'get_content_string') else str(msg.content)
                if content and content.strip():
                    return True
        return False

    def _build_extraction_prompt(
        self,
        session_id: str,
        messages: List[Message],
        enable_planning: bool,
    ) -> List[Message]:
        """Build the extraction prompt for the LLM."""

        # Format conversation
        conversation_parts = []
        for msg in messages:
            if msg.role == "user":
                content = msg.get_content_string() if hasattr(msg, 'get_content_string') else str(msg.content)
                if not content or not content.strip():
                    # Handle media-only messages
                    media_types = []
                    if hasattr(msg, 'images') and msg.images:
                        media_types.append(f"{len(msg.images)} image(s)")
                    if hasattr(msg, 'videos') and msg.videos:
                        media_types.append(f"{len(msg.videos)} video(s)")
                    if hasattr(msg, 'audio') and msg.audio:
                        media_types.append(f"{len(msg.audio)} audio file(s)")
                    if hasattr(msg, 'files') and msg.files:
                        media_types.append(f"{len(msg.files)} file(s)")
                    if media_types:
                        conversation_parts.append(f"User: [Provided {', '.join(media_types)}]")
                else:
                    conversation_parts.append(f"User: {content}")
            elif msg.role in ["assistant", "model"]:
                content = msg.get_content_string() if hasattr(msg, 'get_content_string') else str(msg.content)
                if content:
                    conversation_parts.append(f"Assistant: {content}")

        conversation_text = "\n".join(conversation_parts)

        # Custom or default instructions
        custom_instructions = self.config.instructions if self.config and self.config.instructions else ""

        if enable_planning:
            system_prompt = dedent(f"""\
                Analyze this conversation and extract:
                1. Summary: A concise summary of what's been discussed
                2. Goal: The user's main objective for this session (if apparent)
                3. Plan: Steps to achieve the goal (if a plan has been discussed)
                4. Progress: Which steps have been completed (if any)

                {custom_instructions}

                <conversation>
                {conversation_text}
                </conversation>

                Focus on important information that would help continue the conversation.
                Be concise and factual.
            """)
        else:
            system_prompt = dedent(f"""\
                Summarize this conversation concisely.

                Focus on:
                - Key topics discussed
                - Important decisions or conclusions
                - Outstanding questions or next steps

                {custom_instructions}

                <conversation>
                {conversation_text}
                </conversation>

                Keep the summary brief but informative.
            """)

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content="Provide the summary of the conversation."),
        ]

    def _get_response_format(
        self,
        model: Model,
        enable_planning: bool,
    ) -> Union[Dict[str, Any], Type[BaseModel]]:
        """Get appropriate response format based on model capabilities."""

        response_model = SessionPlanningExtractionResponse if enable_planning else SessionSummaryExtractionResponse

        if model.supports_native_structured_outputs:
            return response_model
        elif model.supports_json_schema_outputs:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": response_model.model_json_schema(),
                },
            }
        else:
            return {"type": "json_object"}

    def _parse_extraction_response(
        self,
        response,
        model: Model,
        session_id: str,
        enable_planning: bool,
    ) -> Optional[BaseModel]:
        """Parse the extraction response from the model."""

        response_model = SessionPlanningExtractionResponse if enable_planning else SessionSummaryExtractionResponse

        extraction = None

        # Handle native structured outputs
        if (model.supports_native_structured_outputs and
            response.parsed is not None and
            isinstance(response.parsed, response_model)):
            extraction = response.parsed

        # Parse from string response
        elif isinstance(response.content, str):
            try:
                from agno.utils.string import parse_response_model_str
                extraction = parse_response_model_str(response.content, response_model)
            except Exception as e:
                log_warning(f"Failed to parse extraction response: {e}")
                return None

        if extraction is None:
            return None

        # Convert to schema
        try:
            context_data = {
                "session_id": session_id,
                "summary": extraction.summary,
            }

            if enable_planning and isinstance(extraction, SessionPlanningExtractionResponse):
                context_data["goal"] = extraction.goal
                context_data["plan"] = extraction.plan
                context_data["progress"] = extraction.progress

            return self.schema.model_validate(context_data)

        except Exception as e:
            log_error(f"Failed to validate session context: {e}")
            return None
