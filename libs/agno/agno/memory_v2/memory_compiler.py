import json
from copy import deepcopy
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_memory import UserMemoryV2
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.run.base import RunContext
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning

# Session state key for pending user memory updates
USER_MEMORY_KEY = "_pending_user_memory"


# --- Batched update helpers for agentic tools ---


def init_pending_user_memory(run_context: RunContext, user_id: str) -> None:
    """Initialize pending memory structure in run_context."""
    if run_context.session_state is None:
        run_context.session_state = {}
    if USER_MEMORY_KEY not in run_context.session_state:
        run_context.session_state[USER_MEMORY_KEY] = {
            "user_id": user_id,
            "profile": {},
            "layers": {},
        }


def merge_user_profile_update(
    run_context: RunContext,
    user_id: str,
    updates: Dict[str, Any],
) -> None:
    """Merge updates into pending user profile."""
    init_pending_user_memory(run_context, user_id)
    pending = run_context.session_state[USER_MEMORY_KEY]
    for key, value in updates.items():
        if value is None:
            pending["profile"].pop(key, None)
        else:
            pending["profile"][key] = value


def merge_user_layer_update(
    run_context: RunContext,
    user_id: str,
    layer: str,
    key: str,
    value: Any,
    action: str = "set",
) -> None:
    """Merge update into a user memory layer (policies/knowledge/feedback)."""
    init_pending_user_memory(run_context, user_id)
    pending = run_context.session_state[USER_MEMORY_KEY]

    # Initialize layer with correct structure
    if layer not in pending["layers"]:
        if layer == "feedback":
            pending["layers"][layer] = {"positive": [], "negative": []}
        elif layer == "knowledge":
            pending["layers"][layer] = []
        else:
            pending["layers"][layer] = {}

    layer_data = pending["layers"][layer]

    if action == "delete":
        if layer == "policies":
            layer_data.pop(key, None)
        elif layer == "knowledge":
            pending["layers"][layer] = [
                item for item in layer_data if not (isinstance(item, dict) and item.get("key") == key)
            ]
        elif layer == "feedback" and key in ("positive", "negative"):
            layer_data[key] = []
    else:  # action == "set"
        if layer == "policies":
            layer_data[key] = value
        elif layer == "knowledge":
            # Replace item with same key, or append
            pending["layers"][layer] = [
                item for item in layer_data if not (isinstance(item, dict) and item.get("key") == key)
            ]
            pending["layers"][layer].append({"key": key, "value": value})
        elif layer == "feedback" and key in ("positive", "negative"):
            if value not in layer_data[key]:
                layer_data[key].append(value)


def has_pending_user_memory(run_context: RunContext) -> bool:
    """Check if there are pending user memory updates."""
    if run_context.session_state is None:
        return False
    return USER_MEMORY_KEY in run_context.session_state


def clear_pending_user_memory(run_context: RunContext) -> None:
    """Clear pending updates after successful commit."""
    if run_context.session_state:
        run_context.session_state.pop(USER_MEMORY_KEY, None)


def commit_user_memory_updates(
    db: BaseDb,
    user_id: str,
    run_context: RunContext,
) -> bool:
    """Commit pending user memory updates to DB."""
    if not has_pending_user_memory(run_context):
        return True

    pending = run_context.session_state[USER_MEMORY_KEY]
    if pending.get("user_id") != user_id:
        return True

    # Load latest from DB
    latest = db.get_user_memory_v2(user_id)
    if isinstance(latest, dict):
        latest = UserMemoryV2.from_dict(latest)
    if latest is None:
        latest = UserMemoryV2(user_id=user_id)

    # Merge profile updates
    for key, value in pending.get("profile", {}).items():
        if value is None:
            latest.profile.pop(key, None)
        else:
            latest.profile[key] = value

    # Merge layer updates
    for layer, layer_data in pending.get("layers", {}).items():
        if layer == "policies":
            if "policies" not in latest.layers:
                latest.layers["policies"] = {}
            for key, value in layer_data.items():
                if value is None:
                    latest.layers["policies"].pop(key, None)
                else:
                    latest.layers["policies"][key] = value

        elif layer == "knowledge":
            if "knowledge" not in latest.layers:
                latest.layers["knowledge"] = []
            existing = latest.layers["knowledge"]
            for item in layer_data:
                if isinstance(item, dict) and "key" in item:
                    existing = [k for k in existing if not (isinstance(k, dict) and k.get("key") == item["key"])]
                    existing.append(item)
            latest.layers["knowledge"] = existing

        elif layer == "feedback":
            if "feedback" not in latest.layers:
                latest.layers["feedback"] = {"positive": [], "negative": []}
            for fb_type in ("positive", "negative"):
                if fb_type in layer_data:
                    existing_fb = latest.layers["feedback"].setdefault(fb_type, [])
                    for val in layer_data[fb_type]:
                        if val not in existing_fb:
                            existing_fb.append(val)

    latest.bump_updated_at()
    db.upsert_user_memory_v2(latest)
    clear_pending_user_memory(run_context)
    log_debug(f"Committed user memory updates for {user_id}")
    return True


async def acommit_user_memory_updates(
    db: Union[AsyncBaseDb, BaseDb],
    user_id: str,
    run_context: RunContext,
) -> bool:
    """Commit pending user memory updates to DB (async)."""
    if not has_pending_user_memory(run_context):
        return True

    pending = run_context.session_state[USER_MEMORY_KEY]
    if pending.get("user_id") != user_id:
        return True

    # Load latest from DB
    if isinstance(db, AsyncBaseDb):
        latest = await db.get_user_memory_v2(user_id)
    else:
        latest = db.get_user_memory_v2(user_id)
    if isinstance(latest, dict):
        latest = UserMemoryV2.from_dict(latest)
    if latest is None:
        latest = UserMemoryV2(user_id=user_id)

    # Merge profile updates
    for key, value in pending.get("profile", {}).items():
        if value is None:
            latest.profile.pop(key, None)
        else:
            latest.profile[key] = value

    # Merge layer updates
    for layer, layer_data in pending.get("layers", {}).items():
        if layer == "policies":
            if "policies" not in latest.layers:
                latest.layers["policies"] = {}
            for key, value in layer_data.items():
                if value is None:
                    latest.layers["policies"].pop(key, None)
                else:
                    latest.layers["policies"][key] = value

        elif layer == "knowledge":
            if "knowledge" not in latest.layers:
                latest.layers["knowledge"] = []
            existing = latest.layers["knowledge"]
            for item in layer_data:
                if isinstance(item, dict) and "key" in item:
                    existing = [k for k in existing if not (isinstance(k, dict) and k.get("key") == item["key"])]
                    existing.append(item)
            latest.layers["knowledge"] = existing

        elif layer == "feedback":
            if "feedback" not in latest.layers:
                latest.layers["feedback"] = {"positive": [], "negative": []}
            for fb_type in ("positive", "negative"):
                if fb_type in layer_data:
                    existing_fb = latest.layers["feedback"].setdefault(fb_type, [])
                    for val in layer_data[fb_type]:
                        if val not in existing_fb:
                            existing_fb.append(val)

    latest.bump_updated_at()
    if isinstance(db, AsyncBaseDb):
        await db.upsert_user_memory_v2(latest)
    else:
        db.upsert_user_memory_v2(latest)
    clear_pending_user_memory(run_context)
    log_debug(f"Committed user memory updates for {user_id}")
    return True


@dataclass
class MemoryCompiler:
    """Compiles user memory from conversations."""

    # Model used for memory extraction
    model: Optional[Model] = None

    # Custom system message for the compiler
    system_message: Optional[str] = None
    # Custom profile capture instructions
    profile_capture_instructions: Optional[str] = None

    # Whether memory was updated in the last run
    memory_updated: bool = False

    # Tool configuration
    enable_delete: bool = True
    enable_update: bool = True

    # Database for user memory storage
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    # Internal: staged memory for batching updates
    _staged_memory: Optional[UserMemoryV2] = field(default=None, repr=False)
    _staged_dirty: bool = field(default=False, repr=False)

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        system_message: Optional[str] = None,
        profile_capture_instructions: Optional[str] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        enable_delete: bool = True,
        enable_update: bool = True,
    ):
        self.model = model  # type: ignore[assignment]
        self.system_message = system_message
        self.profile_capture_instructions = profile_capture_instructions
        self.db = db
        self.enable_delete = enable_delete
        self.enable_update = enable_update
        self.memory_updated = False
        self._staged_memory = None
        self._staged_dirty = False

        if self.model is not None:
            self.model = get_model(self.model)

    # --- Public API: get/save/delete user memory ---

    def get_user_memory(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        if user_id is None:
            user_id = "default"
        self.db = cast(BaseDb, self.db)
        result = self.db.get_user_memory_v2(user_id=user_id)
        if result is None:
            return None
        if isinstance(result, dict):
            return UserMemoryV2.from_dict(result)
        return result

    def save_user_memory(self, user_memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        self.db = cast(BaseDb, self.db)
        return self.db.upsert_user_memory_v2(user_memory=user_memory)

    def delete_user_memory(self, user_id: Optional[str] = None) -> None:
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return
        if user_id is None:
            user_id = "default"
        self.db = cast(BaseDb, self.db)
        self.db.delete_user_memory_v2(user_id=user_id)

    async def aget_user_memory(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        if user_id is None:
            user_id = "default"
        if isinstance(self.db, AsyncBaseDb):
            result = await self.db.get_user_memory_v2(user_id=user_id)
        else:
            result = self.db.get_user_memory_v2(user_id=user_id)
        if result is None:
            return None
        if isinstance(result, dict):
            return UserMemoryV2.from_dict(result)
        return result

    async def asave_user_memory(self, user_memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.upsert_user_memory_v2(user_memory=user_memory)
        return self.db.upsert_user_memory_v2(user_memory=user_memory)

    async def adelete_user_memory(self, user_id: Optional[str] = None) -> None:
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return
        if user_id is None:
            user_id = "default"
        if isinstance(self.db, AsyncBaseDb):
            await self.db.delete_user_memory_v2(user_id=user_id)
        else:
            self.db.delete_user_memory_v2(user_id=user_id)

    # --- Backwards compatibility aliases ---

    def get_user_profile(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        return self.get_user_memory(user_id)

    def save_user_profile(self, user_memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        return self.save_user_memory(user_memory)

    def delete_user_profile(self, user_id: Optional[str] = None) -> None:
        return self.delete_user_memory(user_id)

    async def aget_user_profile(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        return await self.aget_user_memory(user_id)

    async def asave_user_profile(self, user_memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        return await self.asave_user_memory(user_memory)

    async def adelete_user_profile(self, user_id: Optional[str] = None) -> None:
        return await self.adelete_user_memory(user_id)

    # --- Compile user memory as context ---

    def compile_user_memory(self, user_id: Optional[str] = None) -> str:
        if user_id is None:
            user_id = "default"
        user_memory = self.get_user_memory(user_id)
        if not user_memory:
            return ""
        return self._format_memory_as_context(user_memory)

    async def acompile_user_memory(self, user_id: Optional[str] = None) -> str:
        if user_id is None:
            user_id = "default"
        user_memory = await self.aget_user_memory(user_id)
        if not user_memory:
            return ""
        return self._format_memory_as_context(user_memory)

    # Backwards compatibility
    def compile_user_profile(self, user_id: Optional[str] = None) -> str:
        return self.compile_user_memory(user_id)

    async def acompile_user_profile(self, user_id: Optional[str] = None) -> str:
        return await self.acompile_user_memory(user_id)

    def _format_memory_as_context(self, user_memory: UserMemoryV2) -> str:
        data: Dict[str, Any] = {}
        if user_memory.policies:
            data["policies"] = user_memory.policies
        if user_memory.profile:
            data["profile"] = user_memory.profile
        if user_memory.knowledge:
            data["knowledge"] = user_memory.knowledge
        if user_memory.feedback:
            data["feedback"] = user_memory.feedback
        if not data:
            return ""
        return f"<user_memory>\n{json.dumps(data, separators=(',', ':'))}\n</user_memory>"

    # --- Create/update user memory from messages ---

    def create_user_memory(
        self,
        message: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates or updates user memory from a message."""
        if self.db is None:
            log_warning("MemoryCompiler: Database not configured")
            return "Database not configured"

        if not message:
            return "No message provided"

        if user_id is None:
            user_id = "default"

        log_debug("MemoryCompiler Start", center=True)
        result = self._extract_with_tools(message, user_id)
        log_debug("MemoryCompiler End", center=True)
        return result

    async def acreate_user_memory(
        self,
        message: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates or updates user memory from a message (async)."""
        if self.db is None:
            log_warning("MemoryCompiler: Database not configured")
            return "Database not configured"

        if not message:
            return "No message provided"

        if user_id is None:
            user_id = "default"

        log_debug("MemoryCompiler Start", center=True)
        result = await self._aextract_with_tools(message, user_id)
        log_debug("MemoryCompiler End", center=True)
        return result

    # Backwards compatibility
    def create_user_profile(self, message: str, user_id: Optional[str] = None) -> str:
        return self.create_user_memory(message, user_id)

    async def acreate_user_profile(self, message: str, user_id: Optional[str] = None) -> str:
        return await self.acreate_user_memory(message, user_id)

    # --- Internal extraction with tools ---

    def _extract_with_tools(self, message: str, user_id: str) -> str:
        """Extract memory using tool-based approach with staged updates."""
        if self.model is None:
            log_warning("MemoryCompiler: Model not configured")
            return "Model not configured"
        if self.db is None:
            log_warning("MemoryCompiler: Database not configured")
            return "Database not configured"

        # Load existing memory and stage it for updates
        existing = self.get_user_memory(user_id)
        self._staged_memory = existing or UserMemoryV2(user_id=user_id)
        self._staged_dirty = False

        model_copy = deepcopy(self.model)

        # Prepare tools that mutate staged memory
        raw_tools = self._get_staged_tools(user_id)
        _tools = self._determine_tools_for_model(raw_tools)

        messages_for_model: List[Message] = [
            self._get_system_message(existing_memory=existing),
            Message(role="user", content=message),
        ]

        response = model_copy.response(
            messages=messages_for_model,
            tools=_tools,
        )

        # Commit staged changes to DB (single upsert)
        if self._staged_dirty and self._staged_memory is not None:
            self._staged_memory.bump_updated_at()
            self.save_user_memory(self._staged_memory)
            self.memory_updated = True

        # Reset staging
        self._staged_memory = None
        self._staged_dirty = False

        return response.content or "No response from model"

    async def _aextract_with_tools(self, message: str, user_id: str) -> str:
        """Extract memory using tool-based approach (async) with staged updates."""
        if self.model is None:
            log_warning("MemoryCompiler: Model not configured")
            return "Model not configured"
        if self.db is None:
            log_warning("MemoryCompiler: Database not configured")
            return "Database not configured"

        # Load existing memory and stage it
        existing = await self.aget_user_memory(user_id)
        self._staged_memory = existing or UserMemoryV2(user_id=user_id)
        self._staged_dirty = False

        model_copy = deepcopy(self.model)

        # Prepare async tools
        raw_tools = self._get_staged_tools_async(user_id)
        _tools = self._determine_tools_for_model(raw_tools)

        messages_for_model: List[Message] = [
            self._get_system_message(existing_memory=existing),
            Message(role="user", content=message),
        ]

        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=_tools,
        )

        # Commit staged changes (single upsert)
        if self._staged_dirty and self._staged_memory is not None:
            self._staged_memory.bump_updated_at()
            await self.asave_user_memory(self._staged_memory)
            self.memory_updated = True

        # Reset staging
        self._staged_memory = None
        self._staged_dirty = False

        return response.content or "No response from model"

    def _get_system_message(self, existing_memory: Optional[UserMemoryV2] = None) -> Message:
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
            You are a Memory Manager responsible for managing information and preferences about the user.

            ## Security Rules
            NEVER store secrets, credentials, API keys, passwords, tokens, or any sensitive authentication data.
            If the user mentions such information, do NOT save it.

            ## When to Add or Update Memory
            - Decide if memory needs to be added, updated, or deleted based on the user's message.
            - If the user's message meets the criteria in <memory_to_capture> and is not already stored, capture it.
            - If the message does not meet the criteria, no updates are needed.
            - If existing memory already captures the relevant information, no updates are needed.

            ## How to Save Information
            Capture key details as brief, third-person statements.

            Examples:
            - 'My name is John Doe' -> save_user_profile(key='name', value='John Doe')
            - 'I work at Acme Corp' -> save_user_profile(key='company', value='Acme Corp')
            - 'I like anime and video games' -> save_user_knowledge(key='interests', value='enjoys anime and video games')
            - 'Please be concise' -> save_user_policy(key='response_style', value='prefers concise responses')
            - 'I love how you used bullet points' -> save_user_feedback(key='positive', value='prefers bullet point format')
            - 'Great!' -> DO NOT SAVE (too vague, not actionable)

            Create multiple entries if needed. Don't repeat information.
            If user asks to forget something, delete the relevant entry.

            <memory_to_capture>
            {profile_capture_instructions}
            </memory_to_capture>

            ## Available Tools""")

        if self.enable_update:
            system_prompt += """
            - save_user_profile(key, value): Save identity info (name, company, role, location)
            - save_user_knowledge(key, value): Save learned facts (interests, hobbies, habits)
            - save_user_policy(key, value): Save behavior rules (be concise, no emojis)
            - save_user_feedback(key, value): Save response feedback (positive/negative)"""
        if self.enable_delete:
            system_prompt += """
            - delete_user_profile(key): Delete identity info
            - delete_user_knowledge(key): Delete a knowledge fact
            - delete_user_policy(key): Delete a behavior rule
            - delete_user_feedback(key): Clear feedback (key='positive' or 'negative')"""

        system_prompt += "\n\nYou can call multiple tools in a single response if needed."

        if existing_memory:
            existing = self._format_memory_as_context(existing_memory)
            if existing:
                system_prompt += f"\n\n<existing_memory>\n{existing}\n</existing_memory>"

        return Message(role="system", content=system_prompt)

    def _determine_tools_for_model(self, tools: List[Callable]) -> List[Union[Function, Dict[Any, Any]]]:
        """Convert callable tools to Function objects for the model."""
        _functions: List[Union[Function, Dict[Any, Any]]] = []
        for tool in tools:
            func = Function.from_callable(tool, strict=True)
            func.strict = True
            _functions.append(func)
        return _functions

    # --- Staged tools (sync) ---

    def _get_staged_tools(self, user_id: str) -> List[Callable]:
        """Create tools that mutate staged memory (sync)."""
        tools: List[Callable] = []

        if self.enable_update:

            def save_user_profile(key: str, value: str) -> str:
                """Save user identity info (name, company, role, location)."""
                return self._stage_save("profile", key, value)

            def save_user_knowledge(key: str, value: str) -> str:
                """Save a fact about the user (interests, hobbies, habits)."""
                return self._stage_save("knowledge", key, value)

            def save_user_policy(key: str, value: str) -> str:
                """Save a behavior rule (be concise, no emojis)."""
                return self._stage_save("policy", key, value)

            def save_user_feedback(key: str, value: str) -> str:
                """Save response feedback. Key should be 'positive' or 'negative'."""
                return self._stage_save("feedback", key, value)

            tools.extend([save_user_profile, save_user_knowledge, save_user_policy, save_user_feedback])

        if self.enable_delete:

            def delete_user_profile(key: str) -> str:
                """Delete user identity info."""
                return self._stage_delete("profile", key)

            def delete_user_knowledge(key: str) -> str:
                """Delete a knowledge fact."""
                return self._stage_delete("knowledge", key)

            def delete_user_policy(key: str) -> str:
                """Delete a behavior rule."""
                return self._stage_delete("policy", key)

            def delete_user_feedback(key: str) -> str:
                """Clear feedback. Key should be 'positive' or 'negative'."""
                return self._stage_delete("feedback", key)

            tools.extend([delete_user_profile, delete_user_knowledge, delete_user_policy, delete_user_feedback])

        return tools

    def _get_staged_tools_async(self, user_id: str) -> List[Callable]:
        """Create async tools that mutate staged memory."""
        tools: List[Callable] = []

        if self.enable_update:

            async def save_user_profile(key: str, value: str) -> str:
                """Save user identity info (name, company, role, location)."""
                return self._stage_save("profile", key, value)

            async def save_user_knowledge(key: str, value: str) -> str:
                """Save a fact about the user (interests, hobbies, habits)."""
                return self._stage_save("knowledge", key, value)

            async def save_user_policy(key: str, value: str) -> str:
                """Save a behavior rule (be concise, no emojis)."""
                return self._stage_save("policy", key, value)

            async def save_user_feedback(key: str, value: str) -> str:
                """Save response feedback. Key should be 'positive' or 'negative'."""
                return self._stage_save("feedback", key, value)

            tools.extend([save_user_profile, save_user_knowledge, save_user_policy, save_user_feedback])

        if self.enable_delete:

            async def delete_user_profile(key: str) -> str:
                """Delete user identity info."""
                return self._stage_delete("profile", key)

            async def delete_user_knowledge(key: str) -> str:
                """Delete a knowledge fact."""
                return self._stage_delete("knowledge", key)

            async def delete_user_policy(key: str) -> str:
                """Delete a behavior rule."""
                return self._stage_delete("policy", key)

            async def delete_user_feedback(key: str) -> str:
                """Clear feedback. Key should be 'positive' or 'negative'."""
                return self._stage_delete("feedback", key)

            tools.extend([delete_user_profile, delete_user_knowledge, delete_user_policy, delete_user_feedback])

        return tools

    # --- Staged mutation methods ---

    def _stage_save(self, info_type: str, key: str, value: str) -> str:
        """Apply save to staged memory (no DB write yet)."""
        if self._staged_memory is None:
            return "Error: No staged memory"

        memory = self._staged_memory

        if info_type == "profile":
            if memory.profile is None:
                memory.profile = {}
            memory.profile[key] = value

        elif info_type == "policy":
            if memory.layers is None:
                memory.layers = {}
            memory.layers.setdefault("policies", {})[key] = value

        elif info_type == "knowledge":
            if memory.layers is None:
                memory.layers = {}
            knowledge = memory.layers.setdefault("knowledge", [])
            memory.layers["knowledge"] = [f for f in knowledge if f.get("key") != key]
            memory.layers["knowledge"].append({"key": key, "value": value})

        elif info_type == "feedback":
            if memory.layers is None:
                memory.layers = {}
            feedback = memory.layers.setdefault("feedback", {"positive": [], "negative": []})

            if key in ("positive", "negative"):
                if value not in feedback.setdefault(key, []):
                    feedback[key].append(value)
            else:
                return f"Error: feedback key must be 'positive' or 'negative', got '{key}'"

        else:
            return f"Error: Unknown info_type: {info_type}"

        self._staged_dirty = True
        log_debug(f"Staged {info_type} {key}={value}")
        return f"Saved {info_type}: {key} = {value}"

    def _stage_delete(self, info_type: str, key: str) -> str:
        """Apply delete to staged memory (no DB write yet)."""
        if self._staged_memory is None:
            return "Error: No staged memory"

        memory = self._staged_memory
        layers = memory.layers or {}

        if info_type == "profile":
            if memory.profile and key in memory.profile:
                del memory.profile[key]
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
            if memory.layers is None:
                memory.layers = {}
            memory.layers["knowledge"] = [f for f in knowledge if f.get("key") != key]
            if len(memory.layers["knowledge"]) == before:
                return f"Key '{key}' not found in knowledge"

        elif info_type == "feedback":
            if key not in ("positive", "negative"):
                return f"Error: feedback key must be 'positive' or 'negative', got '{key}'"
            feedback = layers.get("feedback", {})
            if key in feedback:
                feedback[key] = []
            else:
                return f"Key '{key}' not found in feedback"

        else:
            return f"Error: Unknown info_type: {info_type}"

        self._staged_dirty = True
        log_debug(f"Staged delete {info_type} {key}")
        return f"Forgot {info_type}: {key}"

    # --- Legacy methods for Agent/Team integration ---

    def _save_to_user_memory_layer(self, user_id: str, info_type: str, key: str, value: str) -> str:
        """Save to user memory layer (immediate DB write)."""
        memory = self.get_user_memory(user_id) or UserMemoryV2(user_id=user_id)
        self._staged_memory = memory
        result = self._stage_save(info_type, key, value)
        if not result.startswith("Error"):
            memory.bump_updated_at()
            self.save_user_memory(memory)
        self._staged_memory = None
        return result

    async def _asave_to_user_memory_layer(self, user_id: str, info_type: str, key: str, value: str) -> str:
        """Async save to user memory layer (immediate DB write)."""
        memory = await self.aget_user_memory(user_id) or UserMemoryV2(user_id=user_id)
        self._staged_memory = memory
        result = self._stage_save(info_type, key, value)
        if not result.startswith("Error"):
            memory.bump_updated_at()
            await self.asave_user_memory(memory)
        self._staged_memory = None
        return result

    def _delete_from_user_memory_layer(self, user_id: str, info_type: str, key: str) -> str:
        """Delete from user memory layer (immediate DB write)."""
        memory = self.get_user_memory(user_id)
        if not memory:
            return f"No memory found for user {user_id}"
        self._staged_memory = memory
        result = self._stage_delete(info_type, key)
        if not result.startswith("Error") and not result.endswith("not found"):
            memory.bump_updated_at()
            self.save_user_memory(memory)
        self._staged_memory = None
        return result

    async def _adelete_from_user_memory_layer(self, user_id: str, info_type: str, key: str) -> str:
        """Async delete from user memory layer (immediate DB write)."""
        memory = await self.aget_user_memory(user_id)
        if not memory:
            return f"No memory found for user {user_id}"
        self._staged_memory = memory
        result = self._stage_delete(info_type, key)
        if not result.startswith("Error") and not result.endswith("not found"):
            memory.bump_updated_at()
            await self.asave_user_memory(memory)
        self._staged_memory = None
        return result
