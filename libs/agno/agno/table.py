import sqlite3

db_path = "tmp/traces.db"
table_name = "agno_spans"

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f"DROP TABLE IF EXISTS {table_name}")
conn.commit()
conn.close()
