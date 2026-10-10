"""Hand uploaded media to a coding harness by placing it in the workspace.

Claude Code and Codex run as subprocesses with their own file tools, so media reaches them
the way it reaches a person at a terminal: as files in the working directory, named in the
prompt. Images and documents are supported; audio and video have no consumer in either harness.
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


def stage_media(workspace: Optional[Any], run_id: str, media: Dict[str, Any]) -> List[StagedMedia]:
    """Write each attachment under <workspace>/.agno/uploads/<run_id>/ and describe it.

    Bytes come from the media object's content, file path or base64 payload. A URL with no
    bytes is not downloaded; it is passed to the harness as a reference instead.
    """
    root = uploads_root(workspace, run_id)
    staged: List[StagedMedia] = []
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
            while target.exists():
                counter += 1
                target = root / f"{target.stem}-{counter}{target.suffix}"
            target.write_bytes(data)
            staged.append(StagedMedia(kind, target.name, str(target), _mime_for(item), len(data)))
            # Remember where it was placed; the run records the object, so a later turn on a
            # replica with a different workspace can tell the harness the new path.
            try:
                item.metadata = {**(getattr(item, "metadata", None) or {}), "staged_path": str(target)}
            except Exception:
                pass
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


def prior_attachments(session: Any, exclude_run_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Attachments recorded on earlier runs of the session, keyed by the run that received them.

    They are re-staged under that run's own folder, so the paths the harness's transcript
    already names resolve again on whichever replica runs the next turn.
    """
    found: Dict[str, Dict[str, Any]] = {}
    for run in getattr(session, "runs", None) or []:
        run_id = getattr(run, "run_id", None)
        run_input = getattr(run, "input", None)
        if not run_id or run_id == exclude_run_id or run_input is None:
            continue
        media = {
            key: list(values)
            for key, values in (
                ("images", getattr(run_input, "images", None)),
                ("files", getattr(run_input, "files", None)),
            )
            if values
        }
        if media:
            found[run_id] = media
    return found


def stage_prior_media(
    workspace: Optional[Any], session: Any, exclude_run_id: Optional[str] = None
) -> Tuple[List[str], str]:
    """Re-stage earlier runs' attachments under their original run folders.

    Returns the run ids whose folders were written and a note for the prompt. The note is
    empty when every file is back at the path the harness already knows; when this turn runs
    in a different workspace than the one that received a file, it lists the new location.
    """
    staged_runs: List[str] = []
    moved: List[str] = []
    for run_id, media in prior_attachments(session, exclude_run_id).items():
        previous = {
            id(item): (getattr(item, "metadata", None) or {}).get("staged_path")
            for values in media.values()
            for item in values
        }
        staged = stage_media(workspace, run_id, media)
        if not staged:
            continue
        staged_runs.append(run_id)
        for item, placed in zip([item for values in media.values() for item in values], staged):
            before = previous.get(id(item))
            if placed.path and before and before != placed.path:
                moved.append(f"- {placed.path} (was {before})")
    note = ""
    if moved:
        note = (
            "\n\nThe files attached earlier in this conversation have moved. Their old paths no longer exist; "
            "use these paths instead:\n" + "\n".join(moved)
        )
    return staged_runs, note
