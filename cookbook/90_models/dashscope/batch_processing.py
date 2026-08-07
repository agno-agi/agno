"""Batch processing examples with Qwen models"""

import asyncio

from agno.agent import Agent
from agno.models.dashscope import DashScope

MODEL_ID = "qwen2.5-3b-instruct"
BASE_URL = "http://localhost:1234/v1"


def example_sequential_batch():
    """Process multiple queries sequentially"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    queries = [
        "What is machine learning?",
        "Explain neural networks",
        "What is deep learning?",
        "Describe transformer architecture",
    ]

    print("\n=== Processing queries sequentially ===")
    for i, query in enumerate(queries, 1):
        print(f"\n--- Query {i}/{len(queries)} ---")
        agent.print_response(query)


async def example_async_batch():
    """Process multiple queries asynchronously"""

    async def process_query(query: str, index: int):
        agent = Agent(
            model=DashScope(id=MODEL_ID, base_url=BASE_URL),
            markdown=True,
        )
        print(f"\n--- Processing query {index} ---")
        result = await agent.arun(query)
        return result

    queries = [
        "Explain quantum computing",
        "What is blockchain?",
        "Describe cloud computing",
        "What is edge computing?",
    ]

    print("\n=== Processing queries asynchronously ===")
    tasks = [process_query(query, i + 1) for i, query in enumerate(queries)]
    results = await asyncio.gather(*tasks)

    for i, result in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        print(result.content)


def example_batch_code_generation():
    """Batch code generation tasks"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    tasks = [
        "Write a Python function to reverse a string",
        "Write a Python function to check if a number is prime",
        "Write a Python function to calculate factorial",
        "Write a Python function to find the GCD",
    ]

    print("\n=== Batch Code Generation ===")
    for i, task in enumerate(tasks, 1):
        print(f"\n--- Task {i}/{len(tasks)} ---")
        agent.print_response(task)


def example_batch_document_processing():
    """Process multiple documents in batch"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    documents = [
        "Document 1: Introduction to AI and its applications...",
        "Document 2: The history of machine learning...",
        "Document 3: Future trends in artificial intelligence...",
    ]

    print("\n=== Batch Document Summarization ===")
    for i, doc in enumerate(documents, 1):
        print(f"\n--- Document {i}/{len(documents)} ---")
        agent.print_response(f"Summarize this document in 2 sentences:\n\n{doc}")


def example_batch_translation():
    """Batch translation tasks"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    texts = [
        "Hello, how are you?",
        "Machine learning is fascinating",
        "The weather is beautiful today",
    ]

    print("\n=== Batch Translation (English to Spanish) ===")
    for i, text in enumerate(texts, 1):
        print(f"\n--- Text {i}/{len(texts)} ---")
        agent.print_response(f"Translate to Spanish: {text}")


def example_batch_data_extraction():
    """Extract data from multiple sources in batch"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    emails = [
        "From: john@example.com\nSubject: Meeting\nLet's meet tomorrow at 3pm in room 205",
        "From: alice@example.com\nSubject: Project Update\nThe deadline is Friday, December 15th",
        "From: bob@example.com\nSubject: Invoice\nPayment due: $1,500 by January 10th",
    ]

    print("\n=== Batch Data Extraction ===")
    for i, email in enumerate(emails, 1):
        print(f"\n--- Email {i}/{len(emails)} ---")
        agent.print_response(
            f"Extract key information (who, what, when, where) from this email:\n\n{email}"
        )


async def example_concurrent_with_rate_limit():
    """Process batch with rate limiting"""
    from asyncio import Semaphore

    semaphore = Semaphore(3)  # Max 3 concurrent requests

    async def process_with_limit(query: str, index: int):
        async with semaphore:
            agent = Agent(
                model=DashScope(id=MODEL_ID, base_url=BASE_URL),
                markdown=True,
            )
            print(f"\n--- Processing {index} ---")
            result = await agent.arun(query)
            return result

    queries = [f"Explain concept {i}" for i in range(10)]

    print("\n=== Processing with rate limit (max 3 concurrent) ===")
    tasks = [process_with_limit(query, i + 1) for i, query in enumerate(queries)]
    results = await asyncio.gather(*tasks)

    print(f"\n--- Processed {len(results)} queries ---")


def example_batch_local_deployment():
    """Batch processing with local Qwen model"""
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        markdown=True,
    )

    questions = [
        "What is Python?",
        "What is JavaScript?",
        "What is Go?",
        "What is Rust?",
    ]

    print("\n=== Batch Processing (Local Model) ===")
    for i, question in enumerate(questions, 1):
        print(f"\n--- Question {i}/{len(questions)} ---")
        agent.print_response(question)


def example_batch_with_different_temperatures():
    """Use different temperatures for different tasks"""
    tasks = [
        (0.3, "Explain quantum physics"),
        (0.7, "Write a creative story about AI"),
        (0.1, "What is 2+2?"),
        (0.9, "Generate innovative product ideas"),
    ]

    print("\n=== Batch with Different Temperatures ===")
    for i, (temp, task) in enumerate(tasks, 1):
        print(f"\n--- Task {i}/{len(tasks)} (Temperature: {temp}) ---")
        agent = Agent(
            model=DashScope(id=MODEL_ID, base_url=BASE_URL, temperature=temp),
            markdown=True,
        )
        agent.print_response(task)


if __name__ == "__main__":
    # Sequential examples
    example_sequential_batch()

    # Async examples (uncomment to run)
    # asyncio.run(example_async_batch())
    # asyncio.run(example_concurrent_with_rate_limit())

    print("\n=== Batch Code Generation ===")
    example_batch_code_generation()
