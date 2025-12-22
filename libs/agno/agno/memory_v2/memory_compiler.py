import json
from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Type, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_profile import UserProfile
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_warning


@dataclass
class MemoryCompiler:
    """Memory Compiler for User Profiles"""

    # Model used for profile extraction
    model: Optional[Model] = None

    # Provide the system message for the compiler as a string. If not provided, the default system message will be used.
    system_message: Optional[str] = None
    # Provide the profile capture instructions for the compiler as a string. If not provided, the default instructions will be used.
    profile_capture_instructions: Optional[str] = None
    # Additional instructions for the compiler. These instructions are appended to the default system message.
    additional_instructions: Optional[str] = None

    # Whether profile was updated in the last run
    profile_updated: bool = False

    # ----- db tools ---------
    # Whether to delete profile fields
    delete_profile: bool = True
    # Whether to update profile fields
    update_profile: bool = True

    # The database to store user profiles
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    # Schema definitions for structured extraction
    profile_schema: Optional[Type] = None
    policies_schema: Optional[Type] = None
    knowledge_schema: Optional[Type] = None
    feedback_schema: Optional[Type] = None

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        system_message: Optional[str] = None,
        profile_capture_instructions: Optional[str] = None,
        additional_instructions: Optional[str] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        profile_schema: Optional[Type] = None,
        policies_schema: Optional[Type] = None,
        knowledge_schema: Optional[Type] = None,
        feedback_schema: Optional[Type] = None,
        delete_profile: bool = True,
        update_profile: bool = True,
    ):
        self.model = model  # type: ignore[assignment]
        self.system_message = system_message
        self.profile_capture_instructions = profile_capture_instructions
        self.additional_instructions = additional_instructions
        self.db = db
        self.profile_schema = profile_schema
        self.policies_schema = policies_schema
        self.knowledge_schema = knowledge_schema
        self.feedback_schema = feedback_schema
        self.delete_profile = delete_profile
        self.update_profile = update_profile
        self.profile_updated = False

        if self.model is not None:
            self.model = get_model(self.model)

    def get_user_profile(self, user_id: Optional[str] = None) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if user_id is None:
            user_id = "default"
        self.db = cast(BaseDb, self.db)
        return self.db.get_user_profile(user_id=user_id)

    def save_user_profile(self, user_profile: UserProfile) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.upsert_user_profile(user_profile=user_profile)

    def delete_user_profile(self, user_id: Optional[str] = None) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        if user_id is None:
            user_id = "default"
        self.db = cast(BaseDb, self.db)
        self.db.delete_user_profile(user_id=user_id)

    async def aget_user_profile(self, user_id: Optional[str] = None) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if user_id is None:
            user_id = "default"
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.get_user_profile(user_id=user_id)
        return self.db.get_user_profile(user_id=user_id)

    async def asave_user_profile(self, user_profile: UserProfile) -> Optional[UserProfile]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.upsert_user_profile(user_profile=user_profile)
        return self.db.upsert_user_profile(user_profile=user_profile)

    async def adelete_user_profile(self, user_id: Optional[str] = None) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        if user_id is None:
            user_id = "default"
        if isinstance(self.db, AsyncBaseDb):
            await self.db.delete_user_profile(user_id=user_id)
        else:
            self.db.delete_user_profile(user_id=user_id)

    def compile_user_profile(self, user_id: Optional[str] = None) -> str:
        if user_id is None:
            user_id = "default"
        user_profile = self.get_user_profile(user_id)
        if not user_profile:
            return ""
        return self._format_profile_as_context(user_profile)

    async def acompile_user_profile(self, user_id: Optional[str] = None) -> str:
        if user_id is None:
            user_id = "default"
        user_profile = await self.aget_user_profile(user_id)
        if not user_profile:
            return ""
        return self._format_profile_as_context(user_profile)

    def _format_profile_as_context(self, user_profile: UserProfile) -> str:
        data: Dict[str, Any] = {}
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

    def create_user_profile(
        self,
        message: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates or updates user profile from a message."""
        if self.db is None:
            log_warning("Database not provided.")
            return "Please provide a db to store profile"

        if not message:
            return "No message provided"

        if user_id is None:
            user_id = "default"

        log_debug("MemoryCompiler Start", center=True)

        # Use schema-based extraction if profile_schema is provided
        if self.profile_schema:
            result = self._extract_with_schema(message, user_id)
        else:
            result = self._extract_with_tools(message, user_id)

        log_debug("MemoryCompiler End", center=True)
        return result

    async def acreate_user_profile(
        self,
        message: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates or updates user profile from a message (async)."""
        if self.db is None:
            log_warning("Database not provided.")
            return "Please provide a db to store profile"

        if not message:
            return "No message provided"

        if user_id is None:
            user_id = "default"

        log_debug("MemoryCompiler Start", center=True)

        # Use schema-based extraction if profile_schema is provided
        if self.profile_schema:
            result = await self._aextract_with_schema(message, user_id)
        else:
            result = await self._aextract_with_tools(message, user_id)

        log_debug("MemoryCompiler End", center=True)
        return result

    def _extract_with_schema(self, message: str, user_id: str) -> str:
        """Extract profile using fixed Pydantic schema (structured output)."""
        model_copy = deepcopy(self.model)

        existing_profile = self.get_user_profile(user_id)
        existing_context = ""
        if existing_profile and existing_profile.user_profile:
            existing_context = f"\n\nExisting profile (update/merge with new info):\n{json.dumps(existing_profile.user_profile, indent=2)}"

        system_content = dedent(
            f"""\
            Extract user profile information from the message.
            Return the extracted information matching the schema.
            Only extract information that is explicitly mentioned.
            Leave fields as null if not mentioned.{existing_context}
            """
        )

        messages_for_model: List[Message] = [
            Message(role="system", content=system_content),
            Message(role="user", content=message),
        ]

        response = model_copy.response(
            messages=messages_for_model,
            response_format=self.profile_schema,
        )

        # Merge extracted data into profile
        if response.parsed:
            profile = self.get_user_profile(user_id) or UserProfile(user_id=user_id)
            extracted = response.parsed.model_dump(exclude_none=True)
            if extracted:
                if profile.user_profile is None:
                    profile.user_profile = {}
                profile.user_profile.update(extracted)
                self.save_user_profile(profile)
                self.profile_updated = True

        return response.content or "Extraction complete"

    async def _aextract_with_schema(self, message: str, user_id: str) -> str:
        """Extract profile using fixed Pydantic schema (structured output) - async."""
        model_copy = deepcopy(self.model)

        existing_profile = await self.aget_user_profile(user_id)
        existing_context = ""
        if existing_profile and existing_profile.user_profile:
            existing_context = f"\n\nExisting profile (update/merge with new info):\n{json.dumps(existing_profile.user_profile, indent=2)}"

        system_content = dedent(
            f"""\
            Extract user profile information from the message.
            Return the extracted information matching the schema.
            Only extract information that is explicitly mentioned.
            Leave fields as null if not mentioned.{existing_context}
            """
        )

        messages_for_model: List[Message] = [
            Message(role="system", content=system_content),
            Message(role="user", content=message),
        ]

        response = await model_copy.aresponse(
            messages=messages_for_model,
            response_format=self.profile_schema,
        )

        # Merge extracted data into profile
        if response.parsed:
            profile = await self.aget_user_profile(user_id) or UserProfile(user_id=user_id)
            extracted = response.parsed.model_dump(exclude_none=True)
            if extracted:
                if profile.user_profile is None:
                    profile.user_profile = {}
                profile.user_profile.update(extracted)
                await self.asave_user_profile(profile)
                self.profile_updated = True

        return response.content or "Extraction complete"

    def _extract_with_tools(self, message: str, user_id: str) -> str:
        """Extract profile using flexible tool-based approach."""
        existing_profile = self.get_user_profile(user_id)

        model_copy = deepcopy(self.model)

        # Prepare tools
        _tools = self._get_db_tools(
            user_id=user_id,
            db=cast(BaseDb, self.db),
            input_string=message,
            enable_update_profile=self.update_profile,
            enable_delete_profile=self.delete_profile,
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_profile=existing_profile,
                enable_update_profile=self.update_profile,
                enable_delete_profile=self.delete_profile,
            ),
            Message(role="user", content=message),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(
            messages=messages_for_model,
            tools=_tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.profile_updated = True

        return response.content or "No response from model"

    async def _aextract_with_tools(self, message: str, user_id: str) -> str:
        """Extract profile using flexible tool-based approach - async."""
        existing_profile = await self.aget_user_profile(user_id)

        model_copy = deepcopy(self.model)

        # Prepare tools
        if isinstance(self.db, AsyncBaseDb):
            _tools = await self._aget_db_tools(
                user_id=user_id,
                db=self.db,
                input_string=message,
                enable_update_profile=self.update_profile,
                enable_delete_profile=self.delete_profile,
            )
        else:
            _tools = self._get_db_tools(
                user_id=user_id,
                db=self.db,
                input_string=message,
                enable_update_profile=self.update_profile,
                enable_delete_profile=self.delete_profile,
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_profile=existing_profile,
                enable_update_profile=self.update_profile,
                enable_delete_profile=self.delete_profile,
            ),
            Message(role="user", content=message),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=_tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.profile_updated = True

        return response.content or "No response from model"

    def get_system_message(
        self,
        existing_profile: Optional[UserProfile] = None,
        enable_delete_profile: bool = True,
        enable_update_profile: bool = True,
    ) -> Message:
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        profile_capture_instructions = self.profile_capture_instructions or dedent(
            """\
            Profile information should capture personal details about the user that are relevant to the current conversation, such as:
            - Personal facts: name, age, occupation, location, interests, and preferences
            - Opinions and preferences: what the user likes, dislikes, enjoys, or finds frustrating
            - Significant life events or experiences shared by the user
            - Important context about the user's current situation, challenges, or goals
            - Policies: user-defined rules or constraints for AI behavior
            - Knowledge: factual information the user wants remembered
            - Feedback: positive or negative feedback about AI responses
        """
        )

        # -*- Return a system message for the memory compiler
        system_prompt_lines = [
            "You are a Profile Manager that is responsible for managing information and preferences about the user. "
            "You will be provided with a criteria for profile information to capture in the <profile_to_capture> section and a list of existing profile data in the <existing_profile> section.",
            "",
            "## When to add or update profile",
            "- Your first task is to decide if profile information needs to be added, updated, or deleted based on the user's message OR if no changes are needed.",
            "- If the user's message meets the criteria in the <profile_to_capture> section and that information is not already captured in the <existing_profile> section, you should capture it.",
            "- If the users messages does not meet the criteria in the <profile_to_capture> section, no profile updates are needed.",
            "- If the existing profile in the <existing_profile> section captures all relevant information, no updates are needed.",
            "",
            "## How to add or update profile",
            "- If you decide to add new profile information, capture key details as if you were storing them for future reference.",
            "- Profile entries should be brief, third-person statements that encapsulate the most important aspect of the user's input.",
            "  - Example: If the user's message is 'I'm going to the gym', save: profile='goes_to_gym', key='habit', value='goes to the gym regularly'",
            "  - Example: If the user's message is 'My name is John Doe', save: profile='name', key='name', value='John Doe'",
            "- Don't make a single entry too long or complex, create multiple entries if needed to capture all the information.",
            "- Don't repeat the same information in multiple entries. Rather update existing entries if needed.",
            "- If a user asks for information to be forgotten, remove all reference to that information.",
            "- When updating an entry, preserve important existing information while adding new details.",
            "",
            "## Criteria for capturing profile information",
            "Use the following criteria to determine if a user's message should be captured:",
            "",
            "<profile_to_capture>",
            profile_capture_instructions,
            "</profile_to_capture>",
            "",
            "## Updating profile",
            "You will also be provided with existing profile data in the <existing_profile> section. You can:",
            "  - Decide to make no changes.",
        ]
        if enable_update_profile:
            system_prompt_lines.append(
                "  - Decide to add or update profile information, using the `save_profile_field` tool."
            )
        if enable_delete_profile:
            system_prompt_lines.append(
                "  - Decide to delete profile information, using the `delete_profile_field` tool."
            )

        system_prompt_lines += [
            "You can call multiple tools in a single response if needed. ",
            "Only add or update profile information if it is necessary to capture key information provided by the user.",
        ]

        # Add schema hints
        schemas = [
            ("profile", self.profile_schema),
            ("policy", self.policies_schema),
            ("knowledge", self.knowledge_schema),
            ("feedback", self.feedback_schema),
        ]
        schema_parts = []
        for layer_name, schema in schemas:
            if schema:
                hints = self._get_schema_hints(schema)
                if hints:
                    schema_parts.append(f"Prioritized {layer_name} fields:\n{hints}")

        if schema_parts:
            system_prompt_lines.append("\n## Schema Hints")
            system_prompt_lines.append("\n\n".join(schema_parts))
            system_prompt_lines.append("You may also save other relevant information.")

        if existing_profile:
            existing = self._format_profile_as_context(existing_profile)
            if existing:
                system_prompt_lines.append(f"\n<existing_profile>\n{existing}\n</existing_profile>")

        if self.additional_instructions:
            system_prompt_lines.append(self.additional_instructions)

        return Message(role="system", content="\n".join(system_prompt_lines))

    def _save_to_user_memory_layer(self, user_id: str, info_type: str, key: str, value: str) -> str:
        """Save to user memory layer."""
        profile = self.get_user_profile(user_id) or UserProfile(user_id=user_id)
        result = self._apply_save_to_layer(profile, info_type, key, value)
        if not result.startswith("Error"):
            self.save_user_profile(profile)
        return result

    async def _asave_to_user_memory_layer(self, user_id: str, info_type: str, key: str, value: str) -> str:
        """Async save to user memory layer."""
        profile = await self.aget_user_profile(user_id) or UserProfile(user_id=user_id)
        result = self._apply_save_to_layer(profile, info_type, key, value)
        if not result.startswith("Error"):
            await self.asave_user_profile(profile)
        return result

    def _delete_from_user_memory_layer(self, user_id: str, info_type: str, key: str) -> str:
        """Delete from user memory layer."""
        profile = self.get_user_profile(user_id)
        if not profile:
            return f"No profile found for user {user_id}"
        result = self._apply_delete_from_layer(profile, info_type, key)
        if not result.startswith("Error") and not result.endswith("not found"):
            self.save_user_profile(profile)
        return result

    async def _adelete_from_user_memory_layer(self, user_id: str, info_type: str, key: str) -> str:
        """Async delete from user memory layer."""
        profile = await self.aget_user_profile(user_id)
        if not profile:
            return f"No profile found for user {user_id}"
        result = self._apply_delete_from_layer(profile, info_type, key)
        if not result.startswith("Error") and not result.endswith("not found"):
            await self.asave_user_profile(profile)
        return result

    def _get_db_tools(
        self,
        user_id: str,
        db: BaseDb,
        input_string: str,
        enable_update_profile: bool = True,
        enable_delete_profile: bool = True,
    ) -> List[Callable]:
        """Create tools for model to call during create_user_profile."""

        def save_profile_field(info_type: str, key: str, value: str) -> str:
            """Use this function to save user profile information.
            Args:
                info_type (str): The type of information (profile/policy/knowledge/feedback).
                key (str): The key/name for the information.
                value (str): The value to save.
            Returns:
                str: A message indicating if the information was saved successfully or not.
            """
            return self._save_to_user_memory_layer(user_id, info_type, key, value)

        def delete_profile_field(info_type: str, key: str) -> str:
            """Use this function to delete/forget user profile information.
            Args:
                info_type (str): The type of information (profile/policy/knowledge/feedback).
                key (str): The key/name of the information to delete.
            Returns:
                str: A message indicating if the information was deleted successfully or not.
            """
            return self._delete_from_user_memory_layer(user_id, info_type, key)

        functions: List[Callable] = []
        if enable_update_profile:
            functions.append(save_profile_field)
        if enable_delete_profile:
            functions.append(delete_profile_field)
        return functions

    async def _aget_db_tools(
        self,
        user_id: str,
        db: Union[BaseDb, AsyncBaseDb],
        input_string: str,
        enable_update_profile: bool = True,
        enable_delete_profile: bool = True,
    ) -> List[Callable]:
        """Create async tools for model to call during acreate_user_profile."""

        async def save_profile_field(info_type: str, key: str, value: str) -> str:
            """Use this function to save user profile information.
            Args:
                info_type (str): The type of information (profile/policy/knowledge/feedback).
                key (str): The key/name for the information.
                value (str): The value to save.
            Returns:
                str: A message indicating if the information was saved successfully or not.
            """
            return await self._asave_to_user_memory_layer(user_id, info_type, key, value)

        async def delete_profile_field(info_type: str, key: str) -> str:
            """Use this function to delete/forget user profile information.
            Args:
                info_type (str): The type of information (profile/policy/knowledge/feedback).
                key (str): The key/name of the information to delete.
            Returns:
                str: A message indicating if the information was deleted successfully or not.
            """
            return await self._adelete_from_user_memory_layer(user_id, info_type, key)

        functions: List[Callable] = []
        if enable_update_profile:
            functions.append(save_profile_field)
        if enable_delete_profile:
            functions.append(delete_profile_field)
        return functions

    def _apply_save_to_layer(self, profile: UserProfile, info_type: str, key: str, value: str) -> str:
        """Modify profile in-place. Returns success/error message."""
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
                return f"Error: For feedback, key must be 'positive' or 'negative', got '{key}'"
            feedback = profile.memory_layers.setdefault("feedback", {"positive": [], "negative": []})
            if value not in feedback.setdefault(key, []):
                feedback[key].append(value)

        else:
            return f"Error: Unknown info_type: {info_type}"

        log_debug(f"Saved {info_type} {key}={value} for {profile.user_id}")
        return f"Saved {info_type}: {key} = {value}"

    def _apply_delete_from_layer(self, profile: UserProfile, info_type: str, key: str) -> str:
        """Modify profile in-place. Returns success/error message."""
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
            profile.memory_layers["knowledge"] = [f for f in knowledge if f.get("key") != key]
            if len(profile.memory_layers["knowledge"]) == before:
                return f"Key '{key}' not found in knowledge"

        elif info_type == "feedback":
            if key not in ("positive", "negative"):
                return f"Error: For feedback, key must be 'positive' or 'negative', got '{key}'"
            feedback = layers.get("feedback", {})
            if key in feedback:
                feedback[key] = []
            else:
                return f"Key '{key}' not found in feedback"

        else:
            return f"Error: Unknown info_type: {info_type}"

        log_debug(f"Deleted {info_type} {key} for {profile.user_id}")
        return f"Forgot {info_type}: {key}"

    def _get_schema_hints(self, schema: Optional[Type]) -> str:
        """Extract field hints from a Pydantic schema."""
        if schema is None:
            return ""

        # Only support Pydantic models
        if not hasattr(schema, "model_fields"):
            return ""

        lines = []
        for name, info in schema.model_fields.items():
            type_name = getattr(info.annotation, "__name__", str(info.annotation))
            desc = getattr(info, "description", None) or ""
            if desc:
                lines.append(f"  - {name} ({type_name}): {desc}")
            else:
                lines.append(f"  - {name} ({type_name})")

        return "\n".join(lines)
