"""
Docling Reader: Input Types
===========================
DoclingReader.read() accepts several kinds of `file` input. This example shows
each supported type resolving to the same document.

Supported `file` inputs:
- Path object            -> Path("cv_1.pdf")
- Local file path string -> "cookbook/.../cv_1.pdf"
- URL string             -> "https://.../file.pdf"
- File-like object       -> BytesIO(...)
"""

from io import BytesIO
from pathlib import Path

from agno.knowledge.reader.docling_reader import DoclingReader

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

PDF_PATH = "cookbook/07_knowledge/testing_resources/cv_1.pdf"
reader = DoclingReader(output_format="markdown")

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Local file path as a Path object ---
    print("\n" + "=" * 60)
    print("Local file: Path object")
    print("=" * 60 + "\n")

    docs = reader.read(Path(PDF_PATH))
    print(f"name={docs[0].name} chars={len(docs[0].content)}")

    # --- Local file path as a string ---
    print("\n" + "=" * 60)
    print("Local file: path string")
    print("=" * 60 + "\n")

    docs = reader.read(PDF_PATH)
    print(f"name={docs[0].name} chars={len(docs[0].content)}")

    # --- File-like object (BytesIO) ---
    print("\n" + "=" * 60)
    print("File-like object: BytesIO")
    print("=" * 60 + "\n")

    with open(PDF_PATH, "rb") as f:
        buffer = BytesIO(f.read())
    buffer.name = "cv_1.pdf"

    docs = reader.read(buffer)
    print(f"name={docs[0].name} chars={len(docs[0].content)}")

    # --- Remote file via URL string ---
    print("\n" + "=" * 60)
    print("Remote file: URL string")
    print("=" * 60 + "\n")

    docs = reader.read(
        "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf"
    )
    print(f"name={docs[0].name} chars={len(docs[0].content)}")
