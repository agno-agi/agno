from collections import Counter
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from agno.fs._place import _connect_arguments, database_place

if TYPE_CHECKING:
    from agno.fs import FileSystem
    from agno.os.app import AgentOS

# Never part of a namespace, so an id that carries a backend cannot be read as another namespace.
_ID_SEPARATOR = ":"
# Marks a place known only as the engine itself, which no other process can name.
_ENGINE_PLACE = "engine"


def _database_place(engine: Any) -> tuple:
    """The database an engine connects to: the same for every engine on it, synchronous or not.

    An engine whose database is not known for certain is its own place: listing
    one store twice hides no file, and merging two stores does.
    """
    return database_place(engine) or (_ENGINE_PLACE, id(engine))


def _filesystem_backend_key(filesystem: "FileSystem") -> tuple:
    """Identify a shared backend within the current process.

    A table in a database is one backend however it is reached: through a
    database object, through an engine, or through two of either. A database
    object whose connection arguments cannot be read is matched by its id.
    """
    backend = filesystem.backend
    engine = getattr(backend, "db_engine", None)
    table_name = getattr(backend, "table_name", None)
    db = getattr(backend, "db", None)
    if engine is not None and table_name is not None and (db is None or _connect_arguments(engine) is not None):
        db_schema = getattr(backend, "db_schema", None)
        place = _database_place(engine)
        if db_schema is None and place[0] == "postgresql":
            # The search_path chooses the table, and a connection can set it outside the URL.
            place = (_ENGINE_PLACE, id(engine))
        return ("db", place, db_schema, table_name)
    if db is not None:
        return (
            "db",
            getattr(db, "id", None) or id(db),
            getattr(backend, "db_schema", None),
            getattr(backend, "table_name", None),
        )
    root = getattr(backend, "root", None)
    if root is not None:
        return ("local", str(root))
    return ("backend", id(backend))


def _filesystem_key(filesystem: "FileSystem", namespace: Optional[str] = None) -> tuple:
    """Identify one store within the current process: its backend and its namespace."""
    return (_filesystem_backend_key(filesystem), filesystem.namespace if namespace is None else namespace)


def _filesystem_id_forms(filesystem: "FileSystem", namespace: Optional[str] = None) -> Tuple[str, ...]:
    """The ids that can name a filesystem, shortest first.

    The namespace, then the namespace with its backend, then with the table or
    folder inside that backend: ``handbook``, ``handbook:main-db``,
    ``handbook:main-db:fs.agno_fs``. A table adds a digest of its database, so
    databases with the same names keep their ids in any order. A folder on disk
    is named by its last segment and a digest of its path. An id never carries
    a server path.
    """
    name = filesystem.namespace if namespace is None else namespace
    backend = filesystem.backend
    table_name = getattr(backend, "table_name", None)
    root = getattr(backend, "root", None)
    if table_name is not None:
        db = getattr(backend, "db", None)
        db_schema = getattr(backend, "db_schema", None)
        parts = [str(getattr(db, "id", None) or "db"), f"{db_schema}.{table_name}" if db_schema else str(table_name)]
        place = _filesystem_backend_key(filesystem)[1]
        if isinstance(place, tuple) and place[0] != _ENGINE_PLACE:
            parts.append(sha1(repr(place).encode("utf-8")).hexdigest()[:8])
    elif root is not None:
        parts = [Path(str(root)).name or "local", sha1(str(root).encode("utf-8")).hexdigest()[:8]]
    else:
        parts = [type(backend).__name__]
    forms = [name]
    for part in parts:
        forms.append(f"{forms[-1]}{_ID_SEPARATOR}{part}")
    return tuple(forms)


def _assign_filesystem_ids(
    forms_by_key: Dict[tuple, Tuple[str, ...]],
    reserved_forms: Iterable[Tuple[str, ...]] = (),
    reserved_ids: Iterable[str] = (),
    *,
    unnumbered_first: bool = True,
) -> Dict[tuple, str]:
    """Give each store its shortest form that names no other store, in ``forms_by_key`` or reserved.

    Stores whose backends have the same names share every form. They are numbered
    in order, skipping any number that would name another store. Without ``unnumbered_first``
    the first of them has a number too: the form alone is one the others answer to, so it would
    open another store when the first is not there.
    """
    reserved = {form for forms in reserved_forms for form in forms} | set(reserved_ids)
    counts = Counter(form for forms in forms_by_key.values() for form in forms)
    assigned: Dict[tuple, str] = {}
    taken = set(reserved)
    for key, forms in forms_by_key.items():
        chosen = next((form for form in forms if counts[form] == 1 and form not in reserved), None)
        if chosen is None:
            # A form another store takes as its own is not given, with or without a number.
            chosen, position = forms[-1], 1
            if not unnumbered_first:
                position = 1 if chosen in reserved else 0
            while chosen in taken or (chosen in counts and not (unnumbered_first and position == 1)):
                position += 1
                chosen = f"{forms[-1]}{_ID_SEPARATOR}{position}"
        taken.add(chosen)
        assigned[key] = chosen
    return assigned


def _filesystem_ids(
    *groups: Iterable[Tuple[tuple, Tuple[str, ...]]], others: Iterable[Tuple[tuple, Tuple[str, ...]]] = ()
) -> Dict[tuple, str]:
    """An id for each store, keyed as given: its namespace, with the backend added when two would share it.

    Each group is ``(key, forms)`` pairs, and the first pair given for a store
    names it. The ids of a group depend on that group and the groups before it
    alone: a store takes the shortest form that can name no store of an earlier
    group. So the ids of declared stores stay the same whatever agents come and go.
    ``others`` are named last. Any of them may not be loaded, so the first of
    those sharing every name is numbered too.
    """
    ids: Dict[tuple, str] = {}
    earlier: List[Tuple[str, ...]] = []
    for group, unnumbered_first in [*((group, True) for group in groups), (others, False)]:
        forms_by_key: Dict[tuple, Tuple[str, ...]] = {}
        for key, forms in group:
            if key not in ids:
                forms_by_key.setdefault(key, forms)
        ids.update(
            _assign_filesystem_ids(forms_by_key, earlier, list(ids.values()), unnumbered_first=unnumbered_first)
        )
        earlier.extend(forms_by_key.values())
    return ids


def _listed_filesystem_ids(
    os: "AgentOS",
    user_id: Optional[str],
    agents: Iterable[Any],
    others: Iterable[Tuple[tuple, Tuple[str, ...]]] = (),
) -> Dict[tuple, str]:
    """The id of each store a caller is shown, for /config and for the /filesystem routes alike.

    The stores /config lists are named first: the Company filesystem and those
    declared on the AgentOS, then those the ``agents`` declared in code hold, in the order of their ids,
    each with its namespace resolved for the caller. ``others`` are the
    ``(key, forms)`` of stores only the routes see, held by agents built for a
    request or stored. They are named last, so an id /config lists names the
    same store on the routes whatever those agents hold.
    """
    from agno.agent import Agent
    from agno.fs import InvalidPathError
    from agno.fs._reserved import is_reserved

    declared: List[Tuple[tuple, Tuple[str, ...]]] = []
    held: List[Tuple[tuple, Tuple[str, ...]]] = []

    def name(group: List[Tuple[tuple, Tuple[str, ...]]], filesystem: "FileSystem", agent_id: Optional[str]) -> None:
        try:
            view = filesystem.resolve(user_id=user_id, agent_id=agent_id)
        except InvalidPathError:
            # The caller's identity cannot be part of the namespace: there is no store of theirs to name.
            return
        if agent_id is not None and not filesystem.user_scoped and is_reserved(view.backend, view.namespace):
            # The agent is refused this namespace, so it holds nothing there.
            return
        namespace = view.namespace
        group.append((_filesystem_key(filesystem, namespace), _filesystem_id_forms(filesystem, namespace)))

    company = os._company_filesystem()
    # The Company filesystem is first, as /config describes it.
    for filesystem in [*([company] if company is not None else []), *os._served_filesystems()]:
        # Only an agent holding the store fills {agent_id} or {team_id}.
        if all(placeholder == "user_id" for placeholder in filesystem._placeholders):
            name(declared, filesystem, None)
    roster = [agent for agent in agents if isinstance(agent, Agent) and agent.id]
    for agent in sorted(roster, key=lambda agent: str(agent.id)):
        for filesystem, _ in agent.filesystems:
            name(held, filesystem, agent.id)
    return _filesystem_ids(declared, held, others=others)


def _can_share_every_name(key: tuple) -> bool:
    """Whether another store can have every name of this one, because where its files are is not known."""
    backend = key[0]
    if backend[0] == "backend":
        return True
    return backend[0] == "db" and not (isinstance(backend[1], tuple) and backend[1][0] != _ENGINE_PLACE)


def _match_filesystem_id(filesystem_id: str, candidates: List[Tuple[str, Tuple[str, ...]]]) -> List[int]:
    """Positions of the ``(id, forms)`` candidates a requested id names: its own id first, else any of its forms.

    A longer form keeps naming a store whose id is shorter, so an id taken while
    another store shared the namespace still resolves once that store is gone.
    """
    exact = [index for index, (candidate_id, _) in enumerate(candidates) if candidate_id == filesystem_id]
    if exact:
        return exact
    return [index for index, (_, forms) in enumerate(candidates) if filesystem_id in forms]
