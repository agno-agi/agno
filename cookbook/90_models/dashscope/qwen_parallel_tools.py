"""Qwen Parallel Function Calls Example"""

from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

MODEL_ID = "qwen2.5-3b-instruct"
BASE_URL = "http://localhost:1234/v1"
EMBEDDER_MODEL_ID = "text-embedding-nomic-embed-text-v1.5"
EMBEDDER_BASE_URL = "http://localhost:1234/v1"


def example_automatic_parallel():
    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        tools=[DuckDuckGoTools(), YFinanceTools()],
        markdown=True,
    )
    agent.print_response(
        "Get latest AI news and Apple stock price, present both together."
    )


def example_custom_parallel_limit():
    agent = Agent(
        model=DashScope(
            id="Qwen/Qwen2.5-Coder-7B-Instruct",
            base_url="http://localhost:8000/v1",
            max_parallel_calls=10,
        ),
        tools=[YFinanceTools()],
        markdown=True,
    )
    agent.print_response(
        "Get current stock prices for: AAPL, GOOGL, MSFT, TSLA, "
        "AMZN, META, NVDA, AMD. Show all in a table."
    )


def example_disable_parallel():
    agent = Agent(
        model=DashScope(
            id="qwen-plus",
            max_parallel_calls=1,
        ),
        tools=[DuckDuckGoTools(), YFinanceTools()],
        markdown=True,
    )
    agent.print_response(
        "Search for Python programming tips and get Microsoft stock price."
    )


def example_comparison_benchmark():
    import time

    parallel_agent = Agent(
        model=DashScope(id="qwen-plus", max_parallel_calls=5),
        tools=[YFinanceTools()],
    )
    sequential_agent = Agent(
        model=DashScope(id="qwen-plus", max_parallel_calls=1),
        tools=[YFinanceTools()],
    )

    query = "Get stock prices for AAPL, GOOGL, MSFT, TSLA, AMZN"

    start = time.time()
    parallel_agent.run(query)
    parallel_time = time.time() - start

    start = time.time()
    sequential_agent.run(query)
    sequential_time = time.time() - start

    print(
        f"Parallel: {parallel_time:.2f}s | Sequential: {sequential_time:.2f}s | Speedup: {sequential_time / parallel_time:.2f}x"
    )


def example_template_types():
    for template in ["qwen", "nous", "glm4"]:
        agent = Agent(
            model=DashScope(
                id="qwen-plus",
                fncall_prompt_type=template,
                max_parallel_calls=5,
            ),
            tools=[YFinanceTools()],
        )
        agent.print_response("Get Apple stock price")


def example_vllm_native_parsing():
    agent = Agent(
        model=DashScope(
            id="Qwen/Qwen2.5-Coder-7B-Instruct",
            base_url="http://localhost:8000/v1",
            max_parallel_calls=10,
        ),
        tools=[DuckDuckGoTools(), YFinanceTools()],
        markdown=True,
    )
    agent.print_response(
        "Search for 'machine learning trends' and get Tesla stock price"
    )


def example_local_embeddings_knowledge():
    from agno.knowledge.chunking.fixed_size import FixedSizeChunking
    from agno.knowledge.embedder.openai import OpenAIEmbedder
    from agno.knowledge.knowledge import Knowledge
    from agno.knowledge.reader.website_reader import WebsiteReader
    from agno.tools.knowledge import KnowledgeTools
    from agno.vectordb.lancedb import LanceDb, SearchType

    local_embedder = OpenAIEmbedder(
        id=EMBEDDER_MODEL_ID,
        base_url=EMBEDDER_BASE_URL,
        api_key="not-needed",
        dimensions=768,
    )

    agno_knowledge = Knowledge(
        vector_db=LanceDb(
            uri="tmp/qwen_lancedb",
            table_name="qwen_docs",
            search_type=SearchType.hybrid,
            embedder=local_embedder,
        ),
    )

    website_reader = WebsiteReader(
        chunking_strategy=FixedSizeChunking(chunk_size=1000, overlap=200),
    )

    agno_knowledge.add_reader(website_reader)
    agno_knowledge.add_content(
        url="https://docs.agno.com/llms-full.txt",
        reader=website_reader,
    )

    knowledge_tools = KnowledgeTools(
        knowledge=agno_knowledge,
        enable_think=True,
        enable_search=True,
        enable_analyze=True,
    )

    agent = Agent(
        model=DashScope(id=MODEL_ID, base_url=BASE_URL),
        tools=[knowledge_tools],
        markdown=True,
    )

    agent.print_response(
        "How do I build a team of agents in agno? Give me code examples.",
        markdown=True,
    )


if __name__ == "__main__":
    example_automatic_parallel()
