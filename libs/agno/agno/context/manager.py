from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING, List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.team.team import Team

DEFAULT_COMPRESSION_PROMPT = dedent("""\
    You are compressing tool call results for an AI agent to save context space while preserving critical information.
    
    The user message contains:
    1. AGENT CONTEXT (if available): The agent's role, purpose, and task focus
    2. TOOL OUTPUT: The raw result that needs compression
    
    Your goal: Extract only the essential information the agent needs to continue its task.
    
    ALWAYS PRESERVE:
    • Specific facts: numbers, statistics, amounts, prices, quantities, metrics
    • Temporal data: dates, times, timestamps (use short format: "Oct 21 2025")
    • Entities: people, companies, products, locations, organizations
    • Identifiers: URLs, IDs, codes, technical identifiers, versions
    • Key quotes, citations, sources (if relevant to agent's task)
    
    COMPRESS TO ESSENTIALS:
    • Descriptions: keep only key attributes
    • Explanations: distill to core insight
    • Lists: focus on most relevant items based on agent context
    • Background: minimal context only if critical
    
    REMOVE ENTIRELY:
    • Introductions, conclusions, transitions
    • Hedging language ("might", "possibly", "appears to")
    • Meta-commentary ("According to", "The results show")
    • Formatting artifacts (markdown, HTML, JSON structure)
    • Redundant or repetitive information
    • Generic background not relevant to agent's task
    • Promotional language, filler words
    
    EXAMPLE:
    Input: "According to recent market analysis and industry reports, OpenAI has made several significant announcements in the technology sector. The company revealed ChatGPT Atlas on October 21, 2025, which represents a new AI-powered browser application that has been specifically designed for macOS users. This browser is strategically positioned to compete with traditional search engines in the market. Additionally, on October 6, 2025, OpenAI launched Apps in ChatGPT, which includes a comprehensive software development kit (SDK) for developers. The company has also announced several initial strategic partners who will be integrating with this new feature, including well-known companies such as Spotify, the popular music streaming service, Zillow, which is a real estate marketplace platform, and Canva, a graphic design platform."
    
    Output: "OpenAI - Oct 21 2025: ChatGPT Atlas (AI browser, macOS, search competitor); Oct 6 2025: Apps in ChatGPT + SDK; Partners: Spotify, Zillow, Canva"
    
    Be concise while retaining all critical facts.
    """)


@dataclass
class ContextManager:
    model: Optional[Model] = None
    agent: Optional["Agent"] = None
    team: Optional["Team"] = None
    compress_tool_calls_limit: int = 3
    tool_compression_instructions: Optional[str] = None

    def _get_additional_details(self) -> Optional[str]:
        """Extract additional details for compression prompt."""
        if not self.agent and not self.team:
            return None

        additional_context = ""

        if self.agent:
            if self.agent.name:
                additional_context += f"Agent Name: {self.agent.name}\n"
            if self.agent.description:
                additional_context += f"Description: {self.agent.description}\n"
            if self.agent.instructions:
                additional_context += f"Instructions: {self.agent.instructions}\n"

        return additional_context if additional_context else None

    def should_compress(self, messages: List[Message]) -> bool:
        uncompressed_tools_count = len([m for m in messages if m.role == "tool" and m.compressed_content is None])

        return uncompressed_tools_count > self.compress_tool_calls_limit

    def _compress_tool_result(self, tool_results: List[Message]) -> Optional[str]:
        if not tool_results:
            return None

        tool_content = "\n---\n".join(f"Tool: {msg.tool_name or 'unknown'}\n{msg.content}" for msg in tool_results)

        self.model = get_model(self.model)
        if not self.model:
            return None

        compression_prompt = self.tool_compression_instructions or DEFAULT_COMPRESSION_PROMPT

        compression_message = ""

        agent_context = self._get_additional_details()
        if agent_context:
            compression_message += "Additional Details: " + agent_context + "\n"

        compression_message += "Tool Results to Compress: " + tool_content + "\n"

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=compression_message),
                ]
            )
            return response.content
        except Exception as e:
            log_warning(f"Error compressing tool results: {e}")
            return None

    def compress_tool_results(self, messages: List[Message]) -> List[Message]:
        """Compress all uncompressed tool results."""
        uncompressed_tools = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed_tools:
            return messages

        for tool_msg in uncompressed_tools:
            compressed_content = self._compress_tool_result([tool_msg])

            if compressed_content:
                tool_msg.compressed_content = compressed_content

        return messages
