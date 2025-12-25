import json
from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Dict, List, Optional, Type, Union, cast

from pydantic import BaseModel

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.user_memory import UserMemoryV2
from agno.memory_v2.schemas import UserFeedback, UserKnowledge, UserPolicies, UserProfile
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
    # what to capture
    user_capture_instructions: Optional[str] = None
    # Layer toggles
    enable_update: bool = True
    # user identity (name, company, role)
    enable_profile: bool = True
    # user facts (languages, hobbies)
    enable_knowledge: bool = True
    enable_policies: bool = True
    enable_feedback: bool = True

    # Schema options (constrain what LLM can save)
    use_default_schemas: bool = False
    user_profile_schema: Optional[Type[BaseModel]] = None
    user_policies_schema: Optional[Type[BaseModel]] = None
    user_knowledge_schema: Optional[Type[BaseModel]] = None
    user_feedback_schema: Optional[Type[BaseModel]] = None

    # Per-layer custom instructions (appended to default prompt)
    user_profile_instructions: Optional[str] = None
    user_knowledge_instructions: Optional[str] = None
    user_policies_instructions: Optional[str] = None
    user_feedback_instructions: Optional[str] = None

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        user_capture_instructions: Optional[str] = None,
        enable_update: bool = True,
        enable_profile: bool = True,
        enable_knowledge: bool = True,
        enable_policies: bool = True,
        enable_feedback: bool = True,
        use_default_schemas: bool = False,
        user_profile_schema: Optional[Type[BaseModel]] = None,
        user_policies_schema: Optional[Type[BaseModel]] = None,
        user_knowledge_schema: Optional[Type[BaseModel]] = None,
        user_feedback_schema: Optional[Type[BaseModel]] = None,
        user_profile_instructions: Optional[str] = None,
        user_knowledge_instructions: Optional[str] = None,
        user_policies_instructions: Optional[str] = None,
        user_feedback_instructions: Optional[str] = None,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.user_capture_instructions = user_capture_instructions
        self.enable_update = enable_update
        self.enable_profile = enable_profile
        self.enable_knowledge = enable_knowledge
        self.enable_policies = enable_policies
        self.enable_feedback = enable_feedback
        self.use_default_schemas = use_default_schemas
        self.user_profile_schema = user_profile_schema
        self.user_policies_schema = user_policies_schema
        self.user_knowledge_schema = user_knowledge_schema
        self.user_feedback_schema = user_feedback_schema
        self.user_profile_instructions = user_profile_instructions
        self.user_knowledge_instructions = user_knowledge_instructions
        self.user_policies_instructions = user_policies_instructions
        self.user_feedback_instructions = user_feedback_instructions

    def get_user_memory_v2(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
        """Get user memory from DB."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        user_id = user_id or "default"
        result = cast(BaseDb, self.db).get_user_memory_v2(user_id)
        if isinstance(result, dict):
            return UserMemoryV2.from_dict(result)
        return result or UserMemoryV2(user_id=user_id)

    async def aget_user_memory_v2(self, user_id: Optional[str] = None) -> Optional[UserMemoryV2]:
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
        """Save user memory to DB."""
        if not self.db:
            log_warning("MemoryCompiler: Database not configured")
            return None
        return cast(BaseDb, self.db).upsert_user_memory_v2(memory)

    async def asave_user_memory_v2(self, memory: UserMemoryV2) -> Optional[Union[UserMemoryV2, Dict[str, Any]]]:
        """Save user memory to DB (async)."""
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

    def _merge_updates(self, existing: UserMemoryV2, updates: UserMemoryV2) -> UserMemoryV2:
        merged_layers = {**existing.layers, **updates.layers}

        # Merge feedback lists instead of overwriting
        if "feedback" in existing.layers or "feedback" in updates.layers:
            existing_fb = existing.layers.get("feedback", {"positive": [], "negative": []})
            updates_fb = updates.layers.get("feedback", {"positive": [], "negative": []})
            merged_layers["feedback"] = {
                "positive": list(dict.fromkeys(existing_fb.get("positive", []) + updates_fb.get("positive", []))),
                "negative": list(dict.fromkeys(existing_fb.get("negative", []) + updates_fb.get("negative", []))),
            }

        return UserMemoryV2(
            user_id=existing.user_id,
            profile={**existing.profile, **updates.profile},
            layers=merged_layers,
            metadata=updates.metadata or existing.metadata,
            created_at=existing.created_at,
        )

    def create_user_memory_v2(self, message: str, user_id: Optional[str] = None) -> str:
        """Extract memory from user message."""
        if not self.db:
            log_warning("No DB configured")
            return "Database not configured"
        if not self.model:
            log_warning("Model not configured")
            return "MemoryCompiler: Model not configured"
        if not message:
            return "No message provided"

        # Load existing memory for LLM context
        user_id = user_id or "default"
        memory = self.get_user_memory_v2(user_id) or UserMemoryV2(user_id=user_id)

        # Get extraction tools based on schema configuration
        use_schemas = (
            self.use_default_schemas
            or self.user_profile_schema is not None
            or self.user_policies_schema is not None
            or self.user_knowledge_schema is not None
            or self.user_feedback_schema is not None
        )
        tools = self._compile_schema_tools(memory) if use_schemas else self._compile_tools(memory)

        # Send to Model for extraction
        response = deepcopy(self.model).response(
            messages=[self._build_user_system_message(memory), Message(role="user", content=message)],
            tools=tools,
        )

        # Save if tools were called (fresh read + merge to minimize race window)
        if response.tool_calls:
            current = self.get_user_memory_v2(user_id) or UserMemoryV2(user_id=user_id)
            merged = self._merge_updates(current, memory)
            merged.bump_updated_at()
            self.save_user_memory_v2(merged)

        return response.content or "No response"

    def _compile_tools(self, memory: UserMemoryV2) -> List[Function]:
        """Get key-value based extraction tools."""
        if not self.enable_update:
            return []

        def save_user_profile(key: str, value: Any) -> str:
            memory.profile[key] = value
            return f"Saved profile: {key}"

        def delete_user_profile(key: str) -> str:
            memory.profile.pop(key, None)
            return f"Deleted profile: {key}"

        def save_user_knowledge(key: str, value: Any) -> str:
            memory.layers.setdefault("knowledge", {})[key] = value
            return f"Saved knowledge: {key}"

        def delete_user_knowledge(key: str) -> str:
            memory.layers.get("knowledge", {}).pop(key, None)
            return f"Deleted knowledge: {key}"

        def save_user_policy(key: str, value: Any) -> str:
            memory.layers.setdefault("policies", {})[key] = value
            return f"Saved policy: {key}"

        def delete_user_policy(key: str) -> str:
            memory.layers.get("policies", {}).pop(key, None)
            return f"Deleted policy: {key}"

        def save_user_feedback(key: str, value: Any) -> str:
            if key in ("positive", "negative"):
                feedback = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
                if value not in feedback[key]:
                    feedback[key].append(value)
            return f"Saved feedback: {key}"

        def delete_user_feedback(key: str) -> str:
            if key in ("positive", "negative"):
                memory.layers.setdefault("feedback", {"positive": [], "negative": []})[key] = []
            return f"Cleared feedback: {key}"

        tools: List[Any] = []
        if self.enable_profile:
            tools.extend([save_user_profile, delete_user_profile])
        if self.enable_knowledge:
            tools.extend([save_user_knowledge, delete_user_knowledge])
        if self.enable_policies:
            tools.extend([save_user_policy, delete_user_policy])
        if self.enable_feedback:
            tools.extend([save_user_feedback, delete_user_feedback])

        return [Function.from_callable(t, strict=True) for t in tools]

    def _compile_schema_tools(self, memory: UserMemoryV2) -> List[Function]:
        """Get schema-based extraction tools."""
        if not self.enable_update:
            return []

        from agno.memory_v2.schemas import UserFeedback, UserKnowledge, UserPolicies, UserProfile

        tools: List[Any] = []

        if self.enable_profile:
            ProfileSchema = self.user_profile_schema or UserProfile

            def save_profile(updates: ProfileSchema) -> str:  # type: ignore
                """Save user profile (name, company, role, skills, etc.)."""
                for key, value in updates.model_dump(exclude_none=True).items():
                    memory.profile[key] = value
                return "Profile saved"

            def delete_profile_fields(keys: List[str]) -> str:
                """Delete specific profile fields."""
                for key in keys:
                    memory.profile.pop(key, None)
                return f"Deleted profile fields: {keys}"

            tools.extend([save_profile, delete_profile_fields])

        if self.enable_policies:
            PoliciesSchema = self.user_policies_schema or UserPolicies

            def save_policies(updates: PoliciesSchema) -> str:  # type: ignore
                """Save user preferences (response_style, tone, formatting)."""
                policies = memory.layers.setdefault("policies", {})
                for key, value in updates.model_dump(exclude_none=True).items():
                    policies[key] = value
                return "Policies saved"

            def delete_policy_fields(keys: List[str]) -> str:
                """Delete specific policy fields."""
                policies = memory.layers.get("policies", {})
                for key in keys:
                    policies.pop(key, None)
                return f"Deleted policy fields: {keys}"

            tools.extend([save_policies, delete_policy_fields])

        if self.enable_knowledge:
            KnowledgeSchema = self.user_knowledge_schema or UserKnowledge

            def save_knowledge(updates: KnowledgeSchema) -> str:  # type: ignore
                """Save user context (current_project, tech_stack, interests)."""
                knowledge = memory.layers.setdefault("knowledge", {})
                for key, value in updates.model_dump(exclude_none=True).items():
                    knowledge[key] = value
                return "Knowledge saved"

            def delete_knowledge_fields(keys: List[str]) -> str:
                """Delete specific knowledge fields."""
                knowledge = memory.layers.get("knowledge", {})
                for key in keys:
                    knowledge.pop(key, None)
                return f"Deleted knowledge fields: {keys}"

            tools.extend([save_knowledge, delete_knowledge_fields])

        if self.enable_feedback:
            FeedbackSchema = self.user_feedback_schema or UserFeedback

            def save_feedback(updates: FeedbackSchema) -> str:  # type: ignore
                """Save response feedback (positive/negative lists)."""
                fb = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
                data = updates.model_dump(exclude_none=True)
                for item in data.get("positive", []):
                    if item not in fb["positive"]:
                        fb["positive"].append(item)
                for item in data.get("negative", []):
                    if item not in fb["negative"]:
                        fb["negative"].append(item)
                return "Feedback saved"

            def clear_feedback(clear_positive: bool = False, clear_negative: bool = False) -> str:
                """Clear feedback lists."""
                fb = memory.layers.setdefault("feedback", {"positive": [], "negative": []})
                if clear_positive:
                    fb["positive"] = []
                if clear_negative:
                    fb["negative"] = []
                return "Feedback cleared"

            tools.extend([save_feedback, clear_feedback])

        return [Function.from_callable(t, strict=True) for t in tools]

    async def acreate_user_memory_v2(self, message: str, user_id: Optional[str] = None) -> str:
        """Extract memory from user message (async)."""
        if not self.db:
            return "Database not configured"
        if not self.model:
            return "MemoryCompiler: Model not configured"
        if not message:
            return "No message provided"

        # Load existing memory for LLM context
        user_id = user_id or "default"
        memory = await self.aget_user_memory_v2(user_id) or UserMemoryV2(user_id=user_id)

        # Get extraction tools based on schema configuration
        use_schemas = (
            self.use_default_schemas
            or self.user_profile_schema is not None
            or self.user_policies_schema is not None
            or self.user_knowledge_schema is not None
            or self.user_feedback_schema is not None
        )
        tools = self._compile_schema_tools(memory) if use_schemas else self._compile_tools(memory)

        # Send to LLM for extraction
        response = await deepcopy(self.model).aresponse(
            messages=[self._build_user_system_message(memory), Message(role="user", content=message)],
            tools=tools,
        )

        # Save if tools were called (fresh read + merge to minimize race window)
        if response.tool_calls:
            current = await self.aget_user_memory_v2(user_id) or UserMemoryV2(user_id=user_id)
            merged = self._merge_updates(current, memory)
            merged.bump_updated_at()
            await self.asave_user_memory_v2(merged)

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

    def _build_user_system_message(self, existing: Optional[UserMemoryV2] = None) -> Message:
        """Build system prompt for LLM extraction."""
        # Build layer info from enabled layers
        layers = []
        if self.enable_profile:
            desc = "identity info (name, company, role, location)"
            if self.user_profile_instructions:
                desc += f" - {self.user_profile_instructions}"
            layers.append(("profile", desc))
        if self.enable_knowledge:
            desc = "personal facts (interests, hobbies, habits)"
            if self.user_knowledge_instructions:
                desc += f" - {self.user_knowledge_instructions}"
            layers.append(("knowledge", desc))
        if self.enable_policies:
            desc = "behavior rules (no emojis, be concise)"
            if self.user_policies_instructions:
                desc += f" - {self.user_policies_instructions}"
            layers.append(("policy", desc))
        if self.enable_feedback:
            desc = "what user liked/disliked about responses"
            if self.user_feedback_instructions:
                desc += f" - {self.user_feedback_instructions}"
            layers.append(("feedback", desc))

        # Build descriptions and tool names from layers
        descriptions = [f"- {name.title()}: {desc}" for name, desc in layers]
        save_tools = [f"save_user_{name}" for name, _ in layers]
        delete_tools = [f"delete_user_{name}" for name, _ in layers]

        layer_descriptions = "\n".join(descriptions)
        custom_instructions = ""
        if self.user_capture_instructions:
            custom_instructions = f"\nAdditional guidance:\n{self.user_capture_instructions}\n"

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

    def get_memory_tools(self, user_id: str) -> List[Function]:
        """Get tools for agentic memory updates (used by Agent/Team)."""
        use_schemas = (
            self.use_default_schemas
            or self.user_profile_schema is not None
            or self.user_policies_schema is not None
            or self.user_knowledge_schema is not None
            or self.user_feedback_schema is not None
        )
        if use_schemas:
            return self._agentic_schema_tools(user_id)
        return self._agentic_tools(user_id)

    def _agentic_tools(self, user_id: str) -> List[Function]:
        """Get key-value tools that stage updates for batch commit."""
        tools: List[Function] = []

        if self.enable_profile:

            def save_user_profile(key: str, value: Any, run_context: RunContext) -> str:
                """Save user identity info (name, company, role, location)."""
                stage_update(run_context, user_id, "profile", key, value)
                return f"Saved profile: {key}"

            def delete_user_profile(key: str, run_context: RunContext) -> str:
                """Delete user identity info."""
                stage_update(run_context, user_id, "profile", key, None, "delete")
                return f"Deleted profile: {key}"

            tools.append(Function.from_callable(save_user_profile))
            tools.append(Function.from_callable(delete_user_profile))

        if self.enable_knowledge:

            def save_user_knowledge(key: str, value: Any, run_context: RunContext) -> str:
                """Save a fact about the user (interests, hobbies, habits)."""
                stage_update(run_context, user_id, "knowledge", key, value)
                return f"Saved knowledge: {key}"

            def delete_user_knowledge(key: str, run_context: RunContext) -> str:
                """Delete a knowledge fact."""
                stage_update(run_context, user_id, "knowledge", key, None, "delete")
                return f"Deleted knowledge: {key}"

            tools.append(Function.from_callable(save_user_knowledge))
            tools.append(Function.from_callable(delete_user_knowledge))

        if self.enable_policies:

            def save_user_policy(key: str, value: Any, run_context: RunContext) -> str:
                """Save a behavior rule (be concise, no emojis)."""
                stage_update(run_context, user_id, "policies", key, value)
                return f"Saved policy: {key}"

            def delete_user_policy(key: str, run_context: RunContext) -> str:
                """Delete a behavior rule."""
                stage_update(run_context, user_id, "policies", key, None, "delete")
                return f"Deleted policy: {key}"

            tools.append(Function.from_callable(save_user_policy))
            tools.append(Function.from_callable(delete_user_policy))

        if self.enable_feedback:

            def save_user_feedback(key: str, value: Any, run_context: RunContext) -> str:
                """Save response feedback. Key should be 'positive' or 'negative'."""
                stage_update(run_context, user_id, "feedback", key, value)
                return f"Saved feedback: {key}"

            def delete_user_feedback(key: str, run_context: RunContext) -> str:
                """Clear feedback. Key should be 'positive' or 'negative'."""
                stage_update(run_context, user_id, "feedback", key, None, "delete")
                return f"Cleared feedback: {key}"

            tools.append(Function.from_callable(save_user_feedback))
            tools.append(Function.from_callable(delete_user_feedback))

        return tools

    def _agentic_schema_tools(self, user_id: str) -> List[Function]:
        """Get schema-based tools that stage updates for batch commit."""

        tools: List[Function] = []

        if self.enable_profile:
            ProfileSchema = self.user_profile_schema or UserProfile

            def save_profile(updates, run_context: RunContext) -> str:
                """Save user profile (name, company, role, skills, etc.)."""
                for key, value in updates.model_dump(exclude_none=True).items():
                    stage_update(run_context, user_id, "profile", key, value)
                return "Profile saved"

            def delete_profile_fields(keys: List[str], run_context: RunContext) -> str:
                """Delete specific profile fields."""
                for key in keys:
                    stage_update(run_context, user_id, "profile", key, None, "delete")
                return f"Deleted profile fields: {keys}"

            save_profile.__annotations__["updates"] = ProfileSchema
            tools.append(Function.from_callable(save_profile, strict=True))
            tools.append(Function.from_callable(delete_profile_fields, strict=True))

        if self.enable_policies:
            PoliciesSchema = self.user_policies_schema or UserPolicies

            def save_policies(updates, run_context: RunContext) -> str:
                """Save user preferences (response_style, tone, formatting)."""
                for key, value in updates.model_dump(exclude_none=True).items():
                    stage_update(run_context, user_id, "policies", key, value)
                return "Policies saved"

            def delete_policy_fields(keys: List[str], run_context: RunContext) -> str:
                """Delete specific policy fields."""
                for key in keys:
                    stage_update(run_context, user_id, "policies", key, None, "delete")
                return f"Deleted policy fields: {keys}"

            save_policies.__annotations__["updates"] = PoliciesSchema
            tools.append(Function.from_callable(save_policies, strict=True))
            tools.append(Function.from_callable(delete_policy_fields, strict=True))

        if self.enable_knowledge:
            KnowledgeSchema = self.user_knowledge_schema or UserKnowledge

            def save_knowledge(updates, run_context: RunContext) -> str:
                """Save user context (current_project, tech_stack, interests)."""
                for key, value in updates.model_dump(exclude_none=True).items():
                    stage_update(run_context, user_id, "knowledge", key, value)
                return "Knowledge saved"

            def delete_knowledge_fields(keys: List[str], run_context: RunContext) -> str:
                """Delete specific knowledge fields."""
                for key in keys:
                    stage_update(run_context, user_id, "knowledge", key, None, "delete")
                return f"Deleted knowledge fields: {keys}"

            save_knowledge.__annotations__["updates"] = KnowledgeSchema
            tools.append(Function.from_callable(save_knowledge, strict=True))
            tools.append(Function.from_callable(delete_knowledge_fields, strict=True))

        if self.enable_feedback:
            FeedbackSchema = self.user_feedback_schema or UserFeedback

            def save_feedback(updates, run_context: RunContext) -> str:
                """Save response feedback (positive/negative lists)."""
                data = updates.model_dump(exclude_none=True)
                for item in data.get("positive", []):
                    stage_update(run_context, user_id, "feedback", "positive", item)
                for item in data.get("negative", []):
                    stage_update(run_context, user_id, "feedback", "negative", item)
                return "Feedback saved"

            def clear_feedback(clear_positive: bool, clear_negative: bool, run_context: RunContext) -> str:
                """Clear feedback lists."""
                if clear_positive:
                    stage_update(run_context, user_id, "feedback", "positive", None, "delete")
                if clear_negative:
                    stage_update(run_context, user_id, "feedback", "negative", None, "delete")
                return "Feedback cleared"

            save_feedback.__annotations__["updates"] = FeedbackSchema
            tools.append(Function.from_callable(save_feedback, strict=True))
            tools.append(Function.from_callable(clear_feedback, strict=True))

        return tools


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
