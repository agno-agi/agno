"""Summarize strategy: Optimize each memory individually while preserving structure."""

from datetime import datetime
from textwrap import dedent
from typing import List, Optional

from agno.db.schemas import UserMemory
from agno.memory.strategy import MemoryOptimizationStrategy
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug


class SummarizeStrategy(MemoryOptimizationStrategy):
    """Optimize each memory individually while preserving structure.

    This strategy compresses each memory separately, maintaining the
    individual memory structure and metadata. Good for preserving
    granular context while reducing token usage.
    """

    def get_system_prompt(self, **kwargs) -> str:
        """Get system prompt for individual memory summarization.

        Args:
            **kwargs: Must include 'target_tokens' for the target token count

        Returns:
            System prompt string for LLM
        """
        target_tokens = kwargs.get("target_tokens", 100)
        return dedent(f"""\
            You are a memory compression assistant. Your task is to summarize the given memory
            while preserving all key facts and information.

            Requirements:
            - Preserve all factual information
            - Remove redundancy and unnecessary details
            - Keep the summary concise but accurate
            - Target approximately {target_tokens} tokens
            - Maintain third-person perspective
            - Do not add information not present in the original

            Return only the summarized memory text, nothing else.\
        """)

    def optimize(
        self,
        memories: List[UserMemory],
        token_limit: int,
        model: Model,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Optimize each memory individually using LLM summarization.

        Args:
            memories: List of UserMemory objects to optimize
            token_limit: Target token limit for all memories combined
            model: Model to use for summarization
            user_id: Optional user ID (not used by this strategy)

        Returns:
            List of optimized UserMemory objects with preserved metadata
        """
        current_tokens = self.count_tokens(memories)

        # Calculate compression ratio needed
        compression_ratio = token_limit / current_tokens if current_tokens > 0 else 1.0

        log_debug(f"Applying compression ratio: {compression_ratio:.2f}")

        optimized_memories = []

        for memory in memories:
            if not memory.memory:
                optimized_memories.append(memory)
                continue

            # Calculate target length for this memory
            memory_tokens = self.count_tokens([memory])
            target_tokens = int(memory_tokens * compression_ratio)

            # Create summarization prompt
            system_prompt = self.get_system_prompt(target_tokens=target_tokens)

            messages_for_model = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=f"Summarize this memory:\n\n{memory.memory}"),
            ]

            # Generate summarized version
            response = model.response(messages=messages_for_model)
            summarized_content = response.content or memory.memory

            # Create optimized memory with preserved metadata
            optimized_memory = UserMemory(
                memory_id=memory.memory_id,
                memory=summarized_content.strip(),
                topics=memory.topics,
                user_id=memory.user_id,
                agent_id=memory.agent_id,
                team_id=memory.team_id,
                input=memory.input,
                updated_at=datetime.now(),
                feedback=memory.feedback,
            )

            optimized_memories.append(optimized_memory)

            log_debug(
                f"Optimized memory {memory.memory_id}: {memory_tokens} -> {self.count_tokens([optimized_memory])} tokens"
            )

        return optimized_memories

    async def aoptimize(
        self,
        memories: List[UserMemory],
        token_limit: int,
        model: Model,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Async version of optimize.

        Args:
            memories: List of UserMemory objects to optimize
            token_limit: Target token limit for all memories combined
            model: Model to use for summarization
            user_id: Optional user ID (not used by this strategy)

        Returns:
            List of optimized UserMemory objects with preserved metadata
        """
        current_tokens = self.count_tokens(memories)

        # Calculate compression ratio needed
        compression_ratio = token_limit / current_tokens if current_tokens > 0 else 1.0

        log_debug(f"Applying compression ratio: {compression_ratio:.2f}")

        optimized_memories = []

        for memory in memories:
            if not memory.memory:
                optimized_memories.append(memory)
                continue

            # Calculate target length for this memory
            memory_tokens = self.count_tokens([memory])
            target_tokens = int(memory_tokens * compression_ratio)

            # Create summarization prompt
            system_prompt = self.get_system_prompt(target_tokens=target_tokens)

            messages_for_model = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=f"Summarize this memory:\n\n{memory.memory}"),
            ]

            # Generate summarized version (async)
            response = await model.aresponse(messages=messages_for_model)
            summarized_content = response.content or memory.memory

            # Create optimized memory with preserved metadata
            optimized_memory = UserMemory(
                memory_id=memory.memory_id,
                memory=summarized_content.strip(),
                topics=memory.topics,
                user_id=memory.user_id,
                agent_id=memory.agent_id,
                team_id=memory.team_id,
                input=memory.input,
                updated_at=datetime.now(),
                feedback=memory.feedback,
            )

            optimized_memories.append(optimized_memory)

            log_debug(
                f"Optimized memory {memory.memory_id}: {memory_tokens} -> {self.count_tokens([optimized_memory])} tokens"
            )

        return optimized_memories
