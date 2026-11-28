"""Hand uploaded media to a coding harness by placing it in the workspace.

Claude Code and Codex run as subprocesses with their own file tools, so media reaches them
the way it reaches a person at a terminal: as files in the working directory, named in the
prompt. Images and documents are supported; audio and video have no consumer in either harness.
"""

import re
import shutil
from base64 import b64encode
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from agno.exceptions import MediaStagingError, UnsupportedMediaError
from agno.utils.media import get_image_type

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
    inline: bool = False  # sent to the model inside the prompt rather than opened from disk


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
    """Resolve an upload directory without allowing IDs or symlinks to escape it."""
    if not run_id or run_id in (".", "..") or "/" in run_id or "\\" in run_id or "\x00" in run_id or ":" in run_id:
        raise MediaStagingError("Attachment run_id must be a single nonempty path component")
    workspace_root = Path(workspace or Path.cwd()).resolve()
    root = workspace_root / UPLOADS_DIR / run_id
    for directory in (root.parent.parent, root.parent, root):
        if directory.is_symlink():
            raise MediaStagingError("Attachment directories must not be symlinks")
    return root


def _rollback_files(paths: Sequence[Path]) -> None:
    """Remove only files created by this staging operation, retaining preexisting files."""
    for path in reversed(paths):
        with suppress(OSError):
            path.unlink()
        for directory in (path.parent, path.parent.parent, path.parent.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                break


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"
    if len(cleaned) <= 120:
        return cleaned
    suffix = Path(cleaned).suffix
    if len(suffix) > 16:
        suffix = ""
    return cleaned[: 120 - len(suffix)] + suffix


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


def _mime_from_bytes(data: bytes) -> Optional[str]:
    """The mime type the bytes announce, used only when the caller named no type or format.
    Images go through the library's shared signature check; a PDF is the one document type
    a model takes inline."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    detected = get_image_type(data)
    return f"image/{detected}" if detected else None


def _name_for(item: Any, kind: str, index: int) -> str:
    # Names depend only on what the caller set: earlier runs are re-staged under the same names
    # their transcripts already mention, so nothing learned from the bytes may change them.
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

    This is a historical locator for relocation notes, never permission to write outside
    the active workspace. Later turns restore into their own workspace.
    """
    if session is None:
        return
    data = getattr(session, "session_data", None)
    if data is None:
        data = {}
        session.session_data = data
    data.setdefault(UPLOADS_ROOT_KEY, str(Path(workspace or Path.cwd()).resolve() / UPLOADS_DIR))


def stage_media(
    workspace: Optional[Any],
    run_id: str,
    media: Dict[str, Any],
    root: Optional[Path] = None,
    reuse_existing: bool = False,
    _created: Optional[List[Path]] = None,
) -> List[StagedMedia]:
    """Write each attachment under <workspace>/.agno/uploads/<run_id>/ and describe it.

    Bytes come from the media object's content, file path or base64 payload. A URL with no
    bytes is not downloaded; it is passed to the harness as a reference instead. With
    reuse_existing, a file already at its target path is left as is instead of written again.
    """
    expected_root = uploads_root(workspace, run_id)
    if root is not None and root.absolute() != expected_root:
        raise MediaStagingError("Attachments must be staged under the active workspace uploads directory")
    root = expected_root
    staged: List[StagedMedia] = []
    created: List[Path] = []
    root_existed = root.exists()
    claimed: Set[str] = set()
    try:
        for kind, key in (("image", "images"), ("file", "files")):
            for index, item in enumerate(media.get(key) or [], start=1):
                name = _safe_name(_name_for(item, kind, index))
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
                detected = _mime_from_bytes(data) if data and not _mime_for(item) else None
                if data is None:
                    if url:
                        staged.append(StagedMedia(kind, name, None, _mime_for(item), 0, str(url)))
                    continue
                root.mkdir(parents=True, exist_ok=True)
                uploads_root(workspace, run_id)
                target = root / name
                counter = 1
                while True:
                    if target.is_symlink():
                        raise MediaStagingError("Attachment files must not be symlinks")
                    if target.name not in claimed:
                        if reuse_existing and target.is_file():
                            break
                        try:
                            # Exclusive creation cannot overwrite an existing file or follow a leaf symlink.
                            with target.open("xb") as output:
                                created.append(target)
                                output.write(data)
                            break
                        except FileExistsError:
                            pass
                    counter += 1
                    target = root / f"{target.stem}-{counter}{target.suffix}"
                claimed.add(target.name)
                staged.append(StagedMedia(kind, target.name, str(target), _mime_for(item) or detected, len(data)))
    except BaseException:
        _rollback_files(created)
        if not root_existed:
            for directory in (root, root.parent, root.parent.parent):
                try:
                    directory.rmdir()
                except OSError:
                    break
        raise
    if _created is not None:
        _created.extend(created)
    return staged


def cleanup_staged_media(staged: Sequence[StagedMedia]) -> None:
    """Remove staged input files without removing preexisting files in the run directory."""
    _rollback_files([Path(item.path) for item in staged if item.path])


def cleanup_run_media(workspace: Optional[Any], run_id: str, staged: Sequence[StagedMedia], created_root: bool) -> None:
    """Remove a run's attachments after the turn.

    A run folder this staging created holds nothing but this run's work, so it goes whole,
    including files the harness wrote next to the inputs. A folder that already existed keeps
    everything except the staged inputs.
    """
    if not staged:
        return
    if created_root:
        with suppress(ValueError):
            remove_upload_folder(uploads_root(workspace, run_id))
        return
    cleanup_staged_media(staged)


# Formats a model reads directly when they arrive inside the message. Everything else stays a file
# the harness opens with its tools.
INLINE_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
INLINE_DOCUMENT_TYPES = ("application/pdf",)
# Above this an attachment stays on disk only: the model API refuses larger inline images, and a
# harness tool reads a large PDF page by page better than one message can carry it.
INLINE_MAX_BYTES = 4 * 1024 * 1024


def inline_blocks(staged: Sequence[StagedMedia], limit: int = INLINE_MAX_BYTES) -> List[Dict[str, Any]]:
    """Content blocks for the staged images and PDFs a model can take inside the prompt.

    Each attachment that becomes a block is marked inline. The file stays on disk as well, so a
    program the harness writes can still open it. A model that sees an image in its message has
    no reason to read the file back through a tool, which is what put the file's bytes into the
    run's tool results and events.
    """
    blocks: List[Dict[str, Any]] = []
    for item in staged:
        if not item.path or item.size > limit:
            continue
        try:
            data = Path(item.path).read_bytes()
        except OSError:
            continue
        # The bytes decide, not the declared type: the API rejects a block whose data is not what
        # its media type says, and a mislabelled file is better left on disk for the file tools.
        mime = _mime_from_bytes(data)
        if mime in INLINE_IMAGE_TYPES:
            block_type = "image"
        elif mime in INLINE_DOCUMENT_TYPES:
            block_type = "document"
        else:
            continue
        blocks.append(
            {"type": block_type, "source": {"type": "base64", "media_type": mime, "data": b64encode(data).decode()}}
        )
        item.inline = True
    return blocks


def media_prompt_block(staged: Sequence[StagedMedia]) -> str:
    """The lines appended to the prompt so the harness knows what was attached and where."""
    if not staged:
        return ""
    lines = ["", "Attached files:"]
    for item in staged:
        label = item.mime_type or item.kind
        if item.path:
            size = f", {item.size // 1024} KB" if item.size >= 1024 else f", {item.size} bytes"
            if item.inline:
                note = "; already included in this message, do not read it, the file is on disk for programs"
            else:
                note = "; read it with the file tools before answering"
            lines.append(f"- {item.path} ({label}{size}{note})")
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
    """Restore recent attachments inside the active workspace and describe relocated paths.

    Stored absolute paths are historical metadata, not write authority. Existing regular
    files are retained, and a partial restore rolls back only files created by this call.
    """
    attachments = prior_attachments(session, exclude_run_id, limit, until_run_id)
    if not attachments:
        return [], ""
    recorded = (getattr(session, "session_data", None) or {}).get(UPLOADS_ROOT_KEY)
    current = Path(workspace or Path.cwd()).resolve() / UPLOADS_DIR
    folders: List[Path] = []
    created: List[Path] = []
    moved: List[str] = []
    try:
        for run_id, media in attachments.items():
            folder = uploads_root(workspace, run_id)
            existed = folder.exists()
            staged = stage_media(workspace, run_id, media, reuse_existing=True, _created=created)
            if not staged:
                continue
            if not existed:
                folders.append(folder)
            if recorded and current != Path(recorded):
                for item in staged:
                    if item.path:
                        moved.append(f"- {item.path} (was {Path(recorded) / run_id / item.name})")
    except BaseException:
        _rollback_files(created)
        raise
    note = ""
    if moved:
        note = (
            "\n\nThe files attached earlier in this conversation have moved. "
            "Use these paths in the current workspace instead:\n" + "\n".join(moved)
        )
    return folders, note
