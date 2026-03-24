"""
glossary.py
===========
Business Glossary sekmesi — AI destekli terim yönetimi.

Özellikler:
  - Tüm tablo/kolon metadata'sından otomatik terim listesi çıkar
  - Claude ile her terim için iş tanımı üret
  - Manuel terim ekleme / düzenleme
  - Domain ve onay durumuna göre filtreleme
  - CSV ve Markdown export

Veri kalıcılığı: st.session_state (uygulama yeniden başlatılınca sıfırlanır)
Gerçek projede → SQLite tablosuna veya JSON dosyasına yazılabilir.

Public API:
    render(st)   ← app.py'den çağrılır
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field, asdict
from typing import Literal

from schema.metadata import TABLE_METADATA, KPI_DEFINITIONS
from utils.claude_client import ask, ask_streaming, is_api_key_set

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

Status = Literal["draft", "approved", "needs_review"]

@dataclass
class GlossaryTerm:
    term: str
    definition: str
    domain: str          # 'Premium' | 'Claim' | 'Portfolio' | 'Agent' | 'General'
    source: str          # 'column' | 'kpi' | 'manual' | 'ai_generated'
    table_ref: str       # ilgili tablo (varsa)
    status: Status       # 'draft' | 'approved' | 'needs_review'
    owner: str           # sorumlu ekip
    notes: str = ""
    examples: str = ""   # virgülle ayrılmış örnek değerler

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Seed data builder  (metadata'dan otomatik)
# ---------------------------------------------------------------------------

_DOMAIN_MAP = {
    "fact_policy": "Premium",
    "fact_claim":  "Claim",
    "dim_customer":"General",
    "dim_product": "Premium",
    "dim_agent":   "Agent",
    "dim_date":    "General",
}

_IMPORTANT_COLUMNS = {
    # fact_policy
    "gross_premium", "net_premium", "commission_amount",
    "policy_status", "payment_frequency",
    # fact_claim
    "claimed_amount", "paid_amount", "reserve_amount",
    "claim_status", "claim_type", "days_to_close",
    # dim_customer
    "customer_segment", "credit_score", "is_current",
    "valid_from", "valid_to",
    # dim_product
    "product_line", "product_type", "risk_category",
    # dim_agent
    "channel",
}


def _build_seed_terms() -> list[GlossaryTerm]:
    """
    Metadata'dan başlangıç terim listesini üretir.
    Sadece önemli kolonlar + tüm KPI'lar dahil edilir.
    """
    terms: list[GlossaryTerm] = []
    seen: set[str] = set()

    # 1. Önemli kolon terimleri
    for tname, tmeta in TABLE_METADATA.items():
        domain = _DOMAIN_MAP.get(tname, "General")
        for col in tmeta.columns:
            if col.name not in _IMPORTANT_COLUMNS:
                continue
            term_key = col.name.lower()
            if term_key in seen:
                continue
            seen.add(term_key)

            human_name = col.name.replace("_", " ").title()
            examples   = ", ".join(col.example_values) if col.example_values else ""
            terms.append(GlossaryTerm(
                term=human_name,
                definition=col.description,
                domain=domain,
                source="column",
                table_ref=tname,
                status="draft",
                owner=tmeta.owner,
                notes=f"Kaynak kolon: {tname}.{col.name}",
                examples=examples,
            ))

    # 2. KPI terimleri
    for kpi in KPI_DEFINITIONS:
        term_key = kpi.name.lower()
        if term_key in seen:
            continue
        seen.add(term_key)
        terms.append(GlossaryTerm(
            term=kpi.name,
            definition=kpi.business_definition,
            domain=kpi.domain,
            source="kpi",
            table_ref="fact_policy / fact_claim",
            status="draft",
            owner="Actuarial & Finance Team",
            notes=kpi.notes,
            examples=f"SQL: {kpi.sql_expression[:80]}{'...' if len(kpi.sql_expression) > 80 else ''}",
        ))

    return terms


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

_STATE_KEY = "glossary_terms"


def _get_terms(st) -> list[GlossaryTerm]:
    """Session state'ten terim listesini alır, yoksa seed ile başlatır."""
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = _build_seed_terms()
    return st.session_state[_STATE_KEY]


def _save_terms(st, terms: list[GlossaryTerm]) -> None:
    st.session_state[_STATE_KEY] = terms


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

_GLOSSARY_SYSTEM = """
Sen bir sigorta sektörü veri yönetimi uzmanısın (Data Governance Lead).
Sana bir veri terimi ve bağlamı verilecek.

GÖREV:
Bu terim için profesyonel bir business glossary tanımı yaz.

FORMAT (kesinlikle bu sırayla, başka bir şey ekleme):
TANIM: <2-3 cümle, iş odaklı, teknik jargon olmadan>
DOMAIN: <tek kelime: Premium | Claim | Portfolio | Agent | General>
ÖRNEKLER: <3-5 gerçekçi örnek değer, virgülle ayrılmış>
NOT: <varsa önemli bir uyarı veya ilişkili terim, yoksa boş bırak>

Türkçe yaz. Kesinlikle sadece bu 4 satırı döndür, başka açıklama ekleme.
""".strip()


def _parse_ai_response(raw: str) -> dict:
    """AI yanıtını parse eder, dict döner."""
    result = {"definition": "", "domain": "General", "examples": "", "notes": ""}
    for line in raw.strip().splitlines():
        line = line.strip()
        if line.startswith("TANIM:"):
            result["definition"] = line[6:].strip()
        elif line.startswith("DOMAIN:"):
            result["domain"] = line[7:].strip()
        elif line.startswith("ÖRNEKLER:"):
            result["examples"] = line[9:].strip()
        elif line.startswith("NOT:"):
            result["notes"] = line[4:].strip()
    return result


def generate_definition(term: str, context: str = "") -> dict:
    """
    Bir terim için AI tanımı üretir.
    context: tablo adı, kolon bilgisi gibi ek bağlam.
    dict döner: definition, domain, examples, notes.
    """
    user_msg = f"Terim: {term}"
    if context:
        user_msg += f"\nBağlam: {context}"
    raw    = ask(user=user_msg, system=_GLOSSARY_SYSTEM, temperature=0.3)
    return _parse_ai_response(raw)


def bulk_generate(st, terms: list[GlossaryTerm]) -> list[GlossaryTerm]:
    """
    Draft durumundaki terimlerin tümü için AI tanımı üretir.
    Progress bar ile Streamlit'te gösterir.
    """
    drafts   = [t for t in terms if t.status == "draft" and t.source != "kpi"]
    updated  = {t.term: t for t in terms}
    progress = st.progress(0, text="AI tanımları üretiliyor...")

    for i, term in enumerate(drafts):
        context = f"Tablo: {term.table_ref}. Mevcut tanım: {term.definition}"
        parsed  = generate_definition(term.term, context)
        t = updated[term.term]
        if parsed["definition"]:
            t.definition = parsed["definition"]
        if parsed["domain"]:
            t.domain = parsed["domain"]
        if parsed["examples"]:
            t.examples = parsed["examples"]
        if parsed["notes"]:
            t.notes = parsed["notes"]
        t.source = "ai_generated"
        progress.progress((i + 1) / len(drafts), text=f"'{term.term}' işlendi...")

    progress.empty()
    return list(updated.values())


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_csv(terms: list[GlossaryTerm]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "term", "definition", "domain", "source",
        "table_ref", "status", "owner", "notes", "examples"
    ])
    writer.writeheader()
    writer.writerows([t.to_dict() for t in terms])
    return buf.getvalue()


def export_markdown(terms: list[GlossaryTerm]) -> str:
    lines = [
        "# Insurance DWH — Business Glossary\n",
        "_Bu doküman Conversational BI & DWH Dokümantasyon Aracı tarafından üretilmiştir._\n",
    ]
    domains = sorted({t.domain for t in terms})
    for domain in domains:
        lines.append(f"\n## {domain}\n")
        domain_terms = sorted(
            [t for t in terms if t.domain == domain],
            key=lambda x: x.term
        )
        for t in domain_terms:
            status_icon = {"approved": "✅", "draft": "📝", "needs_review": "⚠️"}.get(t.status, "")
            lines.append(f"### {t.term} {status_icon}")
            lines.append(f"{t.definition}\n")
            if t.examples:
                lines.append(f"**Örnekler:** {t.examples}\n")
            if t.notes:
                lines.append(f"**Not:** {t.notes}\n")
            lines.append(f"_Kaynak: {t.table_ref} | Owner: {t.owner}_\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Streamlit render
# ---------------------------------------------------------------------------

def render(st) -> None:
    """
    Business Glossary sekmesini render eder.
    st = import edilmiş streamlit modülü.
    """
    st.header("Business Glossary")
    st.caption(
        "Sigorta DWH terimleri, KPI tanımları ve kolon açıklamaları. "
        "AI ile tanım üret, onayla ve dışa aktar."
    )

    terms = _get_terms(st)

    # ── Üst araç çubuğu ─────────────────────────────────────────────────────
    tool_col1, tool_col2, tool_col3, tool_col4 = st.columns([2, 2, 2, 2])

    with tool_col1:
        domains    = ["Tümü"] + sorted({t.domain for t in terms})
        sel_domain = st.selectbox("Domain", domains, key="gloss_domain")

    with tool_col2:
        statuses    = ["Tümü", "draft", "approved", "needs_review"]
        sel_status  = st.selectbox("Durum", statuses, key="gloss_status")

    with tool_col3:
        search_txt = st.text_input("Terim ara", placeholder="gross premium...", key="gloss_search")

    with tool_col4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("Yeni Terim Ekle", type="secondary", use_container_width=True):
            st.session_state["show_add_form"] = True

    # ── Filtrele ─────────────────────────────────────────────────────────────
    filtered = terms
    if sel_domain != "Tümü":
        filtered = [t for t in filtered if t.domain == sel_domain]
    if sel_status != "Tümü":
        filtered = [t for t in filtered if t.status == sel_status]
    if search_txt:
        q = search_txt.lower()
        filtered = [t for t in filtered if q in t.term.lower() or q in t.definition.lower()]

    # ── Özet metrikler ───────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Terim",  len(terms))
    m2.metric("Onaylanmış",    sum(1 for t in terms if t.status == "approved"))
    m3.metric("Draft",         sum(1 for t in terms if t.status == "draft"))
    m4.metric("İnceleme Bekl.",sum(1 for t in terms if t.status == "needs_review"))

    st.divider()

    # ── AI Bulk Generate ─────────────────────────────────────────────────────
    draft_count = sum(1 for t in terms if t.status == "draft" and t.source != "kpi")
    if draft_count > 0 and is_api_key_set():
        with st.expander(f"AI ile {draft_count} draft terimi otomatik tanımla", expanded=False):
            st.warning(
                f"{draft_count} draft terim için Claude API çağrısı yapılacak. "
                "Bu işlem birkaç dakika sürebilir."
            )
            if st.button("Tümünü Üret", type="primary", key="bulk_gen"):
                updated = bulk_generate(st, terms)
                _save_terms(st, updated)
                st.success("Tüm draft tanımlar üretildi!")
                st.rerun()

    # ── Yeni terim formu ─────────────────────────────────────────────────────
    if st.session_state.get("show_add_form"):
        _render_add_form(st, terms)

    # ── Terim listesi ────────────────────────────────────────────────────────
    st.markdown(f"**{len(filtered)}** terim gösteriliyor")

    for i, term in enumerate(sorted(filtered, key=lambda x: x.term)):
        _render_term_card(st, term, terms, i)

    # ── Export ───────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Dışa Aktar")
    exp_col1, exp_col2 = st.columns(2)

    with exp_col1:
        csv_data = export_csv(terms)
        st.download_button(
            label="CSV olarak indir",
            data=csv_data,
            file_name="insurance_dwh_glossary.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with exp_col2:
        md_data = export_markdown(terms)
        st.download_button(
            label="Markdown olarak indir",
            data=md_data,
            file_name="insurance_dwh_glossary.md",
            mime="text/markdown",
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Private render helpers
# ---------------------------------------------------------------------------

def _render_term_card(st, term: GlossaryTerm, all_terms: list[GlossaryTerm], idx: int) -> None:
    """Tek bir terim kartını render eder."""
    status_icons = {"approved": "✅", "draft": "📝", "needs_review": "⚠️"}
    source_icons = {"column": "🗂️", "kpi": "📊", "manual": "✏️", "ai_generated": "🤖"}

    icon   = status_icons.get(term.status, "")
    src    = source_icons.get(term.source, "")
    header = f"{icon} **{term.term}** {src} `{term.domain}`"

    with st.expander(header, expanded=False):
        st.markdown(f"**Tanım:** {term.definition}")

        detail_col1, detail_col2 = st.columns(2)
        with detail_col1:
            st.markdown(f"**Tablo:** `{term.table_ref}`")
            st.markdown(f"**Owner:** {term.owner}")
        with detail_col2:
            st.markdown(f"**Kaynak:** {term.source}")
            if term.examples:
                st.markdown(f"**Örnekler:** {term.examples}")

        if term.notes:
            st.caption(f"💡 {term.notes}")

        # Aksiyon butonları
        btn_col1, btn_col2, btn_col3 = st.columns(3)

        with btn_col1:
            if term.status != "approved":
                if st.button("Onayla", key=f"approve_{idx}", type="primary"):
                    term.status = "approved"
                    _save_terms(st, all_terms)
                    st.rerun()
            else:
                if st.button("Onayı Kaldır", key=f"unapprove_{idx}"):
                    term.status = "needs_review"
                    _save_terms(st, all_terms)
                    st.rerun()

        with btn_col2:
            if is_api_key_set():
                if st.button("AI ile Yenile", key=f"regen_{idx}"):
                    with st.spinner("Claude tanım üretiyor..."):
                        ctx    = f"Tablo: {term.table_ref}. Mevcut: {term.definition}"
                        parsed = generate_definition(term.term, ctx)
                    if parsed["definition"]:
                        term.definition = parsed["definition"]
                        term.domain     = parsed.get("domain", term.domain)
                        term.examples   = parsed.get("examples", term.examples)
                        term.notes      = parsed.get("notes", term.notes)
                        term.source     = "ai_generated"
                        term.status     = "needs_review"
                        _save_terms(st, all_terms)
                        st.rerun()

        with btn_col3:
            if st.button("Sil", key=f"delete_{idx}"):
                updated = [t for t in all_terms if t.term != term.term]
                _save_terms(st, updated)
                st.rerun()


def _render_add_form(st, terms: list[GlossaryTerm]) -> None:
    """Yeni terim ekleme formunu render eder."""
    with st.form("add_term_form"):
        st.subheader("Yeni Terim Ekle")
        f_col1, f_col2 = st.columns(2)

        with f_col1:
            new_term   = st.text_input("Terim *", placeholder="Gross Written Premium")
            new_table  = st.selectbox("İlgili Tablo", ["—"] + list(TABLE_METADATA.keys()))
            new_domain = st.selectbox("Domain", ["Premium", "Claim", "Portfolio", "Agent", "General"])

        with f_col2:
            new_def    = st.text_area("Tanım", placeholder="Terimin iş tanımını buraya yaz...")
            new_owner  = st.text_input("Owner", placeholder="Data Platform Team")
            new_status = st.selectbox("Durum", ["draft", "needs_review", "approved"])

        new_notes    = st.text_input("Not (opsiyonel)")
        new_examples = st.text_input("Örnek Değerler (virgülle ayır)")
        use_ai       = st.checkbox("Tanımı Claude ile üret", value=not bool(new_def))

        submitted = st.form_submit_button("Ekle", type="primary")
        cancel    = st.form_submit_button("İptal")

        if cancel:
            st.session_state["show_add_form"] = False
            st.rerun()

        if submitted and new_term:
            definition = new_def
            domain     = new_domain
            examples   = new_examples
            notes      = new_notes

            if use_ai and is_api_key_set():
                with st.spinner("Claude tanım üretiyor..."):
                    ctx    = f"Tablo: {new_table}" if new_table != "—" else ""
                    parsed = generate_definition(new_term, ctx)
                if parsed["definition"]:
                    definition = parsed["definition"]
                    domain     = parsed.get("domain", domain)
                    examples   = parsed.get("examples", examples)
                    notes      = parsed.get("notes", notes)

            new_entry = GlossaryTerm(
                term=new_term,
                definition=definition or "Tanım girilmedi.",
                domain=domain,
                source="manual" if not use_ai else "ai_generated",
                table_ref=new_table if new_table != "—" else "—",
                status=new_status,
                owner=new_owner or "—",
                notes=notes,
                examples=examples,
            )
            terms.append(new_entry)
            _save_terms(st, terms)
            st.session_state["show_add_form"] = False
            st.success(f"'{new_term}' glossary'ye eklendi.")
            st.rerun()
