from typing import TYPE_CHECKING, Any, Dict, Sequence, Union

from agno.workflow.types import StepOutput

if TYPE_CHECKING:
    from agno.run.workflow import WorkflowRunOutput


def _aggregate_media(outputs: Sequence[Union[StepOutput, "WorkflowRunOutput"]]) -> Dict[str, Any]:
    """Collect media produced by direct children without recounting nested results.

    Containers expose their children's media on their own output, so traversing
    ``steps`` as well would duplicate artifacts at every enclosing boundary.
    """
    return {
        "images": [image for output in outputs for image in output.images or []] or None,
        "videos": [video for output in outputs for video in output.videos or []] or None,
        "audio": [audio for output in outputs for audio in output.audio or []] or None,
        "files": [file for output in outputs for file in output.files or []] or None,
    }
