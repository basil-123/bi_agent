import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import streamlit as st
import os
import json
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from tools import query_monday_board, get_board_schema

load_dotenv()

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Executive BI Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# STYLING
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Hero */
.hero {
    text-align: center;
    padding: 2.5rem 0 1.5rem 0;
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    border-radius: 16px;
    margin-bottom: 1.5rem;
    color: white;
}
.hero h1 {
    font-size: 2.4rem;
    font-weight: 800;
    margin: 0;
    background: linear-gradient(90deg, #60a5fa, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero p {
    color: #94a3b8;
    margin-top: 0.4rem;
    font-size: 1rem;
}

/* Chat messages */
[data-testid="stChatMessage"] {
    border-radius: 12px;
    margin-bottom: 0.5rem;
}

/* Sidebar cards */
.stat-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.6rem;
    color: #e2e8f0;
}
.stat-card .label {
    font-size: 0.7rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.stat-card .value {
    font-size: 1.1rem;
    font-weight: 700;
    color: #60a5fa;
}

/* Suggestion chips */
.chip-container {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin: 1rem 0;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ BI Agent")
    st.divider()

    # Connection status
    api_key = os.getenv("MONDAY_API_KEY")
    deals_board = os.getenv("DEALS_BOARD_ID")
    work_board = os.getenv("WORK_ORDERS_BOARD_ID")
    groq_key = os.getenv("GROQ_API_KEY")

    st.markdown("### 🔌 Connections")
    if api_key:
        st.success("✅ Monday.com API")
    else:
        st.error("❌ Monday.com API Key Missing")

    if groq_key:
        st.success("✅ Groq (Llama-3.1-8b)")
    else:
        st.error("❌ Groq API Key Missing")

    st.divider()

    st.markdown("### 📋 Indexed Boards")
    if deals_board:
        st.markdown(f"🟢 **Deals** `#{deals_board}`")
    else:
        st.warning("Deals Board ID not set")
    if work_board:
        st.markdown(f"🟢 **Work Orders** `#{work_board}`")
    else:
        st.warning("Work Orders Board ID not set")

    st.divider()

    # Suggested queries
    st.markdown("### 💡 Suggested Queries")
    suggestions = [
        "How's our pipeline for the energy sector this quarter?",
        "Show deal breakdown by stage",
        "What's our win rate?",
        "Compare pipeline vs work orders value",
        "Top sectors by revenue",
        "Work orders by status",
        "Show me deals by owner",
        "What's the total pipeline value this year?",
    ]
    for s in suggestions:
        if st.button(s, key=f"btn_{s[:20]}", use_container_width=True):
            st.session_state["suggested_query"] = s

    st.divider()

    # Clear chat
    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.pop("trace_history", None)
        st.rerun()

    st.divider()

    # Trace panel
    if st.session_state.get("last_trace"):
        st.markdown("### 🔍 Last Tool Trace")
        with st.expander("View Trace", expanded=False):
            st.json(st.session_state["last_trace"])


# ─────────────────────────────────────────────
# LLM + AGENT SETUP
# ─────────────────────────────────────────────
@st.cache_resource
def get_agent():
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
    tools = [query_monday_board, get_board_schema]
    return create_react_agent(llm, tools)

agent_executor = get_agent()

SYSTEM_PROMPT = SystemMessage(content="""
You are an expert executive BI analyst with access to live monday.com data.

Your role:
- Answer founder/executive-level business intelligence questions with precision
- Interpret natural language queries and extract relevant filters (sector, quarter, year, stage, owner)
- Use query_monday_board for all data queries — it handles filtering internally
- Use get_board_schema first if you need to understand available columns before a complex query
- Ask 1 targeted clarifying question if the query is genuinely ambiguous (e.g., "Did you mean deals or work orders?")
- Present insights in a clear, executive-friendly format
- Highlight anomalies, data quality issues, and caveats
- Suggest follow-up questions the founder might find valuable

Rules:
- Always use the tools for live data — never assume or hallucinate numbers
- Keep responses concise but insightful — lead with the key number, then context
- If a filter returned 0 results, tell the user and suggest broadening the query
- Format currency values clearly (use ₹ prefix, comma-separated)
- After answering, suggest 1-2 relevant follow-up questions
""")

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_trace" not in st.session_state:
    st.session_state.last_trace = None
if "query_count" not in st.session_state:
    st.session_state.query_count = 0


# ─────────────────────────────────────────────
# MAIN CHAT UI
# ─────────────────────────────────────────────

# Hero header (only when no messages)
if not st.session_state.messages:
    st.markdown("""
    <div class="hero">
        <h1>⚡ Executive BI Copilot</h1>
        <p>Live Monday.com Intelligence · Ask anything about your pipeline, revenue & operations</p>
    </div>
    """, unsafe_allow_html=True)

    # Quick start chips
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📊 Pipeline overview", use_container_width=True):
            st.session_state["suggested_query"] = "Give me a full pipeline overview"
    with col2:
        if st.button("🏭 Energy sector deals", use_container_width=True):
            st.session_state["suggested_query"] = "How's our pipeline for the energy sector this quarter?"
    with col3:
        if st.button("🔧 Operations status", use_container_width=True):
            st.session_state["suggested_query"] = "Show me work orders by status"

# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle suggested query from sidebar buttons
suggested = st.session_state.pop("suggested_query", None)

# Chat input
user_input = st.chat_input("Ask about pipeline, revenue, sectors, work orders...") or suggested

if user_input:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Process with agent
    with st.chat_message("assistant"):
        with st.status("🔍 Querying live Monday.com data...", expanded=True) as status:
            st.write("📡 Sending live API request...")

            # Build chat history for agent
            chat_history = [SYSTEM_PROMPT]
            for m in st.session_state.messages:
                if m["role"] == "user":
                    chat_history.append(HumanMessage(content=m["content"]))
                else:
                    chat_history.append(AIMessage(content=m["content"]))

            try:
                response = agent_executor.invoke(
                    {"messages": chat_history},
                    config={"recursion_limit": 8}
                )

                raw_output = response["messages"][-1].content
                st.write("✅ Data received — processing insights...")

                # Parse structured output from tool if present
                try:
                    parsed = json.loads(raw_output)
                    output_text = parsed.get("answer", raw_output)
                    trace_data = parsed.get("trace", {})
                except Exception:
                    output_text = raw_output
                    trace_data = {"note": "Response was plain text (no structured tool output)."}

                # Try to extract trace from intermediate messages
                for msg in response["messages"]:
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        try:
                            inner = json.loads(msg.content)
                            if "trace" in inner:
                                trace_data = inner["trace"]
                                break
                        except Exception:
                            pass

                st.session_state.last_trace = trace_data
                st.session_state.query_count += 1

                # Update sidebar trace count
                api_calls = len(trace_data.get("api_calls_made", []))
                if api_calls:
                    st.write(f"📊 {api_calls} API call(s) made to Monday.com")

                status.update(
                    label=f"✅ Live query complete — {api_calls} API call(s)",
                    state="complete",
                    expanded=False
                )

            except Exception as e:
                output_text = f"⚠️ Agent error: {str(e)}\n\nPlease check your API credentials in `.env`."
                trace_data = {"error": str(e)}
                status.update(label="❌ Error", state="error", expanded=False)

        # Render the answer
        st.markdown(output_text)

        # Show trace inline (collapsed)
        if trace_data and trace_data != {"note": "Response was plain text (no structured tool output)."}:
            with st.expander("🔍 Tool Execution Trace", expanded=False):
                col_a, col_b = st.columns(2)
                with col_a:
                    if trace_data.get("api_calls_made"):
                        st.markdown("**API Calls Made:**")
                        for call in trace_data["api_calls_made"]:
                            st.markdown(f"- `{call}`")
                    if trace_data.get("filters_extracted"):
                        st.markdown("**Filters Extracted:**")
                        st.json(trace_data["filters_extracted"])
                with col_b:
                    if trace_data.get("boards_queried"):
                        st.markdown("**Boards Queried:**")
                        for b in trace_data["boards_queried"]:
                            st.markdown(f"- {b}")
                    if trace_data.get("data_quality_notes"):
                        st.markdown("**Data Quality Notes:**")
                        for note in trace_data["data_quality_notes"]:
                            st.warning(note)
                if trace_data.get("errors"):
                    st.error(f"Errors: {trace_data['errors']}")

    # Store assistant response
    st.session_state.messages.append({"role": "assistant", "content": output_text})

    # Update sidebar trace
    with st.sidebar:
        if st.session_state.last_trace:
            st.markdown("### 🔍 Last Tool Trace")
            with st.expander("View Trace", expanded=False):
                st.json(st.session_state.last_trace)

# ─────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────
if st.session_state.query_count > 0:
    st.markdown(
        f"<p style='text-align:center;color:#475569;font-size:0.75rem;margin-top:2rem;'>"
        f"Queries this session: {st.session_state.query_count} · All data fetched live from Monday.com"
        f"</p>",
        unsafe_allow_html=True
    )
