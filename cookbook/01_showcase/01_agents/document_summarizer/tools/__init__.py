"""
Document Summarizer Tools
=========================

Tools for reading documents from various sources.
"""

from .pdf_reader import read_pdf
from .text_reader import read_text_file
from .web_fetcher import fetch_url

__all__ = ["read_pdf", "read_text_file", "fetch_url"]
