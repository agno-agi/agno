"""A reader is advertised only when this install can actually run it.

Two things can make a reader unusable, and only one of them is visible to an import.
A missing module-scope dependency makes ``get_reader_class`` raise, which the config
surface has always caught. A dependency imported inside a read method does not: the
class imports cleanly and the reader is published, and the failure only appears after
an upload has already been accepted. These tests pin both halves, plus the report that
now says why a reader is missing instead of dropping it into DEBUG.
"""

import ast
import importlib
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Set, Tuple
from unittest.mock import patch

import pytest

from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.types import ContentType
from agno.knowledge.utils import (
    get_content_types_to_readers_mapping,
    get_reader_info,
    get_unavailable_chunkers_info,
    get_unavailable_readers_info,
)


def _specs(absent: Tuple[str, ...] = (), present: Tuple[str, ...] = ()):
    """Force find_spec's answer for the named packages; defer to reality for the rest.

    Patching the name bound in ``reader.base`` keeps the override local to the probe;
    patching ``importlib.util.find_spec`` would change it for the whole interpreter.
    """
    real = importlib.util.find_spec
    sentinel = object()

    def fake(name, package=None):
        if name in absent:
            return None
        if name in present:
            return sentinel
        return real(name, package)

    return patch("agno.knowledge.reader.base.find_spec", side_effect=fake)


class _BlockedFinder:
    """Refuse one package, so agno's own module-scope guard runs."""

    def __init__(self, blocked: str):
        self.blocked = blocked

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.blocked or fullname.startswith(f"{self.blocked}."):
            raise ImportError(f"blocked for test: {fullname}")
        return None


@contextmanager
def _package_absent(package: str, *reimport: str):
    """Make *package* unimportable and force *reimport* modules to be imported again.

    patch.dict(sys.modules, ...) is the obvious tool and the wrong one: it restores by
    clearing the whole mapping, so anything imported inside the block is evicted from the
    interpreter for good. This touches only the keys it names.
    """
    finder = _BlockedFinder(package)
    saved = {name: sys.modules.pop(name, None) for name in (package, *reimport)}
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        for name in (package, *reimport):
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


def _ffmpeg(present: bool):
    """Force the answer for the ffmpeg binary, leaving every other lookup alone.

    Pinned in both directions on purpose: docling's media formats need the binary as well as
    a speech package, so a test that let PATH decide would assert one thing on a developer
    machine that has ffmpeg and another on a runner that does not.
    """
    import shutil as shutil_module

    real_which = shutil_module.which

    def fake(name, *args, **kwargs):
        if name == "ffmpeg":
            return "/usr/bin/ffmpeg" if present else None
        return real_which(name, *args, **kwargs)

    return patch("agno.knowledge.reader.docling_reader.shutil.which", side_effect=fake)


def test_excel_reader_is_not_advertised_when_neither_engine_is_installed():
    with _specs(absent=("openpyxl", "xlrd")):
        with pytest.raises(ValueError, match=r"^Reader 'excel' has missing dependencies:.*openpyxl"):
            get_reader_info("excel")


def test_excel_advertises_only_xlsx_when_xlrd_is_missing():
    with _specs(absent=("xlrd",), present=("openpyxl",)):
        info = get_reader_info("excel")

    assert info["content_types"] == [ContentType.XLSX.value]
    assert info["unavailable_content_types"] == {ContentType.XLS.value: ["xlrd"]}


def test_excel_is_advertised_when_both_engines_are_installed():
    with _specs(present=("openpyxl", "xlrd")):
        info = get_reader_info("excel")

    assert info["content_types"] == [ContentType.XLSX.value, ContentType.XLS.value]
    assert info["unavailable_content_types"] == {}


def test_readers_without_read_time_requirements_are_unaffected():
    info = get_reader_info("text")

    assert info["content_types"] == [ct.value for ct in TextReader.get_supported_content_types()]
    assert info["unavailable_content_types"] == {}


def test_readers_for_type_drops_a_content_type_whose_engine_is_missing():
    with _specs(absent=("xlrd",), present=("openpyxl",)):
        mapping = get_content_types_to_readers_mapping()

    assert "excel" in mapping[ContentType.XLSX.value]
    assert "excel" not in mapping.get(ContentType.XLS.value, [])


def test_a_cached_reader_on_the_knowledge_instance_is_filtered_too():
    """The instance path takes precedence over the factory path, so it needs the same filter.

    ``Knowledge`` caches factory readers by key the first time it reads a file of that type,
    so an unfiltered instance path would re-advertise exactly what the factory path just
    stopped advertising.
    """
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge(name="Cached reader KB")
    knowledge.readers = {"excel": ExcelReader()}

    with _specs(absent=("openpyxl", "xlrd")):
        mapping = get_content_types_to_readers_mapping(knowledge)

    assert "excel" not in mapping.get(ContentType.XLSX.value, [])
    assert ContentType.XLS.value not in mapping


def test_unavailable_readers_are_reported_with_their_missing_packages():
    with _specs(absent=("openpyxl", "xlrd")):
        by_id = {entry["id"]: entry for entry in get_unavailable_readers_info()}

    assert "excel" in by_id
    assert by_id["excel"]["missing_packages"] == ["openpyxl", "xlrd"]
    assert "openpyxl" in by_id["excel"]["reason"]
    assert by_id["excel"]["name"] == "ExcelReader"


def test_a_read_time_failure_is_not_reported_as_an_unknown_reader():
    """The reason is what an operator reads, so it has to name the package, not the key."""
    with _specs(absent=("openpyxl", "xlrd")):
        by_id = {entry["id"]: entry for entry in get_unavailable_readers_info()}

    assert "Unknown reader" not in by_id["excel"]["reason"]
    assert by_id["excel"]["reason"].startswith("Reader 'excel' has missing dependencies:")


def test_unavailable_reader_reason_is_verbatim_for_module_level_failures():
    with _package_absent("pypdf", "agno.knowledge.reader.pdf_reader"):
        by_id = {entry["id"]: entry for entry in get_unavailable_readers_info()}

    assert "`pypdf` not installed" in by_id["pdf"]["reason"]
    assert by_id["pdf"]["missing_packages"] == ["pypdf"]


def test_unavailable_chunkers_are_reported_with_their_missing_packages():
    chunking_modules = [name for name in sys.modules if name.startswith("agno.knowledge.chunking")]

    with _package_absent("chonkie", *chunking_modules):
        by_id = {entry["id"]: entry for entry in get_unavailable_chunkers_info()}

    assert by_id, "expected at least one chunker to be unavailable without chonkie"
    for entry in by_id.values():
        assert entry["missing_packages"] == ["chonkie"]
        assert "chonkie" in entry["reason"]


def test_docx_reader_does_not_advertise_legacy_doc():
    """python-docx reads the Open XML package only; a legacy OLE2 .doc never opens."""
    assert ContentType.DOC not in get_reader_info("docx")["content_types"]
    assert ContentType.DOC.value not in get_content_types_to_readers_mapping()


# Imports that stay function-scoped on purpose, each with the behaviour that justifies it.
_ALLOWED_FUNCTION_SCOPED_IMPORTS = {
    ("text_reader.py", "aiofiles"),  # falls back to sync I/O with a warning
    ("markdown_reader.py", "aiofiles"),  # falls back to sync I/O with a warning
    ("pdf_reader.py", "rapidocr_onnxruntime"),  # opt-in OCR; base PDF reading does not need it
    ("docling_reader.py", "yaml"),  # only for OutputFormat.YAML; module is already gated on docling
}


def _function_scoped_third_party_imports(path: Path) -> Set[str]:
    """Root packages imported inside a function body, excluding stdlib and agno itself."""
    tree = ast.parse(path.read_text())
    found: Set[str] = set()

    def walk(node: ast.AST, inside_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            is_function = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            if inside_function and isinstance(child, ast.Import):
                for alias in child.names:
                    found.add(alias.name.split(".")[0])
            elif inside_function and isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                found.add(child.module.split(".")[0])
            walk(child, inside_function or is_function)

    walk(tree, False)
    return {name for name in found if name != "agno" and name not in sys.stdlib_module_names}


@pytest.mark.skipif(not hasattr(sys, "stdlib_module_names"), reason="sys.stdlib_module_names is 3.10+")
def test_every_hard_function_scoped_reader_import_is_declared():
    """A dependency imported at read time has to be declared, or the reader lies about itself.

    This is the guard that stops the Excel defect from being reintroduced by the next reader
    that defers an import.
    """
    reader_dir = Path(sys.modules[ReaderFactory.__module__].__file__).parent

    undeclared = []
    for path in sorted(reader_dir.glob("*_reader.py")):
        for package in sorted(_function_scoped_third_party_imports(path)):
            if (path.name, package) in _ALLOWED_FUNCTION_SCOPED_IMPORTS:
                continue

            module_name = f"agno.knowledge.reader.{path.stem}"
            try:
                module = importlib.import_module(module_name)
            except Exception:
                # The module cannot be imported here, so nothing it defers can be advertised.
                continue

            declared: Set[str] = set()
            for attribute in vars(module).values():
                if (
                    isinstance(attribute, type)
                    and issubclass(attribute, Reader)
                    and attribute.__module__ == module_name
                ):
                    for packages in attribute.get_read_time_requirements().values():
                        declared.update(packages)

            if package not in declared:
                undeclared.append((path.name, package))

    assert undeclared == [], (
        f"Undeclared read-time imports: {undeclared}. Declare them in the reader's "
        "get_read_time_requirements(), or allowlist them with the fallback that makes them optional."
    )


def test_docling_does_not_advertise_audio_it_cannot_transcribe():
    """docling loads its speech engine at read time, so the class import proves nothing."""
    with _ffmpeg(present=True), _specs(absent=("whisper", "mlx_whisper", "whisper_s2t")):
        info = get_reader_info("docling")

    assert ContentType.AUDIO_MP3.value not in info["content_types"]
    assert info["unavailable_content_types"][ContentType.AUDIO_MP3.value] == ["openai-whisper"]
    assert ContentType.IMAGE_PNG.value in info["content_types"]


def test_docling_advertises_audio_when_the_engine_is_installed():
    with _ffmpeg(present=True), _specs(present=("whisper",)):
        info = get_reader_info("docling")

    assert ContentType.AUDIO_MP3.value in info["content_types"]
    assert info["unavailable_content_types"] == {}


def test_a_reader_that_does_not_return_enums_is_skipped_not_fatal():
    """One non-conforming reader must not take the whole config sweep down with it."""

    class StringyReader(Reader):
        @classmethod
        def get_supported_chunking_strategies(cls):
            return []

        @classmethod
        def get_supported_content_types(cls):
            return [".mine"]

    from agno.knowledge.utils import get_all_readers_info, get_reader_info_from_instance

    with pytest.raises(ValueError):
        get_reader_info_from_instance(StringyReader(), "stringy")

    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge(name="Stringy KB")
    knowledge.readers = {"stringy": StringyReader()}

    ids = [info["id"] for info in get_all_readers_info(knowledge)]
    assert "stringy" not in ids
    assert "text" in ids


def test_a_declaration_keyed_by_a_plain_string_is_honoured():
    """The declaration is a public hook, so it takes the enum or its value."""

    class StringKeyedReader(Reader):
        @classmethod
        def get_supported_chunking_strategies(cls):
            return []

        @classmethod
        def get_supported_content_types(cls):
            return [ContentType.TXT]

        @classmethod
        def get_read_time_requirements(cls):
            return {ContentType.TXT.value: ["definitely_not_installed_xyz"]}

    assert StringKeyedReader.get_missing_read_time_packages() == ["definitely_not_installed_xyz"]
    assert StringKeyedReader.get_available_content_types() == []


def test_availability_is_answered_by_a_single_sweep():
    """The sweep imports every reader module, so both halves come from one pass."""
    import agno.knowledge.utils as knowledge_utils

    real_get_reader_info = knowledge_utils.get_reader_info
    calls = []

    def counting(key):
        calls.append(key)
        return real_get_reader_info(key)

    with patch.object(knowledge_utils, "get_reader_info", side_effect=counting):
        available, unavailable = knowledge_utils.get_readers_availability()

    assert len(calls) == len(ReaderFactory.get_all_reader_keys())
    assert len(available) + len(unavailable) == len(calls)


def test_docling_media_needs_ffmpeg_not_just_a_speech_package():
    """Docling fails outright without the binary, whatever Python packages are installed."""
    with _ffmpeg(present=False), _specs(present=("whisper",)):
        info = get_reader_info("docling")

    assert ContentType.AUDIO_WAV.value not in info["content_types"]
    assert info["unavailable_content_types"][ContentType.AUDIO_WAV.value] == ["ffmpeg"]
    # Only the media types go; docling still reads documents.
    assert ContentType.PDF.value in info["content_types"]


def test_docling_media_accepts_any_speech_backend():
    """Docling picks its backend by hardware, so requiring one package would hide a working one."""
    with _ffmpeg(present=True), _specs(absent=("whisper", "whisper_s2t"), present=("mlx_whisper",)):
        info = get_reader_info("docling")

    assert ContentType.AUDIO_WAV.value in info["content_types"]
    assert info["unavailable_content_types"] == {}


def test_docling_media_names_a_backend_that_works_everywhere():
    with _ffmpeg(present=True), _specs(absent=("whisper", "mlx_whisper", "whisper_s2t")):
        info = get_reader_info("docling")

    assert ContentType.AUDIO_WAV.value not in info["content_types"]
    assert info["unavailable_content_types"][ContentType.AUDIO_WAV.value] == ["openai-whisper"]


def test_an_unusable_custom_reader_is_not_replaced_by_the_factory_one():
    """The runtime resolves the custom reader for this id, so the config cannot offer another."""
    from agno.knowledge.knowledge import Knowledge

    class UnrunnableTextReader(Reader):
        @classmethod
        def get_supported_chunking_strategies(cls):
            return []

        @classmethod
        def get_supported_content_types(cls):
            return [ContentType.TXT]

        @classmethod
        def get_read_time_requirements(cls):
            return {ContentType.TXT: ["definitely_not_installed_xyz"]}

    knowledge = Knowledge(name="Override KB")
    knowledge.readers = {"text": UnrunnableTextReader()}

    available, unavailable = __import__(
        "agno.knowledge.utils", fromlist=["get_readers_availability"]
    ).get_readers_availability(knowledge)

    assert "text" not in {info["id"] for info in available}
    assert {entry["id"] for entry in unavailable} >= {"text"}
    by_id = {entry["id"]: entry for entry in unavailable}
    assert by_id["text"]["missing_packages"] == ["definitely_not_installed_xyz"]
    # ...and the runtime really would have used it, which is why the factory must not stand in.
    assert type(knowledge._get_reader("text")).__name__ == "UnrunnableTextReader"


def test_a_working_custom_reader_still_owns_its_id():
    """Guards the reservation against shadowing a custom reader that works."""
    from agno.knowledge.knowledge import Knowledge
    from agno.knowledge.reader.text_reader import TextReader
    from agno.knowledge.utils import get_readers_availability

    knowledge = Knowledge(name="Working override KB")
    knowledge.readers = {"text": TextReader(name="My Text Reader")}

    available, unavailable = get_readers_availability(knowledge)
    by_id = {info["id"]: info for info in available}

    assert by_id["text"]["name"] == "My Text Reader"
    assert "text" not in {entry["id"] for entry in unavailable}
