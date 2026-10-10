"""Hand uploaded media to a coding harness by placing it in the workspace.

Claude Code and Codex run as subprocesses with their own file tools, so media reaches them
the way it reaches a person at a terminal: as files in the working directory, named in the
prompt. Images and documents are supported; audio and video have no consumer in either harness.
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from agno.exceptions import UnsupportedMediaError

UPLOADS_DIR = ".agno/uploads"
SUPPORTED_MEDIA = ("images", "files")

_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
    "application/json": "json",
}


@dataclass
class StagedMedia:
    """One attachment as the harness will find it."""

    kind: str  # "image" or "file"
    name: str
    path: Optional[str]  # on disk under the workspace, None for a URL left as a reference
    mime_type: Optional[str] = None
    size: int = 0
    url: Optional[str] = None


def accept_media(media: Dict[str, Any], supported: Sequence[str] = SUPPORTED_MEDIA) -> Dict[str, Any]:
    """Keep the supported kinds that were given; reject the rest before any work starts."""
    unsupported = [name for name, values in media.items() if values and name not in supported]
    if unsupported:
        raise UnsupportedMediaError(
            f"This agent does not support {', '.join(unsupported)} inputs; images and files are placed in "
            "the workspace for the harness to read.",
            media=unsupported,
        )
    accepted = {name: list(values) for name, values in media.items() if values and name in supported}
    return {"media": accepted} if accepted else {}


def uploads_root(workspace: Optional[Any], run_id: str) -> Path:
    return Path(workspace or Path.cwd()) / UPLOADS_DIR / run_id


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"
    return cleaned[:120]


def _mime_for(item: Any) -> Optional[str]:
    """The media object's mime type, or one inferred from its format when the caller only set that."""
    mime = getattr(item, "mime_type", None)
    if mime:
        return str(mime)
    fmt = getattr(item, "format", None)
    if fmt:
        fmt = str(fmt).lower().lstrip(".")
        for known_mime, ext in _EXTENSIONS.items():
            if ext == fmt or (fmt == "jpeg" and ext == "jpg"):
                return known_mime
    return None


def _name_for(item: Any, kind: str, index: int) -> str:
    explicit = getattr(item, "filename", None) or getattr(item, "name", None)
    if explicit:
        return _safe_name(str(explicit))
    filepath = getattr(item, "filepath", None)
    if filepath:
        return _safe_name(Path(str(filepath)).name)
    extension = getattr(item, "format", None) or _EXTENSIONS.get(getattr(item, "mime_type", None) or "", "bin")
    return f"{kind}-{index}.{extension}"


UPLOADS_ROOT_KEY = "uploads_root"
# Earlier runs whose attachments are restored before a turn; older ones stay in the session only.
RESTORED_RUNS_LIMIT = 10


def remember_uploads_root(session: Any, workspace: Optional[Any]) -> None:
    """Record, once per session, the uploads folder the harness's transcript will name.

    Later turns restore earlier attachments there, so the paths already in the transcript
    resolve again on any replica that can write that location.
    """
    if session is None:
        return
    data = getattr(session, "session_data", None)
    if data is None:
        data = {}
        session.session_data = data
    data.setdefault(UPLOADS_ROOT_KEY, str(Path(workspace or Path.cwd()) / UPLOADS_DIR))


def stage_media(
    workspace: Optional[Any],
    run_id: str,
    media: Dict[str, Any],
    root: Optional[Path] = None,
    reuse_existing: bool = False,
) -> List[StagedMedia]:
    """Write each attachment under <workspace>/.agno/uploads/<run_id>/ and describe it.

    Bytes come from the media object's content, file path or base64 payload. A URL with no
    bytes is not downloaded; it is passed to the harness as a reference instead. With
    reuse_existing, a file already at its target path is left as is instead of written again.
    """
    root = root if root is not None else uploads_root(workspace, run_id)
    staged: List[StagedMedia] = []
    claimed: Set[str] = set()
    for kind, key in (("image", "images"), ("file", "files")):
        for index, item in enumerate(media.get(key) or [], start=1):
            name = _name_for(item, kind, index)
            data: Optional[bytes] = None
            getter = getattr(item, "get_content_bytes", None)
            if callable(getter):
                try:
                    data = getter()
                except Exception:
                    data = None
            if data is None and isinstance(getattr(item, "content", None), bytes):
                data = item.content
            url = getattr(item, "url", None)
            if data is None:
                if url:
                    staged.append(StagedMedia(kind, name, None, _mime_for(item), 0, str(url)))
                continue
            root.mkdir(parents=True, exist_ok=True)
            target = root / name
            counter = 1
            # Names are deduplicated within the call, so restaging a run reproduces its original paths.
            while target.name in claimed or (not reuse_existing and target.exists()):
                counter += 1
                target = root / f"{target.stem}-{counter}{target.suffix}"
            claimed.add(target.name)
            # A kept file may have been edited by the harness since; never overwrite it.
            if not (reuse_existing and target.exists()):
                target.write_bytes(data)
            staged.append(StagedMedia(kind, target.name, str(target), _mime_for(item), len(data)))
    return staged


def media_prompt_block(staged: Sequence[StagedMedia]) -> str:
    """The lines appended to the prompt so the harness knows what was attached and where."""
    if not staged:
        return ""
    lines = ["", "Attached files. Read them before answering; images and PDFs can be opened with the file tools:"]
    for item in staged:
        label = item.mime_type or item.kind
        if item.path:
            size = f", {item.size // 1024} KB" if item.size >= 1024 else f", {item.size} bytes"
            lines.append(f"- {item.path} ({label}{size})")
        else:
            lines.append(f"- {item.url} ({label}, remote URL, not downloaded)")
    return "\n".join(lines)


def manifest(staged: Sequence[StagedMedia]) -> List[Dict[str, Any]]:
    return [
        {
            k: v
            for k, v in dict(
                kind=s.kind, name=s.name, path=s.path, mime_type=s.mime_type, size=s.size, url=s.url
            ).items()
            if v
        }
        for s in staged
    ]


def cleanup_media(workspace: Optional[Any], run_id: str) -> None:
    """Remove the run's attachments, and the uploads folders if nothing else is left in them."""
    root = uploads_root(workspace, run_id)
    shutil.rmtree(root, ignore_errors=True)
    for parent in (root.parent, root.parent.parent):
        try:
            parent.rmdir()
        except OSError:
            break


def prior_attachments(
    session: Any,
    exclude_run_id: Optional[str] = None,
    limit: Optional[int] = RESTORED_RUNS_LIMIT,
    until_run_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Attachments on the last `limit` runs of the conversation branch, keyed by the run that received them.

    The branch follows fork ancestry, as history replay does, and ends at until_run_id when a
    continued run's transcript ends there. A fork carries its source's input, so its media is
    keyed by the original run, whose folder the transcript names.
    """
    from agno.agents.base import session_branch

    runs = list(getattr(session, "runs", None) or [])
    branch = session_branch(runs, exclude_run_id=exclude_run_id, until_run_id=until_run_id)
    if limit is not None:
        branch = branch[-limit:] if limit > 0 else []
    forked_from = {run.run_id: run.forked_from_run_id for run in runs if getattr(run, "run_id", None)}
    found: Dict[str, Dict[str, Any]] = {}
    for run in branch:
        if not run.run_id or run.input is None:
            continue
        owner = run.run_id
        seen = {owner}
        while forked_from.get(owner) and forked_from[owner] not in seen:
            owner = forked_from[owner]  # type: ignore[assignment]
            seen.add(owner)
        media = {
            key: list(values) for key, values in (("images", run.input.images), ("files", run.input.files)) if values
        }
        if media and owner not in found:
            found[owner] = media
    return found


def remove_upload_folder(folder: Any) -> None:
    """Remove one run's upload folder and the uploads folders above it if nothing else is left."""
    folder = Path(folder)
    shutil.rmtree(folder, ignore_errors=True)
    for parent in (folder.parent, folder.parent.parent):
        try:
            parent.rmdir()
        except OSError:
            break


def stage_prior_media(
    workspace: Optional[Any],
    session: Any,
    exclude_run_id: Optional[str] = None,
    limit: Optional[int] = RESTORED_RUNS_LIMIT,
    until_run_id: Optional[str] = None,
) -> Tuple[List[Path], str]:
    """Put earlier runs' attachments back where the harness's transcript expects them.

    The session remembers the uploads folder used when the first attachment was staged. Each
    earlier run's files are restored under that folder, so the paths the harness already knows
    resolve again, on the same machine or on a replica with the same layout. When that folder
    cannot be written, the files go under this workspace instead and the returned note tells
    the harness where they are now. Only the last `limit` earlier runs are restored, ending at
    until_run_id when given, and files still on disk are not written again. Returns the folders created, for cleanup, and the note.
    """
    attachments = prior_attachments(session, exclude_run_id, limit, until_run_id)
    if not attachments:
        return [], ""
    recorded = (getattr(session, "session_data", None) or {}).get(UPLOADS_ROOT_KEY)
    current = Path(workspace or Path.cwd()) / UPLOADS_DIR
    target_root = current
    if recorded and Path(recorded) != current:
        try:
            Path(recorded).mkdir(parents=True, exist_ok=True)
            target_root = Path(recorded)
        except OSError:
            target_root = current
    folders: List[Path] = []
    moved: List[str] = []
    for run_id, media in attachments.items():
        folder = target_root / run_id
        existed = folder.exists()
        staged = stage_media(workspace, run_id, media, root=folder, reuse_existing=True)
        if not staged:
            continue
        # A folder that was already there (keep_uploads) belongs to its run, not to this turn.
        if not existed:
            folders.append(folder)
        if recorded and target_root != Path(recorded):
            for item in staged:
                if item.path:
                    moved.append(f"- {item.path} (was {Path(recorded) / run_id / item.name})")
    note = ""
    if moved:
        note = (
            "\n\nThe files attached earlier in this conversation have moved. Their old paths no longer exist; "
            "use these paths instead:\n" + "\n".join(moved)
        )
    return folders, note
