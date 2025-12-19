from copy import deepcopy
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from typing import Any, Callable, List, Optional, Type, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_profile import UserProfile
from agno.memory_v2.v2_prompts import AGENTIC_INSTRUCTIONS, EXTRACTION_PROMPT
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_info, log_warning


@dataclass
class MemoryManagerV2:
    model: Optional[Model] = None
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # Schema overrides (custom dataclasses for each layer)
    profile_schema: Optional[Type] = None
    policies_schema: Optional[Type] = None
    knowledge_schema: Optional[Type] = None
    feedback_schema: Optional[Type] = None

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        profile_schema: Optional[Type] = None,
        policies_schema: Optional[Type] = None,
        knowledge_schema: Optional[Type] = None,
        feedback_schema: Optional[Type] = None,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.profile_schema = profile_schema
        self.policies_schema = policies_schema
        self.knowledge_schema = knowledge_schema
        self.feedback_schema = feedback_schema

    # ==========================================================================
    # CRUD
    # ==========================================================================

    def get_user(self, user_id: str) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.get_user_profile(user_id=user_id)

    async def aget_user(self, user_id: str) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.get_user_profile(user_id=user_id)
        return self.db.get_user_profile(user_id=user_id)

    def upsert_user(self, user_profile: UserProfile) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.upsert_user_profile(user_profile=user_profile)

    async def aupsert_user(self, user_profile: UserProfile) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.upsert_user_profile(user_profile=user_profile)
        return self.db.upsert_user_profile(user_profile=user_profile)

    def delete_user(self, user_id: str) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        self.db = cast(BaseDb, self.db)
        self.db.delete_user_profile(user_id=user_id)

    async def adelete_user(self, user_id: str) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        if isinstance(self.db, AsyncBaseDb):
            await self.db.delete_user_profile(user_id=user_id)
        else:
            self.db.delete_user_profile(user_id=user_id)

    # ==========================================================================
    # CONTEXT COMPILATION
    # ==========================================================================

    def compile_user_context(self, user_id: str) -> str:
        user = self.get_user(user_id)
        if not user:
            return ""
        return self._format_context(user)

    async def acompile_user_context(self, user_id: str) -> str:
        user = await self.aget_user(user_id)
        if not user:
            return ""
        return self._format_context(user)

    def _format_context(self, user: UserProfile) -> str:
        """Format user memory as clean XML for model context."""
        sections = []

        # Policies (highest authority)
        if user.policies:
            lines = ["<policies>"]
            for key, value in user.policies.items():
                if isinstance(value, list):
                    lines.append(f"{key}: {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"{key}: {value}")
            lines.append("</policies>")
            sections.append("\n".join(lines))

        # Profile
        if user.user_profile:
            lines = ["<profile>"]
            for key, value in user.user_profile.items():
                if isinstance(value, list):
                    lines.append(f"{key}: {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"{key}: {value}")
            lines.append("</profile>")
            sections.append("\n".join(lines))

        # Knowledge
        if user.knowledge:
            lines = ["<knowledge>"]
            for item in user.knowledge:
                if isinstance(item, dict):
                    key = item.get("key", "")
                    value = item.get("value", item.get("content", ""))
                    if key:
                        lines.append(f"- {key}: {value}")
                    elif value:
                        lines.append(f"- {value}")
                else:
                    lines.append(f"- {item}")
            lines.append("</knowledge>")
            sections.append("\n".join(lines))

        # Feedback (lowest authority)
        if user.feedback:
            lines = ["<feedback>"]
            if isinstance(user.feedback, dict):
                for key, items in user.feedback.items():
                    if isinstance(items, list) and items:
                        lines.append(f"{key}:")
                        for item in items:
                            lines.append(f"- {item}")
            lines.append("</feedback>")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        return "<user_memory>\n" + "\n\n".join(sections) + "\n</user_memory>"

    # ==========================================================================
    # EXTRACTION
    # ==========================================================================

    def extract_from_conversation(self, messages: List[Message], user_id: str) -> bool:
        if not messages:
            log_debug("No messages to extract from")
            return False

        if not self.db:
            log_warning("Database not provided, cannot save extracted memory")
            return False

        log_debug(f"Extracting memory for user_id={user_id} from {len(messages)} messages")

        existing_profile = self.get_user(user_id)
        system_message = self._get_extraction_prompt(existing_profile)

        conversation_text = "\n".join(
            [f"{m.role}: {m.get_content_string()}" for m in messages if m.role in ("user", "assistant") and m.content]
        )

        messages_for_model: List[Message] = [
            Message(role="system", content=system_message),
            Message(
                role="user",
                content=f"Review this conversation and save any useful user information using the save_user_info tool:\n\n{conversation_text}",
            ),
        ]

        extraction_tools = self._get_extraction_tools(user_id)
        model = self._get_model()
        model_copy = deepcopy(model)

        try:
            response = model_copy.response(messages=messages_for_model, tools=extraction_tools)
            tool_calls_made = response.tool_calls is not None and len(response.tool_calls) > 0
            if tool_calls_made:
                log_info(f"Extracted and saved memory for user {user_id}")
            else:
                log_debug(f"No new information extracted for user {user_id}")
            return True
        except Exception as e:
            log_error(f"Error during memory extraction: {e}")
            return False

    async def aextract_from_conversation(self, messages: List[Message], user_id: str) -> bool:
        if not messages:
            log_debug("No messages to extract from")
            return False

        if not self.db:
            log_warning("Database not provided, cannot save extracted memory")
            return False

        log_debug(f"Extracting memory for user_id={user_id} from {len(messages)} messages")

        existing_profile = await self.aget_user(user_id)
        system_message = self._get_extraction_prompt(existing_profile)

        conversation_text = "\n".join(
            [f"{m.role}: {m.get_content_string()}" for m in messages if m.role in ("user", "assistant") and m.content]
        )

        messages_for_model: List[Message] = [
            Message(role="system", content=system_message),
            Message(
                role="user",
                content=f"Review this conversation and save any useful user information using the save_user_info tool:\n\n{conversation_text}",
            ),
        ]

        extraction_tools = self._get_extraction_tools(user_id)
        model = self._get_model()
        model_copy = deepcopy(model)

        try:
            response = await model_copy.aresponse(messages=messages_for_model, tools=extraction_tools)
            tool_calls_made = response.tool_calls is not None and len(response.tool_calls) > 0
            if tool_calls_made:
                log_info(f"Extracted and saved memory for user {user_id}")
            else:
                log_debug(f"No new information extracted for user {user_id}")
            return True
        except Exception as e:
            log_error(f"Error during memory extraction: {e}")
            return False

    # ==========================================================================
    # AGENTIC TOOLS
    # ==========================================================================

    def get_user_memory_tools(self, user_id: str) -> List[Callable]:
        if not self.db:
            log_warning("No database configured for agentic memory tools")
            return []

        manager = self

        def save_user_info(info_type: str, key: str, value: Any) -> str:
            """Save information about the user for future conversations.

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: A label for the information. For feedback, use "positive" or "negative".
                value: The actual information to remember

            Returns:
                Confirmation message
            """
            result = manager._save_to_layer(user_id, info_type, key, value)
            if result.startswith("Saved "):
                return "Remembered " + result[6:]
            return result

        def forget_user_info(info_type: str, key: str) -> str:
            """Forget specific information about the user.

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: The key/label to forget. For feedback, use "positive" or "negative".

            Returns:
                Confirmation message
            """
            return manager._delete_from_layer(user_id, info_type, key)

        return [save_user_info, forget_user_info]

    def get_agentic_memory_instructions(self) -> str:
        return AGENTIC_INSTRUCTIONS

    # ==========================================================================
    # PRIVATE HELPERS
    # ==========================================================================

    def _get_model(self) -> Model:
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                log_error(e)
                log_error(
                    "Agno uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                )
                raise
            self.model = OpenAIChat(id="gpt-4o-mini")
        return self.model

    def _get_schema_hints(self, schema: Optional[Type]) -> str:
        if schema is None:
            return ""
        if is_dataclass(schema):
            field_info = []
            for field in dataclass_fields(schema):
                field_type = getattr(field.type, "__name__", str(field.type))
                field_info.append(f"{field.name}: {field_type}")
            if field_info:
                return f"\nExpected fields: {', '.join(field_info)}"
        return ""

    def _get_extraction_prompt(self, existing_profile: Optional[UserProfile] = None) -> str:
        """Build extraction system message."""
        parts = [EXTRACTION_PROMPT]

        # Add schema hints if custom schemas provided
        schema_hints = []
        if self.profile_schema:
            schema_hints.append(f"Profile fields: {self._get_schema_hints(self.profile_schema)}")
        if self.policies_schema:
            schema_hints.append(f"Policy fields: {self._get_schema_hints(self.policies_schema)}")
        if self.knowledge_schema:
            schema_hints.append(f"Knowledge fields: {self._get_schema_hints(self.knowledge_schema)}")
        if self.feedback_schema:
            schema_hints.append(f"Feedback fields: {self._get_schema_hints(self.feedback_schema)}")
        if schema_hints:
            parts.append("\n## Schema Hints\n" + "\n".join(schema_hints))

        # Add existing profile to prevent re-saving
        if existing_profile:
            parts.append("\n\n## Existing User Profile (do NOT re-save these)\n")
            if existing_profile.user_profile:
                parts.append("<existing_profile>\n")
                for key, value in existing_profile.user_profile.items():
                    parts.append(f"  {key}: {value}\n")
                parts.append("</existing_profile>\n")
            if existing_profile.policies:
                parts.append("<existing_policies>\n")
                for key, value in existing_profile.policies.items():
                    parts.append(f"  {key}: {value}\n")
                parts.append("</existing_policies>\n")
            if existing_profile.knowledge:
                parts.append("<existing_knowledge>\n")
                for item in existing_profile.knowledge:
                    if isinstance(item, dict):
                        parts.append(f"  - {item.get('value', item.get('content', str(item)))}\n")
                    else:
                        parts.append(f"  - {item}\n")
                parts.append("</existing_knowledge>\n")
            if existing_profile.feedback:
                parts.append("<existing_feedback>\n")
                if isinstance(existing_profile.feedback, dict):
                    for key, items in existing_profile.feedback.items():
                        if items:
                            parts.append(f"  {key}: {items}\n")
                parts.append("</existing_feedback>\n")

        return "".join(parts)

    def _get_extraction_tools(self, user_id: str) -> List[Function]:
        manager = self

        def save_user_info(info_type: str, key: str, value: Any) -> str:
            """Save information about the user.

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: A label for the information. For feedback, use "positive" or "negative".
                value: The actual information to save

            Returns:
                Confirmation message
            """
            return manager._save_to_layer(user_id, info_type, key, value)

        return [Function.from_callable(save_user_info)]

    def _save_to_layer(self, user_id: str, info_type: str, key: str, value: Any) -> str:
        try:
            user = self.get_user(user_id)
            if user is None:
                user = UserProfile(user_id=user_id)

            if info_type == "profile":
                if user.user_profile is None:
                    user.user_profile = {}
                user.user_profile[key] = value
                log_debug(f"Saved profile {key}={value} for {user_id}")

            elif info_type == "policy":
                if user.memory_layers is None:
                    user.memory_layers = {}
                if "policies" not in user.memory_layers:
                    user.memory_layers["policies"] = {}
                user.memory_layers["policies"][key] = value
                log_debug(f"Saved policy {key}={value} for {user_id}")

            elif info_type == "knowledge":
                if user.memory_layers is None:
                    user.memory_layers = {}
                if "knowledge" not in user.memory_layers:
                    user.memory_layers["knowledge"] = []
                fact_entry = {"key": key, "value": value}
                existing = user.memory_layers["knowledge"]
                user.memory_layers["knowledge"] = [f for f in existing if f.get("key") != key]
                user.memory_layers["knowledge"].append(fact_entry)
                log_debug(f"Saved knowledge {key}={value} for {user_id}")

            elif info_type == "feedback":
                if user.memory_layers is None:
                    user.memory_layers = {}
                if "feedback" not in user.memory_layers:
                    user.memory_layers["feedback"] = {"positive": [], "negative": []}
                if key in ["positive", "negative"]:
                    if key not in user.memory_layers["feedback"]:
                        user.memory_layers["feedback"][key] = []
                    if value not in user.memory_layers["feedback"][key]:
                        user.memory_layers["feedback"][key].append(value)
                    log_debug(f"Saved {key} feedback: {value} for {user_id}")
                else:
                    return f"For feedback, key must be 'positive' or 'negative', got '{key}'"

            else:
                return f"Unknown info_type: {info_type}. Use 'profile', 'policy', 'knowledge', or 'feedback'"

            self.upsert_user(user)
            return f"Saved {info_type}: {key} = {value}"

        except Exception as e:
            log_error(f"Error saving to layer: {e}")
            return f"Error: {e}"

    def _delete_from_layer(self, user_id: str, info_type: str, key: str) -> str:
        try:
            user = self.get_user(user_id)
            if user is None:
                return "No memory found for user"

            if info_type == "profile":
                if user.user_profile and key in user.user_profile:
                    del user.user_profile[key]
                    log_debug(f"Forgot profile {key} for {user_id}")

            elif info_type == "policy":
                if user.memory_layers and "policies" in user.memory_layers:
                    if key in user.memory_layers["policies"]:
                        del user.memory_layers["policies"][key]
                        log_debug(f"Forgot policy {key} for {user_id}")

            elif info_type == "knowledge":
                if user.memory_layers and "knowledge" in user.memory_layers:
                    existing = user.memory_layers["knowledge"]
                    user.memory_layers["knowledge"] = [f for f in existing if f.get("key") != key]
                    log_debug(f"Forgot knowledge {key} for {user_id}")

            elif info_type == "feedback":
                if user.memory_layers and "feedback" in user.memory_layers:
                    if key in ["positive", "negative"]:
                        user.memory_layers["feedback"][key] = []
                        log_debug(f"Cleared {key} feedback for {user_id}")
                    else:
                        return f"For feedback, key must be 'positive' or 'negative', got '{key}'"

            else:
                return f"Unknown info_type: {info_type}. Use 'profile', 'policy', 'knowledge', or 'feedback'"

            self.upsert_user(user)
            return f"Forgot {info_type}: {key}"

        except Exception as e:
            log_error(f"Error deleting from layer: {e}")
            return f"Error: {e}"
