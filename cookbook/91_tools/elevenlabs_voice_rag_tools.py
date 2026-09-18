"""
ElevenLabs Voice RAG Agent Example

This example demonstrates how to create a Voice RAG agent using ElevenLabs.
The agent can:
1. Upload documents (PDF, TXT, DOCX) to a knowledge base
2. Create content from URLs or raw text
3. Create a voice agent with RAG capabilities
4. Enable real-time speech-to-speech conversations

Requirements:
    pip install agno httpx

Environment Variables:
    ELEVEN_LABS_API_KEY: Your ElevenLabs API key
    OPENAI_API_KEY: Your OpenAI API key (for the orchestrating agent)

Usage:
    python elevenlabs_voice_rag_tools.py
"""

import json
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.eleven_labs_voice_rag import ElevenLabsVoiceRAGTools

# =============================================================================
# Example 1: Basic Voice RAG Agent
# =============================================================================


def basic_voice_rag_example():
    """
    Create a simple Voice RAG agent that can upload documents and
    create voice agents for conversations.
    """
    print("\n" + "=" * 60)
    print("Example 1: Basic Voice RAG Agent")
    print("=" * 60 + "\n")

    # Initialize the ElevenLabs Voice RAG toolkit
    voice_rag_tools = ElevenLabsVoiceRAGTools(
        voice_id="cjVigY5qzO86Huf0OWal",  # Eric voice
        language="en",
        llm="qwen3-30b-a3b",  # Ultra low latency
        auto_compute_rag_index=True,  # Auto-index for RAG
    )

    # Create an agent with Voice RAG capabilities
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[voice_rag_tools],
        instructions=dedent("""
            You are a helpful assistant that can create voice-enabled AI agents.
            
            You have access to ElevenLabs Voice RAG tools that allow you to:
            1. Upload documents to create a knowledge base
            2. Create content from URLs or text
            3. Create voice agents that can answer questions using the knowledge base
            4. Get conversation URLs to start voice chats
            
            When creating a voice agent:
            - First upload or create the knowledge base content
            - Then create the voice agent with appropriate system prompt
            - Finally, provide the widget URL for voice conversation
        """),
        markdown=True,
        show_tool_calls=True,
    )

    # Example: Create a voice agent from text content
    agent.print_response(
        dedent("""
            Create a voice agent for a pizza restaurant with the following information:
            
            Menu:
            - Margherita Pizza: $12
            - Pepperoni Pizza: $14
            - Hawaiian Pizza: $15
            - Veggie Supreme: $16
            
            Hours: 11am - 10pm daily
            Address: 123 Main Street
            Phone: (555) 123-4567
            
            The agent should help customers with menu questions and taking orders.
            Use English language and create the agent named "Pizza Bot".
        """),
        stream=True,
    )


# =============================================================================
# Example 2: Document Upload and Voice Agent
# =============================================================================


def document_upload_example():
    """
    Upload a document and create a voice agent that can answer
    questions about the document content.
    """
    print("\n" + "=" * 60)
    print("Example 2: Document Upload Voice RAG")
    print("=" * 60 + "\n")

    voice_rag_tools = ElevenLabsVoiceRAGTools(
        llm="gpt-4o",  # Use GPT-4o for better reasoning
        language="en",
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[voice_rag_tools],
        instructions=dedent("""
            You help users create voice agents from their documents.
            
            Steps:
            1. Upload the document they provide
            2. Create a voice agent with a helpful system prompt
            3. Return the widget URL for voice conversation
        """),
        markdown=True,
        show_tool_calls=True,
    )

    # Example with a hypothetical document path
    agent.print_response(
        "Upload the document at './sample_docs/company_handbook.pdf' and create a voice agent named 'HR Assistant' that can answer employee questions about company policies.",
        stream=True,
    )


# =============================================================================
# Example 3: URL-based Knowledge Base
# =============================================================================


def url_knowledge_base_example():
    """
    Create a knowledge base from a URL and build a voice agent.
    """
    print("\n" + "=" * 60)
    print("Example 3: URL-based Knowledge Base")
    print("=" * 60 + "\n")

    voice_rag_tools = ElevenLabsVoiceRAGTools(
        language="en",
        llm="qwen3-30b-a3b",
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[voice_rag_tools],
        instructions=dedent("""
            You can create voice agents that answer questions about web content.
            
            When given a URL:
            1. Create a knowledge base document from the URL
            2. Create a voice agent to answer questions about that content
            3. Provide the conversation widget URL
        """),
        markdown=True,
        show_tool_calls=True,
    )

    agent.print_response(
        "Create a voice agent that can answer questions about Python from the official Python documentation at https://docs.python.org/3/tutorial/index.html. Name it 'Python Tutor'.",
        stream=True,
    )


# =============================================================================
# Example 4: Multi-language Voice Agent (Hindi)
# =============================================================================


def hindi_voice_agent_example():
    """
    Create a voice agent that speaks Hindi.
    """
    print("\n" + "=" * 60)
    print("Example 4: Hindi Voice Agent")
    print("=" * 60 + "\n")

    voice_rag_tools = ElevenLabsVoiceRAGTools(
        language="hi",  # Hindi
        llm="qwen3-30b-a3b",
        rag_embedding_model="multilingual_e5_large_instruct",  # Multilingual support
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[voice_rag_tools],
        instructions=dedent("""
            You create voice agents that speak Hindi.
            
            When creating agents:
            - Use Hindi as the language
            - Create appropriate Hindi greetings
            - Ensure the knowledge base supports Hindi content
        """),
        markdown=True,
        show_tool_calls=True,
    )

    agent.print_response(
        dedent("""
            Create a Hindi voice agent for a travel agency with this info:
            
            सेवाएं (Services):
            - दिल्ली टूर: ₹5000
            - आगरा टूर: ₹3000  
            - जयपुर टूर: ₹4500
            
            संपर्क: +91 98765 43210
            
            Name it "यात्रा सहायक" (Travel Assistant).
        """),
        stream=True,
    )


# =============================================================================
# Example 5: Interactive Voice RAG Session
# =============================================================================


def interactive_session():
    """
    Interactive session where user can create voice agents step by step.
    """
    print("\n" + "=" * 60)
    print("Example 5: Interactive Voice RAG Session")
    print("=" * 60 + "\n")

    voice_rag_tools = ElevenLabsVoiceRAGTools()

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[voice_rag_tools],
        instructions=dedent("""
            You are a Voice RAG assistant. Help users:
            1. Upload documents or create content from URLs/text
            2. Create voice agents with their content
            3. Get links to start voice conversations
            
            Be helpful and guide users through the process.
        """),
        markdown=True,
        show_tool_calls=True,
    )

    print("Interactive Voice RAG Session")
    print("Type 'exit' to quit\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Goodbye!")
                break
            if not user_input:
                continue

            agent.print_response(user_input, stream=True)
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    print("\n" + "=" * 60)
    print("ElevenLabs Voice RAG Tools Examples")
    print("=" * 60)
    print("\nAvailable examples:")
    print("1. Basic Voice RAG Agent")
    print("2. Document Upload Voice RAG")
    print("3. URL-based Knowledge Base")
    print("4. Hindi Voice Agent")
    print("5. Interactive Session")
    print("\nUsage: python elevenlabs_voice_rag_tools.py [1-5]")
    print("Default: Runs Example 1\n")

    example = sys.argv[1] if len(sys.argv) > 1 else "1"

    examples = {
        "1": basic_voice_rag_example,
        "2": document_upload_example,
        "3": url_knowledge_base_example,
        "4": hindi_voice_agent_example,
        "5": interactive_session,
    }

    if example in examples:
        examples[example]()
    else:
        print(f"Unknown example: {example}")
        print("Please choose 1-5")
