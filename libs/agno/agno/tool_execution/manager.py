from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from agno.models.base import Model


@dataclass
class ToolExecutionManager:
    # Model used to generate code (defaults to agent.model if None)
    model: Optional[Model] = None
    # System prompt for the code-generation model
    code_generation_prompt: Optional[str] = None
    # Max retries when code execution fails
    max_retries: int = 3
    # Discovery mode: True/False/"auto" — "auto" enables at discovery_threshold
    discovery: Union[bool, str] = "auto"
    # Number of tools that triggers discovery mode in "auto"
    discovery_threshold: int = 15
    # Extra modules available in the sandbox (name → module object)
    additional_modules: Optional[Dict[str, Any]] = None
    # Max length of generated code (characters)
    max_code_length: int = 10_000
