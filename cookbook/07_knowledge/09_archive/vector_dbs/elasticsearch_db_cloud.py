"""
Elasticsearch on Elastic Cloud

The other Elasticsearch examples connect to a local cluster over plain HTTP. This one
shows the hosted path: authenticating to Elastic Cloud, or to any TLS-protected
cluster, instead of running one yourself.

Three ways to connect, in the order you are most likely to want them:

1. cloud_id + api_key - the Elastic Cloud default. The cloud id is on the deployment
   page; the API key is created under Stack Management > API keys.
2. url + api_key - a self-hosted cluster reachable over https.
3. url + basic_auth - username and password, when no API key is available.

Certificates: a managed deployment presents a publicly trusted certificate, so nothing
extra is needed. A self-hosted cluster usually presents its own, so point ca_certs at
the CA bundle. Leave verify_certs at its default of True - turning it off disables the
check that the cluster is who it claims to be.

Requirements:
- An Elastic Cloud deployment (or any reachable https cluster)
- uv pip install "elasticsearch[async]"
- ELASTIC_CLOUD_ID and ELASTIC_API_KEY exported
- OPENAI_API_KEY
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.elasticsearch import Elasticsearch

CLOUD_ID = os.getenv("ELASTIC_CLOUD_ID")
API_KEY = os.getenv("ELASTIC_API_KEY")

if not CLOUD_ID or not API_KEY:
    raise SystemExit(
        "Set ELASTIC_CLOUD_ID and ELASTIC_API_KEY to run this example. "
        "Both are on your Elastic Cloud deployment page."
    )

# 1. Elastic Cloud: cloud_id replaces url entirely
vector_db = Elasticsearch(
    index_name="recipes_cloud",
    cloud_id=CLOUD_ID,
    api_key=API_KEY,
)

# 2. A self-hosted https cluster with an API key
# vector_db = Elasticsearch(
#     index_name="recipes_cloud",
#     url="https://my-cluster.example.com:9243",
#     api_key=API_KEY,
#     ca_certs="/path/to/http_ca.crt",
# )

# 3. Username and password instead of an API key
# vector_db = Elasticsearch(
#     index_name="recipes_cloud",
#     url="https://my-cluster.example.com:9243",
#     basic_auth=("elastic", os.environ["ELASTIC_PASSWORD"]),
#     ca_certs="/path/to/http_ca.crt",
# )

knowledge = Knowledge(
    name="Elastic Cloud Recipe Knowledge Base",
    description="This is a knowledge base that uses Elasticsearch on Elastic Cloud",
    vector_db=vector_db,
)

knowledge.insert(
    name="Thai Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    search_knowledge=True,
    # A db is required for the agent to read its own chat history
    db=SqliteDb(db_file="tmp/elasticsearch_cloud.db"),
    read_chat_history=True,
    markdown=True,
)

agent.print_response("How to make Thai curry?", stream=True)

vector_db.close()
