import time
from typing import Optional
from sqlalchemy import create_engine, Table, Column, String, MetaData, select
from sqlalchemy.dialects.postgresql import insert
from agno.tools import Toolkit
from agno.utils.log import logger

class CachedSearchTools(Toolkit):
    def __init__(
        self,
        db_url: str,
        table_name: str,
        search_tool: Toolkit,
        sleep: Optional[float] = 0.0, # sleep time to prevent rate limiting
    ):

        super().__init__(name="cached_" + search_tool.name)

        self.search_tool = search_tool
        # Set up the database connection and table
        self.engine = create_engine(db_url)
        self.metadata = MetaData()
        self.table = Table(
            table_name,
            self.metadata,
            Column("query", String, primary_key=True),
            Column("results", String),
        )
        self.metadata.create_all(self.engine)
        self.sleep = sleep

        self.register(self.web_search)

    # Obtain the function that contains the word "search" from the tool
    def getSearchFunction(self):
        search_function = next((self.search_tool.functions[func] for func in self.search_tool.functions if "search" in func), None)

        if search_function:
            logger.debug(f"Found function: {search_function}")
            return search_function
        else:
            logger.debug("No function containing 'search' found.")
            return None

    # entry point performs the search and stores the results in the cache
    def web_search(self, query: str) -> str:

        logger.debug(f"Searching {self.name} for: {query}")

        # Check the cache first
        with self.engine.connect() as conn:
            stmt = select(self.table.c.results).where(self.table.c.query == query)
            result = conn.execute(stmt).fetchone()
            if result:
                logger.info(f"Cache hit for query: {query}")
                return result[0]  # Access the first element of the tuple

        # prevent rate limiting. Open for suggestions to handle this better.
        time.sleep(self.sleep)

        # delegate the search to the search function
        search_function = self.getSearchFunction()
        results_json = search_function.entrypoint(query)

        # Store the results in the cache
        with self.engine.connect() as conn:
            stmt = insert(self.table).values(query=query, results=results_json).on_conflict_do_nothing()
            conn.execute(stmt)
            conn.commit()

        return results_json


