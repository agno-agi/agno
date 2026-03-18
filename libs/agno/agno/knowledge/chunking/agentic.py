from typing import List, Optional, Union

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.models.base import Model
from agno.models.defaults import DEFAULT_OPENAI_MODEL_ID
from agno.models.message import Message
from agno.models.utils import get_model


class AgenticChunking(ChunkingStrategy):
    """Chunking strategy that uses an LLM to determine natural breakpoints in the text"""

    def __init__(self, model: Optional[Union[Model, str]] = None, max_chunk_size: int = 5000):
        # Convert model string to Model instance
        model = get_model(model)
        if model is None:
            try:
                from agno.models.openai import OpenAIChat
            except Exception:
                raise ValueError("`openai` isn't installed. Please install it with `pip install openai`")
            model = OpenAIChat(DEFAULT_OPENAI_MODEL_ID)
        self.chunk_size = max_chunk_size
        self.model = model

    def chunk(self, document: Document) -> List[Document]:
        """Split text into chunks using LLM to determine natural breakpoints based on context"""
        if len(document.content) <= self.chunk_size:
            return [document]

        chunks: List[Document] = []
        remaining_text = self.clean_text(document.content)
        chunk_meta_data = document.meta_data
        chunk_number = 1

        while remaining_text:
            # Ask model to find a good breakpoint within chunk_size
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
