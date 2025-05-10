"""Util logic shared by all eval modules"""

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.eval.accuracy import AccuracyResult
    from agno.eval.performance import PerformanceResult
    from agno.eval.reliability import ReliabilityResult


def store_result_in_file(
    file_path: str,
    result: Union["AccuracyResult", "PerformanceResult", "ReliabilityResult"],
    eval_id: Optional[str] = None,
    name: Optional[str] = None,
):
    """Store the given result in the given file path"""
    try:
        import json

        fn_path = Path(file_path.format(name=name, eval_id=eval_id))
        if not fn_path.parent.exists():
            fn_path.parent.mkdir(parents=True, exist_ok=True)
        fn_path.write_text(json.dumps(asdict(result), indent=4))
    except Exception as e:
        logger.warning(f"Failed to save result to file: {e}")
