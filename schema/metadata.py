"""
metadata.py
===========
DWH Metadata Katmanı

Bu modül iki amaca hizmet eder:
1. Claude API'ye gönderilecek schema context'ini üretir (NL→SQL için)
2. Streamlit UI'da Schema Explorer & Glossary sekmelerinin veri kaynağıdır.

Yapı
----
TABLE_METADATA  : dict[table_name, TableMeta]
KPI_DEFINITIONS : list[KPIDefinition]
LINEAGE         : list[LineageEdge]
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ColumnMeta:
    name: str
    data_type: str
    description: str
    is_pk: bool = False
    is_fk: bool = False
    fk_target: Optional[str] = None    # "table.column"
    is_nullable: bool = True
    example_values: list[str] = field(default_factory=list)


@dataclass
class TableMeta:
    name: str
    layer: str          # 'Dimension' | 'Fact'
    grain: str          # İnsan okunabilir grain tanımı
    scd_type: Optional[str]   # 'SCD0' | 'SCD1' | 'SCD2' | None
    business_description: str
    owner: str          # Sorumlu ekip
    columns: list[ColumnMeta] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class KPIDefinition:
    name: str
    business_definition: str
    sql_expression: str
    unit: str
    domain: str         # 'Premium' | 'Claim' | 'Portfolio' | 'Agent'
    notes: str = ""


@dataclass
class LineageEdge:
    source_table: str
    target_table: str
    join_key: str
    relationship: str   # '1:N' | 'N:1' | '1:1'
    description: str


# ---------------------------------------------------------------------------
# TABLE_METADATA
# ---------------------------------------------------------------------------

TABLE_METADATA: dict[str, TableMeta] = {

    "dim_date": TableMeta(
        name="dim_date",
        layer="Dimension",
        grain="1 satır = 1 takvim günü (2021-01-01 → 2024-12-31)",
        scd_type="SCD0",
        business_description=(
            "Zaman boyutu. Tüm fact tablolarındaki tarih anahtarlarının "
            "join edildiği merkezi tarih referansıdır. YYYYMMDD integer formatında "
            "date_key primary key olarak kullanılır."
        ),
        owner="Data Platform Team",
        tags=["time", "calendar", "reference"],
        columns=[
            ColumnMeta("date_key",     "INTEGER", "YYYYMMDD formatında tarih anahtarı (PK)", is_pk=True, is_nullable=False,
                       example_values=["20220101", "20231231"]),
            ColumnMeta("full_date",    "TEXT",    "ISO 8601 tarih (YYYY-MM-DD)", is_nullable=False),
            ColumnMeta("year",         "INTEGER", "Yıl", is_nullable=False, example_values=["2022","2023","2024"]),
            ColumnMeta("quarter",      "INTEGER", "Çeyrek (1-4)", is_nullable=False, example_values=["1","2","3","4"]),
            ColumnMeta("month",        "INTEGER", "Ay numarası (1-12)", is_nullable=False),
            ColumnMeta("month_name",   "TEXT",    "Ay adı (Türkçe)", is_nullable=False, example_values=["Ocak","Haziran","Aralık"]),
            ColumnMeta("week_of_year", "INTEGER", "ISO hafta numarası"),
            ColumnMeta("day_of_week",  "TEXT",    "Haftanın günü (İngilizce)", example_values=["Monday","Friday"]),
            ColumnMeta("is_weekend",   "INTEGER", "0=Hafta içi, 1=Hafta sonu"),
        ]
    ),

    "dim_customer": TableMeta(
        name="dim_customer",
        layer="Dimension",
        grain="1 satır = 1 müşteri x 1 geçerlilik süreci (SCD2 versiyonu)",
        scd_type="SCD2",
        business_description=(
            "Müşteri boyutu. SCD Type 2 uygulanmıştır: müşterinin şehri veya "
            "segmenti değiştiğinde yeni bir surrogate key ile yeni satır açılır, "
            "eski satırın valid_to doldurulur. is_current=1 olan satır güncel "
            "kaydı temsil eder. customer_nk (doğal anahtar) tüm versiyonlarda aynıdır."
        ),
        owner="CRM & Analytics Team",
        tags=["customer", "scd2", "crm", "segmentation"],
        columns=[
            ColumnMeta("customer_sk",      "INTEGER", "Surrogate key (PK)", is_pk=True, is_nullable=False),
            ColumnMeta("customer_nk",      "TEXT",    "Doğal anahtar — kaynak sistemden gelen müşteri ID", is_nullable=False,
                       example_values=["CST-00001","CST-00120"]),
            ColumnMeta("first_name",       "TEXT",    "Ad"),
            ColumnMeta("last_name",        "TEXT",    "Soyad"),
            ColumnMeta("gender",           "TEXT",    "Cinsiyet (M/F)",        example_values=["M","F"]),
            ColumnMeta("birth_date",       "TEXT",    "Doğum tarihi (ISO 8601)"),
            ColumnMeta("city",             "TEXT",    "İkamet şehri",          example_values=["İstanbul","Ankara","İzmir"]),
            ColumnMeta("region",           "TEXT",    "Coğrafi bölge",         example_values=["Marmara","Ege","Akdeniz"]),
            ColumnMeta("country",          "TEXT",    "Ülke kodu (varsayılan TR)"),
            ColumnMeta("customer_segment", "TEXT",    "Müşteri segmenti",      example_values=["Individual","Corporate","SME"]),
            ColumnMeta("credit_score",     "INTEGER", "Kredi skoru (500-900)"),
            ColumnMeta("is_current",       "INTEGER", "1=Güncel kayıt, 0=Tarihsel", is_nullable=False),
            ColumnMeta("valid_from",       "TEXT",    "Kaydın geçerlilik başlangıcı (SCD2)", is_nullable=False),
            ColumnMeta("valid_to",         "TEXT",    "Kaydın geçerlilik bitişi — NULL ise hâlâ geçerli (SCD2)"),
            ColumnMeta("dw_insert_date",   "TEXT",    "DWH'a yüklenme tarihi"),
        ]
    ),

    "dim_product": TableMeta(
        name="dim_product",
        layer="Dimension",
        grain="1 satır = 1 sigorta ürünü",
        scd_type="SCD1",
        business_description=(
            "Sigorta ürün boyutu. SCD Type 1: ürün bilgisi değiştiğinde "
            "doğrudan güncellenir, tarihsel versiyon tutulmaz. "
            "Ürünler Life / Non-Life / Health satırlarına ayrılmıştır."
        ),
        owner="Product Management",
        tags=["product", "insurance", "scd1"],
        columns=[
            ColumnMeta("product_sk",    "INTEGER", "Surrogate key (PK)", is_pk=True, is_nullable=False),
            ColumnMeta("product_nk",    "TEXT",    "Ürün doğal anahtarı", is_nullable=False, example_values=["PRD-001","PRD-007"]),
            ColumnMeta("product_name",  "TEXT",    "Ürün adı",            example_values=["Kasko","Sağlık Sigortası"]),
            ColumnMeta("product_line",  "TEXT",    "Ürün hattı",          example_values=["Life","Non-Life","Health"]),
            ColumnMeta("product_type",  "TEXT",    "Ürün tipi",           example_values=["Motor","Home","Health","Travel"]),
            ColumnMeta("coverage_type", "TEXT",    "Teminat türü",        example_values=["Comprehensive","Third-Party Liability"]),
            ColumnMeta("base_premium",  "REAL",    "Yıllık baz prim (TRY)"),
            ColumnMeta("risk_category", "TEXT",    "Risk kategorisi",     example_values=["Low","Medium","High"]),
            ColumnMeta("is_active",     "INTEGER", "1=Aktif ürün"),
        ]
    ),

    "dim_agent": TableMeta(
        name="dim_agent",
        layer="Dimension",
        grain="1 satır = 1 acente / satış kanalı",
        scd_type="SCD1",
        business_description=(
            "Acente ve dağıtım kanalı boyutu. SCD Type 1. "
            "Channel alanı dört ana dağıtım kanalını temsil eder: "
            "Direct, Broker, Bancassurance, Digital."
        ),
        owner="Sales & Distribution Team",
        tags=["agent", "channel", "distribution"],
        columns=[
            ColumnMeta("agent_sk",    "INTEGER", "Surrogate key (PK)", is_pk=True, is_nullable=False),
            ColumnMeta("agent_nk",    "TEXT",    "Acente doğal anahtarı", is_nullable=False),
            ColumnMeta("agent_name",  "TEXT",    "Acente temsilci adı"),
            ColumnMeta("agency_name", "TEXT",    "Acente şirket adı"),
            ColumnMeta("region",      "TEXT",    "Acente bölgesi"),
            ColumnMeta("channel",     "TEXT",    "Dağıtım kanalı",   example_values=["Direct","Broker","Bancassurance","Digital"]),
            ColumnMeta("is_active",   "INTEGER", "1=Aktif acente"),
        ]
    ),

    "fact_policy": TableMeta(
        name="fact_policy",
        layer="Fact",
        grain="1 satır = 1 poliçe x 1 aylık snapshot (snapshot_date_key)",
        scd_type=None,
        business_description=(
            "Poliçe olgu tablosu. Her aktif poliçe için her ay bir snapshot satırı "
            "üretilir. Bu yapı aylık prim geliri, portföy büyüklüğü ve poliçe durumu "
            "analizine olanak tanır. policy_nk poliçenin doğal anahtarıdır."
        ),
        owner="Actuarial & Finance Team",
        tags=["policy", "premium", "portfolio", "monthly-snapshot"],
        columns=[
            ColumnMeta("policy_sk",         "INTEGER", "Surrogate key (PK)", is_pk=True, is_nullable=False),
            ColumnMeta("policy_nk",         "TEXT",    "Poliçe numarası (doğal anahtar)", is_nullable=False),
            ColumnMeta("customer_sk",       "INTEGER", "Müşteri FK → dim_customer", is_fk=True, fk_target="dim_customer.customer_sk"),
            ColumnMeta("product_sk",        "INTEGER", "Ürün FK → dim_product",    is_fk=True, fk_target="dim_product.product_sk"),
            ColumnMeta("agent_sk",          "INTEGER", "Acente FK → dim_agent",    is_fk=True, fk_target="dim_agent.agent_sk"),
            ColumnMeta("start_date_key",    "INTEGER", "Poliçe başlangıç tarihi FK → dim_date", is_fk=True, fk_target="dim_date.date_key"),
            ColumnMeta("end_date_key",      "INTEGER", "Poliçe bitiş tarihi FK → dim_date",     is_fk=True, fk_target="dim_date.date_key"),
            ColumnMeta("snapshot_date_key", "INTEGER", "Snapshot ayı FK → dim_date",             is_fk=True, fk_target="dim_date.date_key"),
            ColumnMeta("gross_premium",     "REAL",    "Brüt prim (TRY) — tüm vergiler dahil"),
            ColumnMeta("net_premium",       "REAL",    "Net prim (TRY) — komisyon düşülmüş"),
            ColumnMeta("commission_amount", "REAL",    "Acente komisyon tutarı (TRY)"),
            ColumnMeta("policy_count",      "INTEGER", "Poliçe adedi (her zaman 1 — aggregation için)"),
            ColumnMeta("policy_status",     "TEXT",    "Poliçe durumu", example_values=["Active","Cancelled","Expired","Renewed"]),
            ColumnMeta("payment_frequency", "TEXT",    "Ödeme periyodu", example_values=["Annual","Quarterly","Monthly"]),
        ]
    ),

    "fact_claim": TableMeta(
        name="fact_claim",
        layer="Fact",
        grain="1 satır = 1 hasar bildirimi",
        scd_type=None,
        business_description=(
            "Hasar olgu tablosu. Her hasar bildirimi bir satır olarak tutulur. "
            "paid_amount NULL ise hasar henüz kapanmamıştır. "
            "Loss Ratio hesabı için fact_policy ile policy_nk üzerinden join edilir."
        ),
        owner="Claims Management Team",
        tags=["claim", "loss", "reserve", "claim-settlement"],
        columns=[
            ColumnMeta("claim_sk",       "INTEGER", "Surrogate key (PK)", is_pk=True, is_nullable=False),
            ColumnMeta("claim_nk",       "TEXT",    "Hasar numarası (doğal anahtar)", is_nullable=False),
            ColumnMeta("policy_nk",      "TEXT",    "İlgili poliçe numarası (fact_policy ile bağlantı)"),
            ColumnMeta("customer_sk",    "INTEGER", "Müşteri FK → dim_customer", is_fk=True, fk_target="dim_customer.customer_sk"),
            ColumnMeta("product_sk",     "INTEGER", "Ürün FK → dim_product",    is_fk=True, fk_target="dim_product.product_sk"),
            ColumnMeta("agent_sk",       "INTEGER", "Acente FK → dim_agent",    is_fk=True, fk_target="dim_agent.agent_sk"),
            ColumnMeta("report_date_key","INTEGER", "Hasar bildirim tarihi FK → dim_date", is_fk=True, fk_target="dim_date.date_key"),
            ColumnMeta("close_date_key", "INTEGER", "Hasar kapanış tarihi FK → dim_date — NULL=açık", is_fk=True, fk_target="dim_date.date_key"),
            ColumnMeta("claimed_amount", "REAL",    "Bildirilen hasar tutarı (TRY)"),
            ColumnMeta("paid_amount",    "REAL",    "Ödenen hasar tutarı (TRY) — NULL=açık/reddedilmiş"),
            ColumnMeta("reserve_amount", "REAL",    "Hasar rezervi (TRY) — açık hasarlar için"),
            ColumnMeta("claim_status",   "TEXT",    "Hasar durumu", example_values=["Open","Closed","Rejected","Reopened"]),
            ColumnMeta("claim_type",     "TEXT",    "Hasar tipi",   example_values=["Accident","Theft","Fire","Health","Liability"]),
            ColumnMeta("days_to_close",  "INTEGER", "Kapanış süresi (gün) — NULL=henüz kapanmadı"),
        ]
    ),
}


# ---------------------------------------------------------------------------
# KPI DEFINITIONS
# ---------------------------------------------------------------------------

KPI_DEFINITIONS: list[KPIDefinition] = [
    KPIDefinition(
        name="Gross Written Premium (GWP)",
        business_definition="Belirli dönemde yazılan toplam brüt prim geliri.",
        sql_expression="SUM(fp.gross_premium)",
        unit="TRY",
        domain="Premium",
        notes="fact_policy üzerinden hesaplanır. snapshot_date_key filtresi ile dönem seçilir."
    ),
    KPIDefinition(
        name="Net Premium",
        business_definition="Brüt primden acente komisyonları düşüldükten sonra kalan net prim.",
        sql_expression="SUM(fp.net_premium)",
        unit="TRY",
        domain="Premium",
    ),
    KPIDefinition(
        name="Loss Ratio",
        business_definition="Ödenen hasarların net prime oranı. Teknik kârlılığın temel göstergesi.",
        sql_expression="SUM(fc.paid_amount) / NULLIF(SUM(fp.net_premium), 0) * 100",
        unit="%",
        domain="Claim",
        notes="fact_claim (paid_amount) / fact_policy (net_premium). %70 altı iyi kabul edilir."
    ),
    KPIDefinition(
        name="Claim Frequency",
        business_definition="Aktif poliçe başına düşen ortalama hasar bildirimi sayısı.",
        sql_expression="COUNT(DISTINCT fc.claim_nk) / NULLIF(COUNT(DISTINCT fp.policy_nk), 0)",
        unit="oran",
        domain="Claim",
    ),
    KPIDefinition(
        name="Average Premium per Policy",
        business_definition="Poliçe başına ortalama brüt prim.",
        sql_expression="SUM(fp.gross_premium) / NULLIF(SUM(fp.policy_count), 0)",
        unit="TRY",
        domain="Premium",
    ),
    KPIDefinition(
        name="Claims Settlement Rate",
        business_definition="Kapanan hasarların toplam hasarlara oranı.",
        sql_expression="SUM(CASE WHEN fc.claim_status='Closed' THEN 1 ELSE 0 END) * 100.0 / COUNT(fc.claim_sk)",
        unit="%",
        domain="Claim",
    ),
    KPIDefinition(
        name="Average Days to Close",
        business_definition="Kapalı hasarların ortalama kapanış süresi (gün).",
        sql_expression="AVG(CASE WHEN fc.claim_status='Closed' THEN fc.days_to_close END)",
        unit="gün",
        domain="Claim",
        notes="Düşük değer daha iyi hasar yönetimi performansını gösterir."
    ),
    KPIDefinition(
        name="Active Policy Count",
        business_definition="Belirli snapshot ayındaki aktif poliçe sayısı.",
        sql_expression="SUM(CASE WHEN fp.policy_status='Active' THEN fp.policy_count ELSE 0 END)",
        unit="adet",
        domain="Portfolio",
    ),
    KPIDefinition(
        name="Commission Ratio",
        business_definition="Komisyon tutarının brüt prime oranı.",
        sql_expression="SUM(fp.commission_amount) / NULLIF(SUM(fp.gross_premium), 0) * 100",
        unit="%",
        domain="Agent",
    ),
    KPIDefinition(
        name="Cancellation Rate",
        business_definition="İptal edilen poliçelerin toplam poliçelere oranı.",
        sql_expression="SUM(CASE WHEN fp.policy_status='Cancelled' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(DISTINCT fp.policy_nk), 0)",
        unit="%",
        domain="Portfolio",
    ),
    KPIDefinition(
        name="Total Reserve",
        business_definition="Açık hasarlar için ayrılan toplam rezerv tutarı.",
        sql_expression="SUM(CASE WHEN fc.claim_status='Open' THEN fc.reserve_amount ELSE 0 END)",
        unit="TRY",
        domain="Claim",
        notes="IBNR (Incurred But Not Reported) için ayrıca ayarlanması gerekebilir."
    ),
]


# ---------------------------------------------------------------------------
# LINEAGE
# ---------------------------------------------------------------------------

LINEAGE: list[LineageEdge] = [
    LineageEdge("dim_customer", "fact_policy",  "customer_sk", "1:N", "Bir müşteri birden fazla poliçeye sahip olabilir"),
    LineageEdge("dim_product",  "fact_policy",  "product_sk",  "1:N", "Bir ürün birden fazla poliçede kullanılabilir"),
    LineageEdge("dim_agent",    "fact_policy",  "agent_sk",    "1:N", "Bir acente birden fazla poliçe üretebilir"),
    LineageEdge("dim_date",     "fact_policy",  "date_key → start_date_key / end_date_key / snapshot_date_key", "1:N",
                "dim_date üç farklı tarih anahtarı ile fact_policy'ye bağlanır"),
    LineageEdge("dim_customer", "fact_claim",   "customer_sk", "1:N", "Bir müşteri birden fazla hasar bildiriminde bulunabilir"),
    LineageEdge("dim_product",  "fact_claim",   "product_sk",  "1:N", "Bir ürüne ait birden fazla hasar olabilir"),
    LineageEdge("dim_agent",    "fact_claim",   "agent_sk",    "1:N", "Bir acentenin müşterisine ait birden fazla hasar"),
    LineageEdge("dim_date",     "fact_claim",   "date_key → report_date_key / close_date_key", "1:N",
                "dim_date iki farklı tarih anahtarı ile fact_claim'e bağlanır"),
    LineageEdge("fact_policy",  "fact_claim",   "policy_nk",   "1:N", "Bir poliçeye ait birden fazla hasar bildirimi olabilir"),
]


# ---------------------------------------------------------------------------
# Context builder (Claude API için)
# ---------------------------------------------------------------------------

def build_schema_context() -> str:
    """
    Claude'a gönderilecek sistem context stringini üretir.
    NL→SQL modülünde system prompt'a eklenir.
    """
    lines = ["# Insurance DWH Schema Context\n"]
    lines.append("Bu bir sigorta şirketinin demo Data Warehouse'udur. SQLite kullanılmaktadır.\n")

    for tname, tmeta in TABLE_METADATA.items():
        lines.append(f"## {tname}")
        lines.append(f"- Layer: {tmeta.layer}")
        lines.append(f"- Grain: {tmeta.grain}")
        if tmeta.scd_type:
            lines.append(f"- SCD: {tmeta.scd_type}")
        lines.append(f"- Açıklama: {tmeta.business_description}")
        lines.append("\nKolonlar:")
        for col in tmeta.columns:
            fk_info = f" → FK: {col.fk_target}" if col.is_fk else ""
            pk_info = " [PK]" if col.is_pk else ""
            ex_info = f" (örn: {', '.join(col.example_values)})" if col.example_values else ""
            lines.append(f"  - {col.name} ({col.data_type}){pk_info}{fk_info}: {col.description}{ex_info}")
        lines.append("")

    lines.append("## Önemli Join Kuralları")
    for edge in LINEAGE:
        lines.append(f"- {edge.source_table} → {edge.target_table} via {edge.join_key} ({edge.relationship}): {edge.description}")

    lines.append("\n## Temel KPI Formülleri")
    for kpi in KPI_DEFINITIONS:
        lines.append(f"- **{kpi.name}** ({kpi.unit}): `{kpi.sql_expression}`")

    lines.append("\n## SQLite Uyarıları")
    lines.append("- DATEADD / DATEDIFF yerine DATE() ve JULIANDAY() kullan")
    lines.append("- ISNULL yerine COALESCE veya IFNULL kullan")
    lines.append("- TOP yerine LIMIT kullan")
    lines.append("- Mevcut snapshot yılları: 2022, 2023, 2024")
    lines.append("- dim_customer'da güncel kayıtlar için WHERE is_current=1 filtresi ekle")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ctx = build_schema_context()
    print(ctx[:3000])
    print(f"\n... (total {len(ctx)} chars)")
    print(f"\nKPI count: {len(KPI_DEFINITIONS)}")
    print(f"Lineage edges: {len(LINEAGE)}")
    print(f"Tables documented: {len(TABLE_METADATA)}")
