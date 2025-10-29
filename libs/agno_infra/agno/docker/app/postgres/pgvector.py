from agno.docker.app.postgres.postgres import PostgresDb


class PgVectorDb(PostgresDb):
    # -*- App Name
    name: str = "pgvector"

    # -*- Image Configuration
    image_name: str = "agnohq/pgvector"
    image_tag: str = "16"
