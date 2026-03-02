import requests
import pandas as pd
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv()

MONDAY_API_KEY = os.getenv("MONDAY_API_KEY")
DEALS_BOARD_ID = os.getenv("DEALS_BOARD_ID")
WORK_ORDERS_BOARD_ID = os.getenv("WORK_ORDERS_BOARD_ID")

MONDAY_URL = "https://api.monday.com/v2"

HEADERS = {
    "Authorization": MONDAY_API_KEY,
    "Content-Type": "application/json"
}


# ─────────────────────────────────────────────
# LOW-LEVEL API HELPERS
# ─────────────────────────────────────────────

def fetch_board_columns(board_id: str) -> list[dict]:
    """Return column metadata (id, title, type) for a board."""
    query = f"""
    query {{
      boards(ids: {board_id}) {{
        columns {{
          id
          title
          type
        }}
      }}
    }}
    """
    resp = requests.post(MONDAY_URL, json={"query": query}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise Exception(f"GraphQL Error: {data['errors']}")
    return data["data"]["boards"][0]["columns"]


def fetch_board_data(board_id: str, cursor: str | None = None) -> tuple[str, pd.DataFrame]:
    """
    Live API call with pagination support (handles >500 items).
    Returns (board_name, DataFrame).
    """
    all_items = []
    board_name = ""
    next_cursor = None

    # First page
    query = f"""
    query {{
      boards(ids: {board_id}) {{
        name
        items_page(limit: 500) {{
          cursor
          items {{
            id
            name
            column_values {{
              id
              text
            }}
          }}
        }}
      }}
    }}
    """
    resp = requests.post(MONDAY_URL, json={"query": query}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise Exception(f"GraphQL Error: {data['errors']}")

    board = data["data"]["boards"][0]
    board_name = board["name"]
    page = board["items_page"]
    all_items.extend(page["items"])
    next_cursor = page.get("cursor")

    # Paginate if more items exist
    while next_cursor:
        paginate_query = f"""
        query {{
          next_items_page(limit: 500, cursor: "{next_cursor}") {{
            cursor
            items {{
              id
              name
              column_values {{
                id
                text
              }}
            }}
          }}
        }}
        """
        resp2 = requests.post(MONDAY_URL, json={"query": paginate_query}, headers=HEADERS, timeout=20)
        resp2.raise_for_status()
        data2 = resp2.json()
        if "errors" in data2:
            break
        page2 = data2["data"]["next_items_page"]
        all_items.extend(page2["items"])
        next_cursor = page2.get("cursor")

    rows = []
    for item in all_items:
        row = {"item_name": item["name"], "item_id": item["id"]}
        for col in item["column_values"]:
            row[col["id"]] = col["text"]
        rows.append(row)

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    return board_name, df


# ─────────────────────────────────────────────
# DATA CLEANING UTILITIES
# ─────────────────────────────────────────────

def clean_numeric_column(series: pd.Series) -> pd.Series:
    """Normalize messy currency / numeric formats."""
    return (
        series.fillna("")
        .astype(str)
        .str.replace(r"[₹$£€,\s]", "", regex=True)
        .str.strip()
        .replace("", None)
        .pipe(pd.to_numeric, errors="coerce")
    )


def infer_column_map(df: pd.DataFrame, columns_meta: list[dict]) -> dict:
    """
    Build a human-readable column map: {friendly_name: df_column_id}
    using board column metadata titles.
    """
    id_to_title = {c["id"]: c["title"].lower() for c in columns_meta}
    col_map = {}
    for col_id in df.columns:
        title = id_to_title.get(col_id, col_id)
        col_map[title] = col_id
    return col_map


def build_rich_dataframe(df: pd.DataFrame, columns_meta: list[dict]) -> pd.DataFrame:
    """Rename DataFrame columns from IDs to human-readable titles."""
    id_to_title = {c["id"]: c["title"] for c in columns_meta}
    rename = {col_id: id_to_title.get(col_id, col_id) for col_id in df.columns}
    return df.rename(columns=rename)


def detect_date_column(df: pd.DataFrame) -> str | None:
    """Find the most likely date column."""
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in ["date", "close", "created", "due", "timeline"]):
            sample = df[col].dropna().head(10)
            parsed = pd.to_datetime(sample, errors="coerce", infer_datetime_format=True)
            if parsed.notna().sum() >= 1:
                return col
    return None


def parse_date_column(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", infer_datetime_format=True)


# ─────────────────────────────────────────────
# ANALYSIS ENGINES
# ─────────────────────────────────────────────

def analyse_deals(df: pd.DataFrame, columns_meta: list[dict], filters: dict) -> dict:
    """Run BI analysis on Deals board."""
    rich = build_rich_dataframe(df, columns_meta)
    quality_notes = []
    results = {}

    # --- Numeric (amount/value) column ---
    amount_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["amount", "value", "revenue", "price"])),
        None
    )
    if amount_col:
        rich["_amount"] = clean_numeric_column(rich[amount_col])
        missing_pct = rich["_amount"].isna().mean() * 100
        quality_notes.append(f"'{amount_col}': {missing_pct:.1f}% missing — averages exclude NaN, totals treat NaN as 0.")

    # --- Stage/status column ---
    stage_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["stage", "status", "phase", "pipeline"])),
        None
    )

    # --- Sector/industry column ---
    sector_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["sector", "industry", "vertical", "segment", "category"])),
        None
    )

    # --- Owner/rep column ---
    owner_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["owner", "rep", "assigned", "person", "contact"])),
        None
    )

    # --- Date column ---
    date_col = detect_date_column(rich)
    if date_col:
        rich["_date"] = parse_date_column(rich[date_col])

    # --- Apply filters ---
    filtered = rich.copy()

    if filters.get("sector") and sector_col:
        mask = filtered[sector_col].str.lower().str.contains(filters["sector"].lower(), na=False)
        filtered = filtered[mask]
        results["filter_applied_sector"] = filters["sector"]

    if filters.get("stage") and stage_col:
        mask = filtered[stage_col].str.lower().str.contains(filters["stage"].lower(), na=False)
        filtered = filtered[mask]
        results["filter_applied_stage"] = filters["stage"]

    if filters.get("owner") and owner_col:
        mask = filtered[owner_col].str.lower().str.contains(filters["owner"].lower(), na=False)
        filtered = filtered[mask]
        results["filter_applied_owner"] = filters["owner"]

    if filters.get("quarter") and date_col:
        quarter_map = {"q1": [1,2,3], "q2": [4,5,6], "q3": [7,8,9], "q4": [10,11,12]}
        months = quarter_map.get(filters["quarter"].lower(), [])
        if months:
            filtered = filtered[filtered["_date"].dt.month.isin(months)]
            results["filter_applied_quarter"] = filters["quarter"].upper()

    if filters.get("year") and date_col:
        filtered = filtered[filtered["_date"].dt.year == int(filters["year"])]
        results["filter_applied_year"] = filters["year"]

    results["total_records"] = len(rich)
    results["filtered_records"] = len(filtered)

    if amount_col and "_amount" in filtered.columns:
        results["total_pipeline_value"] = round(filtered["_amount"].fillna(0).sum(), 2)
        results["average_deal_size"] = round(filtered["_amount"].dropna().mean(), 2) if filtered["_amount"].dropna().shape[0] > 0 else 0
        results["median_deal_size"] = round(filtered["_amount"].dropna().median(), 2) if filtered["_amount"].dropna().shape[0] > 0 else 0
        results["max_deal"] = round(filtered["_amount"].dropna().max(), 2) if filtered["_amount"].dropna().shape[0] > 0 else 0
        results["min_deal"] = round(filtered["_amount"].dropna().min(), 2) if filtered["_amount"].dropna().shape[0] > 0 else 0

    if stage_col:
        stage_counts = filtered[stage_col].value_counts().to_dict()
        results["pipeline_by_stage"] = stage_counts
        if "_amount" in filtered.columns:
            stage_value = filtered.groupby(stage_col)["_amount"].sum().round(2).to_dict()
            results["value_by_stage"] = stage_value

    if sector_col:
        sector_counts = filtered[sector_col].value_counts().head(10).to_dict()
        results["deals_by_sector"] = sector_counts
        if "_amount" in filtered.columns:
            sector_value = filtered.groupby(sector_col)["_amount"].sum().round(2).sort_values(ascending=False).head(10).to_dict()
            results["value_by_sector"] = sector_value

    if owner_col:
        owner_value = None
        if "_amount" in filtered.columns:
            owner_value = filtered.groupby(owner_col)["_amount"].sum().round(2).sort_values(ascending=False).head(10).to_dict()
            results["pipeline_by_owner"] = owner_value

    # Win rate if stage data available
    if stage_col:
        won_keywords = ["won", "closed won", "win", "closed"]
        won_mask = filtered[stage_col].str.lower().str.contains("|".join(won_keywords), na=False)
        won_count = won_mask.sum()
        if len(filtered) > 0:
            results["win_rate_percent"] = round((won_count / len(filtered)) * 100, 1)
            if "_amount" in filtered.columns:
                results["won_revenue"] = round(filtered.loc[won_mask, "_amount"].fillna(0).sum(), 2)

    results["data_quality_notes"] = quality_notes
    return results


def analyse_work_orders(df: pd.DataFrame, columns_meta: list[dict], filters: dict) -> dict:
    """Run BI analysis on Work Orders board."""
    rich = build_rich_dataframe(df, columns_meta)
    quality_notes = []
    results = {}

    amount_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["amount", "value", "revenue", "cost", "price", "budget"])),
        None
    )
    if amount_col:
        rich["_amount"] = clean_numeric_column(rich[amount_col])
        missing_pct = rich["_amount"].isna().mean() * 100
        quality_notes.append(f"'{amount_col}': {missing_pct:.1f}% missing values.")

    status_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["status", "stage", "state", "progress"])),
        None
    )
    sector_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["sector", "industry", "category", "type", "vertical"])),
        None
    )
    owner_col = next(
        (c for c in rich.columns if any(kw in str(c).lower() for kw in ["owner", "assigned", "person", "rep", "engineer"])),
        None
    )
    date_col = detect_date_column(rich)
    if date_col:
        rich["_date"] = parse_date_column(rich[date_col])

    # Apply filters
    filtered = rich.copy()
    if filters.get("sector") and sector_col:
        mask = filtered[sector_col].str.lower().str.contains(filters["sector"].lower(), na=False)
        filtered = filtered[mask]
        results["filter_applied_sector"] = filters["sector"]

    if filters.get("status") and status_col:
        mask = filtered[status_col].str.lower().str.contains(filters["status"].lower(), na=False)
        filtered = filtered[mask]
        results["filter_applied_status"] = filters["status"]

    if filters.get("quarter") and date_col:
        quarter_map = {"q1": [1,2,3], "q2": [4,5,6], "q3": [7,8,9], "q4": [10,11,12]}
        months = quarter_map.get(filters["quarter"].lower(), [])
        if months:
            filtered = filtered[filtered["_date"].dt.month.isin(months)]
            results["filter_applied_quarter"] = filters["quarter"].upper()

    if filters.get("year") and date_col:
        filtered = filtered[filtered["_date"].dt.year == int(filters["year"])]
        results["filter_applied_year"] = filters["year"]

    results["total_records"] = len(rich)
    results["filtered_records"] = len(filtered)

    if amount_col and "_amount" in filtered.columns:
        results["total_work_order_value"] = round(filtered["_amount"].fillna(0).sum(), 2)
        results["average_order_value"] = round(filtered["_amount"].dropna().mean(), 2) if filtered["_amount"].dropna().shape[0] > 0 else 0

    if status_col:
        results["orders_by_status"] = filtered[status_col].value_counts().to_dict()
        if "_amount" in filtered.columns:
            results["value_by_status"] = filtered.groupby(status_col)["_amount"].sum().round(2).to_dict()

    if sector_col:
        results["orders_by_sector"] = filtered[sector_col].value_counts().head(10).to_dict()
        if "_amount" in filtered.columns:
            results["value_by_sector"] = filtered.groupby(sector_col)["_amount"].sum().round(2).sort_values(ascending=False).head(10).to_dict()

    if owner_col and "_amount" in filtered.columns:
        results["value_by_owner"] = filtered.groupby(owner_col)["_amount"].sum().round(2).sort_values(ascending=False).head(10).to_dict()

    results["data_quality_notes"] = quality_notes
    return results


# ─────────────────────────────────────────────
# FILTER EXTRACTOR (rule-based NLP)
# ─────────────────────────────────────────────

def extract_filters(query: str) -> dict:
    """Extract structured filters from a natural-language query."""
    q = query.lower()
    filters = {}

    # Quarter detection
    for qtr in ["q1", "q2", "q3", "q4"]:
        if qtr in q:
            filters["quarter"] = qtr
            break

    # Year detection
    import re
    year_match = re.search(r"\b(202[0-9])\b", q)
    if year_match:
        filters["year"] = year_match.group(1)

    # Current quarter shorthand
    if "this quarter" in q or "current quarter" in q:
        current_month = datetime.now().month
        if current_month <= 3:
            filters["quarter"] = "q1"
        elif current_month <= 6:
            filters["quarter"] = "q2"
        elif current_month <= 9:
            filters["quarter"] = "q3"
        else:
            filters["quarter"] = "q4"
        filters["year"] = str(datetime.now().year)

    if "this year" in q or "current year" in q:
        filters["year"] = str(datetime.now().year)

    # Sector detection (common keywords)
    sectors = ["energy", "tech", "technology", "healthcare", "finance", "retail",
               "manufacturing", "real estate", "education", "logistics", "saas",
               "construction", "media", "telecom", "agriculture"]
    for sector in sectors:
        if sector in q:
            filters["sector"] = sector
            break

    # Stage / status detection
    stages = ["prospecting", "qualified", "proposal", "negotiation", "won", "closed",
              "lost", "demo", "discovery", "in progress", "pending", "completed", "cancelled"]
    for stage in stages:
        if stage in q:
            filters["stage"] = stage
            break

    return filters


def determine_boards(query: str) -> tuple[bool, bool]:
    """Decide which boards to query based on natural language."""
    q = query.lower()
    use_deals = any(kw in q for kw in [
        "deal", "pipeline", "revenue", "sales", "prospect", "lead",
        "win", "close", "won", "stage", "quota", "forecast", "crm"
    ])
    use_work = any(kw in q for kw in [
        "work order", "work", "order", "operation", "project",
        "delivery", "service", "task", "job", "ticket", "field"
    ])

    # If still ambiguous, query both
    if not use_deals and not use_work:
        use_deals = True
        use_work = True

    return use_deals, use_work


# ─────────────────────────────────────────────
# MAIN TOOL
# ─────────────────────────────────────────────

@tool
def query_monday_board(query: str) -> str:
    """
    Executive BI tool for querying Deals and/or Work Orders boards on monday.com.

    Capabilities:
    - Live API calls on every invocation (no caching)
    - Handles pagination for large boards
    - Normalizes messy data (currencies, nulls, inconsistent formats)
    - Filters by sector, stage/status, owner, quarter, year
    - Returns pipeline totals, breakdowns by stage/sector/owner, win rate, conversion metrics
    - Full data-quality transparency

    Use for queries about: pipeline, revenue, deals, work orders, operations, conversions, sector performance, quarterly results.
    """

    trace = {
        "timestamp": str(datetime.utcnow()),
        "user_query": query,
        "api_calls_made": [],
        "filters_extracted": {},
        "boards_queried": [],
        "data_quality_notes": [],
        "errors": []
    }

    try:
        filters = extract_filters(query)
        trace["filters_extracted"] = filters

        use_deals, use_work = determine_boards(query)
        trace["boards_queried"] = (["Deals"] if use_deals else []) + (["Work Orders"] if use_work else [])

        results = {}
        deals_df = None
        work_df = None

        # ── DEALS ──────────────────────────────────────────────
        if use_deals:
            deals_cols = fetch_board_columns(DEALS_BOARD_ID)
            trace["api_calls_made"].append("fetch_board_columns(DEALS)")

            deals_name, deals_df = fetch_board_data(DEALS_BOARD_ID)
            trace["api_calls_made"].append(f"fetch_board_data({deals_name}) → {len(deals_df)} rows")

            if deals_df.empty:
                results["deals_error"] = "No data returned from Deals board."
            else:
                deals_results = analyse_deals(deals_df, deals_cols, filters)
                results["deals"] = deals_results
                trace["data_quality_notes"].extend(deals_results.pop("data_quality_notes", []))

        # ── WORK ORDERS ────────────────────────────────────────
        if use_work:
            work_cols = fetch_board_columns(WORK_ORDERS_BOARD_ID)
            trace["api_calls_made"].append("fetch_board_columns(WORK_ORDERS)")

            work_name, work_df = fetch_board_data(WORK_ORDERS_BOARD_ID)
            trace["api_calls_made"].append(f"fetch_board_data({work_name}) → {len(work_df)} rows")

            if work_df.empty:
                results["work_error"] = "No data returned from Work Orders board."
            else:
                work_results = analyse_work_orders(work_df, work_cols, filters)
                results["work_orders"] = work_results
                trace["data_quality_notes"].extend(work_results.pop("data_quality_notes", []))

        # ── CROSS-BOARD METRICS ────────────────────────────────
        if use_deals and use_work and "deals" in results and "work_orders" in results:
            pipeline_val = results["deals"].get("total_pipeline_value", 0) or 0
            work_val = results["work_orders"].get("total_work_order_value", 0) or 0
            if pipeline_val > 0:
                results["cross_board"] = {
                    "revenue_conversion_rate_percent": round((work_val / pipeline_val) * 100, 2),
                    "pipeline_to_operations_ratio": f"1 : {round(work_val / pipeline_val, 2)}" if pipeline_val > 0 else "N/A"
                }

        # ── FORMAT RESPONSE ────────────────────────────────────
        def fmt(val):
            if isinstance(val, float):
                return f"{val:,.2f}"
            if isinstance(val, int):
                return f"{val:,}"
            return str(val)

        lines = ["## 📊 Executive BI Summary\n"]

        if filters:
            filter_str = " | ".join(f"{k.replace('_', ' ').title()}: **{v}**" for k, v in filters.items())
            lines.append(f"**Active Filters:** {filter_str}\n")

        if "deals" in results:
            d = results["deals"]
            lines.append("### 💼 Deals / Pipeline")
            lines.append(f"- Records: {fmt(d.get('filtered_records', 0))} / {fmt(d.get('total_records', 0))} total")
            if "total_pipeline_value" in d:
                lines.append(f"- **Total Pipeline Value:** ₹{fmt(d['total_pipeline_value'])}")
                lines.append(f"- Avg Deal Size: ₹{fmt(d.get('average_deal_size', 0))}")
                lines.append(f"- Median Deal: ₹{fmt(d.get('median_deal_size', 0))}")
                lines.append(f"- Largest Deal: ₹{fmt(d.get('max_deal', 0))}")
            if "win_rate_percent" in d:
                lines.append(f"- **Win Rate:** {d['win_rate_percent']}%")
            if "won_revenue" in d:
                lines.append(f"- Won Revenue: ₹{fmt(d['won_revenue'])}")
            if "pipeline_by_stage" in d:
                lines.append("\n**Pipeline by Stage:**")
                for stage, count in d["pipeline_by_stage"].items():
                    val = d.get("value_by_stage", {}).get(stage, "")
                    val_str = f" — ₹{fmt(val)}" if val else ""
                    lines.append(f"  - {stage}: {count} deals{val_str}")
            if "deals_by_sector" in d:
                lines.append("\n**Top Sectors:**")
                for sector, count in list(d["deals_by_sector"].items())[:5]:
                    val = d.get("value_by_sector", {}).get(sector, "")
                    val_str = f" — ₹{fmt(val)}" if val else ""
                    lines.append(f"  - {sector}: {count} deals{val_str}")
            if "pipeline_by_owner" in d:
                lines.append("\n**Pipeline by Owner:**")
                for owner, val in list(d["pipeline_by_owner"].items())[:5]:
                    lines.append(f"  - {owner}: ₹{fmt(val)}")
            lines.append("")

        if "work_orders" in results:
            w = results["work_orders"]
            lines.append("### 🔧 Work Orders / Operations")
            lines.append(f"- Records: {fmt(w.get('filtered_records', 0))} / {fmt(w.get('total_records', 0))} total")
            if "total_work_order_value" in w:
                lines.append(f"- **Total Value:** ₹{fmt(w['total_work_order_value'])}")
                lines.append(f"- Avg Order Value: ₹{fmt(w.get('average_order_value', 0))}")
            if "orders_by_status" in w:
                lines.append("\n**Orders by Status:**")
                for status, count in w["orders_by_status"].items():
                    val = w.get("value_by_status", {}).get(status, "")
                    val_str = f" — ₹{fmt(val)}" if val else ""
                    lines.append(f"  - {status}: {count}{val_str}")
            if "orders_by_sector" in w:
                lines.append("\n**Top Sectors:**")
                for sector, count in list(w["orders_by_sector"].items())[:5]:
                    lines.append(f"  - {sector}: {count}")
            lines.append("")

        if "cross_board" in results:
            cb = results["cross_board"]
            lines.append("### 🔄 Cross-Board Metrics")
            lines.append(f"- Revenue Conversion Rate: **{cb['revenue_conversion_rate_percent']}%**")
            lines.append(f"- Pipeline-to-Operations Ratio: {cb['pipeline_to_operations_ratio']}")
            lines.append("")

        if trace["data_quality_notes"]:
            lines.append("### ⚠️ Data Quality Notes")
            for note in trace["data_quality_notes"]:
                lines.append(f"- {note}")

        answer_text = "\n".join(lines)

        return json.dumps({
            "answer": answer_text,
            "trace": trace,
            "raw_results": results
        })

    except Exception as e:
        import traceback
        trace["errors"].append(str(e))
        trace["traceback"] = traceback.format_exc()
        return json.dumps({
            "answer": f"⚠️ Error retrieving data: {str(e)}\n\nPlease check your API credentials and board IDs.",
            "trace": trace
        })


@tool
def get_board_schema(board: str) -> str:
    """
    Returns the column schema for a specified board.
    Use this when you need to know what fields are available before querying.
    board: 'deals' or 'work_orders'
    """
    trace = {"timestamp": str(datetime.utcnow()), "action": f"get_board_schema({board})"}
    try:
        board_id = DEALS_BOARD_ID if "deal" in board.lower() else WORK_ORDERS_BOARD_ID
        cols = fetch_board_columns(board_id)
        schema = [{"id": c["id"], "title": c["title"], "type": c["type"]} for c in cols]
        return json.dumps({
            "answer": f"**{board.title()} Board Columns:**\n" + "\n".join(
                f"- **{c['title']}** (type: {c['type']}, id: `{c['id']}`)" for c in schema
            ),
            "trace": trace,
            "schema": schema
        })
    except Exception as e:
        trace["error"] = str(e)
        return json.dumps({"answer": f"Error fetching schema: {e}", "trace": trace})
