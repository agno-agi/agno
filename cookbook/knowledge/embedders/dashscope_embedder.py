from os import getenv

import dotenv
from agno.agent import Agent
from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.dashscope import DashScope
from agno.vectordb.lancedb import LanceDb, SearchType

from libs.agno.agno.knowledge.embedder.dashscop import DashScopeEmbedder
from libs.agno.agno.knowledge.reranker.dashscope import DashScopeReranker

dotenv.load_dotenv()

API_KEY = getenv("DASHSCOPE_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

knowledge = Knowledge(
    vector_db=LanceDb(
        uri="./tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        # dashscope embedder example
        embedder=DashScopeEmbedder(
            id="text-embedding-v4",
            api_key=API_KEY,
            base_url=BASE_URL,
            dimensions=128,
            enable_batch=True,
            batch_size=10
        ),
        # dashscope reranker example
        reranker=DashScopeReranker(
            api_key=API_KEY,
            base_url=BASE_URL,
            top_n=3,
        )
    ),
)

knowledge.add_content(
    name="Agno Docs",
    url="https://docs.agno.com/introduction.md",
    reader=TextReader(
        chunking_strategy=DocumentChunking(
            chunk_size=500,
            overlap=20
        )
    ),
)

agent = Agent(
    model=DashScope(
        id="qwen3-max",
        api_key=API_KEY,
        base_url=BASE_URL,
    ),
    knowledge=knowledge,
    markdown=True,
    debug_mode=True,
    debug_level=2,
)

agent.print_response("what is agno?")
