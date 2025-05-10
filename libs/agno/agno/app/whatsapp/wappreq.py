from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configure constants
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
