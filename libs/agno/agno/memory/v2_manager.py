from copy import deepcopy
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Type, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_profile import UserProfile
from agno.memory.v2_prompts import (
    DEFAULT_AGENTIC_INSTRUCTIONS,
    DEFAULT_DECISION_FRAMEWORK,
    DEFAULT_EXTRACTION_INTRO,
    DEFAULT_EXTRACTION_TOOL_USAGE,
    DEFAULT_FEEDBACK_PROMPT,
    DEFAULT_KNOWLEDGE_PROMPT,
    DEFAULT_POLICIES_PROMPT,
    DEFAULT_PROFILE_PROMPT,
)
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.tools.function import Function
from agno.utils.log import (
    log_debug,
    log_error,
    log_info,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)


@dataclass
class MemoryManagerV2:
    """Memory Manager V2 - Handles structured user memory layers

    This manager handles the new memory system with:
    - User profile (WHO the user is)
    - Policies (rules and constraints)
    - Knowledge (learned patterns)
    - Feedback (what worked/didn't work)
    """

    # Model for LLM extraction (optional for Phase 1)
    model: Optional[Model] = None

    # Database
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # Context compilation flags (READ - what gets injected into system message)
    add_user_profile_to_context: bool = True
    add_user_policies_to_context: bool = True
    add_knowledge_to_context: bool = True
    add_feedback_to_context: bool = True

    # Automatic extraction flags (WRITE - background extraction after run)
    update_memory_on_run: bool = False

    # Per-layer extraction controls (which layers to extract)
    extract_profile: bool = True
    extract_policies: bool = True
    extract_knowledge: bool = True
    extract_feedback: bool = True

    # Agentic memory flags (WRITE - agent has tools to manage memory)
    enable_agentic_memory: bool = False

    # Custom prompts (for LLM extraction)
    extraction_instructions: Optional[str] = None

    # Schema overrides (custom dataclasses for each layer)
    profile_schema: Optional[Type] = None
    policies_schema: Optional[Type] = None
    knowledge_schema: Optional[Type] = None
    feedback_schema: Optional[Type] = None

    # Per-layer extraction prompt overrides
    profile_extraction_prompt: Optional[str] = None
    policies_extraction_prompt: Optional[str] = None
    knowledge_extraction_prompt: Optional[str] = None
    feedback_extraction_prompt: Optional[str] = None

    # Internal settings
    debug_mode: bool = False

    # ==========================================================================
    # INITIALIZATION
    # ==========================================================================

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        # Context compilation flags (READ)
        add_user_profile_to_context: bool = True,
        add_user_policies_to_context: bool = True,
        add_knowledge_to_context: bool = True,
        add_feedback_to_context: bool = True,
        # Automatic extraction (WRITE - background)
        update_memory_on_run: bool = False,
        # Per-layer extraction controls
        extract_profile: bool = True,
        extract_policies: bool = True,
        extract_knowledge: bool = True,
        extract_feedback: bool = True,
        # Agentic memory (WRITE - agent has tools)
        enable_agentic_memory: bool = False,
        # Custom prompts
        extraction_instructions: Optional[str] = None,
        # Schema overrides
        profile_schema: Optional[Type] = None,
        policies_schema: Optional[Type] = None,
        knowledge_schema: Optional[Type] = None,
        feedback_schema: Optional[Type] = None,
        # Per-layer extraction prompt overrides
        profile_extraction_prompt: Optional[str] = None,
        policies_extraction_prompt: Optional[str] = None,
        knowledge_extraction_prompt: Optional[str] = None,
        feedback_extraction_prompt: Optional[str] = None,
        debug_mode: bool = False,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.add_user_profile_to_context = add_user_profile_to_context
        self.add_user_policies_to_context = add_user_policies_to_context
        self.add_knowledge_to_context = add_knowledge_to_context
        self.add_feedback_to_context = add_feedback_to_context
        self.update_memory_on_run = update_memory_on_run
        self.extract_profile = extract_profile
        self.extract_policies = extract_policies
        self.extract_knowledge = extract_knowledge
        self.extract_feedback = extract_feedback
        self.enable_agentic_memory = enable_agentic_memory
        self.extraction_instructions = extraction_instructions
        self.profile_schema = profile_schema
        self.policies_schema = policies_schema
        self.knowledge_schema = knowledge_schema
        self.feedback_schema = feedback_schema
        self.profile_extraction_prompt = profile_extraction_prompt
        self.policies_extraction_prompt = policies_extraction_prompt
        self.knowledge_extraction_prompt = knowledge_extraction_prompt
        self.feedback_extraction_prompt = feedback_extraction_prompt
        self.debug_mode = debug_mode

    # ==========================================================================
    # UTILITY METHODS
    # ==========================================================================

    def set_log_level(self) -> None:
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    def get_model(self) -> Model:
        """Get the model for extraction, defaulting to OpenAI if not provided."""
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
        """Extract field names and types from a dataclass schema for prompt hints.

        Args:
            schema: Optional dataclass type

        Returns:
            String describing the expected fields, or empty string if no schema
        """
        if schema is None:
            return ""

        if is_dataclass(schema):
            field_info = []
            for field in dataclass_fields(schema):
                field_type = getattr(field.type, "__name__", str(field.type))
                field_info.append(f"{field.name}: {field_type}")
            if field_info:
                return f"\n            Expected fields: {', '.join(field_info)}"
        return ""

    # ==========================================================================
    # AUTOMATIC EXTRACTION (background memory extraction)
    # ==========================================================================

    def _get_extraction_system_message(self, existing_profile: Optional[UserProfile] = None) -> str:
        """Build the system message for tool-based extraction.

        Conditionally includes layer sections based on extract_* flags.
        Uses prompts from v2_prompts.py, with optional schema hints appended.
        """
        # If custom instructions provided, use those directly
        if self.extraction_instructions:
            return self.extraction_instructions

        # Build enabled layers list for the intro
        enabled_layers = []
        if self.extract_profile:
            enabled_layers.append("Profile")
        if self.extract_policies:
            enabled_layers.append("Policies")
        if self.extract_knowledge:
            enabled_layers.append("Knowledge")
        if self.extract_feedback:
            enabled_layers.append("Feedback")

        if not enabled_layers:
            return "No memory layers are enabled for extraction."

        # Build system message from constants
        system_message = DEFAULT_EXTRACTION_INTRO
        system_message += f"\n## Enabled Memory Layers: {', '.join(enabled_layers)}\n\n"
        system_message += DEFAULT_EXTRACTION_TOOL_USAGE

        # Add PROFILE layer instructions if enabled
        if self.extract_profile:
            if self.profile_extraction_prompt:
                system_message += f'\n\n### PROFILE (info_type="profile")\n{self.profile_extraction_prompt}'
            else:
                schema_hints = self._get_schema_hints(self.profile_schema)
                system_message += "\n\n" + DEFAULT_PROFILE_PROMPT
                if schema_hints:
                    system_message += schema_hints

        # Add POLICY layer instructions if enabled
        if self.extract_policies:
            if self.policies_extraction_prompt:
                system_message += f'\n\n### POLICY (info_type="policy")\n{self.policies_extraction_prompt}'
            else:
                schema_hints = self._get_schema_hints(self.policies_schema)
                system_message += "\n\n" + DEFAULT_POLICIES_PROMPT
                if schema_hints:
                    system_message += schema_hints

        # Add KNOWLEDGE layer instructions if enabled
        if self.extract_knowledge:
            if self.knowledge_extraction_prompt:
                system_message += f'\n\n### KNOWLEDGE (info_type="knowledge")\n{self.knowledge_extraction_prompt}'
            else:
                schema_hints = self._get_schema_hints(self.knowledge_schema)
                system_message += "\n\n" + DEFAULT_KNOWLEDGE_PROMPT
                if schema_hints:
                    system_message += schema_hints

        # Add FEEDBACK layer instructions if enabled
        if self.extract_feedback:
            if self.feedback_extraction_prompt:
                system_message += f'\n\n### FEEDBACK (info_type="feedback")\n{self.feedback_extraction_prompt}'
            else:
                schema_hints = self._get_schema_hints(self.feedback_schema)
                system_message += "\n\n" + DEFAULT_FEEDBACK_PROMPT
                if schema_hints:
                    system_message += schema_hints

        # Add decision framework
        system_message += "\n\n" + DEFAULT_DECISION_FRAMEWORK

        # Add existing profile context to avoid duplicates
        if existing_profile:
            system_message += "\n## Existing User Profile (do NOT re-save these)\n"

            if self.extract_profile and existing_profile.user_profile:
                system_message += "<existing_profile>\n"
                for key, value in existing_profile.user_profile.items():
                    system_message += f"  {key}: {value}\n"
                system_message += "</existing_profile>\n\n"

            if self.extract_knowledge and existing_profile.knowledge:
                system_message += "<existing_knowledge>\n"
                for item in existing_profile.knowledge:
                    if isinstance(item, dict):
                        system_message += f"  - {item.get('value', item.get('content', str(item)))}\n"
                    else:
                        system_message += f"  - {item}\n"
                system_message += "</existing_knowledge>\n\n"

            if self.extract_policies and existing_profile.policies:
                system_message += "<existing_policies>\n"
                for category, rules in existing_profile.policies.items():
                    system_message += f"  {category}: {rules}\n"
                system_message += "</existing_policies>\n\n"

            if self.extract_feedback and existing_profile.feedback:
                system_message += "<existing_feedback>\n"
                if isinstance(existing_profile.feedback, dict):
                    for key, items in existing_profile.feedback.items():
                        if items:
                            system_message += f"  {key}: {items}\n"
                system_message += "</existing_feedback>\n"

        return system_message

    def _get_extraction_tools(self, user_id: str) -> List[Function]:
        """Get tools for background memory extraction.

        Returns only the save_user_info tool (no forget needed for extraction).
        Respects per-layer extraction flags.

        Args:
            user_id: The user ID to save memory for

        Returns:
            List of Function objects for the model to use
        """
        # Capture self for closure
        manager = self

        def save_user_info(
            info_type: str,
            key: str,
            value: Any,
        ) -> str:
            """Save information about the user.

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: A label for the information. For feedback, use "positive" or "negative".
                value: The actual information to save

            Returns:
                Confirmation message
            """
            # Check if this layer is enabled for extraction
            if info_type == "profile" and not manager.extract_profile:
                log_debug(f"[Extraction] Skipped profile (extraction disabled) for {user_id}")
                return "Profile extraction is disabled"
            if info_type == "policy" and not manager.extract_policies:
                log_debug(f"[Extraction] Skipped policy (extraction disabled) for {user_id}")
                return "Policy extraction is disabled"
            if info_type == "knowledge" and not manager.extract_knowledge:
                log_debug(f"[Extraction] Skipped knowledge (extraction disabled) for {user_id}")
                return "Knowledge extraction is disabled"
            if info_type == "feedback" and not manager.extract_feedback:
                log_debug(f"[Extraction] Skipped feedback (extraction disabled) for {user_id}")
                return "Feedback extraction is disabled"

            # Delegate to shared helper
            return manager._save_to_layer(user_id, info_type, key, value)

        return [Function.from_callable(save_user_info)]

    # ==========================================================================
    # CRUD OPERATIONS (User Profile)
    # ==========================================================================

    def get_user(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by ID."""
        if not self.db:
            log_warning("Database not provided")
            return None

        self.db = cast(BaseDb, self.db)
        return self.db.get_user_profile(user_id=user_id)

    async def aget_user(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by ID (async)."""
        if not self.db:
            log_warning("Database not provided")
            return None

        if isinstance(self.db, AsyncBaseDb):
            return await self.db.get_user_profile(user_id=user_id)
        return self.db.get_user_profile(user_id=user_id)

    def get_users(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[UserProfile]:
        """Get all user profiles with pagination."""
        if not self.db:
            log_warning("Database not provided")
            return []

        self.db = cast(BaseDb, self.db)
        result = self.db.get_user_profiles(
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
            deserialize=True,
        )
        # When deserialize=True, result is a list
        return result if isinstance(result, list) else []

    async def aget_users(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[UserProfile]:
        """Get all user profiles with pagination (async)."""
        if not self.db:
            log_warning("Database not provided")
            return []

        if isinstance(self.db, AsyncBaseDb):
            result = await self.db.get_user_profiles(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=True,
            )
        else:
            result = self.db.get_user_profiles(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=True,
            )
        return result if isinstance(result, list) else []

    def upsert_user(self, user_profile: UserProfile) -> Optional[UserProfile]:
        """Create or update user profile."""
        if not self.db:
            log_warning("Database not provided")
            return None

        self.db = cast(BaseDb, self.db)
        return self.db.upsert_user_profile(user_profile=user_profile)

    async def aupsert_user(self, user_profile: UserProfile) -> Optional[UserProfile]:
        """Create or update user profile (async)."""
        if not self.db:
            log_warning("Database not provided")
            return None

        if isinstance(self.db, AsyncBaseDb):
            return await self.db.upsert_user_profile(user_profile=user_profile)
        return self.db.upsert_user_profile(user_profile=user_profile)

    def delete_user(self, user_id: str) -> None:
        """Delete a user profile."""
        if not self.db:
            log_warning("Database not provided")
            return

        self.db = cast(BaseDb, self.db)
        self.db.delete_user_profile(user_id=user_id)

    async def adelete_user(self, user_id: str) -> None:
        """Delete a user profile (async)."""
        if not self.db:
            log_warning("Database not provided")
            return

        if isinstance(self.db, AsyncBaseDb):
            await self.db.delete_user_profile(user_id=user_id)
        else:
            self.db.delete_user_profile(user_id=user_id)

    # ==========================================================================
    # LAYER HELPERS (shared logic for save/delete operations)
    # ==========================================================================

    def _save_to_layer(self, user_id: str, info_type: str, key: str, value: Any) -> str:
        """Shared logic for saving to any memory layer.

        Used by both extraction tools and agentic memory tools.

        Args:
            user_id: The user ID to save to
            info_type: One of "profile", "policy", "knowledge", or "feedback"
            key: A label for the information
            value: The actual information to save

        Returns:
            Confirmation message or error string
        """
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
                # Deduplicate by key
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
        """Shared logic for deleting from any memory layer.

        Used by agentic memory tools.

        Args:
            user_id: The user ID to delete from
            info_type: One of "profile", "policy", "knowledge", or "feedback"
            key: The key/label to delete

        Returns:
            Confirmation message or error string
        """
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

    # ==========================================================================
    # PROFILE & MEMORY LAYER OPERATIONS
    # ==========================================================================

    def get_user_profile_data(self, user_id: str) -> Dict[str, Any]:
        """Get just the user profile data (not memory layers)."""
        user = self.get_user(user_id)
        if not user:
            return {}
        return user.user_profile

    async def aget_user_profile_data(self, user_id: str) -> Dict[str, Any]:
        """Get just the user profile data (async)."""
        user = await self.aget_user(user_id)
        if not user:
            return {}
        return user.user_profile

    def update_user_profile_data(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserProfile]:
        """Update specific fields in user profile.

        Args:
            user_id: The user ID
            updates: Dictionary of fields to update/add in user_profile
        """
        user = self.get_user(user_id)
        if not user:
            # Create new user with the profile data
            user = UserProfile(user_id=user_id, user_profile=updates)
        else:
            # Merge updates into existing profile
            user.user_profile.update(updates)
            user.bump_updated_at()

        return self.upsert_user(user)

    async def aupdate_user_profile_data(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserProfile]:
        """Update specific fields in user profile (async)."""
        user = await self.aget_user(user_id)
        if not user:
            user = UserProfile(user_id=user_id, user_profile=updates)
        else:
            user.user_profile.update(updates)
            user.bump_updated_at()

        return await self.aupsert_user(user)

    def get_memory_layers(self, user_id: str) -> Dict[str, Any]:
        """Get the memory layers for a user."""
        user = self.get_user(user_id)
        if not user:
            return {}
        return user.memory_layers

    async def aget_memory_layers(self, user_id: str) -> Dict[str, Any]:
        """Get the memory layers for a user (async)."""
        user = await self.aget_user(user_id)
        if not user:
            return {}
        return user.memory_layers

    def update_memory_layers(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserProfile]:
        """Update specific fields in memory layers.

        Args:
            user_id: The user ID
            updates: Dictionary of fields to update/add in memory_layers
                    (e.g., {"policies": {...}, "knowledge": [...], "feedback": [...]})
        """
        user = self.get_user(user_id)
        if not user:
            user = UserProfile(user_id=user_id, memory_layers=updates)
        else:
            user.memory_layers.update(updates)
            user.bump_updated_at()

        return self.upsert_user(user)

    async def aupdate_memory_layers(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserProfile]:
        """Update specific fields in memory layers (async)."""
        user = await self.aget_user(user_id)
        if not user:
            user = UserProfile(user_id=user_id, memory_layers=updates)
        else:
            user.memory_layers.update(updates)
            user.bump_updated_at()

        return await self.aupsert_user(user)

    # ==========================================================================
    # CONTEXT COMPILATION (READ - inject memory into system message)
    # ==========================================================================

    def compile_user_context(self, user_id: str) -> str:
        """Compile user memory layers into XML for system message."""
        user = self.get_user(user_id)
        if not user:
            return ""

        return self._format_user_context(user)

    async def acompile_user_context(self, user_id: str) -> str:
        """Compile user memory layers (async)."""
        user = await self.aget_user(user_id)
        if not user:
            return ""

        return self._format_user_context(user)

    def _format_nested_value(self, value: Any, indent: int = 2) -> str:
        """Format a nested value (dict, list, or scalar) with proper indentation.

        Args:
            value: The value to format
            indent: Current indentation level (spaces)

        Returns:
            Formatted string
        """
        prefix = " " * indent
        output = ""

        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, dict):
                    # Nested dict - use XML-style tags for categories
                    output += f"{prefix}<{k}>\n"
                    output += self._format_nested_value(v, indent + 2)
                    output += f"{prefix}</{k}>\n"
                elif isinstance(v, list):
                    output += f"{prefix}{k}:\n"
                    for item in v:
                        if isinstance(item, dict):
                            output += self._format_nested_value(item, indent + 2)
                        else:
                            output += f"{prefix}  - {item}\n"
                else:
                    output += f"{prefix}{k}: {v}\n"
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    output += self._format_nested_value(item, indent)
                else:
                    output += f"{prefix}- {item}\n"
        else:
            output += f"{prefix}{value}\n"

        return output

    def _format_user_context(self, user: UserProfile) -> str:
        """Format UserProfile as XML context string.

        Layers are formatted in authority order (highest first):
        1. Policies - hard constraints, always win
        2. Profile - user identity
        3. Knowledge - learned patterns
        4. Feedback - adaptation signals (lowest)

        Nested categories are formatted with XML sub-tags for clarity.
        """
        output = ""

        # 1. Policies (HIGHEST AUTHORITY) - preferences and constraints
        if self.add_user_policies_to_context and user.policies:
            output += "<user_policies>\n"
            output += "<!-- These are user preferences that should be followed -->\n"
            for key, value in user.policies.items():
                if isinstance(value, dict):
                    # Use XML sub-tags for category grouping
                    output += f"  <{key}>\n"
                    output += self._format_nested_value(value, indent=4)
                    output += f"  </{key}>\n"
                elif isinstance(value, list):
                    output += f"  {key}:\n"
                    for item in value:
                        output += f"    - {item}\n"
                else:
                    output += f"  {key}: {value}\n"
            output += "</user_policies>\n\n"

        # 2. Profile - user identity information
        if self.add_user_profile_to_context and user.user_profile:
            output += "<user_profile>\n"
            for key, value in user.user_profile.items():
                if isinstance(value, dict):
                    # Use XML sub-tags for category grouping
                    output += f"  <{key}>\n"
                    output += self._format_nested_value(value, indent=4)
                    output += f"  </{key}>\n"
                elif isinstance(value, list):
                    output += f"  {key}:\n"
                    for item in value:
                        output += f"    - {item}\n"
                else:
                    output += f"  {key}: {value}\n"
            output += "</user_profile>\n\n"

        # 3. Knowledge - learned patterns and context
        if self.add_knowledge_to_context and user.knowledge:
            output += "<user_knowledge>\n"
            for item in user.knowledge:
                if isinstance(item, dict):
                    # Handle {"key": "...", "value": "..."} format
                    key = item.get("key", "")
                    value = item.get("value", item.get("content", ""))

                    if key and isinstance(value, dict):
                        # Category-structured knowledge
                        output += f"  <{key}>\n"
                        output += self._format_nested_value(value, indent=4)
                        output += f"  </{key}>\n"
                    elif key:
                        output += f"  {key}: {value}\n"
                    elif value:
                        output += f"  - {value}\n"
                    else:
                        # Fallback: format the whole dict
                        output += self._format_nested_value(item, indent=2)
                else:
                    output += f"  - {item}\n"
            output += "</user_knowledge>\n\n"

        # 4. Feedback (LOWEST AUTHORITY) - what worked/didn't work
        if self.add_feedback_to_context and user.feedback:
            output += "<user_feedback>\n"
            output += "<!-- Signals about what works for this user -->\n"
            if isinstance(user.feedback, dict):
                # Standard format: {"positive": [...], "negative": [...], ...}
                for key, value in user.feedback.items():
                    if isinstance(value, list) and value:
                        output += f"  <{key}>\n"
                        for item in value:
                            output += f"    - {item}\n"
                        output += f"  </{key}>\n"
                    elif isinstance(value, dict):
                        output += f"  <{key}>\n"
                        output += self._format_nested_value(value, indent=4)
                        output += f"  </{key}>\n"
                    elif value:
                        output += f"  {key}: {value}\n"
            elif isinstance(user.feedback, list):
                # Legacy format: [{"type": "...", "content": "..."}]
                for item in user.feedback:
                    if isinstance(item, dict):
                        fb_type = item.get("type", "general")
                        content = item.get("content", str(item))
                        output += f"  {fb_type}: {content}\n"
                    else:
                        output += f"  - {item}\n"
            output += "</user_feedback>\n"

        return output

    # ==========================================================================
    # LLM EXTRACTION (call model to extract memory from conversations)
    # ==========================================================================

    def extract_from_conversation(
        self,
        messages: List[Message],
        user_id: str,
    ) -> bool:
        """Extract user profile and memory from conversation using LLM with tools.

        The LLM is given the save_user_info tool and instructed to extract
        any relevant user information from the conversation. Tools are executed
        directly, saving to the database.

        Args:
            messages: The conversation messages to extract from
            user_id: The user ID to associate extracted memory with

        Returns:
            True if extraction was attempted, False if skipped
        """
        self.set_log_level()

        if not messages:
            log_debug("No messages to extract from")
            return False

        if not self.db:
            log_warning("Database not provided, cannot save extracted memory")
            return False

        log_debug(f"Extracting memory for user_id={user_id} from {len(messages)} messages")

        # Get existing user profile to avoid duplicates
        existing_profile = self.get_user(user_id)

        # Build messages for extraction
        system_message = self._get_extraction_system_message(existing_profile)

        # Format conversation for extraction
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

        # Get extraction tools (just save_user_info)
        extraction_tools = self._get_extraction_tools(user_id)

        # Make a copy of the model to avoid modifying the original
        model = self.get_model()
        model_copy = deepcopy(model)

        try:
            # Call LLM with tools - the model will execute save_user_info directly
            response = model_copy.response(
                messages=messages_for_model,
                tools=extraction_tools,
            )

            # Check if any tools were called
            tool_calls_made = response.tool_calls is not None and len(response.tool_calls) > 0
            if tool_calls_made:
                log_info(f"Extracted and saved memory for user {user_id}")
            else:
                log_debug(f"No new information extracted for user {user_id}")

            return True

        except Exception as e:
            log_error(f"Error during memory extraction: {e}")
            return False

    async def aextract_from_conversation(
        self,
        messages: List[Message],
        user_id: str,
    ) -> bool:
        """Extract user profile and memory from conversation using LLM with tools (async).

        The LLM is given the save_user_info tool and instructed to extract
        any relevant user information from the conversation. Tools are executed
        directly, saving to the database.

        Args:
            messages: The conversation messages to extract from
            user_id: The user ID to associate extracted memory with

        Returns:
            True if extraction was attempted, False if skipped
        """
        self.set_log_level()

        if not messages:
            log_debug("No messages to extract from")
            return False

        if not self.db:
            log_warning("Database not provided, cannot save extracted memory")
            return False

        log_debug(f"Extracting memory for user_id={user_id} from {len(messages)} messages")

        # Get existing user profile to avoid duplicates
        existing_profile = await self.aget_user(user_id)

        # Build messages for extraction
        system_message = self._get_extraction_system_message(existing_profile)

        # Format conversation for extraction
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

        # Get extraction tools (just save_user_info)
        extraction_tools = self._get_extraction_tools(user_id)

        # Make a copy of the model to avoid modifying the original
        model = self.get_model()
        model_copy = deepcopy(model)

        try:
            # Call LLM with tools - the model will execute save_user_info directly
            response = await model_copy.aresponse(
                messages=messages_for_model,
                tools=extraction_tools,
            )

            # Check if any tools were called
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
    # AGENTIC MEMORY TOOLS (agent-controlled memory management)
    # ==========================================================================

    def get_user_memory_tools(self, user_id: str) -> List[Callable]:
        """Get tools for agentic user memory management.

        Returns tools that allow the agent to explicitly manage user memory:
        - save_user_info: Save any user information (profile, preferences, facts)
        - forget_user_info: Delete specific user information

        Args:
            user_id: The user ID to manage memory for

        Returns:
            List of callable tools
        """
        if not self.db:
            log_warning("No database configured for agentic memory tools")
            return []

        # Capture self for closures
        manager = self

        def save_user_info(
            info_type: str,
            key: str,
            value: Any,
        ) -> str:
            """Save information about the user for future conversations.

            Use this to remember important information about the user across 4 categories:
            - profile: Identity info (name, role, company, location, skills)
            - policy: Preferences and constraints (response style, language, format rules)
            - knowledge: Learned patterns and context (projects, decisions, technical context)
            - feedback: Signals about what works (positive/negative reactions to responses)

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: A label for the information. For feedback, use "positive" or "negative".
                value: The actual information to remember

            Returns:
                Confirmation message
            """
            result = manager._save_to_layer(user_id, info_type, key, value)
            # Change "Saved" to "Remembered" for agentic mode
            if result.startswith("Saved "):
                return "Remembered " + result[6:]
            return result

        def forget_user_info(
            info_type: str,
            key: str,
        ) -> str:
            """Forget specific information about the user.

            Use this when the user asks you to forget something or when information is outdated.

            Args:
                info_type: One of "profile", "policy", "knowledge", or "feedback"
                key: The key/label to forget. For feedback, use "positive" or "negative" to clear that list.

            Returns:
                Confirmation message
            """
            return manager._delete_from_layer(user_id, info_type, key)

        return [
            save_user_info,
            forget_user_info,
        ]

    def get_agentic_memory_instructions(self) -> str:
        """Get instructions for the agent on how to use memory tools.

        Returns:
            String with instructions to add to agent's system message.
        """
        return DEFAULT_AGENTIC_INSTRUCTIONS
