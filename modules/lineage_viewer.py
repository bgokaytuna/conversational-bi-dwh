"""
lineage_viewer.py
=================
Lineage Viewer sekmesi — tablo bağımlılıklarını interaktif graf olarak gösterir.

Kütüphane tercihi: pyvis (NetworkX + vis.js wrapper)
  pip install pyvis

Streamlit entegrasyonu: pyvis HTML çıktısı → st.components.v1.html()

Görsel tasarım:
  - Dimension tablolar  → mor (purple)
  - Fact tablolar        → yeşil (green)
  - Kenar kalınlığı      → ilişki tipine göre (1:N kalın, 1:1 ince)
  - Hover               → ilişki açıklaması tooltip olarak

Public API:
    render(st)   ← app.py'den çağrılır
"""

from schema.metadata import TABLE_METADATA, LINEAGE, LineageEdge

# ---------------------------------------------------------------------------
# Renk & boyut sabitleri
# ---------------------------------------------------------------------------

_NODE_COLORS = {
    "Dimension": {"background": "#EEEDFE", "border": "#534AB7", "font": "#3C3489"},
    "Fact":      {"background": "#EAF3DE", "border": "#3B6D11", "font": "#27500A"},
}
_EDGE_WIDTH = {"1:N": 3, "N:1": 3, "1:1": 1.5}
_EDGE_COLOR = "#888780"

# ---------------------------------------------------------------------------
# Pyvis graf oluşturucu
# ---------------------------------------------------------------------------

def _build_graph_html(highlight_table: str | None = None) -> str:
    """
    pyvis Network nesnesi oluşturur, HTML string olarak döner.
    highlight_table seçiliyse o düğüm ve bağlı kenarlar vurgulanır.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        return "<p style='color:red'>pyvis kurulu değil: <code>pip install pyvis</code></p>"

    net = Network(
        height="520px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#2C2C2A",
        directed=True,
    )
    net.set_options("""
    {
      "nodes": {
        "shape": "box",
        "borderWidth": 2,
        "borderWidthSelected": 3,
        "font": { "size": 14, "face": "monospace" },
        "shadow": false
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.8 } },
        "smooth": { "type": "cubicBezier", "forceDirection": "horizontal" },
        "shadow": false
      },
      "physics": {
        "enabled": true,
        "hierarchicalRepulsion": {
          "centralGravity": 0.1,
          "springLength": 160,
          "springConstant": 0.01,
          "nodeDistance": 200
        },
        "solver": "hierarchicalRepulsion",
        "stabilization": { "iterations": 150 }
      },
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "LR",
          "sortMethod": "directed",
          "levelSeparation": 220,
          "nodeSpacing": 110
        }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true,
        "keyboard": false
      }
    }
    """)

    # Düğümler
    for tname, tmeta in TABLE_METADATA.items():
        colors    = _NODE_COLORS.get(tmeta.layer, _NODE_COLORS["Dimension"])
        is_hi     = highlight_table and tname == highlight_table
        size      = 28 if is_hi else 22
        border_w  = 4  if is_hi else 2

        tooltip = (
            f"<b>{tname}</b><br>"
            f"Layer: {tmeta.layer}<br>"
            f"Grain: {tmeta.grain}<br>"
            f"SCD: {tmeta.scd_type or '—'}<br>"
            f"Owner: {tmeta.owner}"
        )
        net.add_node(
            tname,
            label=tname,
            title=tooltip,
            color={
                "background": colors["background"],
                "border":     colors["border"],
                "highlight": {
                    "background": colors["border"],
                    "border":     colors["border"],
                },
            },
            font={"color": colors["font"], "size": size},
            borderWidth=border_w,
            size=size,
        )

    # Kenarlar
    for edge in LINEAGE:
        is_hi   = highlight_table and (
            edge.source_table == highlight_table
            or edge.target_table == highlight_table
        )
        width   = _EDGE_WIDTH.get(edge.relationship, 2) * (1.8 if is_hi else 1.0)
        color   = _NODE_COLORS["Fact"]["border"] if is_hi else _EDGE_COLOR

        tooltip = (
            f"<b>{edge.source_table} → {edge.target_table}</b><br>"
            f"Key: {edge.join_key}<br>"
            f"Cardinality: {edge.relationship}<br>"
            f"{edge.description}"
        )
        net.add_edge(
            edge.source_table,
            edge.target_table,
            title=tooltip,
            label=edge.relationship,
            width=width,
            color=color,
            font={"size": 10, "color": "#5F5E5A"},
        )

    # HTML string
    return net.generate_html(notebook=False)


# ---------------------------------------------------------------------------
# Fallback: Statik SVG (pyvis yoksa)
# ---------------------------------------------------------------------------

def _static_lineage_table(st) -> None:
    """pyvis yoksa basit tablo olarak lineage gösterir."""
    import pandas as pd

    st.info("pyvis kurulu olmadığı için statik tablo gösteriliyor. `pip install pyvis` ile interaktif grafa geçebilirsin.")
    rows = [
        {
            "Kaynak": e.source_table,
            "Hedef": e.target_table,
            "Join Key": e.join_key,
            "Kardinalite": e.relationship,
            "Açıklama": e.description,
        }
        for e in LINEAGE
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------

def render(st) -> None:
    """
    Lineage Viewer sekmesini render eder.
    st = import edilmiş streamlit modülü.
    """
    st.header("Lineage Viewer")
    st.caption(
        "Tablolar arası ilişkileri ve veri akışını gösteren interaktif bağımlılık grafı. "
        "Düğümlere tıklayarak detay görebilirsin."
    )

    # Filtre + legend satırı
    filter_col, legend_col = st.columns([2, 3])

    with filter_col:
        table_options = ["Tümü"] + list(TABLE_METADATA.keys())
        selected = st.selectbox(
            "Tablo vurgula",
            options=table_options,
            index=0,
            key="lineage_highlight",
        )
        highlight = None if selected == "Tümü" else selected

    with legend_col:
        st.markdown(
            "<div style='padding-top:28px; font-size:13px; color:#5F5E5A'>"
            "<span style='background:#EEEDFE; border:2px solid #534AB7; "
            "padding:2px 10px; border-radius:4px; margin-right:8px;'>Dimension</span>"
            "<span style='background:#EAF3DE; border:2px solid #3B6D11; "
            "padding:2px 10px; border-radius:4px;'>Fact</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    # Graf veya fallback
    try:
        from pyvis.network import Network   # noqa — import testi
        html_content = _build_graph_html(highlight_table=highlight)
        import streamlit.components.v1 as components
        components.html(html_content, height=540, scrolling=False)
    except ImportError:
        _static_lineage_table(st)

    st.divider()

    # Detay tablosu — seçili tablo varsa filtrele
    st.subheader("İlişki Detayları")

    filtered_edges: list[LineageEdge] = (
        [e for e in LINEAGE if e.source_table == highlight or e.target_table == highlight]
        if highlight
        else LINEAGE
    )

    for edge in filtered_edges:
        src_layer = TABLE_METADATA[edge.source_table].layer
        tgt_layer = TABLE_METADATA[edge.target_table].layer
        src_icon  = "🟣" if src_layer == "Dimension" else "🟢"
        tgt_icon  = "🟣" if tgt_layer == "Dimension" else "🟢"

        with st.expander(
            f"{src_icon} `{edge.source_table}` → {tgt_icon} `{edge.target_table}`  "
            f"**{edge.relationship}**"
        ):
            st.markdown(f"**Join Key:** `{edge.join_key}`")
            st.markdown(f"**Kardinalite:** `{edge.relationship}`")
            st.markdown(f"**Açıklama:** {edge.description}")

            # İlgili kolon bilgisi — FK'lar hedef tabloda değil, fact tarafında olur
            # fact_policy.customer_sk -> dim_customer.customer_sk gibi
            fact_meta = TABLE_METADATA.get(edge.target_table)
            src_meta  = TABLE_METADATA[edge.source_table]
            search_meta = fact_meta if fact_meta and fact_meta.layer == "Fact" else src_meta
            fk_cols  = [c for c in search_meta.columns if c.fk_target and
                        edge.source_table in (c.fk_target or "")]
            if fk_cols:
                st.markdown("**İlgili FK Kolonlar:**")
                for c in fk_cols:
                    st.markdown(f"  - `{c.name}` → `{c.fk_target}`: {c.description}")
