"""
Regression tests for agno issue #10817:
Several toolkits and model classes default to models their providers have shut down.
These tests read source files directly to avoid importing the full agno module tree.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGNO_SRC = os.path.join(_HERE, "..", "..", "agno")


def _read(rel_path: str) -> str:
    with open(os.path.join(_AGNO_SRC, rel_path)) as f:
        return f.read()


def test_antigravity_agent_default_model():
    """agents/antigravity/agent.py: default field must be antigravity-preview-09-2026."""
    src = _read("agents/antigravity/agent.py")
    assert 'agent: str = "antigravity-preview-09-2026"' in src, (
        "AntGravityAgent default must be antigravity-preview-09-2026 "
        "(antigravity-preview-05-2026 shuts down 2026-10-05)"
    )
    assert 'agent: str = "antigravity-preview-05-2026"' not in src, (
        "antigravity-preview-05-2026 is shut down; update the default field"
    )


def test_antigravity_tools_default_model():
    """tools/antigravity.py: default parameter must be antigravity-preview-09-2026."""
    src = _read("tools/antigravity.py")
    assert 'agent: str = "antigravity-preview-09-2026"' in src, (
        "AntGravityTools default must be antigravity-preview-09-2026 "
        "(antigravity-preview-05-2026 shuts down 2026-10-05)"
    )
    assert 'agent: str = "antigravity-preview-05-2026"' not in src, (
        "antigravity-preview-05-2026 is shut down; update the default parameter"
    )


def test_dalle_tools_default_model():
    """tools/dalle.py: default must be gpt-image-2 (dall-e-3 shut down 2026-05-12)."""
    src = _read("tools/dalle.py")
    assert 'model: str = "gpt-image-2"' in src, (
        "DalleTools default must be gpt-image-2 (dall-e-3 shut down 2026-05-12)"
    )


def test_dalle_tools_accepts_gpt_image_models():
    """tools/dalle.py: validation must accept gpt-image-2."""
    src = _read("tools/dalle.py")
    assert "gpt-image-2" in src, (
        "DalleTools validation must accept gpt-image-2"
    )


def test_sambanova_default_model():
    """models/sambanova/sambanova.py: default must be Meta-Llama-3.3-70B-Instruct."""
    src = _read("models/sambanova/sambanova.py")
    assert 'id: str = "Meta-Llama-3.3-70B-Instruct"' in src, (
        "SambaNova default must be Meta-Llama-3.3-70B-Instruct "
        "(Meta-Llama-3.1-8B-Instruct removed 2026-04-14)"
    )
    assert 'id: str = "Meta-Llama-3.1-8B-Instruct"' not in src, (
        "Meta-Llama-3.1-8B-Instruct was removed 2026-04-14; update the default"
    )
