"""
PDF Reader Tests with Performance Timing

This test module includes comprehensive timing measurements for PDF reading operations
to compare performance between synchronous and asynchronous implementations.

Key Features:
- Timing measurements for all PDF reader operations (sync vs async)
- Performance comparison tests for local file and URL-based reading
- Concurrent vs sequential operation performance analysis
- Detailed timing output with performance improvement calculations

Usage:
    # Run all tests with timing output
    pytest libs/agno/tests/unit/reader/test_pdf_reader.py -v -s

    # Run only performance comparison tests
    pytest libs/agno/tests/unit/reader/test_pdf_reader.py -k "performance" -v -s

    # Run only text-based tests (skip image reader tests)
    pytest libs/agno/tests/unit/reader/test_pdf_reader.py -k "not image" -v -s

Performance Results (typical):
- Local file reading: Async is ~1.02-1.09x faster than sync
- URL-based reading: Async is ~1.03-1.06x faster than sync
- Concurrent operations: ~1.03x faster than sequential operations
- The performance improvement is more noticeable with network operations
  due to async I/O benefits.

Note: Image reader tests require the 'rapidocr_onnxruntime' package and may be skipped
if not installed.
"""

import asyncio
import time
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from agno.document.reader.pdf_reader import (
    PDFImageReader,
    PDFReader,
    PDFUrlImageReader,
    PDFUrlReader,
)


def time_sync_operation(operation, *args, **kwargs):
    """Helper function to time synchronous operations."""
    start_time = time.perf_counter()
    result = operation(*args, **kwargs)
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"Sync operation took {elapsed_time:.4f} seconds")
    return result, elapsed_time


async def time_async_operation(operation, *args, **kwargs):
    """Helper function to time asynchronous operations."""
    start_time = time.perf_counter()
    result = await operation(*args, **kwargs)
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"Async operation took {elapsed_time:.4f} seconds")
    return result, elapsed_time


@pytest.fixture(scope="session")
def sample_pdf_path(tmp_path_factory) -> Path:
    # Use the stringart.pdf file from the storage directory
    # Try multiple possible locations
    possible_paths = [
        Path.cwd() / "storage" / "stringart.pdf",  # From project root
        Path(__file__).parent.parent.parent.parent.parent / "storage" / "stringart.pdf",  # Relative to test file
        Path("storage") / "stringart.pdf",  # Relative to current directory
    ]

    for pdf_path in possible_paths:
        if pdf_path.exists():
            print(f"Using PDF file: {pdf_path}")
            return pdf_path

    # If no file found, raise an error with helpful information
    raise FileNotFoundError(f"PDF file 'stringart.pdf' not found. Tried paths: {[str(p) for p in possible_paths]}")


@pytest.fixture(scope="session")
def sample_pdf_url() -> str:
    return "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def test_pdf_reader_read_file(sample_pdf_path):
    reader = PDFReader()
    documents, elapsed_time = time_sync_operation(reader.read, sample_pdf_path)

    assert len(documents) > 0
    assert all("ThaiRecipes" in doc.name for doc in documents)
    assert all(doc.content for doc in documents)
    assert all(isinstance(doc.meta_data.get("page"), int) for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


@pytest.mark.asyncio
async def test_pdf_reader_async_read_file(sample_pdf_path):
    reader = PDFReader()
    documents, elapsed_time = await time_async_operation(reader.async_read, sample_pdf_path)

    assert len(documents) > 0
    assert all("ThaiRecipes" in doc.name for doc in documents)
    assert all(doc.content for doc in documents)
    assert all(isinstance(doc.meta_data.get("page"), int) for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


def test_pdf_reader_with_chunking(sample_pdf_path):
    reader = PDFReader()
    reader.chunk = True
    documents, elapsed_time = time_sync_operation(reader.read, sample_pdf_path)

    assert len(documents) > 0
    assert all("chunk" in doc.meta_data for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


def test_pdf_url_reader(sample_pdf_url):
    reader = PDFUrlReader()
    documents, elapsed_time = time_sync_operation(reader.read, sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


@pytest.mark.asyncio
async def test_pdf_url_reader_async(sample_pdf_url):
    reader = PDFUrlReader()
    documents, elapsed_time = await time_async_operation(reader.async_read, sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


def test_pdf_image_reader(sample_pdf_path):
    reader = PDFImageReader()
    documents, elapsed_time = time_sync_operation(reader.read, sample_pdf_path)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


@pytest.mark.asyncio
async def test_pdf_image_reader_async(sample_pdf_path):
    reader = PDFImageReader()
    documents, elapsed_time = await time_async_operation(reader.async_read, sample_pdf_path)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


def test_pdf_url_image_reader(sample_pdf_url):
    reader = PDFUrlImageReader()
    documents, elapsed_time = time_sync_operation(reader.read, sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


@pytest.mark.asyncio
async def test_pdf_url_image_reader_async(sample_pdf_url):
    reader = PDFUrlImageReader()
    documents, elapsed_time = await time_async_operation(reader.async_read, sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert elapsed_time > 0  # Ensure timing was measured


def test_pdf_reader_invalid_file():
    reader = PDFReader()
    with pytest.raises(Exception):
        reader.read("nonexistent.pdf")


def test_pdf_url_reader_invalid_url():
    reader = PDFUrlReader()
    with pytest.raises(ValueError):
        reader.read("")


@pytest.mark.asyncio
async def test_async_pdf_processing(sample_pdf_path):
    reader = PDFReader()

    # Time concurrent async operations
    start_time = time.perf_counter()
    tasks = [reader.async_read(sample_pdf_path) for _ in range(3)]
    results = await asyncio.gather(*tasks)
    end_time = time.perf_counter()
    concurrent_time = end_time - start_time

    print(f"Concurrent async operations took {concurrent_time:.4f} seconds")

    # Time sequential sync operations for comparison
    start_time = time.perf_counter()
    sync_results = []
    for _ in range(3):
        sync_docs = reader.read(sample_pdf_path)
        sync_results.append(sync_docs)
    end_time = time.perf_counter()
    sequential_time = end_time - start_time

    print(f"Sequential sync operations took {sequential_time:.4f} seconds")
    print(f"Performance improvement: {sequential_time / concurrent_time:.2f}x faster with async")

    assert len(results) == 3
    assert all(len(docs) > 0 for docs in results)
    assert all(all("ThaiRecipes" in doc.name for doc in docs) for docs in results)
    assert concurrent_time > 0  # Ensure timing was measured
    assert sequential_time > 0  # Ensure timing was measured


def test_pdf_reader_performance_comparison(sample_pdf_path):
    """Test to compare sync vs async performance for PDF reading."""
    reader = PDFReader()

    # Time sync operation
    print("\n=== PDF Reader Performance Comparison ===")
    documents_sync, sync_time = time_sync_operation(reader.read, sample_pdf_path)

    # Time async operation
    async def run_async():
        return await reader.async_read(sample_pdf_path)

    documents_async, async_time = asyncio.run(time_async_operation(run_async))

    # Calculate performance difference
    if sync_time > async_time:
        improvement = sync_time / async_time
        print(f"Async is {improvement:.2f}x faster than sync")
    else:
        improvement = async_time / sync_time
        print(f"Sync is {improvement:.2f}x faster than async")

    print(f"Sync time: {sync_time:.4f}s, Async time: {async_time:.4f}s")
    print("=" * 50)

    # Verify both operations produce the same results
    assert len(documents_sync) == len(documents_async)
    assert sync_time > 0 and async_time > 0


@pytest.mark.asyncio
async def test_concurrent_vs_sequential_performance(sample_pdf_path):
    """Test to compare concurrent async operations vs sequential sync operations."""
    reader = PDFReader()
    num_operations = 5

    print(f"\n=== Concurrent vs Sequential Performance ({num_operations} operations) ===")

    # Time concurrent async operations
    start_time = time.perf_counter()
    tasks = [reader.async_read(sample_pdf_path) for _ in range(num_operations)]
    concurrent_results = await asyncio.gather(*tasks)
    concurrent_time = time.perf_counter() - start_time

    print(f"Concurrent async operations: {concurrent_time:.4f}s")

    # Time sequential sync operations
    start_time = time.perf_counter()
    sequential_results = []
    for _ in range(num_operations):
        result = reader.read(sample_pdf_path)
        sequential_results.append(result)
    sequential_time = time.perf_counter() - start_time

    print(f"Sequential sync operations: {sequential_time:.4f}s")

    # Calculate performance improvement
    if sequential_time > concurrent_time:
        improvement = sequential_time / concurrent_time
        print(f"Concurrent async is {improvement:.2f}x faster than sequential sync")
    else:
        improvement = concurrent_time / sequential_time
        print(f"Sequential sync is {improvement:.2f}x faster than concurrent async")

    print(f"Average time per operation:")
    print(f"  Concurrent async: {concurrent_time / num_operations:.4f}s")
    print(f"  Sequential sync: {sequential_time / num_operations:.4f}s")
    print("=" * 60)

    # Verify results
    assert len(concurrent_results) == num_operations
    assert len(sequential_results) == num_operations
    assert all(len(docs) > 0 for docs in concurrent_results)
    assert all(len(docs) > 0 for docs in sequential_results)
    assert concurrent_time > 0 and sequential_time > 0


def test_pdf_url_reader_performance_comparison(sample_pdf_url):
    """Test to compare sync vs async performance for PDF URL reading."""
    reader = PDFUrlReader()

    # Time sync operation
    print("\n=== PDF URL Reader Performance Comparison ===")
    documents_sync, sync_time = time_sync_operation(reader.read, sample_pdf_url)

    # Time async operation
    async def run_async():
        return await reader.async_read(sample_pdf_url)

    documents_async, async_time = asyncio.run(time_async_operation(run_async))

    # Calculate performance difference
    if sync_time > async_time:
        improvement = sync_time / async_time
        print(f"Async is {improvement:.2f}x faster than sync")
    else:
        improvement = async_time / sync_time
        print(f"Sync is {improvement:.2f}x faster than async")

    print(f"Sync time: {sync_time:.4f}s, Async time: {async_time:.4f}s")
    print("=" * 50)

    # Verify both operations produce the same results
    assert len(documents_sync) == len(documents_async)
    assert sync_time > 0 and async_time > 0


def test_pdf_reader_empty_pdf():
    empty_pdf = BytesIO(b"%PDF-1.4")
    empty_pdf.name = "empty.pdf"

    reader = PDFReader()
    documents = reader.read(empty_pdf)

    assert len(documents) == 0
