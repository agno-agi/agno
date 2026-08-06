"""Merge team-scoped media into kwargs for delegated member runs.

Used when ``Team.add_team_media_to_delegation`` is enabled so
``member_agent.run`` / ``arun`` receive prior team-level inputs and team-visible
attachments from ``TeamSession``, not only the current team turn.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Set, Tuple, cast

from agno.media import Audio, File, Image, Video
from agno.run.base import RunStatus
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.session import TeamSession


def _fingerprint_artifact(artifact: Any) -> str:
    """Stable key for deduplication within a modality."""
    oid = getattr(artifact, "id", None)
    if oid is not None and str(oid).strip() != "":
        return f"id:{oid}"
    for attr in ("url", "filepath", "filename", "name"):
        v = getattr(artifact, attr, None)
        if v is not None and str(v).strip() != "":
            return f"{attr}:{v}"
    content = getattr(artifact, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return f"bytes:{len(content)}"
    if content is not None:
        return f"content:{hash(str(content))}"
    ext = getattr(artifact, "external", None)
    if ext is not None:
        return f"external:{id(ext)}"
    return f"obj:{id(artifact)}"


def _seed_seen(
    images: Sequence[Image],
    videos: Sequence[Video],
    audio: Sequence[Audio],
    files: Sequence[File],
) -> Set[str]:
    seen: Set[str] = set()
    for prefix, seq in (
        ("i", images),
        ("v", videos),
        ("a", audio),
        ("f", files),
    ):
        for item in seq:
            seen.add(f"{prefix}:{_fingerprint_artifact(item)}")
    return seen


def _append_unique(
    out: List[Any],
    items: Optional[Sequence[Any]],
    seen: Set[str],
    prefix: str,
) -> None:
    if not items:
        return
    for item in items:
        key = f"{prefix}:{_fingerprint_artifact(item)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)


def _team_leader_runs_for_media(session: TeamSession, team_id: str) -> List[TeamRunOutput]:
    """Top-level team runs for this team (excludes member runs)."""
    out: List[TeamRunOutput] = []
    for run in session.runs or []:
        if not isinstance(run, TeamRunOutput):
            continue
        if getattr(run, "parent_run_id", None):
            continue
        if getattr(run, "team_id", None) != team_id:
            continue
        st = getattr(run, "status", None)
        if st is not None and st in (RunStatus.paused, RunStatus.cancelled, RunStatus.error):
            continue
        out.append(run)
    return out


def _history_window_runs(team: Any) -> int:
    """How many prior team leader runs may contribute run-input media."""
    if team.num_history_messages is not None:
        return team.num_team_history_runs
    if team.num_history_runs is not None:
        return team.num_history_runs
    return 3


def merge_team_media_for_delegation(
    team: Any,
    session: TeamSession,
    current_run_id: Optional[str],
    images: Optional[Sequence[Image]],
    videos: Optional[Sequence[Video]],
    audio: Optional[Sequence[Audio]],
    files: Optional[Sequence[File]],
) -> Tuple[List[Image], List[Video], List[Audio], List[File]]:
    """Return media lists for member ``run`` / ``arun`` kwargs.

    When ``team.add_team_media_to_delegation`` is false, returns shallow copies of the
    current sequences only.

    When true, order is: **current turn** first, then media from prior **team leader**
    runs (``TeamRunInput`` on top-level ``TeamRunOutput`` rows), then attachments on
    **team-scoped** session messages (see ``TeamSession.get_messages`` with
    ``team_id`` / ``skip_member_messages``). Duplicates are dropped using stable
    fingerprints per modality. The **current** team run id is excluded from run-input
    history so the same assets are not merged twice with current kwargs.

    Bounds follow ``num_history_runs`` / ``num_history_messages`` (and
    ``num_team_history_runs`` for the team-run window when only message limits apply).
    """
    out_images: List[Image] = list(images) if images else []
    out_videos: List[Video] = list(videos) if videos else []
    out_audio: List[Audio] = list(audio) if audio else []
    out_files: List[File] = list(files) if files else []

    if not getattr(team, "add_team_media_to_delegation", False):
        return out_images, out_videos, out_audio, out_files

    if session is None or not session.runs:
        return out_images, out_videos, out_audio, out_files

    team_id = team.id
    if not team_id:
        return out_images, out_videos, out_audio, out_files

    seen = _seed_seen(out_images, out_videos, out_audio, out_files)

    window = _history_window_runs(team)
    leader_runs = _team_leader_runs_for_media(session, team_id)
    historical = [r for r in leader_runs if current_run_id is None or r.run_id != current_run_id]
    if window > 0:
        historical = historical[-window:]

    for run in historical:
        run_input = run.input
        if not isinstance(run_input, TeamRunInput):
            continue
        _append_unique(out_images, run_input.images, seen, "i")
        _append_unique(out_videos, run_input.videos, seen, "v")
        _append_unique(out_audio, run_input.audios, seen, "a")
        _append_unique(out_files, run_input.files, seen, "f")

    last_n = team.num_history_runs if team.num_history_messages is None else None
    limit = team.num_history_messages
    team_messages = session.get_messages(
        team_id=team_id,
        skip_member_messages=True,
        last_n_runs=last_n,
        limit=limit,
        skip_history_messages=False,
    )
    for msg in team_messages:
        _append_unique(out_images, cast(Optional[Sequence[Image]], msg.images), seen, "i")
        _append_unique(out_videos, cast(Optional[Sequence[Video]], msg.videos), seen, "v")
        _append_unique(out_audio, cast(Optional[Sequence[Audio]], msg.audio), seen, "a")
        _append_unique(out_files, cast(Optional[Sequence[File]], msg.files), seen, "f")

    return out_images, out_videos, out_audio, out_files
