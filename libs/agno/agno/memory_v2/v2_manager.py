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
class MemoryCompiler:
    model: Optional[Model] = None
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # Optional schema
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

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.get_user_profile(user_id=user_id)

    def upsert_user_profile(self, user_profile: UserProfile) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.upsert_user_profile(user_profile=user_profile)

    def delete_user_profile(self, user_id: str) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        self.db = cast(BaseDb, self.db)
        self.db.delete_user_profile(user_id=user_id)

    def compile_user_memory(self, user_id: str) -> str:
        user_profile = self.get_user_profile(user_id)
        if not user_profile:
            return ""
        return self._format_context(user_profile)

    def _format_context(self, user_profile: UserProfile) -> str:
        sections = []

        # Policies (highest authority)
        if user_profile.policies:
            lines = ["<policies>"]
            for key, value in user_profile.policies.items():
                if isinstance(value, list):
                    lines.append(f"{key}: {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"{key}: {value}")
            lines.append("</policies>")
            sections.append("\n".join(lines))

        # Profile
        if user_profile.user_profile:
            lines = ["<profile>"]
            for key, value in user_profile.user_profile.items():
                if isinstance(value, list):
                    lines.append(f"{key}: {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"{key}: {value}")
            lines.append("</profile>")
            sections.append("\n".join(lines))

        # Knowledge
        if user_profile.knowledge:
            lines = ["<knowledge>"]
            for item in user_profile.knowledge:
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
        if user_profile.feedback:
            lines = ["<feedback>"]
            if isinstance(user_profile.feedback, dict):
                for key, items in user_profile.feedback.items():
                    if isinstance(items, list) and items:
                        lines.append(f"{key}:")
                        for item in items:
                            lines.append(f"- {item}")
            lines.append("</feedback>")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        return "<user_memory>\n" + "\n\n".join(sections) + "\n</user_memory>"

    def extract_from_conversation(self, messages: List[Message], user_id: str) -> bool:
        if not messages:
            log_debug("No messages to extract from")
            return False

        if not self.db:
            log_warning("Database not provided, cannot save extracted memory")
            return False

        log_debug(f"Extracting memory for user_id={user_id} from {len(messages)} messages")

        existing_profile = self.get_user_profile(user_id)
        system_message = self._get_extraction_prompt(existing_profile)

        conversation_text = "\n".join(
            [f"{m.role}: {m.get_content_string()}" for m in messages if m.role in ("user", "assistant") and m.content]
        )

        messages_for_model: List[Message] = [
            Message(role="system", content=system_message),
            Message(
                role="user",
                content=f"Review this conversation and save any useful user information using the update_user_memory tool:\n\n{conversation_text}",
            ),
        ]

        if self.model is None:
            log_error("No model provided for memory extraction")
            return False

        extraction_tools = self._get_extraction_tools(user_id)
        model_copy = deepcopy(self.model)

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

    def get_user_memory_tools(self, user_id: str) -> List[Callable]:
        if not self.db:
            log_warning("No database configured for agentic memory tools")
            return []

        manager = self

        def update_user_memory(info_type: str, key: str, value: Any = None) -> str:
            """Update or delete user memory.

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: The key/label to update or delete
                value: The value to save. Pass None to delete the key.

            Returns:
                Confirmation message
            """
            result = manager._save_to_user_memory_layer(user_id, info_type, key, value)
            if result.startswith("Saved "):
                return "Remembered " + result[6:]
            return result

        return [update_user_memory]

    def get_agentic_memory_instructions(self) -> str:
        return AGENTIC_INSTRUCTIONS

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
        parts = [EXTRACTION_PROMPT]

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
        tools = self.get_user_memory_tools(user_id)
        if not tools:
            return []
        return [Function.from_callable(tools[0])]

    def _save_to_user_memory_layer(self, user_id: str, info_type: str, key: str, value: Any) -> str:
        try:
            user_profile = self.get_user_profile(user_id)
            if user_profile is None:
                user_profile = UserProfile(user_id=user_id)

            # Handle deletion when value is None
            if value is None:
                return self._delete_key_from_layer(user_profile, user_id, info_type, key)

            if info_type == "profile":
                if user_profile.user_profile is None:
                    user_profile.user_profile = {}
                user_profile.user_profile[key] = value
                log_debug(f"Saved profile {key}={value} for {user_id}")

            elif info_type == "policy":
                if user_profile.memory_layers is None:
                    user_profile.memory_layers = {}
                if "policies" not in user_profile.memory_layers:
                    user_profile.memory_layers["policies"] = {}
                user_profile.memory_layers["policies"][key] = value
                log_debug(f"Saved policy {key}={value} for {user_id}")

            elif info_type == "knowledge":
                if user_profile.memory_layers is None:
                    user_profile.memory_layers = {}
                if "knowledge" not in user_profile.memory_layers:
                    user_profile.memory_layers["knowledge"] = []
                fact_entry = {"key": key, "value": value}
                existing = user_profile.memory_layers["knowledge"]
                user_profile.memory_layers["knowledge"] = [f for f in existing if f.get("key") != key]
                user_profile.memory_layers["knowledge"].append(fact_entry)
                log_debug(f"Saved knowledge {key}={value} for {user_id}")

            elif info_type == "feedback":
                if user_profile.memory_layers is None:
                    user_profile.memory_layers = {}
                if "feedback" not in user_profile.memory_layers:
                    user_profile.memory_layers["feedback"] = {"positive": [], "negative": []}
                if key in ["positive", "negative"]:
                    if key not in user_profile.memory_layers["feedback"]:
                        user_profile.memory_layers["feedback"][key] = []
                    if value not in user_profile.memory_layers["feedback"][key]:
                        user_profile.memory_layers["feedback"][key].append(value)
                    log_debug(f"Saved {key} feedback: {value} for {user_id}")
                else:
                    return f"For feedback, key must be 'positive' or 'negative', got '{key}'"

            else:
                return f"Unknown info_type: {info_type}. Use 'profile', 'policy', 'knowledge', or 'feedback'"

            self.upsert_user_profile(user_profile)
            return f"Saved {info_type}: {key} = {value}"

        except Exception as e:
            log_error(f"Error saving to layer: {e}")
            return f"Error: {e}"

    def _delete_key_from_layer(self, user_profile: UserProfile, user_id: str, info_type: str, key: str) -> str:
        """Delete a key from a memory layer (called when value=None)."""
        deleted = False

        if info_type == "profile":
            if user_profile.user_profile and key in user_profile.user_profile:
                del user_profile.user_profile[key]
                deleted = True
                log_debug(f"Deleted profile {key} for {user_id}")

        elif info_type == "policy":
            if user_profile.memory_layers and "policies" in user_profile.memory_layers:
                if key in user_profile.memory_layers["policies"]:
                    del user_profile.memory_layers["policies"][key]
                    deleted = True
                    log_debug(f"Deleted policy {key} for {user_id}")

        elif info_type == "knowledge":
            if user_profile.memory_layers and "knowledge" in user_profile.memory_layers:
                existing = user_profile.memory_layers["knowledge"]
                new_list = [f for f in existing if f.get("key") != key]
                if len(new_list) < len(existing):
                    user_profile.memory_layers["knowledge"] = new_list
                    deleted = True
                    log_debug(f"Deleted knowledge {key} for {user_id}")

        elif info_type == "feedback":
            if user_profile.memory_layers and "feedback" in user_profile.memory_layers:
                if key in ["positive", "negative"] and key in user_profile.memory_layers["feedback"]:
                    user_profile.memory_layers["feedback"][key] = []
                    deleted = True
                    log_debug(f"Cleared {key} feedback for {user_id}")
                else:
                    return f"For feedback, key must be 'positive' or 'negative', got '{key}'"

        else:
            return f"Unknown info_type: {info_type}. Use 'profile', 'policy', 'knowledge', or 'feedback'"

        if deleted:
            self.upsert_user_profile(user_profile)
            return f"Forgot {info_type}: {key}"
        else:
            return f"Key '{key}' not found in {info_type}"
