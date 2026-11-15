"""Edge cases of the namespace="user" entity re-key migration (issue #9319).

The happy paths (dry run, re-key, purge, conflict, idempotency, multi-page walk)
are pinned in test_entity_memory_user_isolation.py. These cover what the
migration must NOT do when the row or the backend misbehaves: content it cannot
read is never re-keyed or purged, a delete it cannot confirm never counts as a
successful re-key, one raising row never ends the walk, and a contamination that
already reached a user-scoped row is reported instead of destroyed.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.base import AsyncBaseDb
from agno.learn.migrations import arekey_user_entity_learnings, rekey_user_entity_learnings
from agno.learn.utils import build_learning_id, legacy_entity_learning_id

ALICE = "alice@corp.com"
BOB = "bob@corp.com"

MODES = pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])


def _user_key(entity_id: str, entity_type: str, user_id: str) -> str:
    key = build_learning_id(
        "entity_memory", entity_id=entity_id, entity_type=entity_type, namespace="user", user_id=user_id
    )
    assert key is not None
    return key


class FakeLearningDb:
    """In-memory learnings table with the paginated listing the migration walks.

    list_learnings honors sort_by/sort_order: the migration relies on a unique,
    stable sort key to page a table it is about to mutate, and a fake that
    ignored the parameter could not fail when that contract is broken.
    """

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.list_calls: List[Dict[str, Any]] = []

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        self.rows[id] = {**self.rows.get(id, {}), **kwargs, "learning_id": id}

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        return self.rows.get(id)

    def delete_learning(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None

    def list_learnings(self, **kwargs: Any) -> Tuple[List[Dict[str, Any]], int]:
        self.list_calls.append(dict(kwargs))
        learning_type = kwargs.get("learning_type")
        namespace = kwargs.get("namespace")
        limit = kwargs.get("limit") or 100
        page = kwargs.get("page") or 1
        sort_by = kwargs.get("sort_by") or "updated_at"
        rows = [
            dict(row)
            for row in self.rows.values()
            if (learning_type is None or row.get("learning_type") == learning_type)
            and (namespace is None or row.get("namespace") == namespace)
        ]
        rows.sort(key=lambda row: str(row.get(sort_by, "")), reverse=kwargs.get("sort_order") == "desc")
        start = (page - 1) * limit
        return rows[start : start + limit], len(rows)


class AsyncFakeDb(AsyncBaseDb):
    """AsyncBaseDb surface over a FakeLearningDb, so the async twin runs the same table."""

    def __init__(self, inner: FakeLearningDb) -> None:
        self.inner = inner

    async def list_learnings(self, **kwargs: Any) -> Any:
        return self.inner.list_learnings(**kwargs)

    async def get_learning_by_id(self, id: str) -> Any:
        return self.inner.get_learning_by_id(id)

    async def upsert_learning(self, **kwargs: Any) -> None:
        self.inner.upsert_learning(**kwargs)

    async def delete_learning(self, id: str) -> bool:
        return self.inner.delete_learning(id)


AsyncFakeDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]


async def _rekey(db: FakeLearningDb, use_async: bool, **kwargs: Any) -> Dict[str, Any]:
    """Run whichever variant the parametrization asks for against the same fake."""
    if use_async:
        return await arekey_user_entity_learnings(AsyncFakeDb(db), **kwargs)
    return rekey_user_entity_learnings(db, **kwargs)  # type: ignore[arg-type]


def _seed_legacy(
    db: FakeLearningDb,
    entity_id: str,
    owner: Optional[str],
    content: Any,
) -> str:
    legacy_id = legacy_entity_learning_id(entity_id, "company", "user")
    db.upsert_learning(
        id=legacy_id,
        learning_type="entity_memory",
        entity_id=entity_id,
        entity_type="company",
        namespace="user",
        user_id=owner,
        content=content,
    )
    return legacy_id


def _clean_content(entity_id: str, user_id: Optional[str]) -> Dict[str, Any]:
    return {"entity_id": entity_id, "entity_type": "company", "name": entity_id, "user_id": user_id}


class TestUnreadableContent:
    """Content the migration cannot parse to a dict is content whose ownership it
    cannot check, so the row is reported and left exactly where it is."""

    UNREADABLE = [
        pytest.param("just a note", id="bare-string"),
        pytest.param('["a", "list"]', id="json-array-string"),
        pytest.param(["a", "list"], id="list"),
        pytest.param(b'{"entity_id": "acme"}', id="bytes"),
        pytest.param(None, id="missing"),
    ]

    @MODES
    @pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "apply"])
    @pytest.mark.parametrize("content", UNREADABLE)
    async def test_unparseable_content_is_malformed(self, content: Any, dry_run: bool, use_async: bool) -> None:
        db = FakeLearningDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, content)

        report = await _rekey(db, use_async, dry_run=dry_run)

        assert report["malformed"] == [legacy_id]
        assert report["rekeyed"] == []
        assert legacy_id in db.rows
        assert db.rows[legacy_id]["content"] == content
        assert _user_key("acme", "company", ALICE) not in db.rows

    @MODES
    async def test_unparseable_content_survives_purge(self, use_async: bool) -> None:
        db = FakeLearningDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, "just a note")

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["malformed"] == [legacy_id]
        assert report["purged"] == []
        assert legacy_id in db.rows


class TestUnconfirmedDelete:
    """Every adapter's delete_learning swallows its exception and returns False,
    so the migration confirms the outcome by reading the row back."""

    class UndeletableDb(FakeLearningDb):
        def delete_learning(self, id: str) -> bool:
            return False

    class ConcurrentlyDeletedDb(FakeLearningDb):
        """The delete reports failure but the row is gone anyway -- another writer
        removed it while the migration was walking."""

        def delete_learning(self, id: str) -> bool:
            self.rows.pop(id, None)
            return False

    @MODES
    async def test_source_row_that_survives_its_delete_is_failed(self, use_async: bool) -> None:
        db = self.UndeletableDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["failed"] == [legacy_id]
        assert report["rekeyed"] == []
        # The copy landed, so both rows exist and the operator has to reconcile them.
        assert legacy_id in db.rows
        assert _user_key("acme", "company", ALICE) in db.rows

    @MODES
    async def test_concurrently_deleted_source_row_counts_as_rekeyed(self, use_async: bool) -> None:
        db = self.ConcurrentlyDeletedDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["rekeyed"] == [legacy_id]
        assert report["failed"] == []
        assert legacy_id not in db.rows
        assert _user_key("acme", "company", ALICE) in db.rows

    @MODES
    async def test_unconfirmed_purge_is_failed_not_purged(self, use_async: bool) -> None:
        db = self.UndeletableDb()
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["contaminated"] == [dirty]
        assert report["purged"] == []
        assert report["failed"] == [dirty]
        # purge_unrecoverable deletes instead of quarantining, and this delete
        # cannot be confirmed, so the row stays where it is.
        assert dirty in db.rows

    @MODES
    async def test_concurrently_purged_row_counts_as_purged(self, use_async: bool) -> None:
        db = self.ConcurrentlyDeletedDb()
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["purged"] == [dirty]
        assert report["failed"] == []
        assert dirty not in db.rows


class TestPerRowErrorIsolation:
    class BoomOnIdDb(FakeLearningDb):
        """get_learning_by_id re-raises on every adapter, so one unreadable row
        must not take the rest of the walk with it."""

        boom_id = ""

        def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
            if id == self.boom_id:
                raise RuntimeError("backend unavailable")
            return super().get_learning_by_id(id)

    @MODES
    async def test_raising_row_is_failed_and_the_walk_continues(self, use_async: bool) -> None:
        db = self.BoomOnIdDb()
        db.boom_id = _user_key("acme", "company", ALICE)
        # "acme" sorts before "initech" on the migration's sort key, so the raising
        # row is the one processed first.
        broken = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))
        healthy = _seed_legacy(db, "initech", ALICE, _clean_content("initech", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["failed"] == [broken]
        assert report["rekeyed"] == [healthy]
        assert report["scanned"] == 2
        assert broken in db.rows
        assert _user_key("initech", "company", ALICE) in db.rows

    @MODES
    async def test_raising_row_does_not_lose_the_report(self, use_async: bool) -> None:
        db = self.BoomOnIdDb()
        db.boom_id = _user_key("acme", "company", ALICE)
        broken = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=True)

        assert report["failed"] == [broken]
        assert report["dry_run"] is True
        assert broken in db.rows


class TestContaminatedKeyedRows:
    """A contaminated legacy row that received the owner's write before the
    migration ran is now a user-scoped row carrying another user's recorded
    user_id -- alongside the owner's own data, so it is reported, never deleted."""

    def _seed_keyed(self, db: FakeLearningDb, owner: str, content_user: str) -> str:
        keyed_id = _user_key("acme", "company", owner)
        db.upsert_learning(
            id=keyed_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=owner,
            content=_clean_content("acme", content_user),
        )
        return keyed_id

    @MODES
    async def test_contaminated_keyed_row_is_reported(self, use_async: bool) -> None:
        db = FakeLearningDb()
        keyed_id = self._seed_keyed(db, ALICE, BOB)

        report = await _rekey(db, use_async, dry_run=False)

        assert report["contaminated_keyed"] == [keyed_id]
        assert report["contaminated"] == []
        assert report["keyed"] == 0
        assert keyed_id in db.rows

    @MODES
    async def test_purge_never_deletes_a_contaminated_keyed_row(self, use_async: bool) -> None:
        db = FakeLearningDb()
        keyed_id = self._seed_keyed(db, ALICE, BOB)

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["contaminated_keyed"] == [keyed_id]
        assert report["purged"] == []
        assert db.rows[keyed_id]["content"] == _clean_content("acme", BOB)

    @MODES
    async def test_matching_user_ids_stay_plain_keyed(self, use_async: bool) -> None:
        db = FakeLearningDb()
        self._seed_keyed(db, ALICE, ALICE)

        report = await _rekey(db, use_async, dry_run=False)

        assert report["keyed"] == 1
        assert report["contaminated_keyed"] == []


class TestOwnerColumnComparison:
    """The classifier compares the content's recorded user against the owner column.

    The owner column is a string column, so an integer user id stores as "42"
    while the JSON content keeps 42. Both spellings name one user, and a row
    whose two ids differ only in type is "legacy" -- classifying it
    "contaminated" hands a healthy row to purge_unrecoverable, which deletes it.
    Users who genuinely differ are still contaminated and still purged.
    """

    NUMERIC_OWNER = "42"
    FACT = "renewal at 50k"

    def _numeric_user_content(self) -> Dict[str, Any]:
        """Clean content recording user 42 as the integer the owner column stores as "42"."""
        return {**_clean_content("acme", None), "user_id": 42, "facts": [self.FACT]}

    @MODES
    async def test_integer_content_user_matching_the_string_owner_is_legacy(self, use_async: bool) -> None:
        db = FakeLearningDb()
        legacy_id = _seed_legacy(db, "acme", self.NUMERIC_OWNER, self._numeric_user_content())

        report = await _rekey(db, use_async, dry_run=True)

        assert report["rekeyed"] == [legacy_id]
        assert report["contaminated"] == []

    @MODES
    async def test_purge_rekeys_a_numeric_owner_row_instead_of_deleting_it(self, use_async: bool) -> None:
        db = FakeLearningDb()
        legacy_id = _seed_legacy(db, "acme", self.NUMERIC_OWNER, self._numeric_user_content())

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["rekeyed"] == [legacy_id]
        assert report["contaminated"] == []
        assert report["purged"] == []
        # The row lives on under user 42's own key, the fact it was holding intact.
        new_id = _user_key("acme", "company", self.NUMERIC_OWNER)
        assert list(db.rows) == [new_id]
        assert db.rows[new_id]["content"] == self._numeric_user_content()

    @MODES
    async def test_numeric_owner_on_a_user_scoped_row_stays_plain_keyed(self, use_async: bool) -> None:
        db = FakeLearningDb()
        keyed_id = _user_key("acme", "company", self.NUMERIC_OWNER)
        db.upsert_learning(
            id=keyed_id,
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=self.NUMERIC_OWNER,
            content=self._numeric_user_content(),
        )

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["keyed"] == 1
        assert report["contaminated_keyed"] == []
        assert db.rows[keyed_id]["content"] == self._numeric_user_content()

    @MODES
    async def test_two_different_users_are_still_contaminated(self, use_async: bool) -> None:
        db = FakeLearningDb()
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))

        report = await _rekey(db, use_async, dry_run=True)

        assert report["contaminated"] == [dirty]
        assert report["rekeyed"] == []

    @MODES
    async def test_two_different_users_are_still_purged(self, use_async: bool) -> None:
        db = FakeLearningDb()
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))

        report = await _rekey(db, use_async, dry_run=False, purge_unrecoverable=True)

        assert report["contaminated"] == [dirty]
        assert report["purged"] == [dirty]
        assert db.rows == {}

    @MODES
    async def test_row_without_an_owner_is_unowned(self, use_async: bool) -> None:
        db = FakeLearningDb()
        orphan = _seed_legacy(db, "wayne", None, _clean_content("wayne", ALICE))

        report = await _rekey(db, use_async, dry_run=True)

        assert report["unowned"] == [orphan]
        assert report["contaminated"] == []
        assert report["rekeyed"] == []


class TestReportShape:
    @MODES
    async def test_keyed_count_reconciles_scanned_with_the_buckets(self, use_async: bool) -> None:
        db = FakeLearningDb()
        for entity_id in ("acme", "initech"):
            db.upsert_learning(
                id=_user_key(entity_id, "company", ALICE),
                learning_type="entity_memory",
                entity_id=entity_id,
                entity_type="company",
                namespace="user",
                user_id=ALICE,
                content=_clean_content(entity_id, ALICE),
            )
        _seed_legacy(db, "hooli", ALICE, _clean_content("hooli", ALICE))
        _seed_legacy(db, "umbrella", ALICE, _clean_content("umbrella", BOB))
        _seed_legacy(db, "wayne", None, _clean_content("wayne", None))
        _seed_legacy(db, "stark", ALICE, "unreadable")

        report = await _rekey(db, use_async, dry_run=True)

        assert report["keyed"] == 2
        assert report["scanned"] == 6
        buckets = ("rekeyed", "contaminated", "contaminated_keyed", "unowned", "malformed", "conflicts", "failed")
        assert report["keyed"] + sum(len(report[name]) for name in buckets) == report["scanned"]

    @MODES
    async def test_keyed_is_a_count_not_a_list(self, use_async: bool) -> None:
        db = FakeLearningDb()
        db.upsert_learning(
            id=_user_key("acme", "company", ALICE),
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content=_clean_content("acme", ALICE),
        )

        report = await _rekey(db, use_async, dry_run=True)

        assert report["keyed"] == 1
        assert isinstance(report["keyed"], int)


class TestDeterministicPaging:
    @MODES
    async def test_walk_sorts_by_the_unique_key(self, use_async: bool) -> None:
        db = FakeLearningDb()
        _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        await _rekey(db, use_async, dry_run=True)

        assert db.list_calls
        for call in db.list_calls:
            assert call["sort_by"] == "learning_id"
            assert call["sort_order"] == "asc"
            assert call["learning_type"] == "entity_memory"
            assert call["namespace"] == "user"

    @MODES
    async def test_every_row_is_visited_across_pages(self, use_async: bool, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("agno.learn.migrations._PAGE_SIZE", 2)
        db = FakeLearningDb()
        # Insertion order is the reverse of the sort order, so a walk that ignored
        # the sort key would page a different sequence than the fake returns.
        seeded = [_seed_legacy(db, f"entity{i}", ALICE, _clean_content(f"entity{i}", ALICE)) for i in range(7, 0, -1)]

        report = await _rekey(db, use_async, dry_run=False)

        assert report["scanned"] == len(seeded)
        assert sorted(report["rekeyed"]) == sorted(seeded)
        assert len(db.list_calls) > 1
        assert sorted(db.rows) == sorted(_user_key(f"entity{i}", "company", ALICE) for i in range(7, 0, -1))


class TestSourceRowIsReReadBeforeCopy:
    """The walk pages the whole table before it writes anything, so a row's paged
    content is stale once a write lands on that row. The copy carries the row's
    current stored state, and a row that no longer classifies as "legacy" is
    reported under "failed" and left in place.

    The re-read narrows the window between the page and the copy; it does not
    close it. The db surface has no transaction and no compare-and-set, so a
    write landing after the re-read is still lost.
    """

    PAGED_FACT = "renewal at 50k"
    LATE_FACT = "renewal moved to 80k"

    class WriteUnderTheWalkDb(FakeLearningDb):
        """One live write lands on target_id after the walk has paged it.

        The write fires on the migration's first read -- the conflict check it
        runs immediately before the copy -- and replaces the stored row, so the
        paged copy the walk is holding keeps the old values. A change returning
        None deletes the row.
        """

        target_id = ""
        change: Any = None

        def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
            change, self.change = self.change, None
            if change is not None:
                row = self.rows.get(self.target_id)
                if row is not None:
                    updated = change(dict(row))
                    if updated is None:
                        del self.rows[self.target_id]
                    else:
                        self.rows[self.target_id] = updated
            return super().get_learning_by_id(id)

    @staticmethod
    def _append_late_fact(row: Dict[str, Any]) -> Dict[str, Any]:
        content = dict(row["content"])
        content["facts"] = [*content["facts"], TestSourceRowIsReReadBeforeCopy.LATE_FACT]
        return {**row, "content": content}

    @staticmethod
    def _hand_the_row_to_bob(row: Dict[str, Any]) -> Dict[str, Any]:
        return {**row, "user_id": BOB}

    @staticmethod
    def _delete_the_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None

    @MODES
    async def test_write_landing_after_paging_is_carried_into_the_rekeyed_row(self, use_async: bool) -> None:
        db = self.WriteUnderTheWalkDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, {**_clean_content("acme", ALICE), "facts": [self.PAGED_FACT]})
        db.target_id = legacy_id
        db.change = self._append_late_fact

        report = await _rekey(db, use_async, dry_run=False)

        assert report["rekeyed"] == [legacy_id]
        assert db.rows[_user_key("acme", "company", ALICE)]["content"]["facts"] == [self.PAGED_FACT, self.LATE_FACT]
        assert legacy_id not in db.rows

    @MODES
    async def test_row_that_leaves_the_legacy_bucket_under_the_walk_is_failed(self, use_async: bool) -> None:
        db = self.WriteUnderTheWalkDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))
        db.target_id = legacy_id
        # The owner column moves to Bob while the content still records Alice:
        # the row classifies as "contaminated" from its current stored state.
        db.change = self._hand_the_row_to_bob

        report = await _rekey(db, use_async, dry_run=False)

        assert report["failed"] == [legacy_id]
        assert report["rekeyed"] == []
        assert db.rows[legacy_id]["user_id"] == BOB
        assert _user_key("acme", "company", ALICE) not in db.rows
        assert _user_key("acme", "company", BOB) not in db.rows

    @MODES
    async def test_row_deleted_under_the_walk_is_not_copied_back(self, use_async: bool) -> None:
        db = self.WriteUnderTheWalkDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))
        db.target_id = legacy_id
        db.change = self._delete_the_row

        report = await _rekey(db, use_async, dry_run=False)

        assert report["failed"] == [legacy_id]
        assert report["rekeyed"] == []
        assert db.rows == {}

    @MODES
    async def test_quiet_table_reports_the_same_buckets(self, use_async: bool) -> None:
        db = FakeLearningDb()
        clean = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))
        conflicted = _seed_legacy(db, "hooli", ALICE, _clean_content("hooli", ALICE))
        db.upsert_learning(
            id=_user_key("hooli", "company", ALICE),
            learning_type="entity_memory",
            entity_id="hooli",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content=_clean_content("hooli", ALICE),
        )

        report = await _rekey(db, use_async, dry_run=False)

        assert report["rekeyed"] == [clean]
        assert report["contaminated"] == [dirty]
        # A row whose target key is already taken is folded into it, not abandoned.
        assert report["merged"] == [conflicted]
        assert report["conflicts"] == []
        assert report["failed"] == []
        assert report["keyed"] == 1
        assert report["scanned"] == 4
        assert clean not in db.rows
        assert db.rows[_user_key("acme", "company", ALICE)]["content"] == _clean_content("acme", ALICE)
        # A contaminated row is not separable, so it moves under the quarantine
        # namespace: out of every user-filtered read, content preserved.
        quarantined = legacy_entity_learning_id("initech", "company", "quarantined_user")
        assert dirty not in db.rows
        assert quarantined in db.rows
        # The conflicted source is folded into the row already on its key and removed.
        assert conflicted not in db.rows
        assert _user_key("hooli", "company", ALICE) in db.rows

    @MODES
    async def test_dry_run_still_writes_nothing(self, use_async: bool) -> None:
        db = FakeLearningDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=True)

        assert report["rekeyed"] == [legacy_id]
        assert list(db.rows) == [legacy_id]
        assert db.rows[legacy_id]["content"] == _clean_content("acme", ALICE)


class TestCopyIsReadBackBeforeTheSourceIsDeleted:
    """Every adapter's upsert_learning swallows its exception and returns None, so
    a write that never landed looks exactly like one that did. Both moves the
    migration makes -- the re-key to the user-scoped key and the quarantine of a
    contaminated row -- read the destination back, and delete the source only
    once the copy is there."""

    class SilentUpsertDb(FakeLearningDb):
        """upsert_learning drops the write to drop_id without raising or reporting,
        the way an adapter behaves when its statement fails and is swallowed."""

        drop_id = ""

        def upsert_learning(self, id: str, **kwargs: Any) -> None:
            if id == self.drop_id:
                return
            super().upsert_learning(id=id, **kwargs)

    @MODES
    async def test_dropped_rekey_write_leaves_the_source_row_and_reports_failed(self, use_async: bool) -> None:
        db = self.SilentUpsertDb()
        db.drop_id = _user_key("acme", "company", ALICE)
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["failed"] == [legacy_id]
        assert report["rekeyed"] == []
        assert list(db.rows) == [legacy_id]
        assert db.rows[legacy_id]["content"] == _clean_content("acme", ALICE)

    @MODES
    async def test_dropped_quarantine_write_leaves_the_contaminated_row_and_reports_failed(
        self, use_async: bool
    ) -> None:
        db = self.SilentUpsertDb()
        db.drop_id = legacy_entity_learning_id("initech", "company", "quarantined_user")
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["contaminated"] == [dirty]
        assert report["quarantined"] == []
        assert report["failed"] == [dirty]
        # The contaminated content is the only copy of that user's data, so a
        # quarantine whose write did not land leaves the row exactly where it is.
        assert list(db.rows) == [dirty]
        assert db.rows[dirty]["content"] == _clean_content("initech", BOB)

    @MODES
    async def test_landed_rekey_write_removes_the_source_row(self, use_async: bool) -> None:
        db = self.SilentUpsertDb()
        # A key this walk never writes, so every write the migration makes lands.
        db.drop_id = _user_key("acme", "company", BOB)
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["rekeyed"] == [legacy_id]
        assert report["failed"] == []
        assert list(db.rows) == [_user_key("acme", "company", ALICE)]

    @MODES
    async def test_landed_quarantine_write_removes_the_contaminated_row(self, use_async: bool) -> None:
        db = self.SilentUpsertDb()
        db.drop_id = legacy_entity_learning_id("acme", "company", "quarantined_user")
        dirty = _seed_legacy(db, "initech", ALICE, _clean_content("initech", BOB))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["quarantined"] == [dirty]
        assert report["failed"] == []
        quarantined = legacy_entity_learning_id("initech", "company", "quarantined_user")
        assert list(db.rows) == [quarantined]
        assert db.rows[quarantined]["content"] == _clean_content("initech", BOB)


class TestTheDestinationComesFromTheFreshRow:
    """The walk pages the whole table before it writes, so the paged row is
    stale the moment anything touches it. The destination key and every column
    are derived from the row as it stands at copy time, not as it was paged."""

    class OwnerChangesUnderTheWalkDb(FakeLearningDb):
        """The row changes owner between being paged and being copied."""

        target_id = ""
        new_owner = ""
        _fired = False

        def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
            if id == self.target_id and not self._fired:
                self._fired = True
                row = self.rows[id]
                row["user_id"] = self.new_owner
                row["content"] = {**row["content"], "user_id": self.new_owner}
            return super().get_learning_by_id(id)

    @MODES
    async def test_a_row_that_changes_owner_lands_on_the_new_owners_key(self, use_async: bool) -> None:
        db = self.OwnerChangesUnderTheWalkDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))
        db.target_id = legacy_id
        db.new_owner = BOB

        report = await _rekey(db, use_async, dry_run=False)

        assert report["rekeyed"] == [legacy_id]
        # Keyed and owned by whoever holds the row now. The paged owner's key
        # would hand one user's content to another.
        assert _user_key("acme", "company", BOB) in db.rows
        assert _user_key("acme", "company", ALICE) not in db.rows
        assert db.rows[_user_key("acme", "company", BOB)]["user_id"] == BOB

    @MODES
    async def test_an_unchanged_row_still_lands_on_its_own_key(self, use_async: bool) -> None:
        db = FakeLearningDb()
        legacy_id = _seed_legacy(db, "acme", ALICE, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["rekeyed"] == [legacy_id]
        assert _user_key("acme", "company", ALICE) in db.rows
        assert db.rows[_user_key("acme", "company", ALICE)]["user_id"] == ALICE


class TestFoldingIntoAnExistingRow:
    """The row already on the target key is the newer state. It wins every
    conflict, its ordering is preserved, and nothing it carries is dropped."""

    def _fold(self, db: FakeLearningDb, source: Dict[str, Any], target: Dict[str, Any], **kw: Any) -> str:
        legacy_id = _seed_legacy(db, "acme", ALICE, source)
        db.upsert_learning(
            id=_user_key("acme", "company", ALICE),
            learning_type="entity_memory",
            entity_id="acme",
            entity_type="company",
            namespace="user",
            user_id=ALICE,
            content=target,
            **kw,
        )
        return legacy_id

    @MODES
    async def test_the_newer_rows_facts_end_up_last(self, use_async: bool) -> None:
        """The store renders the last N facts as the newest, so the source's go in
        front. Appending them instead buries every fact the newer row holds."""
        db = FakeLearningDb()
        source = {
            **_clean_content("acme", ALICE),
            "facts": [{"id": f"old{i}", "content": f"old {i}"} for i in range(10)],
        }
        target = {**_clean_content("acme", ALICE), "facts": [{"id": "new0", "content": "new 0"}]}
        self._fold(db, source, target)

        await _rekey(db, use_async, dry_run=False)

        facts = db.rows[_user_key("acme", "company", ALICE)]["content"]["facts"]
        assert [f["id"] for f in facts][-1] == "new0"

    @MODES
    async def test_a_fact_recorded_in_both_rows_is_kept_once(self, use_async: bool) -> None:
        """The two rows were written independently so their fact ids never match.
        Facts key on their normalised content, the way the store's own duplicate
        check does."""
        db = FakeLearningDb()
        source = {**_clean_content("acme", ALICE), "facts": [{"id": "a1", "content": "Uses PostgreSQL"}]}
        target = {**_clean_content("acme", ALICE), "facts": [{"id": "b9", "content": "uses   postgresql"}]}
        self._fold(db, source, target)

        await _rekey(db, use_async, dry_run=False)

        facts = db.rows[_user_key("acme", "company", ALICE)]["content"]["facts"]
        assert len(facts) == 1

    @MODES
    async def test_the_newer_rows_plain_string_facts_survive(self, use_async: bool) -> None:
        """A fact is not always a dict. The store renders a bare string, so a fold
        that keeps only dicts destroys the newer row's data."""
        db = FakeLearningDb()
        source = {**_clean_content("acme", ALICE), "facts": [{"id": "s", "content": "legacy"}]}
        target = {**_clean_content("acme", ALICE), "facts": ["Uses PostgreSQL", "API is OAuth2"]}
        self._fold(db, source, target)

        await _rekey(db, use_async, dry_run=False)

        facts = db.rows[_user_key("acme", "company", ALICE)]["content"]["facts"]
        assert "Uses PostgreSQL" in facts and "API is OAuth2" in facts

    @MODES
    async def test_a_field_only_the_older_row_carries_survives(self, use_async: bool) -> None:
        db = FakeLearningDb()
        source = {**_clean_content("acme", ALICE), "internal_ref": "TICKET-42"}
        self._fold(db, source, _clean_content("acme", ALICE))

        await _rekey(db, use_async, dry_run=False)

        assert db.rows[_user_key("acme", "company", ALICE)]["content"]["internal_ref"] == "TICKET-42"

    @MODES
    async def test_the_newer_rows_metadata_survives(self, use_async: bool) -> None:
        db = FakeLearningDb()
        self._fold(db, _clean_content("acme", ALICE), _clean_content("acme", ALICE), metadata={"source": "crm-sync"})

        await _rekey(db, use_async, dry_run=False)

        assert db.rows[_user_key("acme", "company", ALICE)]["metadata"] == {"source": "crm-sync"}

    @MODES
    async def test_a_collection_that_is_not_a_list_is_failed_and_left_alone(self, use_async: bool) -> None:
        db = FakeLearningDb()
        source = {**_clean_content("acme", ALICE), "facts": {"f": "x"}}
        legacy_id = self._fold(db, source, _clean_content("acme", ALICE))

        report = await _rekey(db, use_async, dry_run=False)

        assert report["failed"] == [legacy_id]
        assert report["merged"] == []
        assert legacy_id in db.rows
