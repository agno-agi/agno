from dataclasses import dataclass
from typing import Any

from agno.file import File
from agno.utils.common import dataclass_to_dict


@dataclass
class TextFile(File):
    path: str = ""  # type: ignore
    type: str = "TEXT"

    def get_metadata(self) -> dict[str, Any]:
        if self.name is None:
            from pathlib import Path

            self.name = Path(self.path).name

        return dataclass_to_dict(self, exclude_none=True)
