"""
Contract Review Agent
=====================

An intelligent contract review agent that analyzes legal documents, extracts
key terms and obligations, and flags potential risks or unusual clauses.
"""

from .agent import contract_agent
from .schemas import ContractReview

__all__ = ["contract_agent", "ContractReview"]
