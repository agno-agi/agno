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
    # Model used for creating memories
    model: Optional[Model] = None
    # The database to store memories
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    # what to capture
    user_memory_capture_instructions: Optional[str] = None
    # Layer toggles
    enable_user_memories: bool = True
    # user identity (name, company, role)
    enable_user_profile: bool = True
    # user facts (languages, hobbies)
    enable_user_knowledge: bool = True
    enable_user_policies: bool = True
    enable_user_feedback: bool = True

    # Schema overrides
    use_default_schemas: bool = False
    user_profile_schema: Optional[Type[BaseModel]] = None
    user_policies_schema: Optional[Type[BaseModel]] = None
    user_knowledge_schema: Optional[Type[BaseModel]] = None
    user_feedback_schema: Optional[Type[BaseModel]] = None

    # Enforce strict schema validation (set False for complex schemas)
    strict_schema_validation: bool = True

    # Per-layer custom instructions
    user_profile_instructions: Optional[str] = None
    user_knowledge_instructions: Optional[str] = None
    user_policies_instructions: Optional[str] = None
    user_feedback_instructions: Optional[str] = None

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        # ----- Global user memory ---------
        user_memory_capture_instructions: Optional[str] = None,
        enable_user_memories: bool = True,
        use_default_schemas: bool = False,
        # ----- User profile ---------
        enable_user_profile: bool = True,
        user_profile_instructions: Optional[str] = None,
        user_profile_schema: Optional[Type[BaseModel]] = None,
        # ----- User knowledge ---------
        enable_user_knowledge: bool = True,
        user_knowledge_instructions: Optional[str] = None,
        user_knowledge_schema: Optional[Type[BaseModel]] = None,
        # ----- User policies ---------
        enable_user_policies: bool = True,
        user_policies_instructions: Optional[str] = None,
        user_policies_schema: Optional[Type[BaseModel]] = None,
        # ----- User feedback ---------
        enable_user_feedback: bool = True,
        user_feedback_instructions: Optional[str] = None,
        user_feedback_schema: Optional[Type[BaseModel]] = None,
        # ----- Schema validation ---------
        strict_schema_validation: bool = True,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.user_memory_capture_instructions = user_memory_capture_instructions
        self.enable_user_memories = enable_user_memories
        self.enable_user_profile = enable_user_profile
        self.enable_user_knowledge = enable_user_knowledge
        self.enable_user_policies = enable_user_policies
        self.enable_user_feedback = enable_user_feedback
        self.use_default_schemas = use_default_schemas
        self.user_profile_schema = user_profile_schema
        self.user_policies_schema = user_policies_schema
        self.user_knowledge_schema = user_knowledge_schema
        self.user_feedback_schema = user_feedback_schema
        self.user_profile_instructions = user_profile_instructions
        self.user_knowledge_instructions = user_knowledge_instructions
        self.user_policies_instructions = user_policies_instructions
        self.user_feedback_instructions = user_feedback_instructions
        self.strict_schema_validation = strict_schema_validation

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

    def create_user_memory_v2(self, message: str, user_id: Optional[str] = None) -> str:
        """Extract memory from user message."""
        if not self.db:
            log_warning("No DB configured")
            return "Database not configured"
        if not self.model:
            log_warning("Memory Compiler Model not configured")
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
            tools=cast(list, tools),
        )

        # Save if any tools were executed
        if response.tool_executions:
            memory.bump_updated_at()
            self.save_user_memory_v2(memory)

        return response.content or "No response"

    def _compile_tools(self, memory: UserMemoryV2) -> List[Function]:
        """Get key-value based extraction tools."""
        if not self.enable_user_memories:
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
            memory.layers.setdefault("feedback", {})[key] = value
            return f"Saved feedback: {key}"

        def delete_user_feedback(key: str) -> str:
            memory.layers.get("feedback", {}).pop(key, None)
            return f"Deleted feedback: {key}"

        tools: List[Any] = []
        if self.enable_user_profile:
            tools.extend([save_user_profile, delete_user_profile])
        if self.enable_user_knowledge:
            tools.extend([save_user_knowledge, delete_user_knowledge])
        if self.enable_user_policies:
            tools.extend([save_user_policy, delete_user_policy])
        if self.enable_user_feedback:
            tools.extend([save_user_feedback, delete_user_feedback])

        return [Function.from_callable(t, strict=self.strict_schema_validation) for t in tools]

    def _compile_schema_tools(self, memory: UserMemoryV2) -> List[Function]:
        """Get schema-based extraction tools."""
        if not self.enable_user_memories:
            return []

        from agno.memory_v2.schemas import UserFeedback, UserKnowledge, UserPolicies, UserProfile

        tools: List[Any] = []

        if self.enable_user_profile:
            ProfileSchema = self.user_profile_schema or UserProfile

            def save_profile(updates: ProfileSchema) -> str:  # type: ignore
                """Save user profile (name, company, role, skills, etc.)."""
                for key, value in updates.model_dump(exclude_none=True).items():  # type: ignore[attr-defined]
                    memory.profile[key] = value
                return "Profile saved"

            def delete_profile_fields(keys: List[str]) -> str:
                """Delete specific profile fields."""
                for key in keys:
                    memory.profile.pop(key, None)
                return f"Deleted profile fields: {keys}"

            tools.extend([save_profile, delete_profile_fields])

        if self.enable_user_policies:
            PoliciesSchema = self.user_policies_schema or UserPolicies

            def save_policies(updates: PoliciesSchema) -> str:  # type: ignore
                """Save user preferences (response_style, tone, formatting)."""
                policies = memory.layers.setdefault("policies", {})
                for key, value in updates.model_dump(exclude_none=True).items():  # type: ignore[attr-defined]
                    policies[key] = value
                return "Policies saved"

            def delete_policy_fields(keys: List[str]) -> str:
                """Delete specific policy fields."""
                policies = memory.layers.get("policies", {})
                for key in keys:
                    policies.pop(key, None)
                return f"Deleted policy fields: {keys}"

            tools.extend([save_policies, delete_policy_fields])

        if self.enable_user_knowledge:
            KnowledgeSchema = self.user_knowledge_schema or UserKnowledge

            def save_knowledge(updates: KnowledgeSchema) -> str:  # type: ignore
                """Save user context (current_project, tech_stack, interests)."""
                knowledge = memory.layers.setdefault("knowledge", {})
                for key, value in updates.model_dump(exclude_none=True).items():  # type: ignore[attr-defined]
                    knowledge[key] = value
                return "Knowledge saved"

            def delete_knowledge_fields(keys: List[str]) -> str:
                """Delete specific knowledge fields."""
                knowledge = memory.layers.get("knowledge", {})
                for key in keys:
                    knowledge.pop(key, None)
                return f"Deleted knowledge fields: {keys}"

            tools.extend([save_knowledge, delete_knowledge_fields])

        if self.enable_user_feedback:
            FeedbackSchema = self.user_feedback_schema or UserFeedback

            def save_feedback(updates: FeedbackSchema) -> str:  # type: ignore
                """Save user feedback (preferences, opinions, suggestions)."""
                feedback = memory.layers.setdefault("feedback", {})
                for key, value in updates.model_dump(exclude_none=True).items():  # type: ignore[attr-defined]
                    feedback[key] = value
                return "Feedback saved"

            def delete_feedback_fields(keys: List[str]) -> str:
                """Delete specific feedback fields."""
                feedback = memory.layers.get("feedback", {})
                for key in keys:
                    feedback.pop(key, None)
                return f"Deleted feedback fields: {keys}"

            tools.extend([save_feedback, delete_feedback_fields])

        return [Function.from_callable(t, strict=self.strict_schema_validation) for t in tools]

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
            tools=cast(list, tools),
        )

        # Save if any tools were executed
        if response.tool_executions:
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

    def _build_user_system_message(self, existing: Optional[UserMemoryV2] = None) -> Message:
        """Build system prompt for LLM extraction."""
        # Default layer instructions
        default_profile = dedent("""\
            Capture stable identity information about the user:
            - Personal identity: name, preferred name, age, location, timezone
            - Professional identity: role, title, company, team, department
            - Experience: years of experience, seniority level, career background
            - Only save facts unlikely to change frequently""")

        default_knowledge = dedent("""\
            Capture the user's skills, expertise, and current context:
            - Technical skills: programming languages, frameworks, libraries, tools
            - Domain expertise: areas of specialization, industries worked in
            - Current work: active projects, tech stack in use, challenges faced
            - Interests: topics learning, technologies exploring""")

        default_policies = dedent("""\
            Capture explicit preferences for response formatting:
            - Communication style: concise vs detailed, formal vs casual
            - Formatting: markdown, code blocks, bullet points, examples
            - Code preferences: comments, type hints, error handling style
            - Only save when user explicitly requests a preference""")

        default_feedback = dedent("""\
            Capture any feedback the user provides:
            - Preferences, opinions, or sentiments
            - Things they like or dislike
            - Suggestions or requests""")

        # Build layer info from enabled layers
        layers = []
        tool_names = []
        if self.enable_user_profile:
            desc = self.user_profile_instructions or default_profile
            layers.append(("Profile", desc))
            tool_names.append("profile")
        if self.enable_user_knowledge:
            desc = self.user_knowledge_instructions or default_knowledge
            layers.append(("Knowledge", desc))
            tool_names.append("knowledge")
        if self.enable_user_policies:
            desc = self.user_policies_instructions or default_policies
            layers.append(("Policy", desc))
            tool_names.append("policy")
        if self.enable_user_feedback:
            desc = self.user_feedback_instructions or default_feedback
            layers.append(("Feedback", desc))
            tool_names.append("feedback")

        # Build layer descriptions
        layer_sections = []
        for name, desc in layers:
            layer_sections.append(f"{name}:\n{desc}")
        layer_descriptions = "\n\n".join(layer_sections)

        # Build tool names
        save_tools = [f"save_user_{name}" for name in tool_names]
        delete_tools = [f"delete_user_{name}" for name in tool_names]

        custom_instructions = ""
        if self.user_memory_capture_instructions:
            custom_instructions = f"\nAdditional guidance:\n{self.user_memory_capture_instructions}\n"

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

        if self.enable_user_profile:

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

        if self.enable_user_knowledge:

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

        if self.enable_user_policies:

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

        if self.enable_user_feedback:

            def save_user_feedback(key: str, value: Any, run_context: RunContext) -> str:
                """Save user feedback (preferences, opinions, suggestions)."""
                stage_update(run_context, user_id, "feedback", key, value)
                return f"Saved feedback: {key}"

            def delete_user_feedback(key: str, run_context: RunContext) -> str:
                """Delete a feedback field."""
                stage_update(run_context, user_id, "feedback", key, None, "delete")
                return f"Deleted feedback: {key}"

            tools.append(Function.from_callable(save_user_feedback))
            tools.append(Function.from_callable(delete_user_feedback))

        return tools

    def _agentic_schema_tools(self, user_id: str) -> List[Function]:
        """Get schema-based tools that stage updates for batch commit."""

        tools: List[Function] = []

        if self.enable_user_profile:
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
            tools.append(Function.from_callable(save_profile, strict=self.strict_schema_validation))
            tools.append(Function.from_callable(delete_profile_fields, strict=self.strict_schema_validation))

        if self.enable_user_policies:
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
            tools.append(Function.from_callable(save_policies, strict=self.strict_schema_validation))
            tools.append(Function.from_callable(delete_policy_fields, strict=self.strict_schema_validation))

        if self.enable_user_knowledge:
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
            tools.append(Function.from_callable(save_knowledge, strict=self.strict_schema_validation))
            tools.append(Function.from_callable(delete_knowledge_fields, strict=self.strict_schema_validation))

        if self.enable_user_feedback:
            FeedbackSchema = self.user_feedback_schema or UserFeedback

            def save_feedback(updates, run_context: RunContext) -> str:
                """Save user feedback (preferences, opinions, suggestions)."""
                for key, value in updates.model_dump(exclude_none=True).items():
                    stage_update(run_context, user_id, "feedback", key, value)
                return "Feedback saved"

            def delete_feedback_fields(keys: List[str], run_context: RunContext) -> str:
                """Delete specific feedback fields."""
                for key in keys:
                    stage_update(run_context, user_id, "feedback", key, None, "delete")
                return f"Deleted feedback fields: {keys}"

            save_feedback.__annotations__["updates"] = FeedbackSchema
            tools.append(Function.from_callable(save_feedback, strict=self.strict_schema_validation))
            tools.append(Function.from_callable(delete_feedback_fields, strict=self.strict_schema_validation))

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

    if action == "delete":
        # Track deletion in separate dict
        deletes = pending.setdefault("_deletes", {})
        delete_keys = deletes.setdefault(layer, [])
        if key not in delete_keys:
            delete_keys.append(key)
    else:
        # All layers (profile, knowledge, policies, feedback): set value in layer dict
        layer_dict = pending.setdefault(layer, {})
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
    # First: Apply additions
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

    if pending.get("feedback"):
        if not isinstance(memory.layers.get("feedback"), dict):
            memory.layers["feedback"] = {}
        for key, value in pending["feedback"].items():
            memory.layers["feedback"][key] = value

    # Last: Apply deletions (delete wins over add in same run)
    for layer, keys in pending.get("_deletes", {}).items():
        if layer == "profile":
            for key in keys:
                memory.profile.pop(key, None)
        elif layer in ("policies", "knowledge", "feedback"):
            if isinstance(memory.layers.get(layer), dict):
                for key in keys:
                    memory.layers[layer].pop(key, None)
