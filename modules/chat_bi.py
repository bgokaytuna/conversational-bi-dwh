"""
chat_bi.py
==========
Conversational BI modülü.

Akış:
  kullanıcı sorusu
    → SQL üret  (Claude, temperature=0, schema context ile)
    → SQL çalıştır (SQLite)
    → Insight üret (Claude, temperature=0.5, sonuç + soru ile)
    → Streamlit'e döndür

Public API:
    generate_sql(question: str) -> str
    run_and_explain(question: str) -> ChatBIResult
"""

import re
from dataclasses import dataclass, field
from typing import Iterator

from schema.metadata import build_schema_context
from schema.dwh_schema import run_query
from utils.claude_client import ask, ask_streaming

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SQL_SYSTEM = """
Sen bir Insurance DWH uzmanı ve kıdemli SQL geliştiricisisin.
Sana verilen Insurance DWH şeması üzerinde çalışıyorsun.
Veritabanı motoru: SQLite.

GÖREV:
Kullanıcının doğal dil sorusunu, aşağıdaki kurallara uyarak bir SQLite SQL sorgusuna çevir.

KURALLAR:
1. Yalnızca SQL döndür — başka hiçbir şey yazma, açıklama ekleme, kod bloğu işareti kullanma.
2. Sorgu SELECT ile başlamalı (DML/DDL kesinlikle yasak).
3. dim_customer için her zaman WHERE is_current = 1 filtresi ekle.
4. Tarih karşılaştırmalarında dim_date tablosunu join et; YYYYMMDD integer date_key kullan.
5. SQLite uyumlu sözdizimi: LIMIT (TOP değil), COALESCE/IFNULL (ISNULL değil), strftime().
6. KPI hesaplarında NULLIF ile sıfıra bölünmeyi önle.
7. Alias'lar Türkçe ve anlamlı olsun (örn. toplam_prim, hasar_orani).
8. Sonuç maksimum 500 satır olacak şekilde LIMIT ekle — kullanıcı aksi belirtmediği sürece.
9. Yorum satırı veya açıklama ekleme — sadece saf SQL.

{schema_context}
""".strip()

_INSIGHT_SYSTEM = """
Sen bir sigorta sektörü analisti ve veri yorumcususun.
Sana bir kullanıcı sorusu ve bu soruya karşılık gelen SQL sorgu sonucu verilecek.

GÖREV:
Sonucu 3-5 cümleyle Türkçe olarak yorumla.

KURALLAR:
- Sayısal değerleri mutlaka yoruma dahil et.
- Sigorta sektörü bağlamında anlam çıkar (Loss Ratio, prim büyümesi vb.).
- Dikkat çeken anormallik veya trend varsa vurgula.
- Teknik SQL detaylarından bahsetme — iş odaklı konuş.
- Yanıt 3-5 cümle, sade ve net olsun.
""".strip()

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class ChatBIResult:
    question: str
    sql: str
    columns: list[str]       = field(default_factory=list)
    rows: list[tuple]        = field(default_factory=list)
    insight: str             = ""
    error: str               = ""

    @property
    def success(self) -> bool:
        return not self.error

    @property
    def row_count(self) -> int:
        return len(self.rows)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def generate_sql(question: str) -> str:
    """
    Kullanıcının doğal dil sorusunu SQL'e çevirir.
    Sadece ham SQL string döner — parse/çalıştırma yok.
    """
    schema_ctx = build_schema_context()
    system     = _SQL_SYSTEM.format(schema_context=schema_ctx)
    raw        = ask(user=question, system=system, temperature=0.0)
    return _clean_sql(raw)


def run_and_explain(question: str) -> ChatBIResult:
    """
    Tam pipeline:
      1. NL → SQL üret
      2. SQL çalıştır
      3. Insight üret (streaming değil, tam metin)
    Hata durumunda result.error dolu gelir.
    """
    result = ChatBIResult(question=question, sql="")

    # 1. SQL üret
    try:
        result.sql = generate_sql(question)
    except Exception as exc:
        result.error = f"SQL üretme hatası: {exc}"
        return result

    # 2. SQL çalıştır
    try:
        cols, rows = run_query(result.sql)
        result.columns = cols
        result.rows    = rows
    except Exception as exc:
        result.error = f"SQL çalıştırma hatası: {exc}\n\nÜretilen SQL:\n{result.sql}"
        return result

    # 3. Insight üret
    if result.rows:
        try:
            result.insight = _generate_insight(question, result)
        except Exception:
            result.insight = ""   # insight opsiyonel — hata sessizce geçilir

    return result


def run_and_explain_streaming(question: str) -> Iterator[ChatBIResult | str]:
    """
    Streamlit için hybrid akış:
      - Önce ChatBIResult yield eder (SQL + tablo verisi, insight="")
      - Sonra insight chunk'larını string olarak yield eder

    Kullanım (Streamlit):
        gen = run_and_explain_streaming(question)
        result = next(gen)           # ChatBIResult
        st.dataframe(result.rows)
        insight_box = st.empty()
        text = ""
        for chunk in gen:            # str chunk'ları
            text += chunk
            insight_box.markdown(text)
    """
    result = ChatBIResult(question=question, sql="")

    # SQL üret + çalıştır
    try:
        result.sql = generate_sql(question)
    except Exception as exc:
        result.error = f"SQL üretme hatası: {exc}"
        yield result
        return

    try:
        cols, rows   = run_query(result.sql)
        result.columns = cols
        result.rows    = rows
    except Exception as exc:
        result.error = f"SQL çalıştırma hatası: {exc}\n\nÜretilen SQL:\n{result.sql}"
        yield result
        return

    yield result   # tablo verisi hazır, UI'ı güncelle

    # Insight streaming
    if result.rows:
        user_msg = _build_insight_prompt(question, result)
        yield from ask_streaming(
            user=user_msg,
            system=_INSIGHT_SYSTEM,
            temperature=0.5,
        )


# ---------------------------------------------------------------------------
# Örnek sorular (Streamlit UI'da gösterilecek)
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS: list[str] = [
    "2023 yılında ürün bazında toplam brüt prim geliri nedir?",
    "Kanal bazında aktif poliçe sayısı ve ortalama prim nasıl dağılıyor?",
    "Loss Ratio en yüksek olan 5 ürün hangileri?",
    "2024 yılında aylık hasar bildirimi sayısı nasıl değişti?",
    "Bölge bazında toplam prim geliri ve hasar oranını karşılaştır.",
    "Ortalama hasar kapanış süresi en uzun hasar tipi hangisi?",
    "Açık hasar rezervinin en fazla biriktiği ürün ve bölge nedir?",
    "Corporate segment müşterilerin poliçe başına ortalama primi nedir?",
]

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _clean_sql(raw: str) -> str:
    """
    Model bazen ```sql ... ``` bloğu içinde döndürür.
    Kod bloğu işaretlerini ve başındaki/sonundaki boşlukları temizler.
    """
    raw = raw.strip()
    # ```sql\n...\n``` veya ```\n...\n``` formatını temizle
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _build_insight_prompt(question: str, result: ChatBIResult) -> str:
    """Insight API çağrısı için kullanıcı mesajını oluşturur."""
    # Tablo önizlemesi (maksimum 20 satır)
    preview_rows = result.rows[:20]
    header = " | ".join(result.columns)
    rows_txt = "\n".join(
        " | ".join(str(v) if v is not None else "NULL" for v in row)
        for row in preview_rows
    )
    truncation_note = (
        f"\n(... ve {result.row_count - 20} satır daha)"
        if result.row_count > 20 else ""
    )

    return (
        f"Kullanıcı sorusu: {question}\n\n"
        f"Sorgu sonucu ({result.row_count} satır):\n"
        f"{header}\n{rows_txt}{truncation_note}"
    )


def _generate_insight(question: str, result: ChatBIResult) -> str:
    """Blocking insight üretimi (streaming olmayan versiyon)."""
    user_msg = _build_insight_prompt(question, result)
    return ask(user=user_msg, system=_INSIGHT_SYSTEM, temperature=0.5)
