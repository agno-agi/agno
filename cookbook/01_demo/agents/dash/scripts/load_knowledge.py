"""
Load Knowledge - Loads table metadata, queries, and business rules into knowledge base.

Usage:
    python -m agents.dash.scripts.load_knowledge
    python -m agents.dash.scripts.load_knowledge --recreate
"""

import argparse

from ..paths import KNOWLEDGE_DIR

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load knowledge into vector database")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop existing knowledge and reload from scratch",
    )
    args = parser.parse_args()

    from ..agent import dash_knowledge

    if args.recreate:
        print("Recreating knowledge base (dropping existing data)...\n")
        if dash_knowledge.vector_db:
            dash_knowledge.vector_db.drop()
            dash_knowledge.vector_db.create()

    print(f"Loading knowledge from: {KNOWLEDGE_DIR}\n")

    for subdir in ["tables", "queries", "business"]:
        path = KNOWLEDGE_DIR / subdir
        if not path.exists():
            print(f"  {subdir}/: (not found)")
            continue

        files = [
            f for f in path.iterdir() if f.is_file() and not f.name.startswith(".")
        ]
        print(f"  {subdir}/: {len(files)} files")

        if files:
            dash_knowledge.insert(name=f"knowledge-{subdir}", path=str(path))

    print("\nDone!")
