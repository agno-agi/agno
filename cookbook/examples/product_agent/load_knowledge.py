"""Index the sample product document before starting the API.
Run again after editing product.md to refresh the searchable content.
"""

from product_agent import knowledge

# ---------------------------------------------------------------------------
# Create the document input
# ---------------------------------------------------------------------------
DOCUMENT = "product.md"

# ---------------------------------------------------------------------------
# Run the loader
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    knowledge.insert(name="Product documentation", path=DOCUMENT)
