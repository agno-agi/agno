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
    # LLM for extracting memory
    model: Optional[Model] = None
    # storage backend
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    # custom prompt (overrides default)
    system_message: Optional[str] = None
    # what to capture
    capture_instructions: Optional[str] = None
    # Layer toggles
    enable_update: bool = True
    # user identity (name, company, role)
    enable_profile: bool = True
    # user facts (languages, hobbies)
    enable_knowledge: bool = True
    enable_policies: bool = True
    enable_feedback: bool = True

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        system_message: Optional[str] = None,
        capture_instructions: Optional[str] = None,
        enable_update: bool = True,
        enable_profile: bool = True,
        enable_knowledge: bool = True,
        enable_policies: bool = True,
        enable_feedback: bool = True,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.system_message = system_message
        self.capture_instructions = capture_instructions
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
        """Extract memory from user message"""
        if not self.db:
            log_warning("No DB configured")
            return "Database not configured"
        if not self.model:
            log_warning("Model not configured")
            return "Model not configured"
        if not message:
            return "No message provided"

        # Load existing memory or create new
        user_id = user_id or "default"
        memory = self.get_user_memory_v2(user_id) or UserMemoryV2(user_id=user_id)
        modified = False  # track if LLM made changes

        # Each tool modifies the memory directly. We only save the memory after all tool calls.
        def save_user_profile(key: str, value: Any) -> str:
            nonlocal modified
            memory.profile[key] = value
            modified = True
            return f"Saved profile: {key}"

        def delete_user_profile(key: str) -> str:
            nonlocal modified
            memory.profile.pop(key, None)
            modified = True
            return f"Deleted profile: {key}"

        def save_user_knowledge(key: str, value: Any) -> str:
            nonlocal modified
            memory.layers.setdefault("knowledge", {})[key] = value
            modified = True
            return f"Saved knowledge: {key}"

        def delete_user_knowledge(key: str) -> str:
            nonlocal modified
            memory.layers.get("knowledge", {}).pop(key, None)
            modified = True
            return f"Deleted knowledge: {key}"

        def save_user_policy(key: str, value: Any) -> str:
            nonlocal modified
            memory.layers.setdefault("policies", {})[key] = value
            modified = True
            return f"Saved policy: {key}"

        def delete_user_policy(key: str) -> str:
            nonlocal modified
            memory.layers.get("policies", {}).pop(key, None)
            modified = True
            return f"Deleted policy: {key}"

        def save_user_feedback(key: str, value: Any) -> str:
            nonlocal modified
            if key in ("positive", "negative"):
                feedback = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
                if value not in feedback[key]:
                    feedback[key].append(value)
                modified = True
            return f"Saved feedback: {key}"

        def delete_user_feedback(key: str) -> str:
            nonlocal modified
            if key in ("positive", "negative"):
                memory.layers.setdefault("feedback", {"positive": [], "negative": []})[key] = []
                modified = True
            return f"Cleared feedback: {key}"

        # Collect tools based on enabled layers
        tools = self._get_memory_tools(
            save_user_profile,
            delete_user_profile,
            save_user_knowledge,
            delete_user_knowledge,
            save_user_policy,
            delete_user_policy,
            save_user_feedback,
            delete_user_feedback,
        )

        # Send to LLM for extraction
        response = deepcopy(self.model).response(
            messages=[self._build_system_message(memory), Message(role="user", content=message)],
            tools=tools,
        )

        # Save if anything changed
        if modified:
            memory.bump_updated_at()
            self.save_user_memory_v2(memory)

        return response.content or "No response"

    async def acreate_user_memory_v2(self, message: str, user_id: Optional[str] = None) -> str:
        """Extract user info from message using LLM and save to database (async)."""
        if not self.db:
            return "Database not configured"
        if not self.model:
            return "Model not configured"
        if not message:
            return "No message provided"

        # Load existing memory or create new
        user_id = user_id or "default"
        memory = await self.aget_user_memory_v2(user_id) or UserMemoryV2(user_id=user_id)
        modified = False  # track if LLM made changes

        # Define tools for LLM (each modifies memory directly)
        async def save_user_profile(key: str, value: Any) -> str:
            nonlocal modified
            memory.profile[key] = value
            modified = True
            return f"Saved profile: {key}"

        async def delete_user_profile(key: str) -> str:
            nonlocal modified
            memory.profile.pop(key, None)
            modified = True
            return f"Deleted profile: {key}"

        async def save_user_knowledge(key: str, value: Any) -> str:
            nonlocal modified
            memory.layers.setdefault("knowledge", {})[key] = value
            modified = True
            return f"Saved knowledge: {key}"

        async def delete_user_knowledge(key: str) -> str:
            nonlocal modified
            memory.layers.get("knowledge", {}).pop(key, None)
            modified = True
            return f"Deleted knowledge: {key}"

        async def save_user_policy(key: str, value: Any) -> str:
            nonlocal modified
            memory.layers.setdefault("policies", {})[key] = value
            modified = True
            return f"Saved policy: {key}"

        async def delete_user_policy(key: str) -> str:
            nonlocal modified
            memory.layers.get("policies", {}).pop(key, None)
            modified = True
            return f"Deleted policy: {key}"

        async def save_user_feedback(key: str, value: Any) -> str:
            nonlocal modified
            if key in ("positive", "negative"):
                feedback = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
                if value not in feedback[key]:
                    feedback[key].append(value)
                modified = True
            return f"Saved feedback: {key}"

        async def delete_user_feedback(key: str) -> str:
            nonlocal modified
            if key in ("positive", "negative"):
                memory.layers.setdefault("feedback", {"positive": [], "negative": []})[key] = []
                modified = True
            return f"Cleared feedback: {key}"

        # Collect tools based on enabled layers
        tools = self._get_memory_tools(
            save_user_profile,
            delete_user_profile,
            save_user_knowledge,
            delete_user_knowledge,
            save_user_policy,
            delete_user_policy,
            save_user_feedback,
            delete_user_feedback,
        )

        # Send to LLM for extraction
        response = await deepcopy(self.model).aresponse(
            messages=[self._build_system_message(memory), Message(role="user", content=message)],
            tools=tools,
        )

        # Save if anything changed
        if modified:
            memory.bump_updated_at()
            await self.asave_user_memory_v2(memory)

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

        # Build layer info from enabled layers
        layers = []
        if self.enable_profile:
            layers.append(("profile", "identity info (name, company, role, location)"))
        if self.enable_knowledge:
            layers.append(("knowledge", "personal facts (interests, hobbies, habits)"))
        if self.enable_policies:
            layers.append(("policy", "behavior rules (no emojis, be concise)"))
        if self.enable_feedback:
            layers.append(("feedback", "what user liked/disliked about responses"))

        # Build descriptions and tool names from layers
        descriptions = [f"- {name.title()}: {desc}" for name, desc in layers]
        save_tools = [f"save_user_{name}" for name, _ in layers]
        delete_tools = [f"delete_user_{name}" for name, _ in layers]

        layer_descriptions = "\n".join(descriptions)
        custom_instructions = ""
        if self.capture_instructions:
            custom_instructions = f"\nAdditional guidance:\n{self.capture_instructions}\n"

        prompt = dedent(f"""\
            You are a Memory Manager that extracts user information from conversations.

            SECURITY - NEVER STORE:
            - Secrets, credentials, API keys, passwords
            - Sensitive personal data (SSN, credit cards, etc.)

            MEMORY LAYERS:
            {layer_descriptions}
            {custom_instructions}
            TOOLS:
            Save: {", ".join(save_tools)}
            Delete: {", ".join(delete_tools)}

            GUIDELINES:
            - Use brief, third-person statements ("User is a senior engineer")
            - Only save NEW information not already in existing memory
            - Profile = stable identity facts, not temporary states
            - Policies = explicit user preferences/rules
            - Skip trivial, one-time, or already-stored information

            EXAMPLE:
            Message: "I'm Alex, I work at TechCorp. Please be concise."
            -> save_user_profile("name", "Alex")
            -> save_user_profile("company", "TechCorp")
            -> save_user_policy("response_style", "concise")""")

        if existing:
            context = self._build_memory_context(existing)
            if context:
                prompt += f"\n\n<existing_memory>\n{context}\n</existing_memory>"

        return Message(role="system", content=prompt)

    def _get_memory_tools(
        self,
        save_profile,
        delete_profile,
        save_knowledge,
        delete_knowledge,
        save_policy,
        delete_policy,
        save_feedback,
        delete_feedback,
    ) -> List[Union[Function, dict]]:
        """Filter tools based on enabled layers."""
        tools: List[Any] = []
        if self.enable_update:
            if self.enable_profile:
                tools.extend([save_profile, delete_profile])
            if self.enable_knowledge:
                tools.extend([save_knowledge, delete_knowledge])
            if self.enable_policies:
                tools.extend([save_policy, delete_policy])
            if self.enable_feedback:
                tools.extend([save_feedback, delete_feedback])
        return [Function.from_callable(t, strict=True) for t in tools]


USER_MEMORY_KEY = "_pending_user_memory"


def stage_update(
    run_context: RunContext,
    user_id: str,
    layer: str,
    key: str,
    value: Any,
    action: str = "set",
) -> None:
    """Stage a memory update for batch commit."""
    if run_context.session_state is None:
        run_context.session_state = {}
    pending = run_context.session_state.setdefault(USER_MEMORY_KEY, {"user_id": user_id})

    if layer == "feedback":
        # Feedback: {positive: [...], negative: [...]}
        feedback = pending.setdefault("feedback", {"positive": [], "negative": []})
        if action == "delete" and key in ("positive", "negative"):
            feedback[key] = []
        elif key in ("positive", "negative") and value not in feedback[key]:
            feedback[key].append(value)
    else:
        # profile, knowledge, policies: simple dict
        layer_dict = pending.setdefault(layer, {})
        if action == "delete" or value is None:
            layer_dict.pop(key, None)
        else:
            layer_dict[key] = value


def commit_pending(db: BaseDb, user_id: str, run_context: RunContext) -> bool:
    """Write all staged updates to DB in one call."""
    if not run_context.session_state or USER_MEMORY_KEY not in run_context.session_state:
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

    # Apply pending updates, save, and clear
    _apply_pending_updates(memory, pending)
    memory.bump_updated_at()
    db.upsert_user_memory_v2(memory)
    run_context.session_state.pop(USER_MEMORY_KEY, None)
    log_debug(f"Committed user memory updates for {user_id}")
    return True


async def acommit_pending(db: Union[AsyncBaseDb, BaseDb], user_id: str, run_context: RunContext) -> bool:
    """Write all staged updates to DB in one call (async)."""
    if not run_context.session_state or USER_MEMORY_KEY not in run_context.session_state:
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

    # Apply pending updates, save, and clear
    _apply_pending_updates(memory, pending)
    memory.bump_updated_at()
    if isinstance(db, AsyncBaseDb):
        await db.upsert_user_memory_v2(memory)
    else:
        db.upsert_user_memory_v2(memory)
    run_context.session_state.pop(USER_MEMORY_KEY, None)
    log_debug(f"Committed user memory updates for {user_id}")
    return True


def _apply_pending_updates(memory: UserMemoryV2, pending: Dict[str, Any]) -> None:
    """Merge pending updates into memory."""
    # Profile
    for key, value in pending.get("profile", {}).items():
        memory.profile[key] = value

    # Policies
    if pending.get("policies"):
        if not isinstance(memory.layers.get("policies"), dict):
            memory.layers["policies"] = {}
        for key, value in pending["policies"].items():
            memory.layers["policies"][key] = value

    # Knowledge
    if pending.get("knowledge"):
        if not isinstance(memory.layers.get("knowledge"), dict):
            memory.layers["knowledge"] = {}
        for key, value in pending["knowledge"].items():
            memory.layers["knowledge"][key] = value

    # Feedback (append to lists)
    if pending.get("feedback"):
        if not isinstance(memory.layers.get("feedback"), dict):
            memory.layers["feedback"] = {"positive": [], "negative": []}
        for fb_type in ("positive", "negative"):
            for val in pending["feedback"].get(fb_type, []):
                if val not in memory.layers["feedback"][fb_type]:
                    memory.layers["feedback"][fb_type].append(val)
