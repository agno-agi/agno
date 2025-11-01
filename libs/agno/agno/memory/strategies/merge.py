"""Merge strategy: Combine all memories into single comprehensive summary."""

from datetime import datetime
from textwrap import dedent
from typing import List, Optional
from uuid import uuid4

from agno.db.schemas import UserMemory
from agno.memory.strategy import MemoryOptimizationStrategy
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug


class MergeStrategy(MemoryOptimizationStrategy):
    """Combine all memories into single comprehensive summary.

    This strategy merges all memories into one coherent narrative,
    achieving maximum compression by eliminating redundancy. All
    metadata (topics, user_id) is preserved in the merged memory.
    """

    def get_system_prompt(self, **kwargs) -> str:
        """Get system prompt for memory merging.

        Args:
            **kwargs: Must include 'token_limit' for the target token count

        Returns:
            System prompt string for LLM
        """
        token_limit = kwargs.get("token_limit", 100)
        return dedent(f"""\
            You are a memory compression assistant. Your task is to merge multiple memories about a user
            into a single comprehensive summary while preserving all key facts.

            Requirements:
            - Combine related information from all memories
            - Preserve all factual information
            - Remove redundancy and consolidate repeated facts
            - Create a coherent narrative about the user
            - Target approximately {token_limit} tokens
            - Maintain third-person perspective
            - Do not add information not present in the original memories

            Return only the merged memory text, nothing else.\
        """)

    def optimize(
        self,
        memories: List[UserMemory],
        token_limit: int,
        model: Model,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Merge multiple memories into single comprehensive summary.

        Args:
            memories: List of UserMemory objects to merge
            token_limit: Target token limit for merged memory
            model: Model to use for summarization
            user_id: User ID for the merged memory

        Returns:
            List containing single merged UserMemory object
        """
        # Collect all memory contents
        memory_contents = [mem.memory for mem in memories if mem.memory]

        # Merge topics - get unique topics from all memories
        all_topics: List[str] = []
        for mem in memories:
            if mem.topics:
                all_topics.extend(mem.topics)
        merged_topics = list(set(all_topics)) if all_topics else None

        # Concatenate input and feedback fields
        input_parts = [mem.input for mem in memories if mem.input]
        merged_input = "\n---\n".join(input_parts) if input_parts else None

        feedback_parts = [mem.feedback for mem in memories if mem.feedback]
        merged_feedback = "\n---\n".join(feedback_parts) if feedback_parts else None

        # Check if agent_id and team_id are consistent
        agent_ids = {mem.agent_id for mem in memories if mem.agent_id}
        merged_agent_id = list(agent_ids)[0] if len(agent_ids) == 1 else None

        team_ids = {mem.team_id for mem in memories if mem.team_id}
        merged_team_id = list(team_ids)[0] if len(team_ids) == 1 else None

        # Create comprehensive prompt for merging
        combined_content = "\n\n".join([f"Memory {i + 1}: {content}" for i, content in enumerate(memory_contents)])

        system_prompt = self.get_system_prompt(token_limit=token_limit)

        messages_for_model = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Merge these memories into a single summary:\n\n{combined_content}"),
        ]

        # Generate merged summary
        response = model.response(messages=messages_for_model)
        merged_content = response.content or " ".join(memory_contents)

        # Generate new memory_id
        new_memory_id = str(uuid4())

        # Create merged memory
        merged_memory = UserMemory(
            memory_id=new_memory_id,
            memory=merged_content.strip(),
            topics=merged_topics,
            user_id=user_id or (memories[0].user_id if memories else None),
            agent_id=merged_agent_id,
            team_id=merged_team_id,
            input=merged_input,
            updated_at=datetime.now(),
            feedback=merged_feedback,
        )

        log_debug(
            f"Merged {len(memories)} memories into 1: {self.count_tokens(memories)} -> {self.count_tokens([merged_memory])} tokens"
        )

        return [merged_memory]

    async def aoptimize(
        self,
        memories: List[UserMemory],
        token_limit: int,
        model: Model,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Async version: Merge multiple memories into single comprehensive summary.

        Args:
            memories: List of UserMemory objects to merge
            token_limit: Target token limit for merged memory
            model: Model to use for summarization
            user_id: User ID for the merged memory

        Returns:
            List containing single merged UserMemory object
        """
        # Collect all memory contents
        memory_contents = [mem.memory for mem in memories if mem.memory]

        # Merge topics - get unique topics from all memories
        all_topics: List[str] = []
        for mem in memories:
            if mem.topics:
                all_topics.extend(mem.topics)
        merged_topics = list(set(all_topics)) if all_topics else None

        # Concatenate input and feedback fields
        input_parts = [mem.input for mem in memories if mem.input]
        merged_input = "\n---\n".join(input_parts) if input_parts else None

        feedback_parts = [mem.feedback for mem in memories if mem.feedback]
        merged_feedback = "\n---\n".join(feedback_parts) if feedback_parts else None

        # Check if agent_id and team_id are consistent
        agent_ids = {mem.agent_id for mem in memories if mem.agent_id}
        merged_agent_id = list(agent_ids)[0] if len(agent_ids) == 1 else None

        team_ids = {mem.team_id for mem in memories if mem.team_id}
        merged_team_id = list(team_ids)[0] if len(team_ids) == 1 else None

        # Create comprehensive prompt for merging
        combined_content = "\n\n".join([f"Memory {i + 1}: {content}" for i, content in enumerate(memory_contents)])

        system_prompt = self.get_system_prompt(token_limit=token_limit)

        messages_for_model = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Merge these memories into a single summary:\n\n{combined_content}"),
        ]

        # Generate merged summary (async)
        response = await model.aresponse(messages=messages_for_model)
        merged_content = response.content or " ".join(memory_contents)

        # Generate new memory_id
        new_memory_id = str(uuid4())

        # Create merged memory
        merged_memory = UserMemory(
            memory_id=new_memory_id,
            memory=merged_content.strip(),
            topics=merged_topics,
            user_id=user_id or (memories[0].user_id if memories else None),
            agent_id=merged_agent_id,
            team_id=merged_team_id,
            input=merged_input,
            updated_at=datetime.now(),
            feedback=merged_feedback,
        )

        log_debug(
            f"Merged {len(memories)} memories into 1: {self.count_tokens(memories)} -> {self.count_tokens([merged_memory])} tokens"
        )

        return [merged_memory]
