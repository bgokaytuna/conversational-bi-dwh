"""
app.py
======
Conversational BI & DWH Documentation Tool - Main App

Çalıştırmak için:
    streamlit run app.py

Ortam değişkeni:
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import os
import sys
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Sayfa konfigürasyonu — ilk st komutu olmalı
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Insurance DWH Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Modül importları
# ---------------------------------------------------------------------------

from schema.dwh_schema import get_table_stats
from utils.claude_client import is_api_key_set
import modules.chat_bi as chat_bi_mod
import modules.schema_explorer as schema_explorer_mod
import modules.lineage_viewer as lineage_viewer_mod
import modules.glossary as glossary_mod

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
# Chat BI render — tab bloğundan ÖNCE tanımla
# ---------------------------------------------------------------------------

def _render_chat_bi() -> None:
    st.header("Chat BI")
    st.caption("Doğal dille soru sor, SQL otomatik üretilsin ve çalıştırılsın.")

    if not is_api_key_set():
        st.warning("Chat BI için Claude API key gerekli. Sol panelden gir.")
        return

    # Örnek sorular
    with st.expander("Örnek Sorular", expanded=False):
        cols = st.columns(2)
        for i, q in enumerate(chat_bi_mod.SAMPLE_QUESTIONS):
            with cols[i % 2]:
                if st.button(q, key=f"sample_{i}", use_container_width=True):
                    st.session_state["chat_question"] = q
                    st.rerun()

    # Soru input
    question = st.text_input(
        "Sorunuzu yazın",
        value=st.session_state.get("chat_question", ""),
        placeholder="2023 yılında ürün bazında toplam brüt prim nedir?",
        key="chat_input",
    )

    col_ask, col_clear = st.columns([1, 5])
    with col_ask:
        ask_clicked = st.button("Sor", type="primary", use_container_width=True)
    with col_clear:
        if st.button("Temizle"):
            for key in ["chat_question", "chat_result"]:
                st.session_state.pop(key, None)
            st.rerun()

    # Soru gönder
    if ask_clicked and question.strip():
        st.session_state["chat_question"] = question
        with st.spinner("SQL üretiliyor ve çalıştırılıyor..."):
            result = chat_bi_mod.run_and_explain(question)
        st.session_state["chat_result"] = result
        st.rerun()

    # Sonuç göster
    result = st.session_state.get("chat_result")
    if result is None:
        return

    if not result.success:
        st.error(result.error)
        if result.sql:
            with st.expander("Üretilen SQL (hatalı)", expanded=True):
                st.code(result.sql, language="sql")
        return

    # Üretilen SQL
    with st.expander("Üretilen SQL", expanded=False):
        st.code(result.sql, language="sql")

    # Sonuç tablosu
    st.markdown(f"**{result.row_count:,} satır** döndü")

    if result.row_count > 0:
        try:
            import pandas as pd
            df = pd.DataFrame(result.rows, columns=result.columns)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # 2 kolonlu sayısal sonuçlarda otomatik bar chart
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
        st.info("Sorgu sonuç döndürmedi.")

    # Insight
    if result.insight:
        st.divider()
        st.markdown("#### Insight")
        st.info(result.insight)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📊 Insurance DWH")
    st.caption("Conversational BI & Dokümantasyon")
    st.divider()

    if is_api_key_set():
        st.success("Claude API bağlı", icon="✅")
    else:
        st.error("Claude API bağlı değil", icon="❌")
        api_input = st.text_input(
            "API Key",
            type="password",
            placeholder="sk-ant-...",
            help="console.anthropic.com adresinden alabilirsin.",
        )
        if api_input:
            os.environ["ANTHROPIC_API_KEY"] = api_input.strip()
            st.rerun()

    st.divider()

    st.markdown("**Veritabanı**")
    try:
        stats = get_table_stats()
        for tname, count in stats.items():
            icon = "📐" if tname.startswith("dim") else "📋"
            st.markdown(
                f"<small>{icon} `{tname}` &nbsp;—&nbsp; **{count:,}**</small>",
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.warning(f"DB hatası: {e}")

    st.divider()
    st.markdown(
        "<small>🛠 [GitHub](https://github.com/bgokaytuna) &nbsp;·&nbsp; "
        "[LinkedIn](https://linkedin.com/in/gokaytuna)</small>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Ana sekmeler
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
