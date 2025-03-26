"""
Gemini Tutor: Advanced Educational AI Assistant powered by Gemini 2.5
"""

import os
import uuid
import json
from typing import Optional, Dict, Any
from pathlib import Path

from agno.agent import Agent, RunResponse
from agno.models.google import Gemini
from agno.tools.file import FileTools
from agno.tools.googlesearch import GoogleSearchTools
from agno.utils.log import logger, set_log_level_to_debug
from agno.models.message import Message

import dotenv

# Load environment variables
dotenv.load_dotenv()

# Import essential prompt templates
FORMAT_INSTRUCTIONS = """
Format your response as Markdown with:
- Clear headings and subheadings
- Lists and emphasis for important concepts
- Tables and code blocks when relevant
- Source citations
"""

SEARCH_GROUNDING_INSTRUCTIONS = """
Use search to get accurate, up-to-date information and cite your sources.
"""

class TutorAppAgent:
    """
    Central agent that handles all tutoring functionality.
    Offloads search, content preparation, and learning experience generation.
    """
    def __init__(self, model_id="gemini-2.5-pro-exp-03-25", education_level="High School"):
        """
        Initialize the TutorAppAgent.

        Args:
            model_id: Model identifier to use
            education_level: Target education level for content
        """
        self.model_id = model_id
        self.education_level = education_level
        self.agent = self._create_agent()
        logger.info(f"TutorAppAgent initialized with {model_id} model and {education_level} education level")

    def _create_agent(self):
        """Create and configure the agent with all necessary capabilities"""
        api_key = self._get_api_key()
        set_log_level_to_debug()

        # Initialize model with search grounding
        model = Gemini(
            id=self.model_id,
            api_key=api_key,
            temperature=0.7,
            top_p=0.9,
            top_k=40,
            max_output_tokens=4096,
        )

        # Enable search grounding if supported
        if 'gemini-2.' in self.model_id or 'gemini-1.5' in self.model_id:
            try:
                model.config.tools = ["google_search_retrieval"]
                logger.info("Enabled google_search_retrieval")
            except Exception as e:
                logger.warning(f"Could not enable google_search_retrieval: {e}")

        # Add search tools
        tools = [
            GoogleSearchTools(fixed_max_results=50, timeout=20, cache_results=True),
        ]

        # Create agent with tutor capabilities
        return Agent(
            name="Gemini Tutor",
            model=model,
            session_id=str(uuid.uuid4()),
            tools=tools,
            read_chat_history=True,
            read_tool_call_history=True,
            add_history_to_messages=True,
            num_history_responses=5,
            description=self._get_tutor_description(),
            instructions=self._get_tutor_instructions(),
            debug_mode=True,
            markdown=True,
        )

    def _get_api_key(self):
        """Get and validate API key"""
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set in environment variables")
        if api_key == "your_gemini_api_key_here":
            raise ValueError("Please replace the placeholder API key with your actual Gemini API key")
        return api_key

    def _get_tutor_description(self):
        """Get the tutor description for the agent"""
        return f"""You are Gemini Tutor, an educational AI assistant that provides personalized
                learning for {self.education_level} students. You can analyze text and content
                to create comprehensive learning experiences."""

    def _get_tutor_instructions(self):
        """Get the tutor instructions for the agent"""
        return """
        1. Understand the query and gather relevant information using search
        2. Provide clear, education-level appropriate explanations
        3. Include interactive elements and practice exercises
        4. Cite sources and ensure factual accuracy
        5. When you find useful images or videos, include them directly with their URLs
        """

    def create_learning_experience(self, search_topic, education_level=None):
        """
        Create a complete learning experience from search topic to final content.
        This method offloads the entire process to the agent.

        Args:
            search_topic: The topic to create a learning experience for
            education_level: Override the default education level

        Returns:
            The learning experience response from the agent
        """
        education_level = education_level or self.education_level
        logger.info(f"Creating learning experience for '{search_topic}' at {education_level} level")

        # Construct a comprehensive prompt for the agent
        prompt = f"""
        Create a complete learning experience about '{search_topic}' for {education_level} students.

        Your task:
        1. Search for high-quality, factual information about the topic
        2. Create an engaging learning experience with:
           - Clear introduction to the topic
           - Key concepts and principles
           - Examples, analogies, and visual explanations (include relevant images via URLs)
           - Interactive elements (practice questions, thought experiments)
           - Assessment opportunities

        When you find useful images or videos online, include them directly using their URLs.
        There's no need to download or save them locally - just use markdown syntax to display them.

        For example:
        - Include images using: ![Description](image_url)
        - Include videos with clickable links: [Video Title](video_url)

        {FORMAT_INSTRUCTIONS}
        {SEARCH_GROUNDING_INSTRUCTIONS}
        """

        # Create message
        user_message = Message(role="user", content=prompt)

        # Run the agent to create the learning experience
        return self.agent.run(prompt=prompt, messages=[user_message], stream=True)
