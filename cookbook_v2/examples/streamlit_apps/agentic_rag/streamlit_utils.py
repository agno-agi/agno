import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.agent import Agent
from agno.utils.log import logger
from agno.db.base import SessionType


def get_session_name_from_db(agent, session_id: str) -> str:
    """Get session name from database session_data."""
    try:
        db_session = agent.db.get_session(
            session_id=session_id,
            session_type=SessionType.AGENT
        )
        if db_session and db_session.session_data:
            return db_session.session_data.get('session_name')
        return None
    except Exception as e:
        logger.debug(f"Error getting session name from DB: {e}")
        return None


def clean_html_content(content: str, max_length: int = 1000) -> str:
    """Clean HTML content and make it readable."""
    if not content or not isinstance(content, str):
        return str(content) if content else ""
    
    # Remove HTML tags
    clean_content = re.sub(r'<[^>]+>', '', content)
    
    # Replace HTML entities
    html_entities = {
        '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'",
        '&nbsp;': ' ', '&mdash;': '—', '&ndash;': '–', '&hellip;': '...',
        '&copy;': '©', '&reg;': '®', '&trade;': '™'
    }
    
    for entity, char in html_entities.items():
        clean_content = clean_content.replace(entity, char)
    
    # Clean up whitespace
    clean_content = re.sub(r'\s+', ' ', clean_content)
    clean_content = clean_content.strip()
    
    # Truncate if too long
    if len(clean_content) > max_length:
        clean_content = clean_content[:max_length] + "..."
    
    return clean_content


def _extract_user_query(content: str) -> str:
    """Extract the actual user query from content that may contain HTML references."""
    if not content:
        return ""
    
    # If content is short and doesn't contain HTML, return as is
    if len(content) < 500 and '<' not in content and 'references' not in content.lower():
        return content.strip()
    
    # Look for the pattern "Can you..." or question at the start
    lines = content.split('\n')
    
    # First, look for obvious user queries
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        if line and not line.startswith('<') and not line.startswith('Use the following') and not line.startswith('<references>'):
            # Check if this looks like a user question
            if any(starter in line.lower() for starter in ['can you', 'what is', 'how do', 'tell me', 'explain', '?']):
                if len(line) < 500:
                    return line
            # Or if it's a short, clean line at the beginning
            elif len(line) < 200:
                return line
    
    # If no clean line found, look for first few non-HTML lines
    clean_parts = []
    for line in lines[:10]:  # Only check first 10 lines
        line = line.strip()
        if line and not any(skip in line for skip in ['<', 'Use the following', '<references>', 'meta_data', 'chunk']):
            clean_parts.append(line)
            if len(' '.join(clean_parts)) > 200:  # Stop once we have enough content
                break
                
    result = ' '.join(clean_parts)
    
    # Final cleanup
    if len(result) > 500:
        result = result[:500] + "..."
        
    return result if result else ""


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> None:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    message = {"role": role, "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    st.session_state["messages"].append(message)


def display_tool_calls(container, tools: List[Any]):
    """Display tool calls in expandable sections."""
    if not tools:
        return

    with container.container():
        for tool in tools:
            if hasattr(tool, "tool_name"):
                name = tool.tool_name or "Tool"
                args = tool.tool_args or {}
                result = tool.result or ""
            else:
                name = tool.get("tool_name") or tool.get("name") or "Tool"
                args = tool.get("tool_args") or tool.get("args") or {}
                result = tool.get("result") or tool.get("content") or ""

            with st.expander(f"🛠️ {name.replace('_', ' ')}", expanded=False):
                if args:
                    st.markdown("**Arguments:**")
                    st.json(args)
                if result:
                    st.markdown("**Result:**")
                    st.json(result)


def export_chat_history(app_name: str = "Chat") -> str:
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return "# Chat History\n\n*No messages to export*"

    title = "Chat History"
    for msg in st.session_state["messages"]:
        if msg.get("role") == "user" and msg.get("content"):
            title = msg["content"][:100]
            if len(msg["content"]) > 100:
                title += "..."
            break

    chat_text = f"# {title}\n\n"
    chat_text += f"**Exported:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n\n"
    chat_text += "---\n\n"

    for msg in st.session_state["messages"]:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if not content or str(content).strip().lower() == "none":
            continue

        role_display = "## 🙋 User" if role == "user" else "## 🤖 Assistant"
        chat_text += f"{role_display}\n\n{content}\n\n---\n\n"
    return chat_text


def restart_agent_session(**session_keys) -> None:
    for key in session_keys.values():
        if key in st.session_state:
            st.session_state[key] = None
    if "messages" in st.session_state:
        st.session_state["messages"] = []
    st.rerun()


def session_selector_widget(
    agent: Agent, model_id: str, agent_creation_callback: callable
) -> None:
    if not agent.db:
        st.sidebar.info("💡 Database not configured. Sessions will not be saved.")
        return

    try:
        sessions = agent.db.get_sessions(
            session_type="agent",
            deserialize=True,
            sort_by="created_at",
            sort_order="desc",
        )
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        st.sidebar.error("Could not load sessions")
        return

    if not sessions:
        st.sidebar.info("🆕 New Chat - Start your conversation!")
        return

    session_options = []
    session_dict = {}

    for session in sessions:
        if not hasattr(session, "session_id") or not session.session_id:
            continue

        session_id = session.session_id
        session_name = None

        # Extract session name from session_data  
        if hasattr(session, "session_data") and session.session_data:
            session_name = session.session_data.get("session_name")

        name = session_name or session_id

        if hasattr(session, "created_at") and session.created_at:
            try:
                if hasattr(session.created_at, "strftime"):
                    time_str = session.created_at.strftime("%m/%d %H:%M")
                    display_name = f"{name} ({time_str})"
                else:
                    display_name = name
            except (ValueError, TypeError, OSError):
                display_name = name
        else:
            display_name = name

        session_options.append(display_name)
        session_dict[display_name] = session_id

    current_session_id = st.session_state.get("session_id")
    current_selection = None

    # If we have a current session but it's not in the saved sessions yet (new session)
    if current_session_id and current_session_id not in [s_id for s_id in session_dict.values()]:
        # Add current session to the options with just the session ID
        if agent.session_name:
            current_display_name = agent.session_name
        else:
            current_display_name = f"{current_session_id[:8]}..."
        session_options.insert(0, current_display_name)
        session_dict[current_display_name] = current_session_id
        current_selection = current_display_name

    # Find current selection from existing sessions
    for display_name, session_id in session_dict.items():
        if session_id == current_session_id:
            current_selection = display_name
            break

    # Always use session_options, no "New Chat" option
    display_options = session_options
    selected_index = (
        session_options.index(current_selection)
        if current_selection and current_selection in session_options
        else 0 if session_options else None
    )

    if not display_options:
        st.sidebar.info("🆕 Start your first conversation!")
        return

    selected = st.sidebar.selectbox(
        label="Session",
        options=display_options,
        index=selected_index,
        help="Select a session to continue",
    )

    if selected and selected in session_dict:
        selected_session_id = session_dict[selected]
        if selected_session_id != current_session_id:
            _load_session(selected_session_id, model_id, agent_creation_callback)

    if agent.session_id:
        if "session_edit_mode" not in st.session_state:
            st.session_state.session_edit_mode = False

        # Use a better display name for current session
        current_name = "New Session"
        if agent.session_name:
            current_name = agent.session_name
        elif agent.session_id:
            # Check database for session name
            db_name = get_session_name_from_db(agent, agent.session_id)
            if db_name:
                current_name = db_name
                agent.session_name = db_name  # Update agent property
            else:
                current_name = f"{agent.session_id[:8]}..."  # Show first 8 chars of UUID

        if not st.session_state.session_edit_mode:
            col1, col2 = st.sidebar.columns([3, 1])
            with col1:
                st.write(f"**Session:** {current_name}")
            with col2:
                if st.button("✎", help="Rename session", key="rename_session_button"):
                    st.session_state.session_edit_mode = True
                    st.rerun()
        else:
            new_name = st.sidebar.text_input(
                "Enter new name:", value=current_name, key="session_name_input"
            )

            col1, col2 = st.sidebar.columns([1, 1])
            with col1:
                if st.button(
                    "💾 Save",
                    type="primary",
                    use_container_width=True,
                    key="save_session_name",
                ):
                    if new_name and new_name.strip():
                        try:
                            # Use the agent's built-in set_session_name method
                            result = agent.set_session_name(session_name=new_name.strip())
                            
                            if result:
                                logger.info(f"Session renamed to: {new_name.strip()}")
                            st.session_state.session_edit_mode = False
                            st.sidebar.success("Session renamed!")
                            st.rerun()
                        except Exception as e:
                            st.sidebar.error(f"Error: {str(e)}")
                    else:
                        st.sidebar.error("Please enter a valid name")

            with col2:
                if st.button(
                    "❌ Cancel", use_container_width=True, key="cancel_session_rename"
                ):
                    st.session_state.session_edit_mode = False
                    st.rerun()


def _load_session(session_id: str, model_id: str, agent_creation_callback: callable):
    try:
        # Try creating agent directly with session_id
        logger.info(f"Creating agent with session_id: {session_id}")
        new_agent = agent_creation_callback(model_id=model_id, session_id=session_id)
        
        # Update session state
        st.session_state["agent"] = new_agent
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = []

        try:
            # Load session data directly from database (more reliable than agent.agent_session)
            logger.info(f"Loading session {session_id} - getting session from database...")
            
            # Get the specific session directly by session_id
            target_session = new_agent.db.get_session(
                session_id=session_id,
                session_type="agent",
                deserialize=True
            )
            
            if target_session:
                logger.info(f"Found session in database with {len(getattr(target_session, 'runs', []))} runs")
                
                # Process runs from the database session
                if hasattr(target_session, 'runs') and target_session.runs:
                    for run_idx, run in enumerate(target_session.runs):
                        messages = getattr(run, 'messages', None)
                        msg_count = len(messages) if messages else 0
                        logger.info(f"Processing run {run_idx} with {msg_count} messages")
                        
                        if messages:
                            # Process messages in order, but filter appropriately
                            user_msg = None
                            assistant_msg = None
                            tool_calls = []
                            
                            for msg_idx, message in enumerate(messages):
                                if not hasattr(message, 'role') or not hasattr(message, 'content'):
                                    logger.debug(f"Skipping message {msg_idx} - missing role or content")
                                    continue
                                    
                                role = message.role
                                content = str(message.content) if message.content else ""
                                logger.debug(f"Message {msg_idx}: role={role}, content_length={len(content)}")
                                
                                if role == "system":
                                    # Skip system messages - these are instructions
                                    logger.debug("Skipping system message")
                                    continue
                                elif role == "user":
                                    # Extract the actual user query, clean HTML if present
                                    extracted = _extract_user_query(content)
                                    logger.debug(f"Extracted user query: {extracted[:100]}...")
                                    if extracted:
                                        user_msg = extracted
                                elif role == "assistant":
                                    # Keep assistant messages with actual content
                                    if content and content.strip() and content.strip().lower() != "none":
                                        logger.debug(f"Keeping assistant message: {content[:100]}...")
                                        assistant_msg = content
                                    else:
                                        logger.debug("Skipping empty/none assistant message")
                                elif role == "tool":
                                    # Skip tool messages - they'll be handled as tool_calls
                                    logger.debug("Skipping tool message")
                                    continue
                            
                            # Get tool calls for this run
                            if hasattr(run, 'tools') and run.tools:
                                tool_calls = run.tools
                                logger.debug(f"Found {len(tool_calls)} tool calls")
                            
                            # Add messages to chat history
                            if user_msg:
                                logger.info(f"Adding user message: {user_msg[:50]}...")
                                add_message("user", user_msg)
                            if assistant_msg:
                                logger.info(f"Adding assistant message: {assistant_msg[:50]}...")
                                add_message("assistant", assistant_msg, tool_calls)
                
                # If no runs, try the session's get_messages_for_session method
                elif hasattr(target_session, 'get_messages_for_session'):
                    logger.info("No runs found, trying session.get_messages_for_session...")
                    try:
                        messages = target_session.get_messages_for_session()
                        if messages:
                            logger.info(f"Found {len(messages)} messages from session method")
                            for message in messages:
                                if not hasattr(message, 'role') or not hasattr(message, 'content'):
                                    continue
                                    
                                role = message.role
                                content = str(message.content)
                                
                                if role == "user":
                                    clean_content = _extract_user_query(content)
                                    if clean_content:
                                        add_message("user", clean_content)
                                elif role == "assistant" and content and content.strip() and content.strip().lower() != "none":
                                    add_message("assistant", content)
                    except Exception as e:
                        logger.debug(f"Session get_messages_for_session failed: {e}")
            else:
                logger.warning(f"No session found in database for session_id: {session_id}")
                    
        except Exception as e:
            logger.warning(f"Could not load chat history: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        # Log success
        logger.info(f"Successfully loaded session {session_id} with {len(st.session_state['messages'])} messages")
        st.rerun()
        
    except Exception as e:
        logger.error(f"Error loading session: {e}")
        st.sidebar.error(f"Error loading session: {str(e)}")


def get_tool_executions_for_message(agent: Agent, message) -> Optional[List[Any]]:
    """Get tool executions for a message from the agent's session data."""
    try:
        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return None

        # For stored sessions, find matching tool executions from runs
        if (
            hasattr(agent, "agent_session")
            and agent.agent_session
            and agent.agent_session.runs
        ):
            # Find tools from runs that match this message's tool calls
            for run in agent.agent_session.runs:
                if hasattr(run, "tools") and run.tools:
                    # Check if any tool in this run matches the message's tool calls
                    for tool_exec in run.tools:
                        if hasattr(tool_exec, "tool_name") and tool_exec.tool_name:
                            # Check if this tool matches any tool call in the message
                            for tool_call in message.tool_calls:
                                if (
                                    isinstance(tool_call, dict)
                                    and "function" in tool_call
                                    and tool_call["function"].get("name")
                                    == tool_exec.tool_name
                                ):
                                    # Found matching tools for this message
                                    return run.tools

        return None
    except Exception as e:
        logger.warning(f"Error getting tool executions for message: {e}")
        return None



def handle_agent_response(agent: Agent, question: str) -> None:
    """Handle agent response with streaming and tool call display."""
    with st.chat_message("assistant"):
        tool_calls_container = st.empty()
        resp_container = st.empty()
        with st.spinner("🤔 Thinking..."):
            response = ""
            try:
                # Run the agent and stream the response
                run_response = agent.run(question, stream=True)
                for resp_chunk in run_response:
                    try:
                        # Display tool calls if available
                        if hasattr(resp_chunk, "tool") and resp_chunk.tool:
                            display_tool_calls(tool_calls_container, [resp_chunk.tool])
                    except Exception as tool_error:
                        logger.warning(f"Error displaying tool calls: {tool_error}")

                    # Display response content (filter out tool call text)
                    if resp_chunk.content is not None:
                        # Filter out tool execution messages
                        content = str(resp_chunk.content)
                        
                        # Skip content that looks like tool execution logs
                        if not (
                            content.strip().endswith("completed in") or
                            content.strip().startswith("search_knowledge_base(") or
                            content.strip().startswith("duckduckgo_search(") or
                            "completed in" in content and "s." in content
                        ):
                            response += content
                            
                            # Clean HTML if the response is getting long and contains HTML
                            display_response = response
                            if len(response) > 500 and '<' in response and '>' in response:
                                display_response = clean_html_content(response, max_length=2000)
                            
                            resp_container.markdown(display_response)

                # Clean final response for storage if it contains HTML
                final_response = response
                if len(response) > 500 and '<' in response and '>' in response:
                    cleaned = clean_html_content(response, max_length=2000)
                    if cleaned != response:
                        final_response = cleaned
                
                # Add final response with tools
                try:
                    if hasattr(agent, 'run_response') and agent.run_response and hasattr(agent.run_response, 'tools'):
                        add_message("assistant", final_response, agent.run_response.tools)
                    else:
                        add_message("assistant", final_response)
                except Exception as add_msg_error:
                    logger.warning(f"Error adding message with tools: {add_msg_error}")
                    add_message("assistant", final_response)
                    
            except Exception as e:
                error_message = f"Sorry, I encountered an error: {str(e)}"
                add_message("assistant", error_message)
                st.error(error_message)
                logger.error(f"Full error details: {e}", exc_info=True)


def display_chat_messages() -> None:
    """Display all chat messages from session state."""
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            content = message["content"]
            with st.chat_message(message["role"]):
                # Display tool calls first if they exist
                if "tool_calls" in message and message["tool_calls"]:
                    display_tool_calls(st.container(), message["tool_calls"])

                # Display content if it exists and is not "None"
                if (
                    content is not None
                    and str(content).strip()
                    and str(content).strip().lower() != "none"
                ):
                    # Clean HTML content for assistant messages if needed
                    if message["role"] == "assistant":
                        content_str = str(content)
                        if '<' in content_str and '>' in content_str and len(content_str) > 500:
                            # This looks like HTML content, clean it
                            cleaned_content = clean_html_content(content_str, max_length=2000)
                            if cleaned_content != content_str:
                                st.markdown(f"**Summary:** {cleaned_content}")
                                with st.expander("View Raw Content", expanded=False):
                                    st.text(content_str)
                            else:
                                st.markdown(content)
                        else:
                            st.markdown(content)
                    else:
                        st.markdown(content)


def initialize_agent(model_id: str, agent_creation_callback: callable) -> Agent:
    """Initialize or get agent with proper session management."""
    if (
        "agent" not in st.session_state
        or st.session_state["agent"] is None
        or st.session_state.get("current_model") != model_id
    ):
        if st.session_state.get("current_model") is not None and st.session_state.get("current_model") != model_id:
            logger.info(f"Model changed from {st.session_state.get('current_model')} to {model_id} - starting new chat")
            agent = agent_creation_callback(model_id=model_id, session_id=None)
            
            # Generate new session ID
            agent.new_session()
            
            # Clear all session state for fresh start
            st.session_state["session_id"] = agent.session_id
            st.session_state["messages"] = []
        else:
            # Initial load or same model - use existing session if available
            session_id = st.session_state.get("session_id")
            agent = agent_creation_callback(model_id=model_id, session_id=session_id)
        st.session_state["agent"] = agent
        st.session_state["current_model"] = model_id
        return agent
    else:
        return st.session_state["agent"]


def manage_session_state(agent: Agent) -> None:
    """Manage session state initialization."""
    if agent.session_id:
        st.session_state["session_id"] = agent.session_id

    if "messages" not in st.session_state:
        st.session_state["messages"] = []


def knowledge_base_info_widget(agent: Agent) -> None:
    """Display knowledge base information widget."""
    if not agent.knowledge:
        st.sidebar.info("No knowledge base configured")
        return

    vector_db = getattr(agent.knowledge, "vector_db", None)
    if not vector_db:
        st.sidebar.info("No vector db configured")
        return

    try:
        doc_count = vector_db.get_count()
        if doc_count == 0:
            st.sidebar.info("💡 Upload documents to populate the knowledge base")
        else:
            st.sidebar.metric("Documents Loaded", doc_count)
    except Exception as e:
        logger.error(f"Error getting knowledge base info: {e}")
        st.sidebar.warning("Could not retrieve knowledge base information")


COMMON_CSS = """
    <style>
    .main-title {
        text-align: center;
        background: linear-gradient(45deg, #FF4B2B, #FF416C);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3em;
        font-weight: bold;
        padding: 1em 0;
    }
    .subtitle {
        text-align: center;
        color: #666;
        margin-bottom: 2em;
    }
    .stButton button {
        width: 100%;
        border-radius: 20px;
        margin: 0.2em 0;
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
    }
    </style>
"""
