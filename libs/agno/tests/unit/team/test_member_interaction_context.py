from __future__ import annotations

from agno.media import Image
from agno.run.agent import RunOutput
from agno.team import Team


def test_team_member_interaction_context_is_capped():
    team = Team(
        members=[],
        share_member_interactions=True,
        max_member_interactions_in_context=2,
        telemetry=False,
    )

    team_run_context = {"member_responses": []}
    for idx in range(4):
        team_run_context["member_responses"].append(
            {
                "member_name": f"m{idx}",
                "task": f"t{idx}",
                "run_response": RunOutput(
                    run_id=f"run_{idx}",
                    content=f"r{idx}",
                    images=[Image(url=f"https://example.com/{idx}.png")],
                ),
            }
        )

    images = []
    videos = []
    audio = []
    files = []
    interactions_str = team._determine_team_member_interactions(
        team_run_context=team_run_context,
        images=images,
        videos=videos,
        audio=audio,
        files=files,
    )

    assert interactions_str is not None
    assert "Member: m0" not in interactions_str
    assert "Member: m1" not in interactions_str
    assert "Member: m2" in interactions_str
    assert "Member: m3" in interactions_str

    assert len(images) == 2
    assert images[0].url == "https://example.com/2.png"
    assert images[1].url == "https://example.com/3.png"
