import streamlit as st
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mermaid import MermaidTools


def initialize_agent():
    return Agent(
        name="Mermaid Diagram Generator",
        agent_id="mermaid-diagram-generator",
        model=OpenAIChat(id="gpt-4"),
        tools=[MermaidTools()],
        debug_mode=True,
        instructions=[
            "You are an expert at generating beautiful and complex Mermaid.js flowcharts. Follow these rules:",
            "Core Rules:",
            "- Use 'flowchart LR' by default for left-to-right flow",
            "- Never use semicolons in syntax",
            "- Put each node and connection on a new line",
            "- Return only the Mermaid code without any markdown or explanations",
            "- Indent subgraphs and nested elements with 4 spaces",
            "Node Styling:",
            "- Use [] for rectangular nodes: A[Rectangle]",
            "- Use () for round nodes: B(Round)",
            "- Use {} for diamond nodes: C{Decision}",
            "- Use [[ ]] for cylindrical nodes: D[[Database]]",
            "- Use [( )] for circle nodes: E[(Circle)]",
            "- Use (( )) for double circle nodes: F((Double))",
            "- Use > ] for flag nodes: G>Flag]",
            "- Use { } for rhombus nodes: H{Rhombus}",
            "- Use [/ /] for parallelogram: I[/Parallel/]",
            "- Use [\\ \\] for trapezoid: J[\\Trap\\]",
            "Connection Types:",
            "- Basic arrow: -->",
            "- Dotted line: -.->, -.-, -.->",
            "- Thick line: ==>",
            "- Line with text: -->|text|",
            "- Two-way arrow: <-->",
            "- Curved line: --o, --x",
            "- Line with cross: --x",
            "- Line with circle: --o",
            "Subgraphs and Groups:",
            "- Create subgraphs using:",
            "    subgraph title",
            "        node1 --> node2",
            "    end",
            "- Nest subgraphs for complex grouping",
            "- Use direction TB/BT/LR/RL in subgraphs",
            "Styling:",
            "- Add node styles: style nodeName fill:#f9f,stroke:#333,stroke-width:4px",
            "- Link styles: linkStyle 0 stroke:#ff3,stroke-width:4px",
            "- Class definitions: classDef className fill:#f9f,stroke:#333,stroke-width:4px",
            "- Apply classes: class nodeID className",
            "Complex Features:",
            "- Use click events: click nodeId callback",
            "- Add tooltips to nodes: A[Node]:::tooltip",
            "- Create multi-line text: A[Line1<br>Line2]",
            "- Use fontawesome icons: A[fa:fa-gear Settings]",
            "Example of a complex flowchart:",
            "flowchart LR",
            "    A([Start]) --> B{Input Valid?}",
            "    B -->|Yes| C[Process Data]",
            "    B -->|No| D[Show Error]",
            "    D --> A",
            "    C --> E[[Save to DB]]",
            "    E --> F>Success]",
            "    style A fill:#f9f,stroke:#333",
            "    style F fill:#bfb,stroke:#333",
            "When creating diagrams:",
            "- Start with clear entry and exit points",
            "- Use appropriate node shapes for different purposes",
            "- Add meaningful labels to connections",
            "- Group related nodes in subgraphs",
            "- Apply consistent styling",
            "- Use meaningful node IDs",
            "- Keep the layout balanced and readable",
        ],
    )


def render_mermaid(code):
    st.components.v1.html(
        f"""
    <div style="width: 100%; position: relative;">
        <div style="position: absolute; right: 10px; top: 10px; z-index: 100; background: white; padding: 5px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.2);">
            <button onclick="zoomIn()" style="margin-right: 5px;">➕</button>
            <button onclick="zoomOut()">➖</button>
            <button onclick="resetZoom()" style="margin-left: 5px;">↺</button>
        </div>
        <div id="mermaid-container" style="width: 100%; min-height: 100px; overflow: auto; position: relative;">
            <div class="mermaid" style="transform-origin: top left;">
                {code}
            </div>
        </div>
    </div>

    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11.4.1/+esm';
        
        // Initialize mermaid with a callback to adjust container height
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose'
        }});

        // Wait for the diagram to render
        window.addEventListener('load', function() {{
            setTimeout(() => {{
                const mermaidDiv = document.querySelector('.mermaid svg');
                if (mermaidDiv) {{
                    const height = mermaidDiv.getBoundingClientRect().height;
                    const container = document.getElementById('mermaid-container');
                    container.style.height = `${{height + 50}}px`; // Add padding
                }}
            }}, 500);
        }});

        // Zoom functionality
        let currentZoom = 1;
        const zoomStep = 0.1;
        const mermaidDiv = document.querySelector('.mermaid');

        window.zoomIn = function() {{
            currentZoom += zoomStep;
            mermaidDiv.style.transform = `scale(${{currentZoom}})`;
        }};

        window.zoomOut = function() {{
            if (currentZoom > zoomStep) {{
                currentZoom -= zoomStep;
                mermaidDiv.style.transform = `scale(${{currentZoom}})`;
            }}
        }};

        window.resetZoom = function() {{
            currentZoom = 1;
            mermaidDiv.style.transform = 'scale(1)';
        }};

        // Pan functionality
        let isDragging = false;
        let startX, startY, scrollLeft, scrollTop;
        const container = document.getElementById('mermaid-container');

        container.addEventListener('mousedown', (e) => {{
            isDragging = true;
            startX = e.pageX - container.offsetLeft;
            startY = e.pageY - container.offsetTop;
            scrollLeft = container.scrollLeft;
            scrollTop = container.scrollTop;
        }});

        container.addEventListener('mouseleave', () => {{
            isDragging = false;
        }});

        container.addEventListener('mouseup', () => {{
            isDragging = false;
        }});

        container.addEventListener('mousemove', (e) => {{
            if (!isDragging) return;
            e.preventDefault();
            const x = e.pageX - container.offsetLeft;
            const y = e.pageY - container.offsetTop;
            const walkX = (x - startX) * 2;
            const walkY = (y - startY) * 2;
            container.scrollLeft = scrollLeft - walkX;
            container.scrollTop = scrollTop - walkY;
        }});
    </script>
    """,
        height=None,
    )


# Setup page
st.set_page_config(page_title="Mermaid Diagram Generator", page_icon="📊")
st.title("Mermaid Diagram Generator 📊")
st.markdown("Describe your diagram, and I'll generate it using Mermaid.js!")

# Initialize agent
agent = initialize_agent()

# Get user input
user_input = st.text_area(
    "Describe your diagram (e.g., 'Generate a flowchart for user authentication'):"
)


def extract_mermaid_code(content: str) -> str:
    """Extract Mermaid code from content, handling both raw and markdown formats."""
    if "```mermaid" in content:
        import re

        mermaid_match = re.search(r"```mermaid\s*(.*?)```", content, re.DOTALL)
        return mermaid_match.group(1).strip() if mermaid_match else content.strip()
    return content.strip()


if st.button("Generate Diagram"):
    if not user_input.strip():
        st.warning("Please enter a description for the diagram.")
    else:
        with st.spinner("Generating diagram..."):
            try:
                # Get response from agent
                response = agent.run(user_input)

                if response and hasattr(response, "content"):
                    # Show the raw response in an expander
                    with st.expander("Show raw response", expanded=False):
                        st.text("Raw Response:")
                        st.code(response.content)

                    # Extract and clean Mermaid code
                    mermaid_code = extract_mermaid_code(response.content)

                    # Display diagram
                    st.subheader("Generated Diagram")
                    render_mermaid(mermaid_code)

                    # Show the Mermaid code
                    with st.expander("Show Mermaid code", expanded=True):
                        st.text("Mermaid Code:")
                        st.code(mermaid_code, language="mermaid")

                else:
                    st.error("No valid response received from the agent.")
                    st.write("Please try again with a different description.")

            except Exception as e:
                st.error(f"An error occurred while generating the diagram: {str(e)}")
                st.write("Please try again or modify your description.")
