"""Run `pip install duckduckgo-search sqlalchemy openai` to install dependencies."""

import os
from os import getenv

from agno.agent import Agent
from agno.storage.singlestore import SingleStoreStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.certs import download_cert
from sqlalchemy.engine import create_engine

# Configure SingleStore DB connection
USERNAME = getenv("SINGLESTORE_USERNAME")
PASSWORD = getenv("SINGLESTORE_PASSWORD")
HOST = getenv("SINGLESTORE_HOST")
PORT = getenv("SINGLESTORE_PORT")
DATABASE = getenv("SINGLESTORE_DATABASE")
SSL_CERT = getenv("SINGLESTORE_SSL_CERT", None)


# Download the certificate if SSL_CERT is not provided
if not SSL_CERT:
    SSL_CERT = download_cert(
        cert_url="https://portal.singlestore.com/static/ca/singlestore_bundle.pem",
        filename="singlestore_bundle.pem",
    )
    if SSL_CERT:
        os.environ["SINGLESTORE_SSL_CERT"] = SSL_CERT


# SingleStore DB URL
db_url = (
    f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"
)
if SSL_CERT:
    db_url += f"&ssl_ca={SSL_CERT}&ssl_verify_cert=true"

# Create a DB engine
db_engine = create_engine(db_url)

# Create an agent with SingleStore storage
agent = Agent(
    storage=SingleStoreStorage(
        table_name="agent_sessions", db_engine=db_engine, schema=DATABASE
    ),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
