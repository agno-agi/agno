"""Summarize strategy: Combine all memories into single comprehensive summary."""

from textwrap import dedent
from typing import List
from uuid import uuid4

from agno.db.schemas import UserMemory
from agno.memory.strategies import MemoryOptimizationStrategy
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.dttm import now_epoch_s
from agno.utils.log import log_debug


class SummarizeStrategy(MemoryOptimizationStrategy):
    """Combine all memories into single comprehensive summary.

    This strategy summarizes all memories into one coherent narrative,
    achieving maximum compression by eliminating redundancy. All
    metadata (topics, user_id) is preserved in the summarized memory.
    """

    def _get_system_prompt(self) -> str:
        """Get system prompt for memory summarization.

        Returns:
            System prompt string for LLM
        """
        return dedent("""\
            You are a memory compression assistant. Your task is to summarize multiple memories about a user
            into a single comprehensive summary while preserving all key facts.

            Requirements:
            - Combine related information from all memories
            - Preserve all factual information
            - Remove redundancy and consolidate repeated facts
            - Create a coherent narrative about the user
            - Maintain third-person perspective
            - Do not add information not present in the original memories

            Return only the summarized memory text, nothing else.\
        """)

    def optimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Summarize multiple memories into single comprehensive summary.

        Args:
            memories: List of UserMemory objects to summarize
            model: Model to use for summarization

        Returns:
            List containing single summarized UserMemory object

        Raises:
            ValueError: If memories list is empty or if user_id cannot be determined
        """
        # Validate memories list
        if not memories:
            raise ValueError("No Memories found")

        # Extract user_id from first memory
        user_id = memories[0].user_id
        if user_id is None:
            raise ValueError("Cannot determine user_id: first memory does not have a valid user_id or is None")

        # Collect all memory contents
        memory_contents = [mem.memory for mem in memories if mem.memory]

        # Combine topics - get unique topics from all memories
        all_topics: List[str] = []
        for mem in memories:
            if mem.topics:
                all_topics.extend(mem.topics)
        summarized_topics = list(set(all_topics)) if all_topics else None

        # Check if agent_id and team_id are consistent
        agent_ids = {mem.agent_id for mem in memories if mem.agent_id}
        summarized_agent_id = list(agent_ids)[0] if len(agent_ids) == 1 else None

        team_ids = {mem.team_id for mem in memories if mem.team_id}
        summarized_team_id = list(team_ids)[0] if len(team_ids) == 1 else None

        # Create comprehensive prompt for summarization
        combined_content = "\n\n".join([f"Memory {i + 1}: {content}" for i, content in enumerate(memory_contents)])

        system_prompt = self._get_system_prompt()

        messages_for_model = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Summarize these memories into a single summary:\n\n{combined_content}"),
        ]

        # Generate summarized content
        response = model.response(messages=messages_for_model)
        summarized_content = response.content or " ".join(memory_contents)

        # Generate new memory_id
        new_memory_id = str(uuid4())

        # Create summarized memory
        summarized_memory = UserMemory(
            memory_id=new_memory_id,
            memory=summarized_content.strip(),
            topics=summarized_topics,
            user_id=user_id,
            agent_id=summarized_agent_id,
            team_id=summarized_team_id,
            updated_at=now_epoch_s(),
        )

        log_debug(
            f"Summarized {len(memories)} memories into 1: {self.count_tokens(memories)} -> {self.count_tokens([summarized_memory])} tokens"
        )

        return [summarized_memory]

    async def aoptimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Async version: Summarize multiple memories into single comprehensive summary.

        Args:
            memories: List of UserMemory objects to summarize
            model: Model to use for summarization

        Returns:
            List containing single summarized UserMemory object

        Raises:
            ValueError: If memories list is empty or if user_id cannot be determined
        """
        # Validate memories list
        if not memories:
            raise ValueError("No Memories found")

        # Extract user_id from first memory
        user_id = memories[0].user_id
        if user_id is None:
            raise ValueError("Cannot determine user_id: first memory does not have a valid user_id or is None")

        # Collect all memory contents
        memory_contents = [mem.memory for mem in memories if mem.memory]

        # Combine topics - get unique topics from all memories
        all_topics: List[str] = []
        for mem in memories:
            if mem.topics:
                all_topics.extend(mem.topics)
        summarized_topics = list(set(all_topics)) if all_topics else None

        # Check if agent_id and team_id are consistent
        agent_ids = {mem.agent_id for mem in memories if mem.agent_id}
        summarized_agent_id = list(agent_ids)[0] if len(agent_ids) == 1 else None

        team_ids = {mem.team_id for mem in memories if mem.team_id}
        summarized_team_id = list(team_ids)[0] if len(team_ids) == 1 else None

        # Create comprehensive prompt for summarization
        combined_content = "\n\n".join([f"Memory {i + 1}: {content}" for i, content in enumerate(memory_contents)])

        system_prompt = self._get_system_prompt()

        messages_for_model = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Summarize these memories into a single summary:\n\n{combined_content}"),
        ]

        # Generate summarized content (async)
        response = await model.aresponse(messages=messages_for_model)
        summarized_content = response.content or " ".join(memory_contents)

        # Generate new memory_id
        new_memory_id = str(uuid4())

        # Create summarized memory
        summarized_memory = UserMemory(
            memory_id=new_memory_id,
            memory=summarized_content.strip(),
            topics=summarized_topics,
            user_id=user_id,
            agent_id=summarized_agent_id,
            team_id=summarized_team_id,
            updated_at=now_epoch_s(),
        )

        log_debug(
            f"Summarized {len(memories)} memories into 1: {self.count_tokens(memories)} -> {self.count_tokens([summarized_memory])} tokens"
        )

        return [summarized_memory]
