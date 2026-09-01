"""Moved to ``agno.tools.file``.

Kept so ``from agno.tools.file_generation import FileGenerationTools`` keeps working for
code written against 2.x and 3.0.
"""

from agno.tools.file.generation import CODE_LANGUAGE_MAP, DOCX_AVAILABLE, PDF_AVAILABLE, FileGenerationTools

__all__ = [
    "CODE_LANGUAGE_MAP",
    "DOCX_AVAILABLE",
    "FileGenerationTools",
    "PDF_AVAILABLE",
]
