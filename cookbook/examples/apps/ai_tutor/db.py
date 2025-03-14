from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["adaptive_ai_tutor"]

# Collections
users_collection = db["users"]
learning_paths_collection = db["learning_paths"]
quiz_results_collection = db["quiz_results"]


def save_learning_path(user_id, learning_path):
    """Save learning path in MongoDB."""
    learning_paths_collection.update_one(
        {"user_id": user_id},
        {"$set": {"learning_path": learning_path, "approved": True}},
        upsert=True,
    )


def get_learning_path(user_id):
    """Retrieve learning path for a user."""
    return learning_paths_collection.find_one({"user_id": user_id, "approved": True})


def save_quiz_result(user_id, day, score, answers, report):
    """Save quiz results and performance report."""
    quiz_results_collection.insert_one(
        {
            "user_id": user_id,
            "day": day,
            "score": score,
            "answers": answers,
            "report": report,
        }
    )


def get_users(user_id):
    """Check if user exists in DB."""
    return users_collection.find_one({"user_id": user_id})


def create_user(user_id):
    """Create a new user entry."""
    users_collection.insert_one({"user_id": user_id})
