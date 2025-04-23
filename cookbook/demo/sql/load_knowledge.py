from agents import agent_knowledge
from agno.utils.log import logger


def load_knowledge(recreate: bool = True):
    logger.info("Loading SQL agent knowledge.")
    agent_knowledge.load(recreate=recreate)
    logger.info("SQL agent knowledge loaded.")


if __name__ == "__main__":
    load_knowledge()
