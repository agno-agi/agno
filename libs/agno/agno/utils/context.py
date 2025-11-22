"""
Context building utilities for managing token budgets.

This module provides tools for automatically trimming message history
to fit within model context windows, preventing context overflow errors.
"""

from typing import List, Optional, Literal
from agno.models.message import Message
from agno.models.base import Model
from agno.utils.log import log_info, log_debug, log_warning


class ContextBuilder:
    """
    Build optimized context that fits within token limits.
    
    Supports multiple trimming strategies:
    - truncate_old: Remove oldest messages first (keep system + recent)
    - truncate_middle: Keep first (system) and last N, remove middle
    - summarize: Summarize removed content (requires compression model)
    """
    
    def build_context(
        self,
        messages: List[Message],
        model: Model,
        max_tokens: Optional[int] = None,
        reserve_for_output: int = 1000,
        strategy: Literal["truncate_old", "truncate_middle", "summarize"] = "truncate_old",
    ) -> List[Message]:
        """
        Build context that fits within token budget.
        
        Args:
            messages: Original message list
            model: Model instance (for token counting and context limit)
            max_tokens: Maximum tokens allowed (uses model's limit if None)
            reserve_for_output: Tokens to reserve for model output
            strategy: Trimming strategy to use
        
        Returns:
            Trimmed message list that fits within token budget
        
        Examples:
            >>> builder = ContextBuilder()
            >>> trimmed = builder.build_context(messages, model, strategy="truncate_old")
        """
        if not messages:
            return messages
        
        # Determine max tokens
        if max_tokens is None:
            max_tokens = model.get_context_limit()
        
        if max_tokens is None:
            log_debug("No context limit known for model, skipping trimming")
            return messages  # No limit known, return as-is
        
        # Calculate target tokens (reserve space for output)
        target_tokens = max_tokens - reserve_for_output
        
        # Count current tokens
        current_tokens = model.count_tokens(messages)
        
        log_debug(f"Context: {current_tokens} tokens (limit: {max_tokens}, target: {target_tokens})")
        
        # Check if trimming is needed
        if current_tokens <= target_tokens:
            log_debug("Messages fit within context, no trimming needed")
            return messages
        
        # Apply trimming strategy
        log_info(f"Context overflow: {current_tokens} > {target_tokens}. Trimming with strategy: {strategy}")
        
        if strategy == "truncate_old":
            return self._truncate_old(messages, model, target_tokens)
        elif strategy == "truncate_middle":
            return self._truncate_middle(messages, model, target_tokens)
        elif strategy == "summarize":
            return self._summarize_removed(messages, model, target_tokens)
        else:
            log_warning(f"Unknown strategy: {strategy}. Using truncate_old.")
            return self._truncate_old(messages, model, target_tokens)
    
    def _truncate_old(
        self,
        messages: List[Message],
        model: Model,
        target_tokens: int,
    ) -> List[Message]:
        """
        Remove oldest messages first, keeping system message and recent messages.
        
        Strategy:
        1. Always keep system message (if present)
        2. Add messages from the end (most recent) until we hit target
        3. Ensures latest context is preserved
        """
        if not messages:
            return messages
        
        # Separate system message (first message if role is "system")
        system_msg = None
        start_idx = 0
        
        if messages[0].role == "system":
            system_msg = messages[0]
            start_idx = 1
        
        # Build result by adding messages from the end
        result = []
        if system_msg:
            result.append(system_msg)
        
        # Add messages from most recent, checking token budget
        for msg in reversed(messages[start_idx:]):
            test_messages = [result[0]] + [msg] + result[1:] if system_msg else [msg] + result
            
            if model.count_tokens(test_messages) <= target_tokens:
                if system_msg:
                    result.insert(1, msg)  # Insert after system message
                else:
                    result.insert(0, msg)  # Insert at beginning
            else:
                # Would exceed budget, stop adding
                break
        
        # Reverse to maintain chronological order (except system message)
        if system_msg and len(result) > 1:
            result = [result[0]] + list(reversed(result[1:]))
        elif not system_msg:
            result = list(reversed(result))
        
        removed_count = len(messages) - len(result)
        log_info(f"Truncated {removed_count} old messages. Kept {len(result)} messages.")
        
        return result
    
    def _truncate_middle(
        self,
        messages: List[Message],
        model: Model,
        target_tokens: int,
    ) -> List[Message]:
        """
        Keep first (system) and last N messages, remove middle.
        
        Strategy:
        1. Always keep system message
        2. Always keep last few messages (recent context)
        3. Remove middle messages if needed
        """
        if not messages:
            return messages
        
        # Keep system message
        system_msg = None
        start_idx = 0
        
        if messages[0].role == "system":
            system_msg = messages[0]
            start_idx = 1
        
        # Start with system message
        result = [system_msg] if system_msg else []
        
        # Try to keep as many recent messages as possible
        for i in range(len(messages) - 1, start_idx - 1, -1):
            test_messages = result + [messages[i]]
            
            if model.count_tokens(test_messages) <= target_tokens:
                result.append(messages[i])
            else:
                break
        
        # Reverse recent messages to maintain order
        if system_msg:
            result = [result[0]] + list(reversed(result[1:]))
        else:
            result = list(reversed(result))
        
        removed_count = len(messages) - len(result)
        log_info(f"Truncated {removed_count} middle messages. Kept {len(result)} messages.")
        
        return result
    
    def _summarize_removed(
        self,
        messages: List[Message],
        model: Model,
        target_tokens: int,
    ) -> List[Message]:
        """
        Summarize removed messages instead of just dropping them.
        
        Note: This requires a compression model and is more expensive.
        Falls back to truncate_old if summarization fails.
        """
        log_warning("Summarize strategy not yet implemented. Falling back to truncate_old.")
        return self._truncate_old(messages, model, target_tokens)

