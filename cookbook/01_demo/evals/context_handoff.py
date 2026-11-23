"""Exercise Context across fresh CLI processes using the demo's quick prompts.

Run from the repository root with OPENAI_API_KEY set:
    python cookbook/01_demo/evals/context_handoff.py

Uses a temporary directory. Read the printed handoff alongside the saved page
to judge whether it explains the priority change and keeps approval pending.
"""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

demo = Path(__file__).resolve().parents[1]


def chat(message: str, directory: str) -> None:
    subprocess.run(
        [sys.executable, str(demo / "agents/context.py"), message],
        env={**os.environ, "CONTEXT_DATA_DIR": directory},
        check=True,
    )


if __name__ == "__main__":
    prompts = yaml.safe_load((demo / "config.yaml").read_text())["chat"][
        "quick_prompts"
    ]["context"]
    with TemporaryDirectory() as directory:
        projects = Path(directory) / "context/projects"
        chat(prompts[0], directory)
        (page,) = projects.glob("*.md")
        kickoff = page.read_text()
        assert "felix" in kickoff.lower() and "orla" in kickoff.lower(), kickoff

        handwritten = "Spare headphone pads are in the blue tin."
        with page.open("a") as note:
            note.write(f"\n## Welcome desk\n\n{handwritten}\n")
        other = projects / "harbor-print-fair.md"
        other_note = "# Harbor print fair\n\nOrla will bring the stall signs to the welcome desk on Friday.\n"
        other.write_text(other_note)

        chat(prompts[1], directory)
        revised = page.read_text()
        assert set(projects.glob("*.md")) == {page, other}
        assert other.read_text() == other_note
        assert handwritten in revised
        assert all(
            word in revised.lower()
            for word in ("courtyard", "kit", "friday", "felix", "ferry")
        ), revised
        print(revised)

        chat(
            "One of the two harbor projects is moving its welcome desk. My note doesn't say which one. Update its page.",
            directory,
        )
        assert {p: p.read_text() for p in projects.glob("*.md")} == {
            page: revised,
            other: other_note,
        }
