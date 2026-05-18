"""
Batch driver for the invoice labeling cookbook.

Fans out the labeling pipeline over a folder of PDFs with a bounded
concurrency cap (asyncio.Semaphore). One workflow session per document so
each invoice maps cleanly to one warehouse row downstream.

Each run is tagged with rich metadata:
- source_path        absolute path to the source PDF
- source_hash        sha256 of the file bytes (for idempotency lookups)
- labeler_a_model    OpenAI model id used by Labeler A
- labeler_b_model    Anthropic model id used by Labeler B
- schema_version     bump this when Invoice schema changes
- pipeline_version   bump this when the workflow shape changes

Usage:
    python cookbook/data_labeling/run_batch.py cookbook/data_labeling/data/invoices/

Each invoice file becomes one workflow session row in SQLite at
cookbook/data_labeling/tmp/labeling.db, with the entire run history
(both labelers, reviewer report, optional adjudication) stored.
"""

import argparse
import asyncio
import hashlib
import sys
import time
from pathlib import Path
from typing import List

# Make sibling modules importable when this file is run as a script.
sys.path.insert(0, str(Path(__file__).parent))

from agno.media import File  # noqa: E402
from pipeline import build_pipeline  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "1.0.0"
PIPELINE_VERSION = "1.0.0"
DEFAULT_CONCURRENCY = 16


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_pdfs(folder: Path) -> List[Path]:
    if not folder.is_dir():
        raise SystemExit(f"Not a directory: {folder}")
    return sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf")


# ---------------------------------------------------------------------------
# Per-document task
# ---------------------------------------------------------------------------
async def label_one(workflow, pdf_path: Path, semaphore: asyncio.Semaphore) -> dict:
    """Run the pipeline against one PDF inside a concurrency-bounded slot."""
    async with semaphore:
        started = time.monotonic()
        digest = sha256_of(pdf_path)
        session_id = f"invoice-{digest[:16]}"

        try:
            result = await workflow.arun(
                input=(
                    "Extract structured fields from the attached invoice. "
                    "Follow the labeler instructions exactly."
                ),
                files=[File(filepath=str(pdf_path))],
                session_id=session_id,
                metadata={
                    "source_path": str(pdf_path.resolve()),
                    "source_hash": digest,
                    "labeler_a_model": "gpt-5.4",
                    "labeler_b_model": "claude-sonnet-4-5",
                    "schema_version": SCHEMA_VERSION,
                    "pipeline_version": PIPELINE_VERSION,
                },
            )
            elapsed = time.monotonic() - started
            return {
                "path": str(pdf_path),
                "session_id": session_id,
                "status": "ok",
                "duration_s": round(elapsed, 2),
                "run_id": getattr(result, "run_id", None),
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - started
            return {
                "path": str(pdf_path),
                "session_id": session_id,
                "status": "error",
                "duration_s": round(elapsed, 2),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main(folder: Path, concurrency: int) -> None:
    pdfs = discover_pdfs(folder)
    if not pdfs:
        print(
            f"No PDFs found under {folder}. Drop sample invoices in there and re-run."
        )
        return

    print(f"Labeling {len(pdfs)} document(s) with concurrency={concurrency}")
    workflow = build_pipeline()
    semaphore = asyncio.Semaphore(concurrency)

    tasks = [label_one(workflow, pdf, semaphore) for pdf in pdfs]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    ok = sum(1 for r in results if r["status"] == "ok")
    errors = sum(1 for r in results if r["status"] == "error")
    total_time = sum(r["duration_s"] for r in results)

    print("")
    print(f"Done. {ok} succeeded, {errors} failed.")
    print(f"Total wall-clock per-item time summed: {total_time:.1f}s")
    print("")
    for r in results:
        if r["status"] == "ok":
            print(f"  OK   {r['session_id']}  {r['duration_s']}s  {r['path']}")
        else:
            print(
                f"  ERR  {r['session_id']}  {r['duration_s']}s  {r['path']}  -> {r['error_type']}: {r['error']}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch-label invoices with the Agno pipeline."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default="cookbook/data_labeling/data/invoices",
        help="Folder containing invoice PDFs (default: cookbook/data_labeling/data/invoices)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max concurrent agent calls (default: {DEFAULT_CONCURRENCY})",
    )
    args = parser.parse_args()

    asyncio.run(main(Path(args.folder), args.concurrency))
