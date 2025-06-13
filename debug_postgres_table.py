#!/usr/bin/env python3
"""
Debug script for PostgresDb table visibility
"""
from libs.agno.agno.db.postgres import PostgresDb

def debug_table_info(db: PostgresDb):
    """Debug function to print table information"""
    
    print("=== PostgresDb Configuration ===")
    print(f"Database Schema: {db.db_schema}")
    print(f"Agent Sessions Table Name: {db.agent_sessions.name if db.agent_sessions else 'None'}")
    print(f"Agent Sessions Table Schema: {db.agent_sessions.schema if db.agent_sessions else 'None'}")
    print()
    
    # Check if table exists
    if db.agent_sessions:
        table_name = db.agent_sessions.name
        schema_name = db.db_schema
        
        print("=== Table Existence Check ===")
        exists = db.table_exists(table_name=table_name, db_schema=schema_name)
        print(f"Table {schema_name}.{table_name} exists: {exists}")
        print()
        
        if exists:
            print("=== Row Count ===")
            try:
                with db.Session() as sess:
                    from sqlalchemy import text
                    count_query = text(f"SELECT COUNT(*) FROM {schema_name}.{table_name}")
                    count = sess.execute(count_query).scalar()
                    print(f"Total rows in {schema_name}.{table_name}: {count}")
                    
                    # Show sample data
                    sample_query = text(f"SELECT * FROM {schema_name}.{table_name} LIMIT 5")
                    rows = sess.execute(sample_query).fetchall()
                    print(f"Sample rows (first 5):")
                    for i, row in enumerate(rows):
                        print(f"  Row {i+1}: session_id={row[0]}, agent_id={row[1]}")
                    print()
                    
            except Exception as e:
                print(f"Error querying table: {e}")
                print()
        
        print("=== All Tables in Schema ===")
        try:
            with db.Session() as sess:
                from sqlalchemy import text
                tables_query = text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema_name
                    ORDER BY table_name
                """)
                tables = sess.execute(tables_query, {"schema_name": schema_name}).fetchall()
                print(f"Tables in schema '{schema_name}':")
                for table in tables:
                    print(f"  - {table[0]}")
                print()
        except Exception as e:
            print(f"Error listing tables: {e}")
            print()

if __name__ == "__main__":
    # You'll need to replace these with your actual database configuration
    print("Please configure your database connection below:")
    print("Example usage:")
    print("""
    db = PostgresDb(
        db_url="postgresql://username:password@localhost:5432/database_name",
        agent_sessions="your_agent_sessions_table_name"
    )
    debug_table_info(db)
    """) 