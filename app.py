"""
app.py
======
Conversational BI & DWH Documentation Tool

Run locally:
    streamlit run app.py

Deploy on Streamlit Cloud:
    Add ANTHROPIC_API_KEY to app secrets (Settings → Secrets)
"""

import os
import sys
import datetime
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Page config — must be first st call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Insurance DWH Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from schema.dwh_schema import get_table_stats
import modules.chat_bi as chat_bi_mod
import modules.schema_explorer as schema_explorer_mod
import modules.lineage_viewer as lineage_viewer_mod
import modules.glossary as glossary_mod

# ---------------------------------------------------------------------------
# API key — Streamlit secrets (Cloud) or env var (local)
# ---------------------------------------------------------------------------

DAILY_QUERY_LIMIT = 20   # max queries per day across all users

def _load_api_key() -> None:
    """
    Tries to load API key in this order:
      1. st.secrets (Streamlit Cloud deployment)
      2. OS environment variable (local run)
    Sets os.environ so claude_client picks it up.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
    except Exception:
        pass

_load_api_key()

from utils.claude_client import is_api_key_set

# ---------------------------------------------------------------------------
# Rate limiting — daily query counter stored in session_state
# Uses date-keyed counter so it resets every day automatically
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.date.today().isoformat()

def _get_query_count() -> int:
    key = f"query_count_{_today()}"
    return st.session_state.get(key, 0)

def _increment_query_count() -> None:
    key = f"query_count_{_today()}"
    st.session_state[key] = st.session_state.get(key, 0) + 1

def _limit_reached() -> bool:
    return _get_query_count() >= DAILY_QUERY_LIMIT

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
[data-testid="stMetric"] {
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    border: 1px solid rgba(128,128,128,0.15);
}
pre { overflow-x: auto; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Chat BI tab
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS_EN = [
    "What is the total gross premium by product for 2023?",
    "Which 5 products have the highest loss ratio?",
    "Show active policy count and average premium by distribution channel.",
    "Compare total premium and loss ratio by region.",
    "What is the average claim settlement time by claim type?",
    "Which product and region has the highest open claim reserve?",
    "How did monthly claim count change throughout 2024?",
    "What is the average premium per policy for Corporate segment customers?",
]


def _render_chat_bi() -> None:
    st.header("Chat BI")
    st.caption("Ask questions in plain English — SQL is generated and executed automatically.")

    if not is_api_key_set():
        st.warning("Claude API key not configured. Please contact the administrator.")
        return

    # Rate limit banner
    used  = _get_query_count()
    remaining = DAILY_QUERY_LIMIT - used
    if _limit_reached():
        st.error(
            f"Daily demo limit of {DAILY_QUERY_LIMIT} queries has been reached. "
            "Please check back tomorrow."
        )
        return
    else:
        st.info(f"Demo mode — {remaining} of {DAILY_QUERY_LIMIT} daily queries remaining.")

    # Sample questions
    with st.expander("Sample Questions", expanded=False):
        cols = st.columns(2)
        for i, q in enumerate(SAMPLE_QUESTIONS_EN):
            with cols[i % 2]:
                if st.button(q, key=f"sample_{i}", use_container_width=True):
                    st.session_state["chat_question"] = q
                    st.rerun()

    # Question input
    question = st.text_input(
        "Your question",
        value=st.session_state.get("chat_question", ""),
        placeholder="What is the total gross premium by product for 2023?",
        key="chat_input",
    )

    col_ask, col_clear = st.columns([1, 5])
    with col_ask:
        ask_clicked = st.button("Ask", type="primary", use_container_width=True)
    with col_clear:
        if st.button("Clear"):
            for k in ["chat_question", "chat_result"]:
                st.session_state.pop(k, None)
            st.rerun()

    # Submit
    if ask_clicked and question.strip():
        if _limit_reached():
            st.error("Daily query limit reached.")
            return
        st.session_state["chat_question"] = question
        with st.spinner("Generating SQL and running query..."):
            result = chat_bi_mod.run_and_explain(question)
        _increment_query_count()
        st.session_state["chat_result"] = result
        st.rerun()

    # Results
    result = st.session_state.get("chat_result")
    if result is None:
        return

    if not result.success:
        st.error(result.error)
        if result.sql:
            with st.expander("Generated SQL (failed)", expanded=True):
                st.code(result.sql, language="sql")
        return

    with st.expander("Generated SQL", expanded=False):
        st.code(result.sql, language="sql")

    st.markdown(f"**{result.row_count:,} rows** returned")

    if result.row_count > 0:
        try:
            import pandas as pd
            df = pd.DataFrame(result.rows, columns=result.columns)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Auto bar chart for 2-column numeric results
            if len(result.columns) == 2 and result.row_count > 1:
                try:
                    num_col = result.columns[1]
                    if df[num_col].dtype in ["float64", "int64"]:
                        st.bar_chart(
                            df.set_index(result.columns[0])[num_col],
                            use_container_width=True,
                        )
                except Exception:
                    pass

        except ImportError:
            st.text(" | ".join(result.columns))
            for row in result.rows[:100]:
                st.text(" | ".join(str(v) if v is not None else "NULL" for v in row))
    else:
        st.info("Query returned no results.")

    if result.insight:
        st.divider()
        st.markdown("#### Insight")
        st.info(result.insight)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📊 Insurance DWH")
    st.caption("Conversational BI & Documentation Tool")
    st.divider()

    # API status
    if is_api_key_set():
        st.success("Claude API connected", icon="✅")
    else:
        st.error("Claude API not configured", icon="❌")

    # Query counter
    used = _get_query_count()
    st.progress(
        min(used / DAILY_QUERY_LIMIT, 1.0),
        text=f"Daily queries: {used} / {DAILY_QUERY_LIMIT}",
    )

    st.divider()

    # DB stats
    st.markdown("**Database**")
    try:
        stats = get_table_stats()
        for tname, count in stats.items():
            icon = "📐" if tname.startswith("dim") else "📋"
            st.markdown(
                f"<small>{icon} `{tname}` &nbsp;—&nbsp; **{count:,}**</small>",
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.warning(f"DB error: {e}")

    st.divider()
    st.markdown(
        "<small>"
        "🛠 [GitHub](https://github.com/bgokaytuna/conversational-bi-dwh)"
        " &nbsp;·&nbsp; "
        "[LinkedIn](https://linkedin.com/in/gokaytuna)"
        "</small>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------

tab_chat, tab_schema, tab_lineage, tab_glossary = st.tabs([
    "💬  Chat BI",
    "🗂  Schema Explorer",
    "🔗  Lineage Viewer",
    "📖  Business Glossary",
])

with tab_chat:
    _render_chat_bi()

with tab_schema:
    schema_explorer_mod.render(st)

with tab_lineage:
    lineage_viewer_mod.render(st)

with tab_glossary:
    glossary_mod.render(st)
