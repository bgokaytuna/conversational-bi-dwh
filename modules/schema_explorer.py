"""
schema_explorer.py
==================
Schema Explorer sekmesi için veri ve render fonksiyonları.

Streamlit'te şunu gösterir:
  - Tablo listesi (layer, grain, SCD badge'i)
  - Seçilen tablonun kolon detayları (PK/FK badge, tip, açıklama, örnek değerler)
  - KPI tanımları (domain filtrelenebilir)
  - Claude ile "bu tabloyu açıkla" sorusu (AI Explain butonu)

Public API:
    render(st)   ← app.py'den çağrılır, st = streamlit modülü
"""

from dataclasses import dataclass
from schema.metadata import (
    TABLE_METADATA,
    KPI_DEFINITIONS,
    TableMeta,
    ColumnMeta,
    KPIDefinition,
)
from utils.claude_client import ask, is_api_key_set

# ---------------------------------------------------------------------------
# Badge helpers (Streamlit markdown için)
# ---------------------------------------------------------------------------

_SCD_COLORS = {
    "SCD0": "🔵",
    "SCD1": "🟡",
    "SCD2": "🟠",
}
_LAYER_COLORS = {
    "Dimension": "🟣",
    "Fact":      "🟢",
}

def _scd_badge(scd: str | None) -> str:
    if not scd:
        return ""
    icon = _SCD_COLORS.get(scd, "⚪")
    return f"{icon} `{scd}`"

def _layer_badge(layer: str) -> str:
    icon = _LAYER_COLORS.get(layer, "⚪")
    return f"{icon} {layer}"


# ---------------------------------------------------------------------------
# AI Explain
# ---------------------------------------------------------------------------

_EXPLAIN_SYSTEM = """
Sen bir Insurance DWH mimarısın.
Sana bir DWH tablosunun metadata'sı verilecek.
Tabloyu bir iş analistine açıklar gibi, teknik olmayan ama bilgilendirici bir dille
3-4 paragrafta açıkla:
  1. Bu tablo ne işe yarıyor? Hangi iş sorularını cevaplıyor?
  2. Grain'i ne anlama geliyor — bir satır tam olarak neyi temsil ediyor?
  3. Dikkat edilmesi gereken önemli kolonlar veya SCD mantığı var mı?
  4. Hangi tablolarla birlikte kullanılır?
Türkçe yaz. Teknik jargonu minimumda tut.
""".strip()


def explain_table_with_ai(table_name: str) -> str:
    """Seçilen tablo için Claude'dan açıklama üretir."""
    if not is_api_key_set():
        return "⚠️ API key bulunamadı. Lütfen ANTHROPIC_API_KEY ortam değişkenini ayarlayın."

    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return f"'{table_name}' tablosu metadata'da bulunamadı."

    col_lines = "\n".join(
        f"  - {c.name} ({c.data_type})"
        + (" [PK]" if c.is_pk else "")
        + (f" → {c.fk_target}" if c.is_fk else "")
        + f": {c.description}"
        for c in meta.columns
    )
    user_msg = (
        f"Tablo: {meta.name}\n"
        f"Layer: {meta.layer}\n"
        f"Grain: {meta.grain}\n"
        f"SCD: {meta.scd_type or 'Yok'}\n"
        f"Açıklama: {meta.business_description}\n"
        f"Kolonlar:\n{col_lines}"
    )
    return ask(user=user_msg, system=_EXPLAIN_SYSTEM, temperature=0.3)


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------

def render(st) -> None:
    """
    Schema Explorer sekmesini render eder.
    st = import edilmiş streamlit modülü.
    """
    st.header("Schema Explorer")
    st.caption("Insurance DWH tablolarını, kolonlarını ve KPI tanımlarını keşfet.")

    tab_tables, tab_kpis = st.tabs(["Tablolar & Kolonlar", "KPI Tanımları"])

    # ── TAB 1: Tablolar ──────────────────────────────────────────────────────
    with tab_tables:
        col_left, col_right = st.columns([1, 2])

        with col_left:
            st.subheader("Tablolar")
            table_names = list(TABLE_METADATA.keys())

            # Tablo kartları
            selected_table = st.session_state.get("selected_table", table_names[0])
            for tname in table_names:
                meta = TABLE_METADATA[tname]
                is_selected = tname == selected_table
                border_color = "#7F77DD" if is_selected else "#e0e0e0"

                with st.container():
                    if st.button(
                        f"{_layer_badge(meta.layer)}  **{tname}**\n\n"
                        f"{_scd_badge(meta.scd_type)}",
                        key=f"btn_{tname}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary",
                    ):
                        st.session_state["selected_table"] = tname
                        selected_table = tname
                        st.rerun()

        with col_right:
            meta: TableMeta = TABLE_METADATA[selected_table]
            _render_table_detail(st, meta)

    # ── TAB 2: KPIs ─────────────────────────────────────────────────────────
    with tab_kpis:
        _render_kpi_panel(st)


# ---------------------------------------------------------------------------
# Private render helpers
# ---------------------------------------------------------------------------

def _render_table_detail(st, meta: TableMeta) -> None:
    """Seçilen tablonun detay panelini render eder."""

    # Başlık ve meta bilgiler
    st.subheader(f"`{meta.name}`")

    info_col1, info_col2, info_col3 = st.columns(3)
    with info_col1:
        st.metric("Layer", meta.layer)
    with info_col2:
        st.metric("SCD Tipi", meta.scd_type or "—")
    with info_col3:
        st.metric("Kolon Sayısı", len(meta.columns))

    st.markdown(f"**Grain:** {meta.grain}")
    st.markdown(f"**Açıklama:** {meta.business_description}")
    st.markdown(f"**Owner:** `{meta.owner}`")

    if meta.tags:
        tags_str = "  ".join(f"`{t}`" for t in meta.tags)
        st.markdown(f"**Tags:** {tags_str}")

    st.divider()

    # Kolon tablosu
    st.markdown("#### Kolonlar")
    col_data = []
    for col in meta.columns:
        badges = []
        if col.is_pk:
            badges.append("🔑 PK")
        if col.is_fk:
            badges.append(f"🔗 FK → {col.fk_target}")
        nullable = "NULL" if col.is_nullable else "NOT NULL"
        examples = ", ".join(col.example_values) if col.example_values else "—"
        col_data.append({
            "Kolon": col.name,
            "Tip": col.data_type,
            "Badge": " | ".join(badges) if badges else "—",
            "Nullable": nullable,
            "Açıklama": col.description,
            "Örnek Değerler": examples,
        })

    # Streamlit dataframe
    try:
        import pandas as pd
        df = pd.DataFrame(col_data)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Kolon":          st.column_config.TextColumn(width="medium"),
                "Tip":            st.column_config.TextColumn(width="small"),
                "Badge":          st.column_config.TextColumn(width="medium"),
                "Nullable":       st.column_config.TextColumn(width="small"),
                "Açıklama":       st.column_config.TextColumn(width="large"),
                "Örnek Değerler": st.column_config.TextColumn(width="medium"),
            },
        )
    except ImportError:
        # pandas yoksa basit tablo
        for row in col_data:
            st.markdown(
                f"**{row['Kolon']}** `{row['Tip']}` {row['Badge']} — {row['Açıklama']}"
            )

    st.divider()

    # AI Explain butonu
    st.markdown("#### AI Açıklaması")
    if not is_api_key_set():
        st.warning("API key ayarlanmadığında AI açıklaması kullanılamaz.")
    else:
        explain_key = f"explain_{meta.name}"
        if st.button(
            f"Claude ile `{meta.name}` tablosunu açıkla",
            key=explain_key,
            type="primary",
        ):
            with st.spinner("Claude açıklama üretiyor..."):
                explanation = explain_table_with_ai(meta.name)
            st.session_state[f"explanation_{meta.name}"] = explanation

        saved = st.session_state.get(f"explanation_{meta.name}")
        if saved:
            st.info(saved)


def _render_kpi_panel(st) -> None:
    """KPI tanımları panelini render eder."""
    st.subheader("KPI Tanımları")

    # Domain filtresi
    domains = sorted({kpi.domain for kpi in KPI_DEFINITIONS})
    selected_domain = st.selectbox(
        "Domain filtrele",
        options=["Tümü"] + domains,
        index=0,
        key="kpi_domain_filter",
    )

    filtered: list[KPIDefinition] = [
        k for k in KPI_DEFINITIONS
        if selected_domain == "Tümü" or k.domain == selected_domain
    ]

    st.caption(f"{len(filtered)} KPI gösteriliyor")

    for kpi in filtered:
        with st.expander(f"**{kpi.name}** — `{kpi.unit}` ({kpi.domain})"):
            st.markdown(f"**İş Tanımı:** {kpi.business_definition}")
            st.code(kpi.sql_expression, language="sql")
            if kpi.notes:
                st.caption(f"💡 {kpi.notes}")
