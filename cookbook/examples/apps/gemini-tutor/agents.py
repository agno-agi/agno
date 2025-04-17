"""
Gemini Tutor: Advanced Educational AI Assistant powered by Gemini 2.5
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from agno.agent import Agent, RunResponse
from agno.models.google import Gemini
from agno.models.message import Message
from agno.tools.file import FileTools
from agno.tools.googlesearch import GoogleSearchTools
from agno.utils.log import logger

# Import prompt templates
from prompts import (
    SEARCH_GROUNDING_INSTRUCTIONS,
    TUTOR_DESCRIPTION_TEMPLATE,
    TUTOR_INSTRUCTIONS_TEMPLATE,
)


class TutorAppAgent:
    """
    Central agent that handles all tutoring functionality.
    Offloads search, content preparation, and learning experience generation.
    """

    def __init__(
        self, model_id="gemini-2.5-pro-exp-03-25", education_level="High School"
    ):
        """
        Initialize the TutorAppAgent.

        Args:
            model_id: Model identifier to use
            education_level: Target education level for content
        """
        self.model_id = model_id
        self.education_level = education_level
        self.agent = self._create_agent()
        logger.info(
            f"TutorAppAgent initialized with {model_id} model and {education_level} education level"
        )

    def _create_agent(self):
        """Create and configure the agent with all necessary capabilities"""

        gemini_model = Gemini(
            id=self.model_id,
            temperature=1,
            top_p=0.9,
            top_k=40,
        )

        # Enable grounding if supported by the model
        if "gemini-2." in self.model_id or "gemini-1.5" in self.model_id:
            try:
                setattr(gemini_model, "grounding", True)
                logger.info("Enabled model grounding (google_search_retrieval)")
            except AttributeError:
                logger.warning(
                    f"Model {self.model_id} does not support grounding attribute."
                )
            except Exception as e:
                logger.warning(f"Could not enable model grounding: {e}")

        # Format description and instructions directly
        tutor_description = TUTOR_DESCRIPTION_TEMPLATE.format(
            education_level=self.education_level
        )
        tutor_instructions = TUTOR_INSTRUCTIONS_TEMPLATE.format(
            education_level=self.education_level,
        )

        # Create agent with tutor capabilities, passing the created model
        return Agent(
            name="Gemini Tutor",
            model=gemini_model,
            session_id=str(uuid.uuid4()),
            read_chat_history=True,
            read_tool_call_history=True,
            add_history_to_messages=True,
            num_history_responses=5,
            description=tutor_description,  # Pass formatted description
            instructions=tutor_instructions,  # Pass formatted instructions
            debug_mode=True,
            markdown=True,
        )

    def create_learning_experience(self, search_topic, education_level=None):
        """
        Create a complete learning experience from search topic to final content.
        This method offloads the entire process to the agent.

        Args:
            search_topic: The topic to create a learning experience for
            education_level: Override the default education level for this specific call.

        Returns:
            The learning experience response from the agent
        """
        # Determine the education level for this specific request
        current_education_level = education_level or self.education_level
        if education_level and self.education_level != education_level:
            logger.info(
                f"Using temporary education level for this request: {education_level}"
            )
        else:
            # Use the agent's default education level if not overridden
            current_education_level = self.education_level

        logger.info(
            f"Creating learning experience for '{search_topic}' at {current_education_level} level"
        )

        # Construct a focused prompt for the agent, relying on its core instructions
        grounding_instructions = (
            SEARCH_GROUNDING_INSTRUCTIONS
            if "gemini-2." in self.model_id or "gemini-1.5" in self.model_id
            else ""
        )
        # The agent's core instructions (set during init) already contain formatting rules.
        # This prompt focuses on the specific task.
        prompt = f"""
        Create a complete and engaging learning experience about '{search_topic}' specifically tailored for {current_education_level} students.

        **Task:**
        Generate a comprehensive learning module covering the key aspects of '{search_topic}'.

        **Follow your core instructions regarding:**
        *   Adapting content complexity and style for the {current_education_level} level.
        *   Structuring the response logically (introduction, key concepts, examples, etc.).
        *   Including interactive elements (thought experiments/questions) and assessments (2-3 simple questions with answers).
        *   Strictly adhering to the rules for embedding images and videos (using direct, stable URLs only or omitting embeds).
        *   Citing up to 5 key sources if external information was used.

        {grounding_instructions}
        """

        # Create message
        user_message = Message(role="user", content=prompt)
        return self.agent.run(prompt=prompt, messages=[user_message], stream=True)
