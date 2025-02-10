from typing import Any, List, Optional, cast

from pydantic import BaseModel

from agno.memory.memory import Memory
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import logger


class MemoryClassifier(BaseModel):
    model: Optional[Model] = None

    # Provide the system prompt for the classifier as a string
    system_prompt: Optional[str] = None
    # Existing Memories
    existing_memories: Optional[List[Memory]] = None

    def update_model(self) -> None:
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                logger.exception(e)
                logger.error(
                    "Agno uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                )
                exit(1)
            self.model = OpenAIChat(id="gpt-4o")

    def get_system_message(self) -> Message:
        # -*- Return a system message for classification
        system_prompt_lines = [
            "Your task is to identify if the user's message contains information that is worth remembering for future conversations.",
            "This includes details that could personalize ongoing interactions with the user, such as:\n"
            "  - Personal facts: name, age, occupation, location, interests, preferences, etc.\n"
            "  - Significant life events or experiences shared by the user\n"
            "  - Important context about the user's current situation, challenges or goals\n"
            "  - What the user likes or dislikes, their opinions, beliefs, values, etc.\n"
            "  - Any other details that provide valuable insights into the user's personality, perspective or needs",
            "Your task is to decide whether the user input contains any of the above information worth remembering.",
            "If the user input contains any information worth remembering for future conversations, respond with 'yes'.",
            "If the input does not contain any important details worth saving, respond with 'no' to disregard it.",
            "You will also be provided with a list of existing memories to help you decide if the input is new or already known.",
            "If the memory already exists that matches the input, respond with 'no' to keep it as is.",
            "If a memory exists that needs to be updated or deleted, respond with 'yes' to update/delete it.",
            "You must only respond with 'yes' or 'no'. Nothing else will be considered as a valid response.",
        ]
        if self.existing_memories and len(self.existing_memories) > 0:
            system_prompt_lines.extend(
                [
                    "\nExisting memories:",
                    "<existing_memories>\n"
                    + "\n".join([f"  - {m.memory}" for m in self.existing_memories])
                    + "\n</existing_memories>",
                ]
            )
        return Message(role="system", content="\n".join(system_prompt_lines))

    def run(
        self,
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        logger.debug("*********** MemoryClassifier Start ***********")

        # Update the Model (set defaults, add logit etc.)
        self.update_model()

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [self.get_system_message()]
        # Add the user prompt message
        user_prompt_message = Message(role="user", content=message, **kwargs) if message else None
        if user_prompt_message is not None:
            messages_for_model += [user_prompt_message]

        # Generate a response from the Model (includes running function calls)
        self.model = cast(Model, self.model)
        response = self.model.response(messages=messages_for_model)
        logger.debug("*********** MemoryClassifier End ***********")
        return response.content

    async def arun(
        self,
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        logger.debug("*********** Async MemoryClassifier Start ***********")

        # Update the Model (set defaults, add logit etc.)
        self.update_model()

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [self.get_system_message()]
        # Add the user prompt message
        user_prompt_message = Message(role="user", content=message, **kwargs) if message else None
        if user_prompt_message is not None:
            messages_for_model += [user_prompt_message]

        # Generate a response from the Model (includes running function calls)
        self.model = cast(Model, self.model)
        response = await self.model.aresponse(messages=messages_for_model)
        logger.debug("*********** Async MemoryClassifier End ***********")
        return response.content
