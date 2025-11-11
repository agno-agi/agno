import io
import tempfile
from os import unlink

import nest_asyncio
import streamlit as st
from agents import get_recipe_image_agent
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
    add_message,
    display_chat_messages,
    display_tool_calls,
    export_chat_history,
    initialize_agent,
    knowledge_base_info_widget,
    reset_session_state,
    session_selector_widget,
)
from PIL import Image

nest_asyncio.apply()
st.set_page_config(
    page_title="Recipe Image Generator",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_agent(model_id: str = None):
    target_model = model_id or st.session_state.get("current_model", MODELS[0])

    new_agent = get_recipe_image_agent(model_id=target_model, session_id=None)

    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["is_new_session"] = True


def on_model_change():
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in MODELS:
            new_model_id = selected_model
            current_model = st.session_state.get("current_model")

            if current_model and current_model != new_model_id:
                try:
                    st.session_state["is_loading_session"] = False
                    # Start new chat
                    restart_agent(model_id=new_model_id)

                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")
        else:
            st.sidebar.error(f"Unknown model: {selected_model}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>Recipe Image Generator</h1>", unsafe_allow_html=True
    )
    st.markdown(
        "<p class='subtitle'>Your AI cooking companion - Upload recipes or use defaults, then get visual step-by-step cooking guides!</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=MODELS,
        index=0,
        key="model_selector",
        on_change=on_model_change,
    )

    ####################################################################
    # Initialize Agent and Session
    ####################################################################
    recipe_image_agent = initialize_agent(selected_model, get_recipe_image_agent)
    reset_session_state(recipe_image_agent)

    if prompt := st.chat_input("👋 Ask me for a recipe (e.g., 'Recipe for Pad Thai')"):
        add_message("user", prompt)

    ####################################################################
    # Recipe Management
    ####################################################################
    st.sidebar.markdown("#### 📚 Recipe Management")
    knowledge_base_info_widget(recipe_image_agent)

    # File upload
    uploaded_file = st.sidebar.file_uploader(
        "Upload Recipe PDF (.pdf)", type=["pdf"], key="recipe_upload"
    )
    if uploaded_file and not prompt:
        alert = st.sidebar.info("Processing recipe PDF...", icon="ℹ️")
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                tmp_file.write(uploaded_file.read())
                tmp_path = tmp_file.name

            recipe_image_agent.knowledge.add_content(
                name=f"Uploaded Recipe: {uploaded_file.name}",
                path=tmp_path,
                description=f"Custom recipe PDF: {uploaded_file.name}",
            )

            unlink(tmp_path)
            st.sidebar.success(f"{uploaded_file.name} added to recipe collection")
        except Exception as e:
            st.sidebar.error(f"Error processing recipe PDF: {str(e)}")
        finally:
            alert.empty()

    if st.sidebar.button("Clear Recipe Collection"):
        if recipe_image_agent.knowledge.vector_db:
            recipe_image_agent.knowledge.vector_db.delete()
        st.sidebar.success("Recipe collection cleared")

    ###############################################################
    # Sample Recipes
    ###############################################################
    st.sidebar.markdown("#### 🍜 Sample Recipes")
    if st.sidebar.button("🍝 Recipe for Pad Thai"):
        add_message("user", "Recipe for Pad Thai with visual steps")
    if st.sidebar.button("🥗 Recipe for Som Tum"):
        add_message("user", "Recipe for Som Tum (Papaya Salad)")
    if st.sidebar.button("🍲 Recipe for Tom Kha Gai"):
        add_message("user", "Recipe for Tom Kha Gai soup")

    ###############################################################
    # Utility buttons
    ###############################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if st.sidebar.button("🔄 New Chat", use_container_width=True):
            restart_agent()
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            session_id = st.session_state.get("session_id")
            if session_id:
                try:
                    session_name = recipe_image_agent.get_session_name()
                    if session_name:
                        filename = f"recipe_chat_{session_name}.md"
                    else:
                        filename = f"recipe_chat_{session_id}.md"
                except Exception:
                    filename = f"recipe_chat_{session_id}.md"
            else:
                filename = "recipe_chat_new.md"

            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("Recipe Image Generator"),
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} messages",
            ):
                st.sidebar.success("Chat history exported!")
        else:
            st.sidebar.button(
                "💾 Export Chat",
                disabled=True,
                use_container_width=True,
                help="No messages to export",
            )

    ####################################################################
    # Display Chat Messages
    ####################################################################
    display_chat_messages()

    ####################################################################
    # Generate response for user message with image handling
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]

        with st.chat_message("assistant"):
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner("🤔 Thinking..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = recipe_image_agent.run(question, stream=True)
                    for resp_chunk in run_response:
                        try:
                            # Display tool calls if available
                            if hasattr(resp_chunk, "tool") and resp_chunk.tool:
                                display_tool_calls(
                                    tool_calls_container, [resp_chunk.tool]
                                )
                        except Exception:
                            pass

                        if resp_chunk.content is not None:
                            content = str(resp_chunk.content)
                            if not (
                                content.strip().endswith("completed in")
                                or "completed in" in content
                                and "s." in content
                            ):
                                response += content
                                resp_container.markdown(response)

                        if hasattr(resp_chunk, "images") and getattr(
                            resp_chunk, "images", None
                        ):
                            captured_run_output = resp_chunk

                    # Display generated images
                    if captured_run_output and hasattr(captured_run_output, "images"):
                        for i, img in enumerate(captured_run_output.images or []):
                            try:
                                if hasattr(img, "content") and img.content:
                                    image = Image.open(io.BytesIO(img.content))
                                    st.image(
                                        image,
                                        caption=f"Step-by-step cooking guide {i + 1}",
                                        use_container_width=True,
                                    )
                                elif hasattr(img, "url") and img.url:
                                    st.image(
                                        img.url,
                                        caption=f"Step-by-step cooking guide {i + 1}",
                                        use_container_width=True,
                                    )
                            except Exception as img_error:
                                st.warning(
                                    f"Could not display image {i + 1}: {str(img_error)}"
                                )

                    # Add message with tools
                    try:
                        if captured_run_output and hasattr(
                            captured_run_output, "tools"
                        ):
                            add_message(
                                "assistant", response, captured_run_output.tools
                            )
                        else:
                            add_message("assistant", response)
                    except Exception:
                        add_message("assistant", response)

                except Exception as e:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Session management widgets
    ####################################################################
    session_selector_widget(recipe_image_agent, selected_model, get_recipe_image_agent)

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Recipe Image Generator creates visual step-by-step cooking guides from recipe collections. Upload your own recipes or use the built-in Thai recipe collection."
    )


if __name__ == "__main__":
    main()
