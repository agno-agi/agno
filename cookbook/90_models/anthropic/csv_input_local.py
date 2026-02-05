from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude

# Self-contained sample data — no external file dependencies
csv_content = b"""\
title,year,genre,worldwide_gross_usd
Avatar,2009,Action/Sci-Fi,2923706026
Avengers: Endgame,2019,Action/Sci-Fi,2799439100
Avatar: The Way of Water,2022,Action/Sci-Fi,2320250281
Titanic,1997,Drama/Romance,2264743305
Star Wars: The Force Awakens,2015,Action/Sci-Fi,2071310218
Avengers: Infinity War,2018,Action/Sci-Fi,2052415039
Spider-Man: No Way Home,2021,Action/Sci-Fi,1921847111
Inside Out 2,2024,Animation/Comedy,1698640000
Jurassic World,2015,Action/Sci-Fi,1671537444
The Lion King,2019,Animation/Musical,1663075401
Frozen II,2019,Animation/Musical,1453683476
Top Gun: Maverick,2022,Action/Drama,1495696292
Barbie,2023,Comedy/Fantasy,1441981895
The Super Mario Bros. Movie,2023,Animation/Comedy,1361992475
The Avengers,2012,Action/Sci-Fi,1520538536
"""

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    markdown=True,
)

agent.print_response(
    "Analyze this box office dataset. Which genres perform best? Show a ranking.",
    files=[
        File(
            content=csv_content,
            mime_type="text/csv",
        ),
    ],
)
