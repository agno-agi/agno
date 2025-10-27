from os import getenv

from agno.agent.agent import Agent
from agno.embedder.azure_openai import AzureOpenAIEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.azureaisearch import AzureAISearch
from agno.vectordb.search import SearchType

# Azure AI Search Config
AZURE_SEARCH_ENDPOINT = getenv(
    "SEARCH_ENDPOINT"
)  #  Azure AI Search Endpoint: https://<your-search-instance>.search.windows.net
AZURE_SEARCH_API_KEY = getenv("SEARCH_API_KEY")  # Search index api key
INDEX_NAME = "thai-recipe-index"  # Index name

# Azure OpenAI Embedding Model Config
EMBED_API_KEY = getenv("EMBED_API_KEY")  # Azure OpenAI embedding model api key
EMBED_MODEL = getenv("EMBED_MODEL")  # Type of embedding model: text-embedding-3-large
EMBED_DEPLOYMENT = getenv("EMBED_DEPLOYMENT")  # Name of your embedding model deployment
EMBED_ENDPOINT = getenv("EMBED_ENDPOINT")  # Embedding model endpoint
# https://<specified-name>.cognitiveservices.azure.com/openai/deployments/<deployment-name>/embeddings?api-version=<api-version>
EMBED_VERSION = getenv("EMBED_VERSION")  # Embedding model api version

embedder = AzureOpenAIEmbedder(
    id=EMBED_MODEL,
    dimensions=3072,
    api_key=EMBED_API_KEY,
    azure_endpoint=EMBED_ENDPOINT,
    api_version=EMBED_VERSION,
    azure_deployment=EMBED_DEPLOYMENT,
)

vector_db = AzureAISearch(
    endpoint=AZURE_SEARCH_ENDPOINT,
    api_key=AZURE_SEARCH_API_KEY,
    index_name=INDEX_NAME,
    embedder=embedder,
    search_type=SearchType.hybrid,
)

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

knowledge_base.load(upsert=True)

agent = Agent(knowledge=knowledge_base, show_tool_calls=True, search_knowledge=True)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", markdown=True
)
