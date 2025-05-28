from datetime import datetime

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

# Create indexes for better performance
users_collection.create_index("user_id", unique=True)
learning_paths_collection.create_index([("user_id", 1), ("created_at", -1)])
quiz_results_collection.create_index([("user_id", 1), ("day", 1), ("created_at", -1)])


def get_users(user_id):
    """Check if user exists in DB."""
    return users_collection.find_one({"user_id": user_id})


def create_user(user_id):
    """Create a new user entry."""
    timestamp = datetime.now()

    users_collection.insert_one({
        "user_id": user_id,
        "created_at": timestamp,
    })

    return user_id


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


def save_quiz_result(user_id, day, score, quiz, report):
    """Save quiz results and performance report.

    Args:
        user_id: The user's identifier
        day: The day number in the learning path
        score: Overall quiz score (0-100)
        quiz: Quiz questions and answers
        report: Report generated on the quiz
    """
    timestamp = datetime.now()
    quiz_results_collection.insert_one(
        {
            "user_id": user_id,
            "day": day,
            "score": score,
            "quiz": quiz,
            "report": report,
            "created_at": timestamp,
        }
    )


def get_quiz_results(user_id, day=None, limit=3):
    """Retrieve quiz results for a user and day.

    Args:
        user_id: The user's identifier
        day: Optional day number to filter results
        limit: Maximum number of results to return

    Returns:
        List of quiz result documents
    """
    query = {"user_id": user_id}

    if day is not None:
        query["day"] = day

    cursor = quiz_results_collection.find(
        query,
        sort=[("created_at", -1)]
    ).limit(limit)

    return list(cursor)


def get_quiz_performance_summary(user_id, path_id=None):
    """Get aggregated quiz performance data for a user.

    Args:
        user_id: The user's identifier
        path_id: Optional learning path ID to filter results

    Returns:
        Performance summary by day
    """
    match_stage = {"user_id": user_id}
    if path_id:
        match_stage["path_id"] = path_id

    pipeline = [
        {"$match": match_stage},
        {"$group": {
            "_id": "$day",
            "avg_score": {"$avg": "$score"},
            "attempts": {"$sum": 1},
            "best_score": {"$max": "$score"},
            "latest_attempt": {"$max": "$created_at"}
        }},
        {"$sort": {"_id": 1}}
    ]

    results = list(quiz_results_collection.aggregate(pipeline))
    return results

