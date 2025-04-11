from typing import List

from scipy.spatial.distance import cosine

from agno.storage.base import Storage
from agno.utils.log import log_warning


def vector_match_message(storage: Storage, session_id: str, query: str, top_k: int = 3) -> List[dict]:
    """
    Find the top-k user messages from a session most similar to the query string.
    """
    from agno.embedder.openai import OpenAIEmbedder

    session = storage.read(session_id=session_id)
    if session is None:
        log_warning(f"Session not found: {session_id}")
        return []

    print(query)

    embedder = OpenAIEmbedder()
    query_embedding = embedder.get_embedding(query)
    if query_embedding is None:
        log_warning(f"Could not compute embedding for query: {query}")
        return []

    messages = session.memory.get("messages", [])
    scored_messages = []

    for msg in messages:
        if msg.get("role") != "user":
            continue
        vector = msg.get("vector")
        if vector is None:
            continue
        score = 1 - cosine(query_embedding, vector)
        scored_messages.append((score, msg))

    # Sort by similarity (descending)
    scored_messages.sort(key=lambda x: x[0], reverse=True)

    message_content = []

    for s, m in scored_messages[:top_k]:
        message_content.append(m.get("content"))

    return "\n".join(message_content)
