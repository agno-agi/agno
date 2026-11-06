"""Persist company identity without replacing human edits on startup.

Run with a local PostgreSQL DATABASE_URL. No model or external provider is called.
"""

from os import getenv

from agno.db.postgres import PostgresDb


def main() -> None:
    db = PostgresDb(
        db_url=getenv(
            "DATABASE_URL", "postgresql+psycopg://agno:agno@localhost:5532/agno"
        )
    )
    try:
        company = db.initialize_company("Example company")
        print(company)
        # An admin UI sends this observed timestamp with PATCH /company/details.
        updated = db.update_company(
            company["updated_at"], description="We build reliable agent applications."
        )
        assert updated is not None
        assert db.initialize_company("Deployment default") == updated
        assert (
            db.update_company(company["updated_at"], description="Stale edit") is None
        )
        print("Saved identity retained; stale edit rejected.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
