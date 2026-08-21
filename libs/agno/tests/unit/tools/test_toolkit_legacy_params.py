"""Agno 2.x toolkit constructor kwargs must keep working in 3.0.

The 3.0 toolkit cleanup renamed tool-toggle params (enable_search -> search),
renamed a few others (proxies -> proxy), and removed `all` from some toolkits.
Every 2.x kwarg must still be accepted: it is still a constructor parameter,
the base Toolkit shim maps it (stripping the `enable_` prefix, or through the
class's `_legacy_param_aliases`), or the constructor consumes it itself with an
`if "<name>" in kwargs:` check.

`data/toolkit_constructor_params_v2.json` is the frozen list of 2.x
constructor parameters per toolkit class (captured from the pre-cleanup
branch; `creds_path`/`auth_port` on the Google toolkits are excluded because
#9560 removed that deprecated auth surface separately). The static check below parses each toolkit's source, so it covers
toolkits whose SDKs are not installed; the runtime checks construct the
SDK-free toolkits with 2.x kwargs for real.
"""

import ast
import json
from pathlib import Path
from typing import Dict, List, Set

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[3] / "agno" / "tools"
CONTRACT = json.loads((Path(__file__).parent / "data" / "toolkit_constructor_params_v2.json").read_text())


def _class_nodes(tree: ast.Module) -> Dict[str, ast.ClassDef]:
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _init(node: ast.ClassDef):
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            return item
    return None


def _accepted_kwargs(init: ast.FunctionDef) -> Set[str]:
    """Explicit params plus every `"name" in kwargs` the body checks."""
    names = {a.arg for a in init.args.args[1:]} | {a.arg for a in init.args.kwonlyargs}
    for node in ast.walk(init):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.In)
        ):
            names.add(node.left.value)
    return names


def _legacy_aliases(cls: ast.ClassDef, classes: Dict[str, ast.ClassDef]) -> Dict[str, object]:
    """The class's `_legacy_param_aliases`, inherited from same-module bases like the shim does."""
    for item in cls.body:
        if isinstance(item, ast.Assign) and any(
            getattr(t, "id", None) == "_legacy_param_aliases" for t in item.targets
        ):
            return ast.literal_eval(item.value)
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id in classes:
            return _legacy_aliases(classes[base.id], classes)
    return {}


def _effective_kwargs(cls: ast.ClassDef, classes: Dict[str, ast.ClassDef]) -> Set[str]:
    init = _init(cls)
    if init is None:
        return set()
    names = _accepted_kwargs(init)
    # The base Toolkit shim strips enable_ and applies the alias map before binding
    names |= {f"enable_{n}" for n in list(names)}
    for legacy, target in _legacy_aliases(cls, classes).items():
        if target is None or target in names:
            names.add(legacy)
    # A thin alias like `class OldName(NewName): def __init__(self, *args, **kwargs)`
    # accepts whatever its base accepts.
    if not init.args.args[1:] and init.args.vararg and init.args.kwarg:
        for base in cls.bases:
            if isinstance(base, ast.Name) and base.id in classes:
                names |= _effective_kwargs(classes[base.id], classes)
    return names


def _cases() -> List[pytest.param]:
    cases = []
    for module, class_params in CONTRACT.items():
        for class_name, params in class_params.items():
            cases.append(pytest.param(module, class_name, params, id=f"{module}.{class_name}"))
    return cases


@pytest.mark.parametrize("module, class_name, legacy_params", _cases())
def test_every_2x_constructor_kwarg_is_still_accepted(module: str, class_name: str, legacy_params: List[str]):
    source_path = TOOLS_DIR / Path(*module.split(".")[2:]).with_suffix(".py")
    classes = _class_nodes(ast.parse(source_path.read_text()))
    assert class_name in classes, f"{class_name} no longer defined in {source_path}"
    accepted = _effective_kwargs(classes[class_name], classes)
    missing = [p for p in legacy_params if p not in accepted]
    assert not missing, f"{module}.{class_name} would raise TypeError for 2.x kwargs: {missing}"


# ---------------------------------------------------------------------------
# Runtime checks on toolkits that need no third-party SDK
# ---------------------------------------------------------------------------


def test_hackernews_accepts_legacy_all_and_enable_flags():
    from agno.tools.hackernews import HackerNewsTools

    assert set(HackerNewsTools(all=True).functions) == {"get_top_hackernews_stories", "get_user_details"}
    assert set(HackerNewsTools(enable_get_top_stories=False).functions) == {"get_user_details"}


def test_webbrowser_accepts_legacy_all():
    from agno.tools.webbrowser import WebBrowserTools

    assert "open_page" in WebBrowserTools(all=True).functions
    assert "open_page" not in WebBrowserTools().functions


def test_user_control_flow_accepts_legacy_all():
    from agno.tools.user_control_flow import UserControlFlowTools

    assert "get_user_input" in UserControlFlowTools(all=True).functions


def test_webtools_accepts_legacy_all():
    from agno.tools.webtools import WebTools

    assert "expand_url" in WebTools(all=True).functions


def test_websearch_accepts_legacy_enable_flags():
    pytest.importorskip("ddgs")
    from agno.tools.websearch import WebSearchTools

    tools = WebSearchTools(enable_search=False, enable_news=True)
    assert set(tools.functions) == {"web_search_news"}


def test_file_generation_registers_generators_by_default():
    from agno.tools.file_generation import FileGenerationTools

    names = set(FileGenerationTools().functions)
    assert {
        "generate_json_file",
        "generate_csv_file",
        "generate_text_file",
        "generate_html_file",
        "generate_code_file",
    } <= names


def test_youtube_accepts_legacy_proxies_dict():
    pytest.importorskip("youtube_transcript_api")
    from agno.tools.youtube import YouTubeTools

    tools = YouTubeTools(proxies={"https": "http://proxy.example:8080"})
    assert tools is not None


def test_openai_tools_accept_legacy_enable_flags(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from agno.tools.models.openai import OpenAITools

    tools = OpenAITools(enable_transcription=False, enable_image_generation=False, enable_speech_generation=True)
    assert set(tools.functions) == {"openai_generate_speech"}
