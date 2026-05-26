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

        return SessionMetrics(
            input_tokens=self.input_tokens + other_metrics.input_tokens,
            output_tokens=self.output_tokens + other_metrics.output_tokens,
            total_tokens=self.total_tokens + other_metrics.total_tokens,
            completion_tokens=self.completion_tokens + other_metrics.completion_tokens,
            prompt_tokens=self.prompt_tokens + other_metrics.prompt_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other_metrics.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other_metrics.cache_read_input_tokens,
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
