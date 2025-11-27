from agno.db.sqlite import SqliteDb

db_file = "tmp/google_examples.db"
demo_db = SqliteDb(id="google-examples-db", db_file=db_file)
