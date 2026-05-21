"""
ChromaDB Batch Size Limit Test
========================================================

This cookbook demonstrates inserting a large document that produces more than
maximum allowed chunks, which triggers ChromaDB's batch size limit.

ChromaDB has a maximum batch size of 5461 documents per operation due to
SQLite's max variable number limit set to 32766 divided by 6 variables per record.
"""

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.vectordb.chroma import ChromaDb

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1000  # Small chunk size to generate many chunks
TARGET_CHUNKS = 6000  # Exceeds the max allowed limit
TEXT_SIZE = CHUNK_SIZE * TARGET_CHUNKS

# ---------------------------------------------------------------------------
# Generate Large Text Document
# ---------------------------------------------------------------------------

paragraph_template = """
Section {section}: Technical Overview of System Component {component}

This section provides detailed information about component {component} of the system.
The component is responsible for handling various operations and maintaining state.
Key features include data processing, error handling, and integration with other
system components. Performance characteristics depend on configuration parameters
and operational environment. Refer to the configuration guide for optimal settings.

Implementation Details:
- Module initialization occurs during system startup
- Resource allocation follows best practices for memory management
- Error recovery mechanisms ensure system stability
- Logging provides detailed diagnostics for troubleshooting

Configuration Parameters:
- timeout: Maximum wait time for operations (default: 30 seconds)
- buffer_size: Internal buffer allocation (default: 1024 bytes)
- retry_count: Number of retry attempts on failure (default: 3)
- enable_logging: Toggle diagnostic output (default: true)

For more information, consult the API documentation and implementation guide.
"""

paragraph_size = len(paragraph_template.format(section=1, component=1))
num_paragraphs = (TEXT_SIZE // paragraph_size) + 1

large_text = ""
for i in range(num_paragraphs):
    large_text += paragraph_template.format(section=i + 1, component=i + 1)

actual_text_size = len(large_text)
expected_chunks = actual_text_size // CHUNK_SIZE

# ---------------------------------------------------------------------------
# Setup Knowledge Base with ChromaDB
# ---------------------------------------------------------------------------

print("Setting up ChromaDB knowledge base...")

knowledge = Knowledge(
    name="Large Document Test",
    vector_db=ChromaDb(
        collection="large_doc_test",
        path="tmp/chromadb_batch_test",
        persistent_client=True,
    ),
)

reader = TextReader(
    chunking_strategy=FixedSizeChunking(chunk_size=CHUNK_SIZE, overlap=0)
)

knowledge.insert(
    name="Large Technical Manual",
    text_content=large_text,
    reader=reader,
)

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

knowledge.vector_db.drop()
