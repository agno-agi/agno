# 📘 RedisVL Integration with Agno

This guide walks through how to integrate the RedisVL vector database with the Agno framework for structured document ingestion, semantic retrieval, and intelligent querying using an agent-based architecture.

---

## 📌 Overview

The integration leverages:

- **RedisVL** for storing and retrieving vectorized document embeddings  
- **CSVKnowledgeBase** to load and manage knowledge from CSV files  
- **OpenAIEmbedder** to embed text using OpenAI models  
- **Agno Agent** to perform reasoning over the ingested data

---

## 🔧 Prerequisites

Install the required Python packages:

```bash
pip install redis redisvl openai numpy
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=your-key
```

Ensure your Python path includes the `libs/agno` directory:

```python
import sys
sys.path.append("/path/to/your/agno/libs/agno")
```

---

## 🏗️ Project Structure

```
project/
├── main.py
├── libs/
│   └── agno/
│       └── agno/
│           ├── agent/
│           ├── embedder/
│           ├── knowledge/
│           └── vectordb/
├── questions_set.csv
```

---

## 🔌 Redis Connection

You can connect to a Redis server using:

```python
redis_connection_string = "redis://localhost:6379"
```

Other formats:

```
redis://user:password@remote-server:6379/0
redis://localhost:6379/0
redis://localhost:6379/1
```

---

## 📥 Load CSV Documents

```python
from libs.agno.agno.knowledge.csv import CSVKnowledgeBase, CSVReader
from libs.agno.agno.vectordb.redisvl.redisvl import RedisVL
from libs.agno.agno.embedder.openai import OpenAIEmbedder

knowledge_base = CSVKnowledgeBase(
    path="/path/to/questions_set.csv",
    reader=CSVReader(chunk_size=50),
    vector_db=RedisVL(
        db_url=redis_connection_string,
        search_index_name="questions_set",
        field_names=["question1", "question_2", "is_duplicate"],
        embedder=OpenAIEmbedder()
    ),
    num_documents=2
)
```

### Load and Index Data

```python
knowledge_base.load(recreate=True, upsert=False, skip_existing=False)
```

---

## 🤖 Create an Agno Agent

```python
from libs.agno.agno.agent.agent import Agent

query = "I'm a triple Capricorn (Sun, Moon and ascendant in Capricorn) What does that say about me?"

agent = Agent(
    description="An agent that finds if the query is a duplicate of ingested documents or not.",
    instructions=[
        "Is the user query a duplicate to any queries stored in knowledge base? Return True if duplicate, otherwise False."
    ],
    knowledge=knowledge_base,
    search_knowledge=True,
    show_tool_calls=True,
    markdown=True
)

agent.print_response(query, markdown=True)
```

---

## 🔄 Full Document Lifecycle

| Operation        | Method                        |
|------------------|-------------------------------|
| Create Index     | `.load(recreate=True)`        |
| Insert Documents | `.load(upsert=True)`          |
| Search           | `.search(query)`              |
| Delete Index     | `.drop()`                     |
| Async Support    | `.async_*()` methods          |

---

## ⚙️ Configuration Parameters

| Parameter           | Description                                        |
|---------------------|----------------------------------------------------|
| `db_url`            | Redis connection string                            |
| `search_index_name` | Name of the Redis Search index                     |
| `field_names`       | CSV column names to vectorize                      |
| `embedder`          | Instance of Agno-compatible embedder (e.g., OpenAIEmbedder) |
| `distance_metric`   | `cosine`, `l2`, or `ip`                            |
| `distance_threshold`| (Optional) Distance threshold for similarity       |

---

## ✅ Summary

With RedisVL and Agno:

- You can ingest structured datasets from CSV files  
- Embed them with OpenAI  
- Store and search them efficiently using Redis  
- Query them intelligently using an Agent-based framework  

This enables **semantic search and reasoning** on structured data with ease.