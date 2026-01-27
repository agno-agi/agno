"""
Contract Review Agent Examples
==============================

Run the contract review agent on sample documents.
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agno.media import File
from agent import contract_agent

from schemas import ContractReview
# Get documents directory
DOCS_DIR = Path(__file__).parent.parent / "documents"


def review_all_documents():
    """Review all documents in the documents folder."""
    documents = list(DOCS_DIR.glob("*.pdf")) + list(DOCS_DIR.glob("*.txt"))

    for doc in documents:
        print("\n" + "=" * 60)
        print(f"Reviewing: {doc.name}")
        print("=" * 60)

        contract_agent.print_response(
            "Analyze this contract and identify key risks.",
            files=[File(filepath=doc)],
            stream=True,
        )


def review_single_document(filename: str):
    """Review a specific document."""
    doc_path = DOCS_DIR / filename

    if not doc_path.exists():
        print(f"File not found: {doc_path}")
        return

    print(f"Reviewing: {filename}")
    print("=" * 60)

    contract_agent.print_response(
        "Analyze this contract and identify key risks.",
        files=[File(filepath=doc_path)],
        stream=True,
    )


if __name__ == "__main__":
    # Review a single document
    review_single_document("Sample_NDA.pdf")
    contract_agent.output_schema=ContractReview
    #updated with schema
    review_single_document("Sample_NDA.pdf")
    # Or review all documents
    #review_all_documents()
