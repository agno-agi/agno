"""Long context handling examples with Qwen models (32K+ tokens)"""

from agno.agent import Agent
from agno.models.dashscope import DashScope

MODEL_ID = "qwen/qwen3-4b-thinking-2507"
BASE_URL = "http://localhost:1234/v1"


def example_long_document_analysis():
    """Analyze a long document with context window management"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    long_text = (
        """
    [This would contain a long document, research paper, or codebase analysis]
    """
        * 100
    )  # Simulate long context

    agent.print_response(
        f"Analyze this document and provide a comprehensive summary:\n\n{long_text[:1000]}...[truncated for example]"
    )


def example_codebase_analysis():
    """Analyze multiple code files in a single context"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    # Simulating multiple file contents
    files_content = """
# File: main.py
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

# File: models.py
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str

# File: database.py
from sqlalchemy import create_engine
engine = create_engine("sqlite:///./app.db")
"""

    agent.print_response(
        f"Review this codebase and suggest improvements:\n\n{files_content}"
    )


def example_conversation_with_long_history():
    """Handle long conversation history"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=2000,
        ),
        markdown=True,
    )

    # Simulate a conversation with extensive context
    context = """
Previous conversation:
User: Tell me about machine learning
AI: Machine learning is a subset of artificial intelligence...
User: What are the main types?
AI: The main types are supervised, unsupervised, and reinforcement learning...
[... many more exchanges ...]
"""

    agent.print_response(
        f"{context}\n\nBased on our previous discussion, explain how to implement a neural network"
    )


def example_book_summarization():
    """Summarize long-form content like books or articles"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    book_excerpt = """
    Chapter 1: Introduction to Distributed Systems
    [Long chapter content...]

    Chapter 2: Communication Protocols
    [Long chapter content...]

    Chapter 3: Consensus Algorithms
    [Long chapter content...]
    """

    agent.print_response(
        f"Provide a chapter-by-chapter summary of this book:\n\n{book_excerpt}"
    )


def example_legal_document_analysis():
    """Analyze legal documents or contracts"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    contract = """
    SOFTWARE LICENSE AGREEMENT
    [Long legal document with multiple sections, clauses, and subclauses...]
    """

    agent.print_response(
        f"Analyze this contract and highlight key terms and potential issues:\n\n{contract}"
    )


def example_research_paper_analysis():
    """Analyze research papers with long context"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    paper = """
    Title: Attention Is All You Need
    Abstract: [...]
    1. Introduction: [...]
    2. Background: [...]
    3. Model Architecture: [...]
    4. Experiments: [...]
    5. Results: [...]
    6. Conclusion: [...]
    References: [...]
    """

    agent.print_response(
        f"Summarize this research paper and explain the key contributions:\n\n{paper}"
    )


def example_local_long_context():
    """Long context with local deployment"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    large_codebase = """
    # Multiple Python files with extensive code
    [Large codebase content...]
    """

    agent.print_response(
        f"Review this codebase and identify architectural patterns:\n\n{large_codebase}"
    )


def example_context_window_management():
    """Demonstrate context window management strategies"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=2000,
            temperature=0.7,
        ),
        markdown=True,
    )

    # Example of handling context that might exceed window
    agent.print_response(
        "Explain best practices for managing context windows in LLM applications"
    )


def example_streaming_long_output():
    """Handle long outputs with streaming"""
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            max_tokens=4000,
        ),
        markdown=True,
    )

    agent.print_response(
        "Write a detailed tutorial on building a microservices architecture with examples",
        stream=True,
    )


if __name__ == "__main__":
    print("\n=== Example 1: Long Document Analysis ===")
    example_long_document_analysis()

    print("\n=== Example 2: Codebase Analysis ===")
    example_codebase_analysis()

    print("\n=== Example 3: Research Paper Analysis ===")
    example_research_paper_analysis()
