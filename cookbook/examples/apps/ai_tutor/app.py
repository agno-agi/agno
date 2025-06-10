import nest_asyncio
import streamlit as st
from agents import generate_quiz, learning_path_agent
from agno.utils.log import logger
from db import get_learning_path, save_learning_path, save_quiz_result
from dotenv import load_dotenv
from utils import apply_custom_css, authenticate_user

# Load environment variables
load_dotenv()
nest_asyncio.apply()

# Configure page
st.set_page_config(
    page_title="Adaptive AI Tutor",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS
apply_custom_css()


# Display app header only when logged in
def display_header():
    st.markdown(
        """
    <div class="app-header">
        <div class="app-title">🎓 Adaptive Tutor</div>
        <div class="centered-subtitle">Built using <a href="https://github.com/agno-agi/agno">Agno</a></div>
        <div class="app-subtitle">Personalized AI-Powered Learning Journey</div>
    </div>
    """,
        unsafe_allow_html=True,
    )


# Login Page
def login_page():
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.markdown(
            """
        <div class="form-container">
            <h2 class="form-header">Welcome to Adaptive Tutor</h2>
            <p style="text-align: center; margin-bottom: 10px;">Your personalized AI learning companion</p>
            <p style="text-align: center; margin-bottom: 10px;">Built using <a href="https://github.com/agno-agi/agno">Agno</a></p>
        """,
            unsafe_allow_html=True,
        )

        user_id = st.text_input("Enter your name to continue:", key="user_id_input")

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("👋 Login", use_container_width=True):
                authenticate_user(user_id)

        with col2:
            if st.button("👨‍💻 Demo User", use_container_width=True):
                user_id = "Demo User"
                authenticate_user(user_id)

        st.markdown(
            """
        </div>
        """,
            unsafe_allow_html=True,
        )


# Restart Agent Function
def restart_agent():
    """Reset the agent and conversation history."""
    for key in ["learning_path_agent", "messages", "quiz_questions"]:
        st.session_state.pop(key, None)
    st.rerun()


# Main App
def main():
    # Check if user is logged in
    if "user_id" not in st.session_state:
        login_page()
        return

    # Display header
    display_header()

    # Sidebar Navigation
    with st.sidebar:
        st.markdown("## 📌 Navigation")
        st.markdown("---")
        app_mode = st.radio(
            "Choose whether you want to:", ["💬 Chat with AI Tutor", "📝 Take a Quiz"]
        )

        st.markdown("---")
        st.markdown("## 👤 User Profile")
        st.markdown(f"**Name:** {st.session_state['user_id']}")

        if st.button("🔄 Restart Conversation"):
            restart_agent()

        if st.button("🚪 Logout"):
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

    # ========================== CHAT MODE (LEARNING PATH) ========================== #
    if app_mode == "💬 Chat with AI Tutor":
        # Initialize Agent & Messages
        if (
            "learning_path_agent" not in st.session_state
            or st.session_state["learning_path_agent"] is None
        ):
            logger.info(f"---*--- Creating Adaptive AI Tutor ---*---")
            path_agent = learning_path_agent()
            st.session_state["learning_path_agent"] = path_agent
        else:
            path_agent = st.session_state["learning_path_agent"]

        if "messages" not in st.session_state:
            st.session_state["messages"] = [
                {
                    "role": "agent",
                    "content": "👋 Hello! I'm your adaptive AI tutor. Tell me what topic you want to learn, your current knowledge level, and preferred learning formats (videos, articles, books).",
                }
            ]

        # Chat container
        st.markdown('<div class="card">', unsafe_allow_html=True)

        # Display Chat Messages
        for message in st.session_state["messages"]:
            if message["role"] == "system":
                continue
            with st.chat_message(message["role"]):
                st.write(message["content"])

        # Handle user input and generate responses
        if prompt := st.chat_input("Mention the topic that you want to learn:"):
            # Display user message first
            with st.chat_message("user"):
                st.write(prompt)

            # Then display agent response
            with st.chat_message("agent"):
                # Create an empty container for the streaming response
                response_container = st.empty()
                with st.spinner(
                    "AI Tutor is thinking..."
                ):  # Add spinner while generating response
                    response = ""
                    for chunk in path_agent.run(prompt, stream=True):
                        if chunk and chunk.content:
                            response += chunk.content
                            # Update the response in real-time
                            response_container.markdown(response)

            # Add messages to session state after completion
            st.session_state["messages"].append({"role": "user", "content": prompt})
            st.session_state["messages"].append({"role": "agent", "content": response})

        # Save Learning Path if Approved (only show if there are messages)
        if len(st.session_state["messages"]) > 1:
            cols = st.columns([3, 1])
            with cols[1]:
                #  Use a key with the CSS class name to style directly
                if st.button("✅ Approve Learning Path", use_container_width=True):
                    # Get the latest agent message
                    agent_messages = [
                        msg
                        for msg in st.session_state["messages"]
                        if msg["role"] == "agent"
                    ]
                    if agent_messages:
                        latest_path = agent_messages[-1]["content"]
                        save_learning_path(st.session_state["user_id"], latest_path)
                        st.success("Learning path saved successfully!")

    # ========================== QUIZ MODE ========================== #
    elif app_mode == "📝 Take a Quiz":
        st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
        st.markdown("#### 📝 Adaptive Quiz")

        learning_path = get_learning_path(st.session_state["user_id"])
        if not learning_path:
            st.warning(
                "No learning path found. Please generate one in the Chat mode first."
            )
        else:
            st.markdown("##### Select which day's content you want to be tested on:")
            day = st.number_input("Day Number:", min_value=1)

            if st.button("🚀 Generate Quiz", use_container_width=True):
                with st.spinner("Creating personalized quiz questions..."):
                    quiz = generate_quiz(learning_path, day)
                    st.session_state["quiz"] = quiz
                    st.session_state["score"] = 0
                    st.session_state["current_question"] = 0
                    st.session_state["total_questions"] = len(quiz)
                st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)

        # Display Quiz
        if "quiz" in st.session_state and st.session_state["quiz"]:
            questions = st.session_state["quiz"]
            current_q = st.session_state["current_question"]
            total_q = st.session_state["total_questions"]

            if current_q < len(questions):
                # Progress bar
                progress = current_q / total_q
                st.progress(progress)
                st.markdown(f"**Question {current_q + 1} of {total_q}**")

                st.markdown('<div class="quiz-card">', unsafe_allow_html=True)

                q = questions[current_q]
                st.markdown(
                    f'<div class="quiz-question">{q["question"]}</div>',
                    unsafe_allow_html=True,
                )

                selected = st.radio(
                    "Choose an answer:", options=q["options"], key=f"q{current_q}"
                )

                # After the user clicks "Next Question" button
                if st.button("Next Question →", use_container_width=True):
                    # Save the selected answer to session state with a unique key
                    st.session_state[f"user_answer_{current_q}"] = selected

                    if selected == q["correct_answer"]:
                        st.session_state["score"] += 100 / total_q
                    st.session_state["current_question"] += 1
                    st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)
            else:
                # Quiz completed
                final_score = int(st.session_state["score"])

                st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="quiz-result">🎉 Quiz Completed!</div>',
                    unsafe_allow_html=True,
                )

                # Show score with appropriate emoji
                if final_score >= 80:
                    emoji = "🏆"
                    message = "Excellent! You've mastered this material!"
                elif final_score >= 60:
                    emoji = "🌟"
                    message = "Good job! You're making great progress!"
                else:
                    emoji = "📚"
                    message = "Keep learning! Review the material and try again."

                st.markdown(
                    f"""
                <div style="text-align: center; margin: 20px 0;">
                    <div style="font-size: 5em; margin-bottom: 10px;">{emoji}</div>
                    <div style="font-size: 2em; font-weight: bold; color: #FF7F00;">Score: {final_score}/100</div>
                    <div style="margin-top: 10px; color: #FFFFFF;">{message}</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )

                cols = st.columns([1, 1])

                with cols[0]:
                    if st.button("📊 View Results", use_container_width=True):
                        # Display detailed results
                        st.markdown("### Question Review")
                        for i, q in enumerate(questions):
                            correct = q["correct_answer"]
                            user_answer = st.session_state.get(f"user_answer_{i}", None)

                            status = "✅" if user_answer == correct else "❌"

                            st.markdown(
                                f"""
                            <div style="padding: 10px; margin: 5px 0; border-radius: 5px;
                                background-color: {'#252525' if user_answer == correct else '#3A1F00'}">
                                <div><strong>Q{i + 1}:</strong> {q['question']}</div>
                                <div><strong>Your answer:</strong> {user_answer}</div>
                                <div><strong>Correct answer:</strong> {correct}</div>
                                <div>{status}</div>
                            </div>
                            """,
                                unsafe_allow_html=True,
                            )

                with cols[1]:
                    if st.button("🔄 Take Another Quiz", use_container_width=True):
                        # Save results to database
                        save_quiz_result(
                            st.session_state["user_id"], day, final_score, questions, {}
                        )
                        # Reset quiz state
                        st.session_state.pop("quiz", None)
                        st.session_state.pop("score", None)
                        st.session_state.pop("current_question", None)
                        st.session_state.pop("total_questions", None)
                        st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)


# Run the app
if __name__ == "__main__":
    main()
