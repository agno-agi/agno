## Summary

This PR introduces support for **Moss VectorDB**, a high-performance vector database that handles embeddings internally and provides sub-10ms semantic search.

### Key Changes:
1.  **New VectorDB Provider**: Implemented the `Moss` class in `libs/agno/agno/vectordb/moss/moss.py`, fully compliant with the `VectorDb` interface.
2.  **Robust Metadata Handling**: Implemented automatic stringification of all metadata keys and values to ensure seamless compatibility with the `inferedge-moss` client.
3.  **Configurable Search**: Added support for the `alpha` parameter (hybrid search weighting) and user-controlled `top_k` (via `limit`). Parameters can be set during initialization or overridden per-search via the `filters` argument.
4.  **Cookbook Integration**: Added a comprehensive cookbook recipe in `cookbook/08_knowledge/vector_db/moss_db/moss_db.py` demonstrating:
    - Initializing Moss with custom parameters.
    - Creating a Knowledge Base.
    - Using Google Gemini (gemini-2.0-flash-001) for retrieval-augmented generation.
    - Implementing a system prompt to ensure reliable tool usage for domain-specific queries.

## Type of change

- [ ] Bug fix
- [X] New feature
- [ ] Breaking change
- [X] Improvement
- [ ] Model update
- [ ] Other:

---

## Checklist

- [X] Code complies with style guidelines
- [X] Ran format/validation scripts (`./scripts/format.sh` and `./scripts/validate.sh`)
- [X] Self-review completed
- [X] Documentation updated (comments, docstrings)
- [X] Examples and guides: Relevant cookbook examples have been included or updated
- [X] Tested in clean environment
- [X] Tests added/updated (Verified with cookbook example)

---

## Additional Notes

- **Dependency**: Requires `inferedge-moss` (installable via `pip install inferedge-moss`).
- **Performance**: Moss handles embeddings on the server side, reducing client-side compute and latency.
- **Verification**: The implementation has been verified to correctly handle document insertion, async operations, and semantic search queries (including potential safety refusals by using a dedicated system prompt).
