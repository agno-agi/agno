import json
from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.org_memory import OrganizationMemory
from agno.db.schemas.user_profile import UserProfile
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


@dataclass
class MemoryCompiler:
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

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        system_message: Optional[str] = None,
        profile_capture_instructions: Optional[str] = None,
        additional_instructions: Optional[str] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        delete_profile: bool = True,
        update_profile: bool = True,
    ):
        self.model = model  # type: ignore[assignment]
        self.system_message = system_message
        self.profile_capture_instructions = profile_capture_instructions
        self.additional_instructions = additional_instructions
        self.db = db
        self.delete_profile = delete_profile
        self.update_profile = update_profile
        self.profile_updated = False

        if self.model is not None:
            self.model = get_model(self.model)

    def get_user_profile(self, user_id: Optional[str] = None) -> Optional[Union[UserProfile, Dict[str, Any]]]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if user_id is None:
            user_id = "default"
        self.db = cast(BaseDb, self.db)
        return self.db.get_user_profile(user_id=user_id)

    def save_user_profile(self, user_profile: UserProfile) -> Optional[Union[UserProfile, Dict[str, Any]]]:
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

    async def aget_user_profile(self, user_id: Optional[str] = None) -> Optional[Union[UserProfile, Dict[str, Any]]]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if user_id is None:
            user_id = "default"
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.get_user_profile(user_id=user_id)
        return self.db.get_user_profile(user_id=user_id)

    async def asave_user_profile(self, user_profile: UserProfile) -> Optional[Union[UserProfile, Dict[str, Any]]]:
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
        # Use compact JSON to reduce token usage
        return f"<user_memory>\n{json.dumps(data, separators=(',', ':'))}\n</user_memory>"

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
        result = await self._aextract_with_tools(message, user_id)
        log_debug("MemoryCompiler End", center=True)
        return result

    def _extract_with_tools(self, message: str, user_id: str) -> str:
        """Extract profile using flexible tool-based approach."""
        if self.model is None:
            log_warning("Model not configured")
            return "Model not configured"
        if self.db is None:
            log_warning("Database not configured")
            return "Database not configured"

        existing_profile = self.get_user_profile(user_id)

        model_copy = deepcopy(self.model)

        # Prepare tools and wrap them as Function objects
        raw_tools = self._get_db_tools(
            user_id=user_id,
            db=cast(BaseDb, self.db),
            input_string=message,
            enable_update_profile=self.update_profile,
            enable_delete_profile=self.delete_profile,
        )
        _tools = self.determine_tools_for_model(raw_tools)

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
        if self.model is None:
            log_warning("Model not configured")
            return "Model not configured"
        if self.db is None:
            log_warning("Database not configured")
            return "Database not configured"

        existing_profile = await self.aget_user_profile(user_id)

        model_copy = deepcopy(self.model)

        # Prepare tools and wrap them as Function objects
        if isinstance(self.db, AsyncBaseDb):
            raw_tools = await self._aget_db_tools(
                user_id=user_id,
                db=self.db,
                input_string=message,
                enable_update_profile=self.update_profile,
                enable_delete_profile=self.delete_profile,
            )
        else:
            raw_tools = self._get_db_tools(
                user_id=user_id,
                db=self.db,
                input_string=message,
                enable_update_profile=self.update_profile,
                enable_delete_profile=self.delete_profile,
            )
        _tools = self.determine_tools_for_model(raw_tools)

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
            Capture user information into the appropriate memory layer:
            - Profile: identity info (name, company, role, location, tone preference)
            - Knowledge: personal facts (interests, hobbies, habits, plans, preferences)
            - Policies: behavior rules (no emojis, be concise, avoid buzzwords)
            - Feedback: evaluative signals (what user liked/disliked about responses)"""
        )

        system_prompt = dedent(f"""\
            You are a Profile Manager responsible for managing information and preferences about the user.

            ## Security Rules
            NEVER store secrets, credentials, API keys, passwords, tokens, or any sensitive authentication data.
            If the user mentions such information, do NOT save it to the profile.

            ## When to Add or Update Profile
            - Decide if profile information needs to be added, updated, or deleted based on the user's message.
            - If the user's message meets the criteria in <profile_to_capture> and is not already in <existing_profile>, capture it.
            - If the message does not meet the criteria, no updates are needed.
            - If the existing profile already captures the relevant information, no updates are needed.

            ## Categorization Rules
            Use the correct info_type for each piece of information:

            info_type='profile' - ONLY for identity:
            - name, preferred_name, company, role, location, tone_preference

            info_type='knowledge' - For learned facts about the user:
            - interests, hobbies, habits, plans, preferences, personal facts

            info_type='policy' - For behavior rules:
            - constraints, preferences about AI behavior (no emojis, be concise)

            info_type='feedback' - For SPECIFIC response preferences:
            - key='positive': specific format/style/content the user liked
            - key='negative': specific format/style/content the user disliked
            - SKIP vague praise ("great job", "thanks") - not actionable
            - Only save if it tells you HOW to improve future responses

            ## How to Save Information
            Capture key details as brief, third-person statements.

            Examples:
            - 'My name is John Doe' -> info_type='profile', key='name', value='John Doe'
            - 'I work at Acme Corp' -> info_type='profile', key='company', value='Acme Corp'
            - 'I like anime and video games' -> info_type='knowledge', key='interests', value='enjoys anime and video games'
            - 'I go to the gym every day' -> info_type='knowledge', key='habit', value='goes to the gym daily'
            - 'Please be concise' -> info_type='policy', key='response_style', value='prefers concise responses'
            - 'I love how you used bullet points' -> info_type='feedback', key='positive', value='prefers bullet point format'
            - 'That was too long' -> info_type='feedback', key='negative', value='prefers shorter responses'
            - 'Great!' -> DO NOT SAVE (too vague, not actionable)

            Create multiple entries if needed. Don't repeat information.
            If user asks to forget something, delete the relevant entry.

            <profile_to_capture>
            {profile_capture_instructions}
            </profile_to_capture>

            ## Updating Profile
            You can:
            - Decide to make no changes.""")

        if enable_update_profile:
            system_prompt += "\n- Add or update profile information using the `save_profile_field` tool."
        if enable_delete_profile:
            system_prompt += "\n- Delete profile information using the `delete_profile_field` tool."

        system_prompt += "\n\nYou can call multiple tools in a single response if needed. Only add or update profile information if it is necessary to capture key information provided by the user."

        if existing_profile:
            existing = self._format_profile_as_context(existing_profile)
            if existing:
                system_prompt += f"\n\n<existing_profile>\n{existing}\n</existing_profile>"

        if self.additional_instructions:
            system_prompt += f"\n\n{self.additional_instructions}"

        return Message(role="system", content=system_prompt)

    def determine_tools_for_model(self, tools: List[Callable]) -> List[Union[Function, Dict[Any, Any]]]:
        """Convert callable tools to Function objects for the model."""
        _functions: List[Union[Function, Dict[Any, Any]]] = []
        for tool in tools:
            func = Function.from_callable(tool, strict=True)
            func.strict = True
            _functions.append(func)
        return _functions

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
            """Save user profile information. NEVER store secrets, credentials, API keys, or passwords.
            Args:
                info_type (str): The type of information (profile/policy/knowledge/feedback).
                key (str): The key/name for the information.
                value (str): The value to save.
            Returns:
                str: A message indicating if the information was saved successfully or not.
            """
            return self._save_to_user_memory_layer(user_id, info_type, key, value)

        def delete_profile_field(info_type: str, key: str) -> str:
            """Delete/forget user profile information.
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
            """Save user profile information. NEVER store secrets, credentials, API keys, or passwords.
            Args:
                info_type (str): The type of information (profile/policy/knowledge/feedback).
                key (str): The key/name for the information.
                value (str): The value to save.
            Returns:
                str: A message indicating if the information was saved successfully or not.
            """
            return await self._asave_to_user_memory_layer(user_id, info_type, key, value)

        async def delete_profile_field(info_type: str, key: str) -> str:
            """Delete/forget user profile information.
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

    # --- Organization Memory ---

    def get_org_memory(self, org_id: str) -> Optional[Union[OrganizationMemory, Dict[str, Any]]]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.get_org_memory(org_id=org_id)

    def save_org_memory(self, org_memory: OrganizationMemory) -> Optional[Union[OrganizationMemory, Dict[str, Any]]]:
        if not self.db:
            log_warning("Database not provided")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.upsert_org_memory(org_memory=org_memory)

    def delete_org_memory(self, org_id: str) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        self.db = cast(BaseDb, self.db)
        self.db.delete_org_memory(org_id=org_id)

    async def aget_org_memory(self, org_id: str) -> Optional[Union[OrganizationMemory, Dict[str, Any]]]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.get_org_memory(org_id=org_id)
        return self.db.get_org_memory(org_id=org_id)

    async def asave_org_memory(
        self, org_memory: OrganizationMemory
    ) -> Optional[Union[OrganizationMemory, Dict[str, Any]]]:
        if not self.db:
            log_warning("Database not provided")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.upsert_org_memory(org_memory=org_memory)
        return self.db.upsert_org_memory(org_memory=org_memory)

    async def adelete_org_memory(self, org_id: str) -> None:
        if not self.db:
            log_warning("Database not provided")
            return
        if isinstance(self.db, AsyncBaseDb):
            await self.db.delete_org_memory(org_id=org_id)
        else:
            self.db.delete_org_memory(org_id=org_id)

    def compile_org_memory(self, org_id: str) -> str:
        org_memory = self.get_org_memory(org_id)
        if not org_memory:
            return ""
        return self._format_org_memory_as_context(org_memory)

    async def acompile_org_memory(self, org_id: str) -> str:
        org_memory = await self.aget_org_memory(org_id)
        if not org_memory:
            return ""
        return self._format_org_memory_as_context(org_memory)

    def _format_org_memory_as_context(self, org_memory: OrganizationMemory) -> str:
        data: Dict[str, Any] = {}
        if org_memory.context:
            data["context"] = org_memory.context
        if org_memory.policies:
            data["policies"] = org_memory.policies
        if not data:
            return ""
        return f"<org_memory>\n{json.dumps(data, separators=(',', ':'))}\n</org_memory>"

    def _save_to_org_memory_layer(self, org_id: str, layer: str, key: str, value: str) -> str:
        """Save to organization memory layer."""
        org_memory = self.get_org_memory(org_id) or OrganizationMemory(org_id=org_id)
        result = self._apply_save_to_org_layer(org_memory, layer, key, value)
        if not result.startswith("Error"):
            self.save_org_memory(org_memory)
        return result

    async def _asave_to_org_memory_layer(self, org_id: str, layer: str, key: str, value: str) -> str:
        """Async save to organization memory layer."""
        org_memory = await self.aget_org_memory(org_id) or OrganizationMemory(org_id=org_id)
        result = self._apply_save_to_org_layer(org_memory, layer, key, value)
        if not result.startswith("Error"):
            await self.asave_org_memory(org_memory)
        return result

    def _delete_from_org_memory_layer(self, org_id: str, layer: str, key: str) -> str:
        """Delete from organization memory layer."""
        org_memory = self.get_org_memory(org_id)
        if not org_memory:
            return f"No org memory found for {org_id}"
        result = self._apply_delete_from_org_layer(org_memory, layer, key)
        if not result.startswith("Error") and not result.endswith("not found"):
            self.save_org_memory(org_memory)
        return result

    async def _adelete_from_org_memory_layer(self, org_id: str, layer: str, key: str) -> str:
        """Async delete from organization memory layer."""
        org_memory = await self.aget_org_memory(org_id)
        if not org_memory:
            return f"No org memory found for {org_id}"
        result = self._apply_delete_from_org_layer(org_memory, layer, key)
        if not result.startswith("Error") and not result.endswith("not found"):
            await self.asave_org_memory(org_memory)
        return result

    def _apply_save_to_org_layer(self, org_memory: OrganizationMemory, layer: str, key: str, value: str) -> str:
        """Modify org memory in-place. Returns success/error message."""
        if layer not in ("context", "policies"):
            return f"Error: layer must be 'context' or 'policies', got '{layer}'"

        if org_memory.memory_layers is None:
            org_memory.memory_layers = {}

        org_memory.memory_layers.setdefault(layer, {})[key] = value
        log_debug(f"Saved org {layer} {key}={value} for {org_memory.org_id}")
        return f"Saved org {layer}: {key} = {value}"

    def _apply_delete_from_org_layer(self, org_memory: OrganizationMemory, layer: str, key: str) -> str:
        """Modify org memory in-place. Returns success/error message."""
        if layer not in ("context", "policies"):
            return f"Error: layer must be 'context' or 'policies', got '{layer}'"

        layers = org_memory.memory_layers or {}
        layer_dict = layers.get(layer, {})
        if key in layer_dict:
            del layer_dict[key]
            log_debug(f"Deleted org {layer} {key} for {org_memory.org_id}")
            return f"Forgot org {layer}: {key}"
        return f"Key '{key}' not found in org {layer}"
