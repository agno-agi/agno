"""
Async Couchbase Query Vector DB Example (GSI-based Vector Search)
==================================================================

This example demonstrates using CouchbaseQuery asynchronously, which uses 
Couchbase's General Secondary Indexes (GSI) for vector search via SQL++ queries.

Setup Couchbase Cluster (Local via Docker):
-------------------------------------------
1. Run Couchbase 8.0+ locally:

   docker run -d --name couchbase-server \
     -p 8091-8096:8091-8096 \
     -p 11210:11210 \
     -e COUCHBASE_ADMINISTRATOR_USERNAME=Administrator \
     -e COUCHBASE_ADMINISTRATOR_PASSWORD=password \
     couchbase:latest

2. Access the Couchbase UI at: http://localhost:8091
   (Login with the username and password above)

3. Create a new cluster. You can select "Finish with defaults".

4. Create a bucket named 'recipe_bucket', a scope 'recipe_scope', and a collection 'recipes'.

Managed Couchbase (Capella):
----------------------------
- For a managed cluster, use Couchbase Capella: https://cloud.couchbase.com/
- Follow Capella's UI to create a database, bucket, scope, and collection as above.

Environment Variables (export before running):
----------------------------------------------
Create a shell script (e.g., set_couchbase_env.sh):

    export COUCHBASE_USER="Administrator"
    export COUCHBASE_PASSWORD="password"
    export COUCHBASE_CONNECTION_STRING="couchbase://localhost"
    export OPENAI_API_KEY="<your-openai-api-key>"

# For Capella, set COUCHBASE_CONNECTION_STRING to the Capella connection string.

Install couchbase-sdk:
----------------------
    pip install couchbase
"""

import asyncio
import os

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.couchbase import CouchbaseQuery
from couchbase.auth import PasswordAuthenticator
from couchbase.options import ClusterOptions, KnownConfigProfiles

# Couchbase connection settings
username = os.getenv("COUCHBASE_USER")
password = os.getenv("COUCHBASE_PASSWORD")
connection_string = os.getenv("COUCHBASE_CONNECTION_STRING")

# Create cluster options with authentication
auth = PasswordAuthenticator(username, password)
cluster_options = ClusterOptions(auth)
cluster_options.apply_profile(KnownConfigProfiles.WanDevelopment)

knowledge_base = Knowledge(
    vector_db=CouchbaseQuery(
        bucket_name="recipe_bucket",
        scope_name="recipe_scope",
        collection_name="recipes",
        couchbase_connection_string=connection_string,
        cluster_options=cluster_options,
        search_type="ANN",  # Can be "ANN" or "KNN"
        similarity="DOT",  # Can be "COSINE", "DOT", "L2", "EUCLIDEAN", etc.
        n_probes=10,  # Number of probes for ANN search
        # Embedder is optional - if not provided, OpenAIEmbedder with dimensions=1536 will be used by default
        embedder=OpenAIEmbedder(
            id="text-embedding-3-large",
            dimensions=3072,
            api_key=os.getenv("OPENAI_API_KEY"),
        ),
        overwrite=True,
    ),
)

# Create and use the agent
agent = Agent(knowledge=knowledge_base, search_knowledge=True, read_chat_history=True)


async def run_agent():
    await knowledge_base.add_content_async(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book"},
    )
    await agent.aprint_response("How to make Thai curry?", markdown=True)


if __name__ == "__main__":
    asyncio.run(run_agent())
