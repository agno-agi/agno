from agno.agent import Agent
from agno.models.google import Gemini

topic = "HTML and CSS"
quiz_count = 5

agent1: Agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    markdown=False
)

schema = {
    "description": "List of quiz questions",
    "type": "object",
    "properties": {
        "response_code": {
            "type": "number",
            "description": "Response code indicating the status of the request",
            "nullable": "false",
        },
        "results": {
            "type": "array",
            "description": "Array of quiz questions",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Type of question (e.g., multiple choice, boolean)",
                        "nullable": "false",
                    },
                    "difficulty": {
                        "type": "string",
                        "description": "Difficulty level of the question (easy, medium, hard)",
                        "nullable": "false",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category of the question",
                        "nullable": "false",
                    },
                    "question": {
                        "type": "string",
                        "description": "The quiz question",
                        "nullable": "false",
                    },
                    "correct_answer": {
                        "type": "string",
                        "description": "The correct answer to the question",
                        "nullable": "false",
                    },
                    "incorrect_answers": {
                        "type": "array",
                        "description": "Array of incorrect answers",
                        "items": {
                            "type": "string",
                        },
                        "nullable": "false",
                    },
                },
                "required": [
                    "type",
                    "difficulty",
                    "category",
                    "question",
                    "correct_answer",
                    "incorrect_answers",
                ],
            },
            "nullable": "false",
        },
    },
    "required": ["response_code", "results"],
}

agent1.print_response(f"""
    You are a quiz maker. Your task is to generate quiz questions with the following specifications for the response:
        1. Schema : {schema}
        2. Just plain text, no markdown or code blocks.
    Create a quiz with {quiz_count} questions about {topic}.
""")
