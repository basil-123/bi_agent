# Decision Log — Executive BI Agent

**Project:** Monday.com Business Intelligence Agent
**Author:** [Your Name]
**Date:** March 2026

---

## 1. Tech Stack Choices

### LLM: Groq (Llama-3.1-8b-instant)

**Decision:** Use Groq's hosted Llama-3.1-8b-instant over GPT-4, Claude, or self-hosted models.

**Reasoning:**
- **Speed:** Groq's LPU inference delivers ~800 tokens/second — critical for a live BI tool where latency degrades trust. GPT-4 averages 30–50 tokens/second.
- **Free tier:** Groq offers a generous free tier, removing cost friction for evaluators running the prototype.
- **Tool calling:** Llama-3.1-8b-instant supports LangChain-compatible tool calling reliably.
- **Trade-off:** Slightly weaker reasoning than GPT-4o on very complex multi-step queries, mitigated by the structured output format from our tools.

### Agent Framework: LangGraph ReAct

**Decision:** Use `langgraph.prebuilt.create_react_agent` over a custom chain or bare LangChain AgentExecutor.

**Reasoning:**
- **Reliability:** LangGraph's ReAct loop handles tool-call → observe → respond cycles robustly, with explicit `recursion_limit` to prevent infinite loops.
- **Visibility:** Each intermediate step (tool call, tool result) is preserved in `response["messages"]`, enabling the trace panel in the UI.
- **Simplicity:** `create_react_agent` requires minimal boilerplate vs. building a custom graph, keeping the codebase maintainable.
- **Trade-off:** LangGraph adds dependency weight; for a simple single-tool agent, a direct LangChain chain would suffice. Chosen here for extensibility.

### Frontend: Streamlit

**Decision:** Streamlit over FastAPI+React, Flask, or Gradio.

**Reasoning:**
- **Speed to prototype:** Streamlit's `st.chat_message`, `st.status`, and `st.json` components map directly to the requirements (conversational UI + trace visibility) with zero frontend code.
- **Deployment:** One-click Streamlit Cloud deployment with secrets management — evaluators can run the live demo without any local setup.
- **Trade-off:** Less flexible than a custom React frontend for advanced UI interactions, but requirements do not demand that level of customization.

### Data Source: Monday.com GraphQL API (direct)

**Decision:** Use Monday.com's REST/GraphQL API directly rather than MCP (Model Context Protocol).

**Reasoning:**
- **Control:** Direct API calls give full control over pagination, column introspection, and error handling.
- **Reliability:** MCP is still maturing; direct HTTP calls are battle-tested and easier to debug.
- **Pagination:** Implemented cursor-based pagination (`next_items_page`) to handle boards with >500 items — not straightforward in standard MCP connectors.
- **Note:** MCP integration is listed as a bonus in the spec. The architecture is designed so a `monday_mcp` tool could be swapped in alongside `query_monday_board` without restructuring the agent.

---

## 2. Key Design Decisions

### No Caching

Every invocation of `query_monday_board` makes a fresh API call. No in-memory store, no file cache, no Redis. This satisfies the spec's requirement explicitly and ensures founders always see current data. The trade-off is latency (~1–3s per query depending on board size), which is acceptable for an executive BI tool.

### Rule-Based Filter Extraction + LLM Interpretation (Hybrid)

**Problem:** Relying purely on the LLM to "figure out" filters is unpredictable. Relying purely on regex misses paraphrases.

**Solution:** `extract_filters()` in `tools.py` handles deterministic extraction (quarter keywords, year regex, known sector names, stage keywords). The LLM handles everything else: disambiguating intent, deciding which boards to query, and formatting the final narrative response.

**Result:** "How's our energy sector pipeline this quarter?" reliably filters to `{sector: "energy", quarter: "q3", year: "2026"}` without LLM hallucination risk.

### Column Introspection Before Analysis

Rather than hardcoding column IDs (which vary per Monday.com workspace), `fetch_board_columns()` fetches the board's schema on every query. This makes the tool workspace-agnostic — it works regardless of how the evaluator names their columns when importing the CSVs.

### Two Tools Instead of One

`query_monday_board` handles all BI queries. `get_board_schema` exists for the agent to call when it needs to understand available dimensions before a complex or ambiguous query (e.g., "what sectors do you track?"). This mirrors the ReAct pattern: observe the environment, then act.

### Data Quality Communication

All missing-value rates, normalization assumptions, and filter results are surfaced explicitly in both the tool's structured response and the Streamlit UI. Founders making decisions based on incomplete data need to know its completeness level.

---

## 3. Known Limitations & Future Work

| Limitation | Mitigation / Future Fix |
|---|---|
| Groq rate limits (free tier: ~30 req/min) | Upgrade to paid tier or swap to OpenAI for production |
| No date-range filtering (only quarterly) | Add `start_date` / `end_date` filter params to `extract_filters()` |
| Sector detection uses keyword list | Replace with LLM-based entity extraction for arbitrary sector names |
| No write operations | Add `create_item` / `update_item` tools for action-taking agent |
| No chart rendering | Integrate `plotly` or `altair` for visual breakdowns in Streamlit |
| Single-workspace | Parameterize workspace URL for multi-tenant use |
