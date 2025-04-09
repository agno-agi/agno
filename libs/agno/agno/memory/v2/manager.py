from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

from pydantic import BaseModel, Field

from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.prompts import get_json_output_prompt
from agno.utils.string import parse_response_model_str


class MemoryUpdate(BaseModel):
    """Model for updates to the user's memory."""

    memory: str = Field(
        ...,
        description="The user memory to be stored or updated.",
    )
    topics: Optional[List[str]] = Field(None, description="The topics of the memory.")
    id: Optional[str] = Field(
        None, description="The id of the memory to update. ONLY use if you want to update an existing memory."
    )


class MemoryUpdatesResponse(BaseModel):
    """Model for updates to the user's memory."""

    updates: List[MemoryUpdate] = Field(
        ...,
        description="The updates to the user's memory.",
    )


@dataclass
class MemoryManager:
    """Model for Memory Manager"""

    model: Optional[Model] = None
    use_json_mode: Optional[bool] = None

    # Provide the system prompt for the manager as a string
    system_prompt: Optional[str] = None

    def update_model(self) -> None:
        self.model = cast(Model, self.model)
        if self.use_json_mode is not None and self.use_json_mode is True:
            self.model.response_format = {"type": "json_object"}

        elif self.model.supports_native_structured_outputs:
            self.model.response_format = MemoryUpdatesResponse
            self.model.structured_outputs = True

        elif self.model.supports_json_schema_outputs:
            self.model.response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": MemoryUpdatesResponse.__name__,
                    "schema": MemoryUpdatesResponse.model_json_schema(),
                },
            }
        else:
            self.model.response_format = {"type": "json_object"}

    def get_system_message(
        self, messages: List[Message], existing_memories: Optional[List[Dict[str, Any]]] = None
    ) -> Message:
        if self.system_prompt is not None:
            return Message(role="system", content=self.system_prompt)
        self.model = cast(Model, self.model)

        # -*- Return a system message for the memory manager
        system_prompt_lines = [
            "Your task is to generate concise memories for the user's messages. "
            "You can also decide that no new memories are needed."
            "If you do create new memories, create one or more memories that captures the key information provided by the user, as if you were storing it for future reference. "
            "Each memory should be a brief, third-person statement that encapsulates the most important aspect of the user's input, without adding any extraneous information. "
            "Memories should include details that could personalize ongoing interactions with the user, such as:\n"
            "  - Personal facts: name, age, occupation, location, interests, preferences, etc.\n"
            "  - Significant life events or experiences shared by the user\n"
            "  - Important context about the user's current situation, challenges or goals\n"
            "  - What the user likes or dislikes, their opinions, beliefs, values, etc.\n"
            "  - Any other details that provide valuable insights into the user's personality, perspective or needs",
            "You will also be provided with a list of existing memories. You may:",
            "  1. Decide to make no changes to the existing memories.",
            "  2. Decide to add new memories.",
            "  3. Decide to update existing memories.",
        ]
        system_prompt_lines.append("<user_messages>")
        user_messages = []
        for message in messages:
            if message.role == "user":
                user_messages.append(message.get_content_string())
        system_prompt_lines.append("\n".join(user_messages))
        system_prompt_lines.append("</user_messages>")

        if existing_memories and len(existing_memories) > 0:
            system_prompt_lines.append("<existing_memories>")
            for existing_memory in existing_memories:
                system_prompt_lines.append(f"ID: {existing_memory['memory_id']}")
                system_prompt_lines.append(f"Memory: {existing_memory['memory']}")
                system_prompt_lines.append("\n")
            system_prompt_lines.append("</existing_memories>")

        if self.model.response_format == {"type": "json_object"}:
            system_prompt_lines.append(get_json_output_prompt(MemoryUpdatesResponse))  # type: ignore

        return Message(role="system", content="\n".join(system_prompt_lines))

    def run(
        self,
        messages: List[Message],
        existing_memories: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[MemoryUpdatesResponse]:
        if self.model is None:
            log_error("No model provided for memory manager")
            return None

        log_debug("MemoryManager Start", center=True)

        # Update the Model (set defaults, add logit etc.)
        self.update_model()

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(messages, existing_memories),
            # For models that require a non-system message
            Message(role="user", content="Create or update memories based on the user's messages."),
        ]

        # Generate a response from the Model (includes running function calls)
        response = self.model.response(messages=messages_for_model)
        log_debug("MemoryManager End", center=True)

        # If the model natively supports structured outputs, the parsed value is already in the structured format
        if (
            self.model.supports_native_structured_outputs
            and response.parsed is not None
            and isinstance(response.parsed, MemoryUpdatesResponse)
        ):
            return response.parsed

        # Otherwise convert the response to the structured format
        if isinstance(response.content, str):
            try:
                memory_updates: Optional[MemoryUpdatesResponse] = parse_response_model_str(  # type: ignore
                    response.content, MemoryUpdatesResponse
                )

                # Update RunResponse
                if memory_updates is not None:
                    return memory_updates
                else:
                    log_warning("Failed to convert memory_updates response to MemoryUpdatesResponse object")
            except Exception as e:
                log_warning(f"Failed to convert memory_updates response to MemoryUpdatesResponse: {e}")
        return None

    async def arun(
        self,
        messages: List[Message],
        existing_memories: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[MemoryUpdatesResponse]:
        if self.model is None:
            log_error("No model provided for memory manager")
            return None

        log_debug("MemoryManager Start", center=True)

        # Update the Model (set defaults, add logit etc.)
        self.update_model()

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(messages, existing_memories),
            # For models that require a non-system message
            Message(role="user", content="Create or update memories based on the user's messages."),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await self.model.aresponse(messages=messages_for_model)
        log_debug("MemoryManager End", center=True)

        # If the model natively supports structured outputs, the parsed value is already in the structured format
        if (
            self.model.supports_native_structured_outputs
            and response.parsed is not None
            and isinstance(response.parsed, MemoryUpdatesResponse)
        ):
            return response.parsed

        # Otherwise convert the response to the structured format
        if isinstance(response.content, str):
            try:
                memory_updates: Optional[MemoryUpdatesResponse] = parse_response_model_str(  # type: ignore
                    response.content, MemoryUpdatesResponse
                )

                # Update RunResponse
                if memory_updates is not None:
                    return memory_updates
                else:
                    log_warning("Failed to convert memory_updates response to MemoryUpdatesResponse object")
            except Exception as e:
                log_warning(f"Failed to convert memory_updates response to MemoryUpdatesResponse: {e}")
        return None
