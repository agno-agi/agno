import os
from enum import Enum

from dotenv import load_dotenv

load_dotenv()


TYPEFULLY_API_URL = "https://api.typefully.com/v1/drafts/"
TYPEFULLY_API_KEY = os.getenv("TYPEFULLY_API_KEY")
HEADERS = {"X-API-KEY": f"Bearer {TYPEFULLY_API_KEY}"}


# Define the enums
class PostType(Enum):
    TWITTER = "Twitter"
    LINKEDIN = "LinkedIn"
