"""Modal sandbox contracts against a fake Modal SDK that runs commands on this host."""

import asyncio
import io
import json
import os
import subprocess
import sys
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import CheckpointContentError, CheckpointRef, FileCheckpointStore
from agno.sandbox.modal import ModalCheckpointTransfer, ModalSandbox


class NotFoundError(Exception):
    pass


class AlreadyExistsError(Exception):
    pass


def _aio(function):
    return SimpleNamespace(aio=function)


class Stream:
    """A finished process stream: async iteration in chunks, or read whole."""

    def __init__(self, process, index):
        self.process, self.index = process, index
        self.read = _aio(self._read)

    async def _read(self):
        await self.process.done.wait()
        data = self.process.result[self.index]
        return data if not self.process.text else data.decode()

    async def __aiter__(self):
        await self.process.done.wait()
        data = self.process.result[self.index]
        for offset in range(0, len(data), 65536):
            yield data[offset : offset + 65536]


class Stdin:
    def __init__(self, process):
        self.process = process
        self.drain = _aio(self._drain)

    def write(self, data):
        self.process.buffer.extend(data)

    def write_eof(self):
        self.process.start()

    async def _drain(self):
        await asyncio.sleep(0)


class Process:
    def __init__(self, world, box, argv, workdir, timeout, text):
        self.world, self.box, self.argv, self.workdir, self.timeout, self.text = (
            world,
            box,
            argv,
            workdir,
            timeout,
            text,
        )
        self.buffer = bytearray()
        self.done = asyncio.Event()
        self.result = None
        self.task = None
        self.stdin, self.stdout, self.stderr = Stdin(self), Stream(self, 1), Stream(self, 2)
        self.wait = _aio(self._wait)
        command = self._command()
        if not (command[:3] == ["python", "-I", "-c"] or command[:2] == ["tar", "-x"]):
            self.start()

    def _command(self):
        argv = list(self.argv)
        if argv[0] == "setpriv":
            argv = argv[argv.index("--") + 1 :]
        return argv

    def start(self):
        if self.task is None:
            self.task = asyncio.ensure_future(self._run())

    async def _run(self):
        argv = [self.box.path(arg) for arg in self._command()]
        if argv[0] == "python":
            argv[0] = sys.executable
        data = bytes(self.buffer)
        if argv[:3] == [sys.executable, "-I", "-c"]:
            request = json.loads(data)
            request["argv"] = [self.box.path(arg) for arg in request["argv"]]
            if request["argv"][0] == "python":
                request["argv"][0] = sys.executable
            data = json.dumps(request).encode()
        environment = dict(os.environ, COPYFILE_DISABLE="1")
        if argv[0] == "sh" and "chown" in argv[-1]:
            # This host cannot chown to the sandbox user; the script is checked by the test instead.
            self.result = (0, b"", b"")
            self.done.set()
            return
        if self.world.exec_error is not None:
            error, self.world.exec_error = self.world.exec_error, None
            self.result = (1, b"", b"")
            self.done.set()
            raise error
        completed = await asyncio.to_thread(
            subprocess.run,
            argv,
            input=data,
            capture_output=True,
            cwd=self.box.path(self.workdir or "/"),
            env=environment,
        )
        self.result = (completed.returncode, completed.stdout, completed.stderr)
        self.done.set()

    async def _wait(self):
        await self.done.wait()
        return self.result[0]


class Box:
    """One fake Modal sandbox: a host directory standing in for its root."""

    def __init__(self, world, object_id, name, tags, options, root):
        self.world, self.object_id, self.name, self.tags, self.options, self.root = (
            world,
            object_id,
            name,
            dict(tags),
            options,
            root,
        )
        self.exit_code = None
        (root / "workspace").mkdir(parents=True)
        (root / "runtime").mkdir()
        self.poll = _aio(self._poll)
        self.get_tags = _aio(self._get_tags)
        self.exec = _aio(self._exec)
        self.terminate = _aio(self._terminate)

    def path(self, value):
        if value == "/":
            return str(self.root)
        for prefix in ("/workspace", "/runtime"):
            value = value.replace(prefix, str(self.root) + prefix)
        return value

    async def _poll(self):
        return self.exit_code

    async def _get_tags(self):
        return dict(self.tags)

    async def _exec(self, *argv, timeout=None, workdir=None, text=True):
        if self.exit_code is not None:
            raise RuntimeError("Sandbox has already finished")
        self.world.execs.append(list(argv))
        return Process(self.world, self, argv, workdir, timeout, text)

    async def _terminate(self, wait=False):
        self.world.terminated.append(self.object_id)
        if self.exit_code is None:
            self.exit_code = 137
        return self.exit_code if wait else None


class Image:
    def __init__(self, reference):
        self.reference = reference
        self.object_id = None
        self.build = _aio(self._build)

    @classmethod
    def from_registry(cls, reference):
        return cls(reference)

    def entrypoint(self, value):
        self.cleared = value == []
        return self

    async def _build(self, app):
        self.object_id = "im-" + str(abs(hash(self.reference)))


class World:
    def __init__(self, root):
        self.root = root
        self.boxes = {}
        self.creates, self.execs, self.terminated = [], [], []
        self.create_error = None
        self.exec_error = None
        self.apps = []

    async def lookup(self, name, create_if_missing=False, environment_name=None, client=None):
        self.apps.append(name)
        await asyncio.sleep(0)
        return SimpleNamespace(name=name)

    async def create(self, *argv, app, name, tags, image, **options):
        self.creates.append(dict(options, name=name, argv=argv, image=image))
        if any(box.name == name and box.exit_code is None for box in self.boxes.values()):
            raise AlreadyExistsError(name)
        object_id = f"sb-{len(self.boxes) + 1}"
        box = Box(self, object_id, name, tags, options, self.root / object_id)
        self.boxes[object_id] = box
        if self.create_error is not None:
            error, self.create_error = self.create_error, None
            raise error
        return box

    async def from_name(self, app_name, name, environment_name=None, client=None):
        for box in self.boxes.values():
            if box.name == name and box.exit_code is None:
                return box
        raise NotFoundError(name)

    async def from_id(self, object_id, client=None):
        if object_id not in self.boxes:
            raise NotFoundError(object_id)
        return self.boxes[object_id]


@pytest.fixture
def world(tmp_path, monkeypatch):
    world = World(tmp_path / "modal")
    fake = SimpleNamespace(
        App=SimpleNamespace(lookup=_aio(world.lookup)),
        Image=Image,
        Sandbox=SimpleNamespace(
            create=_aio(world.create), from_name=_aio(world.from_name), from_id=_aio(world.from_id)
        ),
        exception=SimpleNamespace(NotFoundError=NotFoundError, AlreadyExistsError=AlreadyExistsError),
    )
    monkeypatch.setitem(sys.modules, "modal", fake)
    return world


def provider(**kwargs):
    kwargs.setdefault("uid", None)
    return ModalSandbox("registry.example/agno-sandbox:1", namespace="tests", **kwargs)


def test_constructor_validates_settings(world):
    with pytest.raises(ValueError, match="lifetime"):
        provider(lifetime=30)
    with pytest.raises(ValueError, match="shorter than the lifetime"):
        provider(lifetime=600, execution_timeout=600)
    with pytest.raises(ValueError, match="both block"):
        provider(block_network=True, outbound_domain_allowlist=["api.anthropic.com"])
    with pytest.raises(ValueError, match="modal.Image"):
        ModalSandbox(object())
    assert provider(lifetime=600).execution_timeout == 300
    with pytest.raises(ValueError, match="retain_checkpoints"):
        provider(retain_checkpoints=0)
    assert provider().retain_checkpoints == 3 and provider(retain_checkpoints=None).retain_checkpoints is None


def test_missing_sdk_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "modal", None)
    with pytest.raises(ImportError, match="modal-sandbox"):
        ModalSandbox("image")


@pytest.mark.asyncio
async def test_create_is_idempotent_and_tags_identity(world):
    sandbox = provider(env={"A": "1"})
    first = await sandbox.acreate("session", agent_id="coder", env={"KEY": "v"})
    second = await sandbox.acreate("session", agent_id="coder", env={"KEY": "v"})
    assert first == second
    assert (first.session_id, first.agent_id, first.generation, first.state) == ("session", "coder", 1, "running")
    assert len(world.boxes) == 1
    create = world.creates[0]
    assert create["env"] == {"HOME": "/runtime", "KEY": "v"}
    assert create["timeout"] == 3600 and create["image"].cleared
    assert world.boxes[first.provider_ref].tags["agno_config"] == first.config_digest
    assert await sandbox.afind("session", agent_id="coder", env={"KEY": "v"}) == first
    assert await sandbox.aget(first.provider_ref) == first


@pytest.mark.asyncio
async def test_concurrent_first_creates_resolve_the_image_once(world):
    sandbox = provider()
    handles = await asyncio.gather(*(sandbox.acreate(f"session-{index}") for index in range(10)))
    assert len({handle.provider_ref for handle in handles}) == 10
    assert world.apps == ["agno-sandbox"]
    assert len({id(create["image"]) for create in world.creates}) == 1


@pytest.mark.asyncio
async def test_lost_create_reply_is_found_by_name(world):
    sandbox = provider()
    world.create_error = ConnectionError("reply lost")
    handle = await sandbox.acreate("session")
    assert handle.provider_ref == "sb-1" and len(world.boxes) == 1


@pytest.mark.asyncio
async def test_failed_create_with_nothing_running_raises(world):
    sandbox = provider()

    async def refuse(*args, **kwargs):
        raise ConnectionError("unreachable")

    sys.modules["modal"].Sandbox.create = _aio(refuse)
    with pytest.raises(SandboxError, match="creation failed"):
        await sandbox.acreate("session")


@pytest.mark.asyncio
async def test_generation_with_other_configuration_is_refused(world):
    await provider().acreate("session", env={"KEY": "a"})
    with pytest.raises(SandboxError, match="different configuration"):
        await provider().acreate("session", env={"KEY": "b"})
    with pytest.raises(SandboxError, match="different compute configuration"):
        await provider().afind("session", env={"KEY": "b"})
    with pytest.raises(SandboxError, match="namespace"):
        await ModalSandbox("registry.example/agno-sandbox:1", uid=None).aget("sb-1")


@pytest.mark.asyncio
async def test_commands_and_termination_require_the_owning_identity(world):
    owner = provider()
    handle = await owner.acreate("session", env={"KEY": "v"})
    other = ModalSandbox("registry.example/agno-sandbox:1", namespace="other", uid=None)
    for call in (other.aexec(handle, ["true"]), other.astop(handle), other.adestroy(handle)):
        with pytest.raises(SandboxError, match="namespace"):
            await call
    for forged in (replace(handle, session_id="another"), replace(handle, config_digest="0" * 64)):
        for call in (owner.aexec(forged, ["true"]), owner.astop(forged), owner.adestroy(forged)):
            with pytest.raises(SandboxError, match="identity changed"):
                await call
    assert world.terminated == [] and world.boxes[handle.provider_ref].exit_code is None
    assert (await owner.aexec(handle, ["true"])).exit_code == 0


@pytest.mark.asyncio
async def test_stopped_generation_is_not_recreated_but_destroyed_one_is(world):
    sandbox = provider()
    handle = await sandbox.acreate("session")
    await sandbox.astop(handle)
    assert await sandbox.aget(handle.provider_ref) is None
    assert await sandbox.afind("session") is None
    with pytest.raises(SandboxError, match="new generation"):
        await sandbox.acreate("session")
    with pytest.raises(SandboxError, match="not running"):
        await sandbox.aexec(handle, ["true"])
    await sandbox.adestroy(handle)
    fresh = await sandbox.acreate("session")
    assert fresh.provider_ref != handle.provider_ref
    assert await sandbox.aget("sb-404") is None
    with pytest.raises(ValueError, match="reference"):
        await sandbox.aget("agno-not-an-id")


@pytest.mark.asyncio
async def test_exec_runs_the_bounded_runner(world):
    sandbox = provider()
    handle = await sandbox.acreate("session")
    result = await sandbox.aexec(handle, ["python", "-c", "import sys; print(sys.stdin.read().upper())"], stdin=b"hi")
    assert (result.exit_code, result.stdout.strip(), result.timed_out) == (0, "HI", False)
    pwd = await sandbox.aexec(handle, ["pwd"])
    assert pwd.stdout.strip().endswith("/workspace")
    assert world.terminated == []


@pytest.mark.asyncio
async def test_timed_out_or_lost_commands_stop_compute(world):
    sandbox = provider()
    handle = await sandbox.acreate("session")
    result = await sandbox.aexec(handle, ["sleep", "5"], timeout=0.2)
    assert result.timed_out and world.terminated == [handle.provider_ref]

    other = await sandbox.acreate("other")
    world.exec_error = ConnectionError("stream reset")
    with pytest.raises(SandboxError, match="transport failed"):
        await sandbox.aexec(other, ["true"])
    assert world.terminated[-1] == other.provider_ref


@pytest.mark.asyncio
async def test_runtime_rpc_failure_leaves_compute_alone(world):
    sandbox = provider()
    handle = await sandbox.acreate("session")
    world.exec_error = ConnectionError("stream reset")
    with pytest.raises(SandboxError):
        await sandbox.arpc(handle, "poll", b"{}")
    assert world.terminated == []
    with pytest.raises(ValueError, match="start/poll"):
        await sandbox.arpc(handle, "exec", b"{}")


@pytest.mark.asyncio
async def test_commands_drop_to_the_sandbox_user(world):
    sandbox = ModalSandbox("registry.example/agno-sandbox:1", namespace="tests")
    await sandbox.acreate("session")
    setup = world.execs[0]
    assert setup[:2] == ["sh", "-c"] and "chown 1000:1000 /workspace /runtime" in setup[2]
    assert sandbox._argv(["tar", "-cf", "-"]) == [
        "setpriv",
        "--reuid=1000",
        "--regid=1000",
        "--clear-groups",
        "--",
        "tar",
        "-cf",
        "-",
    ]


def write_tree(root: Path) -> None:
    (root / "workspace" / "src").mkdir(parents=True, exist_ok=True)
    (root / "workspace" / "src" / "main.py").write_text("print('hi')\n")
    (root / "workspace" / "link").symlink_to("src/main.py")
    native = root / "runtime" / "native"
    (native / "codex").mkdir(parents=True)
    (native / "codex" / "auth.json").write_text("secret")
    (native / "session.json").write_text("{}")
    native.chmod(0o750)


@pytest.mark.asyncio
async def test_checkpoint_round_trip_into_a_fresh_generation(world, tmp_path):
    sandbox = provider()
    store = FileCheckpointStore(tmp_path / "store")
    transfer = sandbox.checkpoint_transfer(store)
    assert isinstance(transfer, ModalCheckpointTransfer)
    source = await sandbox.acreate("session")
    write_tree(world.boxes[source.provider_ref].root)
    reference = await transfer.acapture(source, state={"binding": "b1"})
    assert isinstance(reference, CheckpointRef)

    target = await sandbox.acreate("session", generation=2)
    state = await transfer.arestore(target, reference)
    assert state == {"binding": "b1"}
    root = world.boxes[target.provider_ref].root
    assert (root / "workspace" / "src" / "main.py").read_text() == "print('hi')\n"
    assert os.readlink(root / "workspace" / "link") == "src/main.py"
    assert (root / "runtime" / "native" / "session.json").read_text() == "{}"
    assert not (root / "runtime" / "native" / "codex" / "auth.json").exists()
    assert (root / "runtime" / "native").stat().st_mode & 0o777 == 0o750

    with pytest.raises(SandboxError, match="empty, unused generation"):
        await transfer.arestore(target, reference)


@pytest.mark.asyncio
async def test_failed_restore_stops_the_partial_computer(world, tmp_path, monkeypatch):
    sandbox = provider()
    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "store"))
    source = await sandbox.acreate("session")
    write_tree(world.boxes[source.provider_ref].root)
    reference = await transfer.acapture(source, state={})
    target = await sandbox.acreate("session", generation=2)

    async def broken(handle, root, path):
        raise SandboxError("import failed")

    monkeypatch.setattr(transfer, "_import", broken)
    with pytest.raises(SandboxError, match="import failed"):
        await transfer.arestore(target, reference)
    assert world.terminated == [target.provider_ref]


@pytest.mark.asyncio
async def test_capture_rejects_an_export_that_escapes_its_root(world, tmp_path, monkeypatch):
    sandbox = provider()
    transfer = sandbox.checkpoint_transfer(FileCheckpointStore(tmp_path / "store"))
    handle = await sandbox.acreate("session")

    async def hostile(handle, root, destination):
        with tarfile.open(destination, "w") as archive:
            info = tarfile.TarInfo("native/escaped" if root == "workspace" else "native")
            if root == "workspace":
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            else:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)

    monkeypatch.setattr(transfer, "_export", hostile)
    with pytest.raises(SandboxError, match="escaped its declared root"):
        await transfer.acapture(handle, state={})


@pytest.mark.asyncio
async def test_capture_stops_reading_past_the_byte_limit(world, tmp_path):
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

    sandbox = provider()
    transfer = ModalCheckpointTransfer(
        sandbox, FileCheckpointStore(tmp_path / "store"), archive=CheckpointArchive(CheckpointLimits(max_bytes=4096))
    )
    handle = await sandbox.acreate("session")
    (world.boxes[handle.provider_ref].root / "workspace" / "big").write_bytes(b"x" * 100_000)
    with pytest.raises(CheckpointContentError, match="byte limit"):
        await transfer.acapture(handle, state={})


def test_sync_variants_delegate(world):
    sandbox = provider()
    handle = sandbox.create("session")
    assert sandbox.get(handle.provider_ref) == handle
    assert sandbox.exec(handle, ["true"]).exit_code == 0
    sandbox.destroy(handle)
    assert sandbox.get(handle.provider_ref) is None
