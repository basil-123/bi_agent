import os
import re
import json
import requests
import pandas as pd
from dotenv import load_dotenv
from monday_client import fetch_board_items

load_dotenv()

GROK_API_KEY = os.getenv("GROK_API_KEY")

# ⚠️ Replace with your actual board IDs
WORK_ORDERS_BOARD_ID = 123456789
DEALS_BOARD_ID = 987654321


# ----------------------------
# Grok Intent Parsing
# ----------------------------
def parse_intent(user_query):

    prompt = f"""
    Convert this business question into structured JSON.

    Question: {user_query}

    Return only valid JSON:
    {{
      "sector": "...",
      "timeframe": "...",
      "metric": "..."
    }}
    """

    response = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "grok-2-latest",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        }
    )

    result = response.json()
    content = result["choices"][0]["message"]["content"]

    try:
        return json.loads(content)
    except:
        return {}


# ----------------------------
# Data Cleaning
# ----------------------------
def clean_currency(value):
    if not value:
        return 0
    value = re.sub(r"[₹,$]", "", value)
    value = value.replace(",", "")
    try:
        return float(value)
    except:
        return 0


def normalize_items(items):
    rows = []
    for item in items:
        row = {"name": item["name"]}
        for col in item["column_values"]:
            row[col["id"]] = col["text"]
        rows.append(row)
    return pd.DataFrame(rows)


# ----------------------------
# Core BI Logic
# ----------------------------
def run_analysis(user_query, trace_callback=None):

    if trace_callback:
        trace_callback("Parsing intent using Grok...")

    intent = parse_intent(user_query)

    if trace_callback:
        trace_callback("Fetching Work Orders board (live API call)...")

    work_orders_raw = fetch_board_items(WORK_ORDERS_BOARD_ID)

    if trace_callback:
        trace_callback("Fetching Deals board (live API call)...")

    deals_raw = fetch_board_items(DEALS_BOARD_ID)

    if trace_callback:
        trace_callback("Normalizing messy data...")

    work_df = normalize_items(work_orders_raw)
    deals_df = normalize_items(deals_raw)

    # Adjust column IDs as needed
    work_df["amount"] = work_df.get("amount", "").apply(clean_currency)
    deals_df["amount"] = deals_df.get("amount", "").apply(clean_currency)

    total_pipeline = deals_df["amount"].sum()
    total_revenue = work_df["amount"].sum()

    conversion_rate = 0
    if total_pipeline > 0:
        conversion_rate = total_revenue / total_pipeline * 100

    insight = f"""
📊 Business Summary

Intent Parsed: {intent}

Total Pipeline: ₹{total_pipeline:,.2f}
Total Revenue (Work Orders): ₹{total_revenue:,.2f}
Conversion Rate: {conversion_rate:.2f}%

Note: Data cleaned and normalized from live boards.
"""

    return insight