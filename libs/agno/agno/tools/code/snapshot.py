"""Per-variable dill snapshots of the kernel namespace into AgentFS.

Each top-level name is pickled independently, so one socket or open file
handle is skipped and reported rather than aborting the whole snapshot. The
store is the database (AgentFS over the agent's db): nothing about resume
depends on a container's disk surviving. Payloads are base64 text because
AgentFS v1 is text-only, four stored bytes for every three pickle bytes.

Both caps count stored bytes, the bytes the file store actually holds, and
they are lowered at setup to the store's own per-file and per-namespace
limits so a variable the caps admit is a variable the store accepts. A
variable that is still refused is reported to the model by name with the
size and the limit, never as unpicklable.

Restore never raises — a missing or corrupt file yields an empty restore and
a logged warning — and runs BEFORE the bootstrap cell that rebinds the live
toolkit handles, so a stale pickled handle loses to this run's live one.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agno.fs import FileSystem
from agno.tools.code.kernel import KernelSession, parse_marker_line
from agno.utils.log import log_debug, log_warning
from agno.utils.string import hash_string_sha256

SNAPSHOT_MARKER = "__AGNO_CM_SNAPSHOT__"

# Prefixed to the next execute result when stored state could not be read or
# restored in time. The kernel is then held back from writing snapshots (its
# namespace is not the stored state), so the model must know its new work
# lives only as long as this kernel.
NO_PERSIST_NOTICE = (
    "<code_mode_not_persisted>\n"
    "The stored state for this session could not be restored. Nothing was loaded, and to "
    "avoid overwriting state this environment never read, nothing from this session will "
    "be saved either. Variables you create last only until this kernel stops.\n"
    "</code_mode_not_persisted>"
)
RESTORE_MARKER = "__AGNO_CM_RESTORE__"

# Pickles each candidate name independently. Builtins go through the _cm_b
# alias so a user variable named ``list`` or ``open`` cannot break the save.
# Sizes are the base64 length the store will hold, computed arithmetically so
# an oversized value is never encoded just to be discarded.
_SNAPSHOT_CODE_TEMPLATE = (
    "import base64 as _cm_b64\n"
    "import builtins as _cm_b\n"
    "import json as _cm_json\n"
    "try:\n"
    "    import dill as _cm_dill\n"
    "except Exception as _cm_e:\n"
    "    _cm_b.print('\\n{marker}' + _cm_json.dumps({{'error': 'dill unavailable: ' + _cm_b.str(_cm_e)}}))\n"
    "else:\n"
    "    _cm_skip = _cm_b.set(_cm_json.loads(_cm_b64.b64decode('{skip_b64}').decode('utf-8')))\n"
    "    _cm_skip.update(('In', 'Out', 'get_ipython', 'exit', 'quit'))\n"
    "    _cm_base = _cm_b.globals().get('_agno_cm_baseline', {{}})\n"
    "    _cm_entries = []\n"
    "    _cm_skipped = []\n"
    "    _cm_total = 0\n"
    "    for _cm_k in _cm_b.list(_cm_b.globals()):\n"
    "        if _cm_k.startswith('_') or _cm_k in _cm_skip:\n"
    "            continue\n"
    "        if not _cm_k.isidentifier():\n"
    "            _cm_skipped.append({{'name': _cm_k, 'reason': 'name is not a valid identifier'}})\n"
    "            continue\n"
    "        _cm_v = _cm_b.globals()[_cm_k]\n"
    "        if _cm_k in _cm_base and _cm_base[_cm_k] is _cm_v:\n"
    "            continue\n"
    "        try:\n"
    "            _cm_payload = _cm_dill.dumps(_cm_v)\n"
    "        except Exception as _cm_e:\n"
    "            _cm_skipped.append({{'name': _cm_k, 'reason': _cm_b.type(_cm_e).__name__ + ': ' + _cm_b.str(_cm_e)[:200]}})\n"
    "            continue\n"
    "        _cm_size = ((_cm_b.len(_cm_payload) + 2) // 3) * 4\n"
    "        if _cm_size > {max_variable_bytes}:\n"
    "            _cm_skipped.append({{'name': _cm_k, 'reason': 'too large to store: ' + _cm_b.str(_cm_size) + ' bytes, over the {max_variable_bytes}-byte limit'}})\n"
    "            continue\n"
    "        if _cm_total + _cm_size > {max_snapshot_bytes}:\n"
    "            _cm_skipped.append({{'name': _cm_k, 'reason': 'over the {max_snapshot_bytes}-byte snapshot budget: ' + _cm_b.str(_cm_size) + ' bytes'}})\n"
    "            continue\n"
    "        _cm_total += _cm_size\n"
    "        _cm_entries.append({{'name': _cm_k, 'data': _cm_b64.b64encode(_cm_payload).decode('ascii'), 'bytes': _cm_size, 'type': _cm_b.type(_cm_v).__name__}})\n"
    "    _cm_b.print('\\n{marker}' + _cm_json.dumps({{'entries': _cm_entries, 'skipped': _cm_skipped}}))\n"
)

# Restores each payload independently; a failure names the variable instead of
# aborting the rest.
_RESTORE_CODE_TEMPLATE = (
    "import base64 as _cm_b64\n"
    "import builtins as _cm_b\n"
    "import json as _cm_json\n"
    "try:\n"
    "    import dill as _cm_dill\n"
    "except Exception as _cm_e:\n"
    "    _cm_b.print('\\n{marker}' + _cm_json.dumps({{'restored': [], 'failed': [['*', 'dill unavailable: ' + _cm_b.str(_cm_e)]]}}))\n"
    "else:\n"
    "    _cm_payloads = _cm_json.loads(_cm_b64.b64decode('{payloads_b64}').decode('utf-8'))\n"
    "    _cm_restored = []\n"
    "    _cm_failed = []\n"
    "    for _cm_k, _cm_data in _cm_payloads:\n"
    "        try:\n"
    "            _cm_b.globals()[_cm_k] = _cm_dill.loads(_cm_b64.b64decode(_cm_data))\n"
    "            _cm_restored.append(_cm_k)\n"
    "        except Exception as _cm_e:\n"
    "            _cm_failed.append([_cm_k, _cm_b.type(_cm_e).__name__ + ': ' + _cm_b.str(_cm_e)[:200]])\n"
    "    _cm_b.print('\\n{marker}' + _cm_json.dumps({{'restored': _cm_restored, 'failed': _cm_failed}}))\n"
)


def reconcile_caps(
    max_variable_bytes: int,
    max_snapshot_bytes: int,
    max_file_bytes: Optional[int],
    max_namespace_bytes: Optional[int],
) -> Tuple[int, int, List[str]]:
    """Lower the snapshot caps to what the file store will accept.

    All four numbers count stored bytes. A cap above the store's own limit
    hands the store a payload it refuses, which costs the variable and tells
    the model nothing useful, so the smaller number wins and becomes the cap
    the snapshot is held to. Limits that are not numbers (a store that does
    not publish them) leave the caps alone. Returns the effective
    (per-variable, per-snapshot) caps and one sentence per lowered cap.
    """
    notes: List[str] = []
    variable_bytes = max_variable_bytes
    snapshot_bytes = max_snapshot_bytes
    if isinstance(max_file_bytes, int) and max_file_bytes < variable_bytes:
        notes.append(f"per-variable {variable_bytes} -> {max_file_bytes} bytes (the store's max_file_bytes)")
        variable_bytes = max_file_bytes
    if isinstance(max_namespace_bytes, int) and max_namespace_bytes < snapshot_bytes:
        notes.append(f"per-snapshot {snapshot_bytes} -> {max_namespace_bytes} bytes (the store's max_namespace_bytes)")
        snapshot_bytes = max_namespace_bytes
    return variable_bytes, snapshot_bytes, notes


def apply_snapshot_budget(
    entries: List[Dict[str, Any]], max_snapshot_bytes: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Enforce the cumulative snapshot budget over stored bytes.

    Entries are taken in manifest order — smallest first, largest last — and
    cut when the running total would cross ``max_snapshot_bytes``, so one
    oversized DataFrame does not evict the small variables that carry the
    reasoning. Returns (kept, cut); cut entries carry a ``reason``.
    """
    ordered = sorted(entries, key=lambda e: (int(e.get("bytes", 0)), str(e.get("name", ""))))
    kept: List[Dict[str, Any]] = []
    cut: List[Dict[str, Any]] = []
    total = 0
    for entry in ordered:
        size = int(entry.get("bytes", 0))
        if total + size <= max_snapshot_bytes:
            kept.append(entry)
            total += size
        else:
            cut.append(
                {
                    "name": entry.get("name"),
                    "reason": f"over the {max_snapshot_bytes}-byte snapshot budget ({size} bytes)",
                }
            )
    return kept, cut


def build_restored_notice(restored: Sequence[str], not_restored: Sequence[Tuple[str, str]]) -> Optional[str]:
    """The in-band notice prefixed to the next execute result after a restore.

    ``not_restored`` holds one ``(name, reason)`` pair per variable that did
    not come back. The reason is what the model acts on — a value refused for
    its size is worth rebuilding smaller, an unpicklable handle is worth
    reopening, a value that failed to unpickle is worth recomputing — so each
    one is named rather than folded into a single verdict.
    """
    if not restored and not not_restored:
        return None
    lines = ["<code_mode_restored>"]
    if restored:
        lines.append(f"Restored {len(restored)} variables: " + ", ".join(restored) + ".")
    else:
        lines.append("Restored 0 variables.")
    if not_restored:
        lines.append("Not restored:")
        lines.extend(f"- {name}: {reason or 'no reason recorded'}" for name, reason in not_restored)
    lines.append("</code_mode_restored>")
    return "\n".join(lines)


class SnapshotManager:
    """Schedules, writes, restores, and clears per-session snapshots.

    ``max_variable_bytes`` and ``max_snapshot_bytes`` count stored bytes and
    are lowered at construction to the store's own limits, so the caps the
    kernel enforces are the caps the store honours. The namespace is shared
    with whatever else writes to this FileSystem, so a write can still be
    refused when the namespace fills; those refusals are logged and carried
    to the model by name and reason.
    """

    def __init__(
        self,
        fs: FileSystem,
        *,
        debounce: float = 1.5,
        max_variable_bytes: int = 2_000_000,
        max_snapshot_bytes: int = 64_000_000,
        skip_names: Optional[Sequence[str]] = None,
    ) -> None:
        self.fs = fs
        self.debounce = debounce
        self.max_variable_bytes, self.max_snapshot_bytes, adjustments = reconcile_caps(
            max_variable_bytes,
            max_snapshot_bytes,
            getattr(fs, "max_file_bytes", None),
            getattr(fs, "max_namespace_bytes", None),
        )
        if adjustments:
            log_warning(
                "CodeMode snapshot caps lowered to fit the file store: "
                + "; ".join(adjustments)
                + ". Raise the FileSystem limits to keep the larger caps."
            )
        self.skip_names = list(skip_names or [])
        self._timers: Dict[str, "asyncio.Task[None]"] = {}

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @staticmethod
    def _session_segment(session_id: str) -> str:
        """One safe path segment per session id.

        A session id containing '/', '..', control characters, or hundreds of
        characters must neither nest inside another session's tree nor make
        every fs call fail. Sanitized ids get a hash suffix so distinct raw
        ids can never collide after cleaning.
        """
        cleaned = re.sub(r"[^\w.\-]", "_", session_id)[:80].strip(".") or "_"
        if cleaned != session_id:
            cleaned = f"{cleaned}-{hash_string_sha256(session_id)[:8]}"
        return cleaned

    def _manifest_path(self, session_id: str) -> str:
        return f"kernel/{self._session_segment(session_id)}/manifest.json"

    def _vars_dir(self, session_id: str) -> str:
        return f"kernel/{self._session_segment(session_id)}/vars"

    def _var_path(self, session_id: str, name: str) -> str:
        return f"kernel/{self._session_segment(session_id)}/vars/{name}.b64"

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def schedule(self, session: KernelSession) -> None:
        """Schedule a debounced snapshot after a successful cell."""
        existing = self._timers.pop(session.session_id, None)
        if existing is not None:
            existing.cancel()
        self._timers[session.session_id] = asyncio.get_running_loop().create_task(self._debounced(session))

    async def _debounced(self, session: KernelSession) -> None:
        try:
            await asyncio.sleep(self.debounce)
            async with session.lock:
                if session.running:
                    await self.flush_locked(session)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log_warning(f"CodeMode snapshot for session {session.session_id} failed: {e}")
        finally:
            # Pop only our own registration: schedule() may already have
            # replaced it with a newer timer, and popping that one would
            # orphan a live flush from clear()'s cancellation.
            if self._timers.get(session.session_id) is asyncio.current_task():
                self._timers.pop(session.session_id, None)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    async def flush_locked(self, session: KernelSession) -> None:
        """Write a snapshot now. The caller holds the session lock.

        A kernel that did not take over the stored snapshot writes nothing:
        its namespace is not that state, and the write would take the stored
        variables with it.
        """
        if not session.running:
            return
        if not session.snapshot_writable:
            log_debug(
                f"CodeMode snapshot for session {session.session_id} held back: "
                "this kernel did not take over the stored snapshot"
            )
            return
        skip_b64 = base64.b64encode(json.dumps(self.skip_names).encode("utf-8")).decode("ascii")
        code = _SNAPSHOT_CODE_TEMPLATE.format(
            marker=SNAPSHOT_MARKER,
            skip_b64=skip_b64,
            max_variable_bytes=self.max_variable_bytes,
            max_snapshot_bytes=self.max_snapshot_bytes,
        )
        # Every kept payload rides the marker line, and the kernel-side budget
        # caps their total at max_snapshot_bytes of base64, so this ceiling is
        # the budget plus half again for the JSON frame around it.
        max_chars = int(self.max_snapshot_bytes * 1.5) + 1_000_000
        result = await session._run_silent(code, timeout=120.0, max_chars=max_chars)
        payload = parse_marker_line(result.stdout, SNAPSHOT_MARKER)
        if payload is None:
            log_warning(
                f"CodeMode snapshot for session {session.session_id} produced no data: "
                f"{result.traceback or result.stderr or 'no output'}"
            )
            return
        try:
            data = json.loads(payload)
        except ValueError as e:
            log_warning(f"CodeMode snapshot for session {session.session_id} produced unparsable data: {e}")
            return
        if "error" in data:
            log_warning(f"CodeMode snapshot for session {session.session_id} failed: {data['error']}")
            return
        kept, cut = apply_snapshot_budget(data.get("entries", []), self.max_snapshot_bytes)
        skipped = list(data.get("skipped", [])) + cut

        session_id = session.session_id
        written: List[Dict[str, Any]] = []
        for entry in kept:
            name = str(entry["name"])
            try:
                await self.fs.awrite(self._var_path(session_id, name), str(entry["data"]))
                written.append({"name": name, "type": entry.get("type"), "bytes": int(entry.get("bytes", 0))})
            except Exception as e:
                log_warning(f"CodeMode snapshot for session {session_id}: store refused '{name}': {e}")
                skipped.append({"name": name, "reason": f"store refused the write: {e}"})

        # Drop var files for names that no longer exist in the kernel, so a
        # deleted variable cannot resurrect on the next restore. Names that
        # still exist but were skipped this round (unpicklable, over a cap,
        # write refused) keep their previous file: it is not restored (the
        # manifest governs restore) but deleting it would destroy the last
        # good copy for nothing.
        try:
            keep = {w["name"] for w in written} | {str(s.get("name")) for s in skipped}
            for meta in await self.fs.alist(self._vars_dir(session_id)):
                file_name = meta.path.rsplit("/", 1)[-1]
                if file_name.endswith(".b64") and file_name[: -len(".b64")] not in keep:
                    await self.fs.adelete(meta.path)
        except Exception as e:
            log_debug(f"CodeMode snapshot cleanup for session {session_id}: {e}")

        manifest = {
            "schema": 1,
            "saved_at": int(time.time()),
            "execution_count": session.execution_count,
            # The user whose state this is. A restore into a run of another
            # user is refused; None means no run that built this state carried
            # an identity, and it stays readable by any run.
            "owner_user_id": session.owner_user_id,
            "variables": written,
            "skipped": skipped,
        }
        try:
            await self.fs.awrite(self._manifest_path(session_id), json.dumps(manifest))
        except Exception as e:
            log_warning(f"CodeMode snapshot manifest write failed for session {session_id}: {e}")
            return
        log_debug(f"CodeMode snapshot for session {session_id}: {len(written)} variables, {len(skipped)} skipped")

    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------

    async def owner(self, session_id: str) -> Optional[str]:
        """The user_id recorded in this session's snapshot, or None.

        None also covers a snapshot that does not exist and one that cannot be
        read or parsed: what cannot be read here cannot be restored later
        either, so an unreadable manifest hands over no state.
        """
        try:
            manifest_text = await self.fs.aread(self._manifest_path(session_id))
        except Exception as e:
            log_warning(f"CodeMode owner check for session {session_id}: manifest read failed: {e}")
            return None
        if manifest_text is None:
            return None
        try:
            recorded = json.loads(manifest_text).get("owner_user_id")
        except Exception as e:
            log_warning(f"CodeMode owner check for session {session_id}: corrupt manifest: {e}")
            return None
        return str(recorded) if recorded is not None else None

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def restore(self, session: KernelSession) -> Optional[str]:
        """Restore the last snapshot into a fresh kernel. Never raises.

        Returns the ``<code_mode_restored>`` notice, or None when there was
        nothing to restore. Runs before the bootstrap cell by contract.
        """
        session_id = session.session_id
        session.snapshot_writable = True
        try:
            manifest_text = await self.fs.aread(self._manifest_path(session_id))
        except Exception as e:
            # What is stored may hold variables this kernel never read, so the
            # kernel is held back from writing over them until it starts again
            # and reads the manifest.
            session.snapshot_writable = False
            log_warning(
                f"CodeMode restore for session {session_id}: manifest read failed: {e}. "
                "Snapshots for this kernel are held back."
            )
            return NO_PERSIST_NOTICE
        if manifest_text is None:
            return None
        try:
            manifest = json.loads(manifest_text)
            variables = list(manifest.get("variables", []))
            manifest_skipped = [
                (str(s.get("name")), str(s.get("reason") or "no reason recorded")) for s in manifest.get("skipped", [])
            ]
        except Exception as e:
            log_warning(f"CodeMode restore for session {session_id}: corrupt manifest: {e}")
            return None
        # Compared as text: a manifest written before identity was normalized
        # can hold a non-str owner, and '42' and 42 are the same user.
        recorded_owner = manifest.get("owner_user_id")
        if recorded_owner is not None:
            recorded_owner = str(recorded_owner)
            if session.owner_user_id is None:
                # A run that carries no identity may read this state, but it
                # must not erase whose state it is: the session takes the
                # recorded owner, the next flush writes it back, and a later
                # run of a different user is still refused.
                session.owner_user_id = recorded_owner
            elif recorded_owner != str(session.owner_user_id):
                session.snapshot_writable = False
                log_warning(
                    f"CodeMode restore for session {session_id} refused: the snapshot belongs to "
                    f"user '{recorded_owner}', this kernel to user '{session.owner_user_id}'. "
                    "Snapshots for this kernel are held back."
                )
                return None

        payloads: List[List[str]] = []
        failed: List[Tuple[str, str]] = []
        for var in variables:
            name = str(var.get("name"))
            try:
                data = await self.fs.aread(self._var_path(session_id, name))
            except Exception as e:
                log_warning(f"CodeMode restore for session {session_id}: read of '{name}' failed: {e}")
                failed.append((name, f"stored payload could not be read: {e}"))
                continue
            if data is None:
                failed.append((name, "stored payload is missing"))
            else:
                payloads.append([name, data])

        restored: List[str] = []
        if payloads:
            payloads_b64 = base64.b64encode(json.dumps(payloads).encode("utf-8")).decode("ascii")
            code = _RESTORE_CODE_TEMPLATE.format(marker=RESTORE_MARKER, payloads_b64=payloads_b64)
            try:
                result = await session._run_silent(code, timeout=120.0)
                if result.status == "aborted":
                    # The kernel may still be restoring; claiming zero restored
                    # variables here would be a lie the model acts on. The
                    # namespace is part of the stored snapshot at best, so it
                    # must not be written back over the whole of it either.
                    session.snapshot_writable = False
                    log_warning(
                        f"CodeMode restore for session {session_id} timed out. Snapshots for this kernel are held back."
                    )
                    return NO_PERSIST_NOTICE
                marker_payload = parse_marker_line(result.stdout, RESTORE_MARKER)
                if marker_payload is None:
                    log_warning(
                        f"CodeMode restore for session {session_id} produced no result: "
                        f"{result.traceback or result.stderr or 'no output'}"
                    )
                    failed.extend((name, "the kernel produced no restore result") for name, _ in payloads)
                else:
                    outcome = json.loads(marker_payload)
                    restored = [str(n) for n in outcome.get("restored", [])]
                    for name, reason in outcome.get("failed", []):
                        log_warning(f"CodeMode restore for session {session_id}: '{name}' failed: {reason}")
                        if name == "*":
                            # A whole-cell failure: every payload is gone, and
                            # each one carries that reason to the model.
                            failed.extend((sent, str(reason)) for sent, _ in payloads)
                        else:
                            failed.append((str(name), str(reason)))
            except Exception as e:
                log_warning(f"CodeMode restore for session {session_id} failed: {e}")
                failed.extend((name, f"restore failed: {e}") for name, _ in payloads)

        # One line per variable, first reason recorded wins, and a name that
        # did come back is never also reported as missing.
        seen = set(restored)
        not_restored: List[Tuple[str, str]] = []
        for name, reason in manifest_skipped + failed:
            if name in seen:
                continue
            seen.add(name)
            not_restored.append((name, reason))
        return build_restored_notice(restored, not_restored)

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    async def clear(self, session_id: str) -> None:
        """Delete the session's snapshot. Used by the restart tool.

        Callers run this under the session lock (restart's ``before_start``)
        so a debounced flush cannot interleave with the deletes.
        """
        timer = self._timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()
            # Give the cancelled task a tick to unwind before deleting.
            await asyncio.sleep(0)
        try:
            await self.fs.adelete(self._manifest_path(session_id))
            for meta in await self.fs.alist(self._vars_dir(session_id)):
                await self.fs.adelete(meta.path)
        except Exception as e:
            log_warning(f"CodeMode snapshot clear for session {session_id} failed: {e}")
