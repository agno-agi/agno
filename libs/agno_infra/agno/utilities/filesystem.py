from pathlib import Path


def rmdir_recursive(dir_path: Path) -> bool:
    """Deletes dir_path recursively, including all files and dirs in that directory
    Returns True if dir deleted successfully.
    """

    if not dir_path.exists():
        return True

    if dir_path.is_dir():
        from shutil import rmtree

        rmtree(path=dir_path, ignore_errors=True)
    elif dir_path.is_file():
        dir_path.unlink(missing_ok=True)

    return True if not dir_path.exists() else False


def delete_files_in_dir(dir: Path) -> None:
    """Deletes all files in a directory, but doesn't delete the directory"""

    for item in dir.iterdir():
        if item.is_dir():
            rmdir_recursive(item)
        else:
            item.unlink()


def delete_from_fs(path_to_del: Path) -> bool:
    if not path_to_del.exists():
        return True
    if path_to_del.is_dir():
        return rmdir_recursive(path_to_del)
    else:
        path_to_del.unlink()
    return True if not path_to_del.exists() else False
