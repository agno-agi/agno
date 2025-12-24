import json
from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_memory import UserMemoryV2
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.run.base import RunContext
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


@dataclass
class MemoryCompiler:
    # LLM model for extracting memory from messages
    model: Optional[Model] = None

    # The database to store memories
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    # Custom system prompt (overrides default extraction prompt)
    system_message: Optional[str] = None

    # Instructions for what to capture
    profile_capture_instructions: Optional[str] = None

    # Whether to enable save/update tools during LLM extraction
    enable_update: bool = True

    # ----- Memory layer toggles -----
    # Enable profile layer
    enable_profile: bool = True
    # Enable knowledge layer
    enable_knowledge: bool = True
    # Enable policies layer
    enable_policies: bool = True
    # Enable feedback layer
    enable_feedback: bool = True

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        system_message: Optional[str] = None,
        profile_capture_instructions: Optional[str] = None,
        enable_update: bool = True,
        enable_profile: bool = True,
        enable_knowledge: bool = True,
        enable_policies: bool = True,
        enable_feedback: bool = True,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.system_message = system_message
        self.profile_capture_instructions = profile_capture_instructions
        self.enable_update = enable_update
        self.enable_profile = enable_profile
        self.enable_knowledge = enable_knowledge
        self.enable_policies = enable_policies
        self.enable_feedback = enable_feedback

    def get_user_memory_v2(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        """Get user memory from database."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        user_id = user_id or "default"
        result = cast(BaseDb, self.db).get_user_memory_v2(user_id)
        if isinstance(result, dict):
            return UserMemoryV2.from_dict(result)
        return result or UserMemoryV2(user_id=user_id)

    async def aget_user_memory_v2(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        """Get user memory from database (async)."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        user_id = user_id or "default"
        if isinstance(self.db, AsyncBaseDb):
            result = await self.db.get_user_memory_v2(user_id)
        else:
            result = self.db.get_user_memory_v2(user_id)
        if isinstance(result, dict):
            return UserMemoryV2.from_dict(result)
        return result or UserMemoryV2(user_id=user_id)

    def save_user_memory_v2(self, memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        """Save user memory to database."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        return cast(BaseDb, self.db).upsert_user_memory_v2(memory)

    async def asave_user_memory_v2(self, memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        """Save user memory to database (async)."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        if isinstance(self.db, AsyncBaseDb):
            return await self.db.upsert_user_memory_v2(memory)
        return self.db.upsert_user_memory_v2(memory)

    def delete_user_memory_v2(self, user_id: Optional[str] = None) -> None:
        """Delete user memory from database."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return
        cast(BaseDb, self.db).delete_user_memory_v2(user_id or "default")

    async def adelete_user_memory_v2(self, user_id: Optional[str] = None) -> None:
        """Delete user memory from database (async)."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return
        if isinstance(self.db, AsyncBaseDb):
            await self.db.delete_user_memory_v2(user_id or "default")
        else:
            self.db.delete_user_memory_v2(user_id or "default")

    def compile_user_memory_v2(self, user_id: Optional[str] = None) -> str:
        """Compile user memory into context string."""
        memory = self.get_user_memory_v2(user_id)
        return self._build_memory_context(memory) if memory else ""

    async def acompile_user_memory_v2(self, user_id: Optional[str] = None) -> str:
        """Compile user memory into context string (async)."""
        memory = await self.aget_user_memory_v2(user_id)
        return self._build_memory_context(memory) if memory else ""

    def create_user_memory_v2(self, message: str, user_id: Optional[str] = None) -> str:
        """Create user memory from a message"""
        if not self.db:
            return "Database not configured"
        if not self.model:
            return "Model not configured"
        if not message:
            return "No message provided"

        user_id = user_id or "default"
        existing = self.get_user_memory_v2(user_id)

        # Use local state to avoid race conditions with concurrent calls
        staged: Dict[str, Any] = {
            "memory": existing or UserMemoryV2(user_id=user_id),
            "dirty": False,
        }

        response = deepcopy(self.model).response(
            messages=[self._build_system_message(existing), Message(role="user", content=message)],
            tools=self._build_tools(staged),
        )

        if staged["dirty"]:
            staged["memory"].bump_updated_at()
            self.save_user_memory_v2(staged["memory"])

        return response.content or "No response"

    async def acreate_user_memory_v2(self, message: str, user_id: Optional[str] = None) -> str:
        """Extract and create user memory from a message using LLM (async)."""
        if not self.db:
            return "Database not configured"
        if not self.model:
            return "Model not configured"
        if not message:
            return "No message provided"

        user_id = user_id or "default"
        existing = await self.aget_user_memory_v2(user_id)

        # Use local state to avoid race conditions with concurrent calls
        staged: Dict[str, Any] = {
            "memory": existing or UserMemoryV2(user_id=user_id),
            "dirty": False,
        }

        response = await deepcopy(self.model).aresponse(
            messages=[self._build_system_message(existing), Message(role="user", content=message)],
            tools=self._build_tools(staged, async_mode=True),
        )

        if staged["dirty"]:
            staged["memory"].bump_updated_at()
            await self.asave_user_memory_v2(staged["memory"])

        return response.content or "No response"

    def _build_memory_context(self, memory: UserMemoryV2) -> str:
        data: Dict[str, Any] = {}
        policies = memory.layers.get("policies", {})
        knowledge = memory.layers.get("knowledge", {})
        feedback = memory.layers.get("feedback", {})
        if policies:
            data["policies"] = policies
        if memory.profile:
            data["profile"] = memory.profile
        if knowledge:
            data["knowledge"] = knowledge
        if feedback:
            data["feedback"] = feedback
        if not data:
            return ""
        return f"<user_memory>\n{json.dumps(data, separators=(',', ':'))}\n</user_memory>"

    def _build_system_message(self, existing: Optional[UserMemoryV2] = None) -> Message:
        """Build system prompt for LLM extraction."""
        if self.system_message:
            return Message(role="system", content=self.system_message)

        # Build instructions based on enabled layers
        if self.profile_capture_instructions:
            instructions = self.profile_capture_instructions
        else:
            layer_descriptions = []
            if self.enable_profile:
                layer_descriptions.append("- Profile: identity info (name, company, role, location)")
            if self.enable_knowledge:
                layer_descriptions.append("- Knowledge: personal facts (interests, hobbies, habits)")
            if self.enable_policies:
                layer_descriptions.append("- Policies: behavior rules (no emojis, be concise)")
            if self.enable_feedback:
                layer_descriptions.append("- Feedback: what user liked/disliked about responses")
            instructions = "Capture user information into the appropriate memory layer:\n" + "\n".join(
                layer_descriptions
            )

        # Build save tools list
        save_tools = []
        if self.enable_profile:
            save_tools.append("save_user_profile")
        if self.enable_knowledge:
            save_tools.append("save_user_knowledge")
        if self.enable_policies:
            save_tools.append("save_user_policy")
        if self.enable_feedback:
            save_tools.append("save_user_feedback")

        prompt = dedent(f"""\
            You are a Memory Manager for user information and preferences.

            NEVER store secrets, credentials, API keys, or passwords.

            Capture information only if it meets the criteria below and isn't already stored.
            Use brief, third-person statements.

            <criteria>
            {instructions}
            </criteria>

            Tools: {", ".join(save_tools)}""")

        # Build delete tools list
        delete_tools = []
        if self.enable_profile:
            delete_tools.append("delete_user_profile")
        if self.enable_knowledge:
            delete_tools.append("delete_user_knowledge")
        if self.enable_policies:
            delete_tools.append("delete_user_policy")
        if self.enable_feedback:
            delete_tools.append("delete_user_feedback")
        if delete_tools:
            prompt += f"\nDelete tools: {', '.join(delete_tools)}"

        if existing:
            context = self._build_memory_context(existing)
            if context:
                prompt += f"\n\n<existing_memory>\n{context}\n</existing_memory>"

        return Message(role="system", content=prompt)

    def _build_tools(self, staged: Dict[str, Any], async_mode: bool = False) -> List[Function]:
        """Build LLM tools for memory extraction.

        Args:
            staged: Local dict with 'memory' and 'dirty' keys. Closures capture this
                    to avoid race conditions with concurrent extract() calls.
            async_mode: Whether to create async tool functions.
        """
        tools: List[Any] = []

        def make_save(info_type: str, doc: str):
            if async_mode:

                async def tool(key: str, value: str) -> str:
                    return _stage_save(staged, info_type, key, value)
            else:

                def tool(key: str, value: str) -> str:
                    return _stage_save(staged, info_type, key, value)

            tool.__doc__ = doc
            tool.__name__ = f"save_user_{info_type}"
            return tool

        def make_delete(info_type: str, doc: str):
            if async_mode:

                async def tool(key: str) -> str:
                    return _stage_delete(staged, info_type, key)
            else:

                def tool(key: str) -> str:
                    return _stage_delete(staged, info_type, key)

            tool.__doc__ = doc
            tool.__name__ = f"delete_user_{info_type}"
            return tool

        if self.enable_update:
            if self.enable_profile:
                tools.append(make_save("profile", "Save user identity info (name, company, role, location)."))
                tools.append(make_delete("profile", "Delete user identity info."))
            if self.enable_knowledge:
                tools.append(make_save("knowledge", "Save a fact about the user (interests, hobbies)."))
                tools.append(make_delete("knowledge", "Delete a knowledge fact."))
            if self.enable_policies:
                tools.append(make_save("policy", "Save a behavior rule (be concise, no emojis)."))
                tools.append(make_delete("policy", "Delete a behavior rule."))
            if self.enable_feedback:
                tools.append(make_save("feedback", "Save response feedback. Key: 'positive' or 'negative'."))
                tools.append(make_delete("feedback", "Clear feedback. Key: 'positive' or 'negative'."))

        return [Function.from_callable(t, strict=True) for t in tools]


def _stage_save(staged: Dict[str, Any], info_type: str, key: str, value: Any) -> str:
    """Stage a save operation during LLM extraction."""
    memory: UserMemoryV2 = staged["memory"]

    if info_type == "profile":
        memory.profile[key] = value
    elif info_type == "policy":
        memory.layers.setdefault("policies", {})[key] = value
    elif info_type == "knowledge":
        memory.layers.setdefault("knowledge", {})[key] = value
    elif info_type == "feedback":
        if key not in ("positive", "negative"):
            return "Error: key must be 'positive' or 'negative'"
        feedback = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
        if value not in feedback[key]:
            feedback[key].append(value)
    else:
        return f"Error: Unknown type {info_type}"

    staged["dirty"] = True
    return f"Saved {info_type}: {key}"


def _stage_delete(staged: Dict[str, Any], info_type: str, key: str) -> str:
    """Stage a delete operation during LLM extraction."""
    memory: UserMemoryV2 = staged["memory"]
    layers = memory.layers

    if info_type == "profile":
        if key in memory.profile:
            del memory.profile[key]
        else:
            return f"Key '{key}' not found"
    elif info_type == "policy":
        policies = layers.get("policies", {})
        if key in policies:
            del policies[key]
        else:
            return f"Key '{key}' not found"
    elif info_type == "knowledge":
        knowledge = layers.get("knowledge", {})
        if key in knowledge:
            del knowledge[key]
        else:
            return f"Key '{key}' not found"
    elif info_type == "feedback":
        if key not in ("positive", "negative"):
            return "Error: key must be 'positive' or 'negative'"
        feedback = layers.get("feedback", {})
        if key in feedback:
            feedback[key] = []
        else:
            return f"Key '{key}' not found"
    else:
        return f"Error: Unknown type {info_type}"

    staged["dirty"] = True
    return f"Deleted {info_type}: {key}"


# =============================================================================
# Pending Updates (for Agent/Team agentic tools)
# =============================================================================
#
# These functions allow Agent/Team to batch memory updates during a run.
# Instead of writing to the database on each tool call, updates are staged
# in run_context.session_state and committed at the end of the run.
#
# Flow:
# 1. Agent tool calls init_pending() to start batching
# 2. Tool calls stage_profile_update() or stage_layer_update() for each change
# 3. At end of run, commit_pending() writes all changes to database
#
# This batching improves performance and ensures atomicity.

USER_MEMORY_KEY = "_pending_user_memory"


def init_pending(run_context: RunContext, user_id: str) -> None:
    """Initialize pending memory structure in run_context.

    Call this before staging any updates. Safe to call multiple times.

    Args:
        run_context: The RunContext from the current agent run.
        user_id: User ID for the pending updates.
    """
    if run_context.session_state is None:
        run_context.session_state = {}
    if USER_MEMORY_KEY not in run_context.session_state:
        run_context.session_state[USER_MEMORY_KEY] = {
            "user_id": user_id,
            "profile": {},
            "layers": {},
        }


def stage_profile_update(run_context: RunContext, user_id: str, key: str, value: Any) -> None:
    """Stage a profile field update.

    Args:
        run_context: The RunContext from the current agent run.
        user_id: User ID for the update.
        key: Profile field name (e.g., "name", "company").
        value: New value, or None to delete.
    """
    init_pending(run_context, user_id)
    pending = run_context.session_state[USER_MEMORY_KEY]
    if value is None:
        pending["profile"].pop(key, None)
    else:
        pending["profile"][key] = value


def stage_layer_update(
    run_context: RunContext,
    user_id: str,
    layer: str,
    key: str,
    value: Any,
    action: str = "set",
) -> None:
    """Stage a layer update (policies, knowledge, or feedback).

    Args:
        run_context: The RunContext from the current agent run.
        user_id: User ID for the update.
        layer: Layer name ("policies", "knowledge", or "feedback").
        key: Key within the layer.
        value: New value.
        action: "set" to add/update, "delete" to remove.
    """
    init_pending(run_context, user_id)
    pending = run_context.session_state[USER_MEMORY_KEY]
    _apply_layer_update(pending["layers"], layer, key, value, action)


def has_pending(run_context: RunContext) -> bool:
    """Check if there are pending memory updates.

    Args:
        run_context: The RunContext to check.

    Returns:
        True if there are staged updates waiting to be committed.
    """
    return bool(run_context.session_state and USER_MEMORY_KEY in run_context.session_state)


def clear_pending(run_context: RunContext) -> None:
    """Clear all pending memory updates without committing.

    Args:
        run_context: The RunContext to clear.
    """
    if run_context.session_state:
        run_context.session_state.pop(USER_MEMORY_KEY, None)


def commit_pending(db: BaseDb, user_id: str, run_context: RunContext) -> bool:
    """Commit all pending updates to database.

    Loads existing memory, applies all staged updates, and saves.

    Args:
        db: Database to commit to.
        user_id: User ID for the memory.
        run_context: RunContext containing staged updates.

    Returns:
        True on success.
    """
    if not has_pending(run_context):
        return True

    pending = run_context.session_state[USER_MEMORY_KEY]
    if pending.get("user_id") != user_id:
        return True

    # Load existing memory
    result = db.get_user_memory_v2(user_id)
    if isinstance(result, dict):
        memory = UserMemoryV2.from_dict(result)
    else:
        memory = result or UserMemoryV2(user_id=user_id)

    # Apply all pending updates
    _apply_pending_updates(memory, pending)
    memory.bump_updated_at()

    # Save and clear
    db.upsert_user_memory_v2(memory)
    clear_pending(run_context)
    log_debug(f"Committed user memory updates for {user_id}")
    return True


async def acommit_pending(db: Union[AsyncBaseDb, BaseDb], user_id: str, run_context: RunContext) -> bool:
    """Commit all pending updates to database (async).

    Args:
        db: Database to commit to.
        user_id: User ID for the memory.
        run_context: RunContext containing staged updates.

    Returns:
        True on success.
    """
    if not has_pending(run_context):
        return True

    pending = run_context.session_state[USER_MEMORY_KEY]
    if pending.get("user_id") != user_id:
        return True

    # Load existing memory
    if isinstance(db, AsyncBaseDb):
        result = await db.get_user_memory_v2(user_id)
    else:
        result = db.get_user_memory_v2(user_id)

    if isinstance(result, dict):
        memory = UserMemoryV2.from_dict(result)
    else:
        memory = result or UserMemoryV2(user_id=user_id)

    # Apply all pending updates
    _apply_pending_updates(memory, pending)
    memory.bump_updated_at()

    # Save and clear
    if isinstance(db, AsyncBaseDb):
        await db.upsert_user_memory_v2(memory)
    else:
        db.upsert_user_memory_v2(memory)

    clear_pending(run_context)
    log_debug(f"Committed user memory updates for {user_id}")
    return True


# =============================================================================
# Private: Helpers
# =============================================================================


def _apply_pending_updates(memory: UserMemoryV2, pending: Dict[str, Any]) -> None:
    """Apply all pending updates to memory object."""
    # Profile updates
    for key, value in pending.get("profile", {}).items():
        if value is None:
            memory.profile.pop(key, None)
        else:
            memory.profile[key] = value

    # Layer updates
    for layer, data in pending.get("layers", {}).items():
        if layer == "feedback":
            feedback = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
            for fb_type in ("positive", "negative"):
                if fb_type in data:
                    for val in data[fb_type]:
                        if val not in feedback.setdefault(fb_type, []):
                            feedback[fb_type].append(val)
        else:
            # policies and knowledge: simple dict merge
            layer_dict = memory.layers.setdefault(layer, {})
            for key, value in data.items():
                if value is None:
                    layer_dict.pop(key, None)
                else:
                    layer_dict[key] = value


def _apply_layer_update(layers: Dict[str, Any], layer: str, key: str, value: Any, action: str) -> None:
    """Apply a single layer update to pending layers dict."""
    # Initialize layer structure if needed
    if layer not in layers:
        if layer == "feedback":
            layers[layer] = {"positive": [], "negative": []}
        else:
            layers[layer] = {}

    layer_data = layers[layer]

    if action == "delete":
        if layer == "policies" or layer == "knowledge":
            layer_data.pop(key, None)
        elif layer == "feedback" and key in ("positive", "negative"):
            layer_data[key] = []
    else:  # action == "set"
        if layer == "policies" or layer == "knowledge":
            layer_data[key] = value
        elif layer == "feedback" and key in ("positive", "negative"):
            if value not in layer_data[key]:
                layer_data[key].append(value)
