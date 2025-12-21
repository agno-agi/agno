from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from typing import Any, Dict, List, Optional, Type, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_profile import UserProfile
from agno.memory_v2.v2_prompts import USER_MEMORY_EXTRACTION_PROMPT
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_info, log_warning


@dataclass
class MemoryCompiler:
    model: Optional[Model] = None
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # Allow schema overrides
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
        result = self.db.get_user_profile(user_id=user_id)
        return cast(Optional[UserProfile], result)

    def upsert_user_profile(self, user_profile: UserProfile) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        result = self.db.upsert_user_profile(user_profile=user_profile)
        return cast(Optional[UserProfile], result)

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
        import json

        data = {}
        if user_profile.policies:
            data["policies"] = user_profile.policies
        if user_profile.user_profile:
            data["profile"] = user_profile.user_profile
        if user_profile.knowledge:
            data["knowledge"] = user_profile.knowledge
        if user_profile.feedback:
            data["feedback"] = user_profile.feedback

        if not data:
            return ""

        return f"<user_memory>\n{json.dumps(data, indent=2)}\n</user_memory>"

    def _prepare_extraction(self, messages: List[Message], user_id: str) -> Optional[tuple]:
        """Prepare messages and tools for extraction. Returns (messages_for_model, tools) or None."""
        if not messages or not self.db or not self.model:
            return None

        existing_profile = self.get_user_profile(user_id)
        conversation = "\n".join(f"{m.role}: {m.get_content_string()}" for m in messages if m.content)

        messages_for_model = [
            Message(role="system", content=self._get_extraction_prompt(existing_profile)),
            Message(role="user", content=f"Extract user info:\n\n{conversation}"),
        ]

        return (messages_for_model, self._get_extraction_tools(user_id))

    def extract_from_conversation(self, messages: List[Message], user_id: str) -> bool:
        prep = self._prepare_extraction(messages, user_id)
        if not prep:
            return False
        messages_for_model, tools = prep
        try:
            self.model.response(messages=messages_for_model, tools=tools)
            return True
        except Exception:
            return False

    async def aextract_from_conversation(self, messages: List[Message], user_id: str) -> bool:
        prep = self._prepare_extraction(messages, user_id)
        if not prep:
            return False
        messages_for_model, tools = prep
        try:
            await self.model.aresponse(messages=messages_for_model, tools=tools)
            return True
        except Exception:
            return False

    def _get_extraction_prompt(self, existing_profile: Optional[UserProfile] = None) -> str:
        parts = [USER_MEMORY_EXTRACTION_PROMPT]

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

    def _get_extraction_tools(self, user_id: str) -> List[Union[Function, Dict[str, Any]]]:
        if not self.db:
            return []

        def update_user_memory(info_type: str, key: str, value: Any) -> str:
            """Update user memory. info_type: profile/policy/knowledge/feedback. Pass value=None to delete."""
            return self._save_to_user_memory_layer(user_id, info_type, key, value)

        return [Function.from_callable(update_user_memory)]

    def _save_to_user_memory_layer(self, user_id: str, info_type: str, key: str, value: Any) -> str:
        try:
            profile = self.get_user_profile(user_id) or UserProfile(user_id=user_id)

            if value is None:
                return self._delete_key_from_layer(profile, user_id, info_type, key)

            # Ensure memory_layers exists for non-profile types
            if info_type != "profile" and profile.memory_layers is None:
                profile.memory_layers = {}

            if info_type == "profile":
                if profile.user_profile is None:
                    profile.user_profile = {}
                profile.user_profile[key] = value

            elif info_type == "policy":
                profile.memory_layers.setdefault("policies", {})[key] = value

            elif info_type == "knowledge":
                knowledge = profile.memory_layers.setdefault("knowledge", [])
                profile.memory_layers["knowledge"] = [f for f in knowledge if f.get("key") != key]
                profile.memory_layers["knowledge"].append({"key": key, "value": value})

            elif info_type == "feedback":
                if key not in ("positive", "negative"):
                    return f"For feedback, key must be 'positive' or 'negative', got '{key}'"
                feedback = profile.memory_layers.setdefault("feedback", {"positive": [], "negative": []})
                if value not in feedback.setdefault(key, []):
                    feedback[key].append(value)

            else:
                return f"Unknown info_type: {info_type}"

            log_debug(f"Saved {info_type} {key}={value} for {user_id}")
            self.upsert_user_profile(profile)
            return f"Saved {info_type}: {key} = {value}"

        except Exception as e:
            log_error(f"Error saving to layer: {e}")
            return f"Error: {e}"

    def _delete_key_from_layer(self, profile: UserProfile, user_id: str, info_type: str, key: str) -> str:
        """Delete a key from a memory layer (called when value=None)."""
        layers = profile.memory_layers or {}

        if info_type == "profile":
            if profile.user_profile and key in profile.user_profile:
                del profile.user_profile[key]
            else:
                return f"Key '{key}' not found in profile"

        elif info_type == "policy":
            policies = layers.get("policies", {})
            if key in policies:
                del policies[key]
            else:
                return f"Key '{key}' not found in policies"

        elif info_type == "knowledge":
            knowledge = layers.get("knowledge", [])
            before = len(knowledge)
            layers["knowledge"] = [f for f in knowledge if f.get("key") != key]
            if len(layers["knowledge"]) == before:
                return f"Key '{key}' not found in knowledge"

        elif info_type == "feedback":
            if key not in ("positive", "negative"):
                return f"For feedback, key must be 'positive' or 'negative', got '{key}'"
            feedback = layers.get("feedback", {})
            if key in feedback:
                feedback[key] = []
            else:
                return f"Key '{key}' not found in feedback"

        else:
            return f"Unknown info_type: {info_type}"

        log_debug(f"Deleted {info_type} {key} for {user_id}")
        self.upsert_user_profile(profile)
        return f"Forgot {info_type}: {key}"

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
