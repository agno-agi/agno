from typing import List, Optional, Union

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.models.base import Model
from agno.models.defaults import DEFAULT_OPENAI_MODEL_ID
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug

MAX_CHUNK_SIZE = 5000

DEFAULT_INSTRUCTIONS = """Determine where to split this text following the user instructions below.

User Instructions:
{custom_instructions}

Constraint: Never exceed {max_chunk_size} characters.

Text:
{text}

Output: Return ONLY the character position number (integer) where to split the above text."""


class AgenticChunking(ChunkingStrategy):
    """Chunking strategy that uses an LLM to determine natural breakpoints in the text"""

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        max_chunk_size: Optional[int] = None,
        custom_prompt: Optional[str] = None,
    ):
        # Convert model string to Model instance
        model = get_model(model)
        if model is None:
            try:
                from agno.models.openai import OpenAIChat
            except Exception:
                raise ValueError("`openai` isn't installed. Please install it with `pip install openai`")
            model = OpenAIChat(DEFAULT_OPENAI_MODEL_ID)

        if max_chunk_size is None:
            max_chunk_size = MAX_CHUNK_SIZE
            if custom_prompt:
                log_debug(
                    f"Using default chunk size of {max_chunk_size} characters. "
                    "Consider specifying `max_chunk_size` explicitly when using `custom_prompt`."
                )

        self.chunk_size = max_chunk_size
        self.custom_prompt = custom_prompt
        self.model = model

    def chunk(self, document: Document) -> List[Document]:
        """Split text into chunks using LLM to determine natural breakpoints based on context"""
        # Skip chunking if content is already within chunk_size
        if len(document.content) <= self.chunk_size:
            return [document]

        chunks: List[Document] = []
        remaining_text = self.clean_text(document.content)
        chunk_meta_data = document.meta_data
        chunk_number = 1

        while remaining_text:
            # Ask model to find a good breakpoint within chunk_size
            if self.custom_prompt:
                # Use custom prompt with DEFAULT_INSTRUCTIONS
                prompt = DEFAULT_INSTRUCTIONS.format(
                    custom_instructions=self.custom_prompt,
                    max_chunk_size=self.chunk_size,
                    text=remaining_text[: self.chunk_size],
                )
            else:
                # Use default prompt
                prompt = f"""Analyze this text and determine a natural breakpoint within the first {self.chunk_size} characters.
                Consider semantic completeness, paragraph boundaries, and topic transitions.
                Return only the character position number of where to break the text:

                {remaining_text[: self.chunk_size]}"""

            try:
                response = self.model.response([Message(role="user", content=prompt)])
                if response and response.content:
                    break_point = min(int(response.content.strip()), self.chunk_size)
                else:
                    break_point = self.chunk_size
            except Exception:
                # Fallback to max size if model fails
                break_point = self.chunk_size

            # Extract chunk and update remaining text
            chunk = remaining_text[:break_point].strip()
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = self._generate_chunk_id(document, chunk_number, chunk)
            meta_data["chunk_size"] = len(chunk)
            chunks.append(
                Document(
                    id=chunk_id,
                    name=document.name,
                    meta_data=meta_data,
                    content=chunk,
                )
            )
            chunk_number += 1

            remaining_text = remaining_text[break_point:].strip()

            if not remaining_text:
                break

        return chunks
