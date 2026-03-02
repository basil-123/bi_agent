# ⚡ Executive BI Agent — Monday.com Intelligence

An AI-powered Business Intelligence agent that answers founder-level queries against live Monday.com boards (Deals + Work Orders) using natural language.

---

## 🚀 Live Demo

> **Hosted URL:** `https://biagent.streamlit.app

> **Monday.com Boards:**
> - Deals Board: `https://your-workspace.monday.com/boards/DEALS_BOARD_ID`
> - Work Orders Board: `https://your-workspace.monday.com/boards/WORK_ORDERS_BOARD_ID`

---

## 📁 Project Structure

```
bi-agent/
├── app.py                  # Streamlit frontend + LangGraph agent
├── tools.py                # Monday.com API tools + BI analysis engine
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── decision_log.md         # Technical decision log (max 2 pages)
└── README.md               # This file
```

---

## ⚙️ Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/basil-123/bi_agent.git
cd bi-agent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```env
MONDAY_API_KEY=your_monday_api_key_here
DEALS_BOARD_ID=your_deals_board_id
WORK_ORDERS_BOARD_ID=your_work_orders_board_id
GROQ_API_KEY=your_groq_api_key_here
```

#### How to get your Monday.com API Key:
1. Log in to Monday.com
2. Click your avatar → **Developers** → **My Access Tokens**
3. Copy the personal API token

#### How to get Board IDs:
1. Open the board in Monday.com
2. The URL will look like: `https://yourapp.monday.com/boards/123456789`
3. The number at the end is your Board ID

#### How to get Groq API Key:
1. Sign up at [console.groq.com](https://console.groq.com)
2. Navigate to **API Keys** → **Create API Key**

### 4. Import sample data into Monday.com

1. Go to Monday.com → **+ New Board** → **Import from Excel/CSV**
2. Import `deals_sample.csv` → name the board **"Deals"**
3. Import `work_orders_sample.csv` → name the board **"Work Orders"**
4. Copy each board's ID from the URL into `.env`

### 5. Run the app

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## 🧠 Features

| Feature | Details |
|---|---|
| **Live API Calls** | Every query hits the Monday.com API in real time — no caching |
| **Natural Language Filters** | Extracts sector, quarter, year, stage, owner from plain English |
| **Pagination** | Handles boards with >500 items via cursor-based pagination |
| **Data Resilience** | Normalizes ₹/$/£ formats, handles nulls, communicates data quality |
| **Cross-Board Analytics** | Revenue conversion rate, pipeline-to-operations ratio |
| **Tool Trace Visibility** | Every API call, filter extracted, and data quality note shown in UI |
| **Clarifying Questions** | Agent asks follow-ups for ambiguous queries |
| **Board Schema Introspection** | Agent can inspect column names before querying |

---

## 💬 Sample Queries

```
How's our pipeline for the energy sector this quarter?
Show deal breakdown by stage with values
What's our win rate?
Compare total pipeline value vs work orders
Top 5 sectors by revenue
Work orders by status — show me what's pending
Who has the largest pipeline by owner?
What's our total revenue this year?
```

---

## 🏗️ Architecture

```
User Query
    ↓
Streamlit Chat UI (app.py)
    ↓
LangGraph ReAct Agent (Groq Llama-3.1-8b-instant)
    ↓
Tools:
  ├── query_monday_board   → fetch + filter + analyse both boards
  └── get_board_schema     → introspect column metadata
    ↓
Monday.com GraphQL API (live, no cache)
    ↓
Formatted BI Summary + Tool Trace
```

---

## 🌐 Deployment (Streamlit Cloud)

1. Push code to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New App**
3. Select your repo and set `app.py` as the main file
4. Under **Advanced Settings → Secrets**, add:

```toml
MONDAY_API_KEY = "your_key"
DEALS_BOARD_ID = "your_id"
WORK_ORDERS_BOARD_ID = "your_id"
GROQ_API_KEY = "your_key"
```

5. Click **Deploy**

---

## 🔧 Tech Stack

| Component | Technology | Reason |
|---|---|---|
| Frontend | Streamlit | Rapid prototyping, built-in chat UI |
| LLM | Groq Llama-3.1-8b-instant | Fast inference, free tier available |
| Agent Framework | LangGraph ReAct | Reliable tool-calling loop with recursion control |
| Data Source | Monday.com GraphQL API | Live data, no ETL pipeline needed |
| Data Processing | Pandas | Flexible filtering and aggregation |

See `decision_log.md` for full justification.
