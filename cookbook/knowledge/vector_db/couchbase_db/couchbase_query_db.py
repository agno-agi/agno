"""
Couchbase Query Vector DB Example (GSI-based Vector Search)
============================================================

This example demonstrates using CouchbaseQuery, which uses Couchbase's 
General Secondary Indexes (GSI) for vector search via SQL++ queries.
This is available in Couchbase Server 8.0+ and is an alternative to 
the FTS-based CouchbaseSearch.

Key Differences from CouchbaseSearch:
- Uses GSI (SQL++/N1QL) for vector search, not FTS
- Requires Couchbase Server 8.0+ with GSI vector search support
- Supports different search types (ANN, KNN) and similarity metrics
- May offer different performance characteristics compared to FTS

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

# Create CouchbaseQuery vector database
# Note: Embedder is optional - if not provided, OpenAIEmbedder with dimensions=1536 will be used by default
vector_db = CouchbaseQuery(
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
        dimensions=1536,
    ),
    overwrite=True,
)

knowledge = Knowledge(
    name="Couchbase Query Knowledge Base",
    description="This is a knowledge base that uses Couchbase GSI for vector search",
    vector_db=vector_db,
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    knowledge=knowledge,
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)

agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# Clean up
vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
