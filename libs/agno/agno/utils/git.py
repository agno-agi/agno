from pathlib import Path
from typing import Optional

import git

from agno.utils.log import log_debug


def get_remote_origin_for_dir(
    ws_root_path: Optional[Path],
) -> Optional[str]:
    """Returns the remote origin for a directory"""

    if ws_root_path is None or not ws_root_path.exists() or not ws_root_path.is_dir():
        return None

    _remote_origin: Optional[git.Remote] = None
    try:
        _git_repo: git.Repo = git.Repo(path=ws_root_path)
        _remote_origin = _git_repo.remote("origin")
    except (git.InvalidGitRepositoryError, ValueError):
        return None
    except git.NoSuchPathError:
        return None

    if _remote_origin is None:
        return None

    # TODO: Figure out multiple urls for origin and how to only get the fetch url
    # _remote_origin.urls returns a generator
    _remote_origin_url: Optional[str] = None
    for _remote_url in _remote_origin.urls:
        _remote_origin_url = _remote_url
        break
    return _remote_origin_url


class GitCloneProgress(git.RemoteProgress):
    # https://gitpython.readthedocs.io/en/stable/reference.html#module-git.remote
    # def line_dropped(self, line):
    #     print("line dropped: {}".format(line))

    def update(self, op_code, cur_count, max_count=None, message=""):
        if op_code == 5:
            log_debug("Starting copy")
        if op_code == 10:
            log_debug("Copy complete")
        # log_debug(f"op_code: {op_code}")
        # log_debug(f"cur_count: {cur_count}")
        # log_debug(f"max_count: {max_count}")
        # log_debug(f"message: {message}")
        # print(self._cur_line)
