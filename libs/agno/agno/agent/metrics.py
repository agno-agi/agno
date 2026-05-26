from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SessionMetrics:
    """V1 compatibility stub for session metrics tracking"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def __add__(self, other):
        if other is None:
            return self
        if isinstance(other, dict):
            other_metrics = SessionMetrics(**other)
        else:
            other_metrics = other

        # Use getattr for V1/V2 compatibility - V2 MessageMetrics may not have all V1 attributes
        other_input = getattr(other_metrics, 'input_tokens', 0) or 0
        other_output = getattr(other_metrics, 'output_tokens', 0) or 0
        other_total = getattr(other_metrics, 'total_tokens', 0) or 0
        other_completion = getattr(other_metrics, 'completion_tokens', 0) or 0
        other_prompt = getattr(other_metrics, 'prompt_tokens', 0) or 0
        other_cache_creation = getattr(other_metrics, 'cache_creation_input_tokens', 0) or 0
        other_cache_read = getattr(other_metrics, 'cache_read_input_tokens', 0) or 0

        return SessionMetrics(
            input_tokens=self.input_tokens + other_input,
            output_tokens=self.output_tokens + other_output,
            total_tokens=self.total_tokens + other_total,
            completion_tokens=self.completion_tokens + other_completion,
            prompt_tokens=self.prompt_tokens + other_prompt,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other_cache_creation,
            cache_read_input_tokens=self.cache_read_input_tokens + other_cache_read,
        )

    def __iadd__(self, other):
        if other is None:
            return self
        result = self + other
        self.input_tokens = result.input_tokens
        self.output_tokens = result.output_tokens
        self.total_tokens = result.total_tokens
        self.completion_tokens = result.completion_tokens
        self.prompt_tokens = result.prompt_tokens
        self.cache_creation_input_tokens = result.cache_creation_input_tokens
        self.cache_read_input_tokens = result.cache_read_input_tokens
        return self
