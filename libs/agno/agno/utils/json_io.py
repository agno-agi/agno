import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from agno.utils.log import log_debug


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime) or isinstance(o, date):
            return o.isoformat()

        if isinstance(o, Path):
            return str(o)

        return json.JSONEncoder.default(self, o)


def read_json_file(file_path: Optional[Path]) -> Optional[Union[Dict, List]]:
    if file_path is not None and file_path.exists() and file_path.is_file():
        # log_debug(f"Reading {file_path}")
        return json.loads(file_path.read_text())
    return None


def write_json_file(file_path: Optional[Path], data: Optional[Union[Dict, List]], **kwargs) -> None:
    if file_path is not None and data is not None:
        log_debug(f"Writing {file_path}")
        file_path.write_text(json.dumps(data, cls=CustomJSONEncoder, indent=4, **kwargs))
