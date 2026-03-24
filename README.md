# 📊 Conversational BI & DWH Documentation Tool

> **Insurance DWH üzerinde doğal dille soru sor, schema'yı keşfet, lineage'ı görselleştir, glossary yönet.**

Anthropic Claude API ile güçlendirilmiş, sigorta/finans sektörüne yönelik demo bir Data Warehouse asistanı.

---

## Özellikler

| Sekme | Ne Yapar? |
|---|---|
| 💬 **Chat BI** | Türkçe doğal dil sorusunu SQL'e çevirir, SQLite'ta çalıştırır, sonucu tablo + bar chart + AI insight olarak gösterir |
| 🗂 **Schema Explorer** | 6 DWH tablosunu grain, SCD tipi, kolon açıklamaları ve KPI tanımlarıyla belgeler; Claude ile tablo açıklaması üretir |
| 🔗 **Lineage Viewer** | Fact ↔ Dimension ilişkilerini interaktif pyvis grafı ile gösterir; FK kolon detayları |
| 📖 **Business Glossary** | 31 seed terim; Claude ile bulk tanım üretimi; onay akışı (draft → approved); CSV & Markdown export |

## Demo DWH Schema

```
dim_date        SCD0  — Zaman boyutu (2021–2024)
dim_customer    SCD2  — Müşteri (tarihsel versiyon)
dim_product     SCD1  — Ürün (10 sigorta ürünü)
dim_agent       SCD1  — Acente / dağıtım kanalı
fact_policy     —     — Grain: 1 poliçe × 1 ay snapshot  (3.367 satır)
fact_claim      —     — Grain: 1 hasar bildirimi           (63 satır)
```

Veri tamamen **in-memory SQLite** — disk'e hiçbir şey yazılmaz, `pip install` + `streamlit run` yeterli.

## Kurulum

```bash
git clone https://github.com/bgokaytuna/conversational-bi-dwh
cd conversational-bi-dwh

pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...   # Windows: set ANTHROPIC_API_KEY=sk-ant-...

streamlit run app.py
```

Uygulama `http://localhost:8501` adresinde açılır.

## Proje Yapısı

```
conversational-bi-dwh/
├── app.py                      # Streamlit ana uygulama (4 sekme)
├── requirements.txt
│
├── schema/
│   ├── dwh_schema.py           # SQLite in-memory DB + seed data
│   └── metadata.py             # Tablo/kolon meta, KPI, lineage tanımları
│
├── utils/
│   └── claude_client.py        # Anthropic API wrapper (ask / ask_streaming)
│
└── modules/
    ├── chat_bi.py              # NL → SQL → çalıştır → insight pipeline
    ├── schema_explorer.py      # Tablo/kolon dokümantasyonu + KPI listesi
    ├── lineage_viewer.py       # İnteraktif lineage grafı (pyvis)
    └── glossary.py             # AI destekli business glossary yönetimi
```

## Teknik Detaylar

### NL → SQL Akışı
1. `build_schema_context()` ile 8.500 karakterlik schema context'i hazırlanır
2. Claude'a `temperature=0` ile gönderilir (deterministik SQL)
3. `_clean_sql()` ile kod bloğu işaretleri temizlenir
4. SQLite'ta çalıştırılır
5. Sonuç Claude'a tekrar gönderilir → Türkçe insight üretilir

### Schema Context İçeriği
- 6 tablo: grain, SCD tipi, business açıklama, owner
- 54 kolon: tip, PK/FK, açıklama, örnek değerler
- 9 lineage edge: kardinalite ve join key bilgisi
- 11 KPI formülü: SQL expression + iş tanımı
- SQLite uyarıları (LIMIT, COALESCE, strftime)

### SCD Tipleri
- `dim_date`: SCD0 — hiç değişmez
- `dim_product`, `dim_agent`: SCD1 — yerinde güncelleme
- `dim_customer`: SCD2 — `is_current`, `valid_from`, `valid_to` ile tarihsel versiyon

## Örnek Sorular

```
2023 yılında ürün bazında toplam brüt prim geliri nedir?
Loss Ratio en yüksek olan 5 ürün hangileri?
Kanal bazında aktif poliçe sayısı ve ortalama prim nasıl dağılıyor?
Bölge bazında toplam prim geliri ve hasar oranını karşılaştır.
Ortalama hasar kapanış süresi en uzun hasar tipi hangisi?
Açık hasar rezervinin en fazla biriktiği ürün ve bölge nedir?
```

## Bağımlılıklar

| Paket | Versiyon | Kullanım |
|---|---|---|
| `anthropic` | ≥0.40 | Claude API istemcisi |
| `streamlit` | ≥1.35 | Web UI |
| `pandas` | ≥2.0 | Dataframe görüntüleme |
| `pyvis` | ≥0.3.2 | İnteraktif lineage grafı |

> `pyvis` kurulu değilse Lineage Viewer otomatik olarak statik tablo görünümüne geçer.

## Yazar

**Gökay Tuna** — Senior Data Engineer & Data Platform Architect  
[linkedin.com/in/gokaytuna](https://linkedin.com/in/gokaytuna)

---

*Microsoft Fabric Data Engineer (DP-700) · Fabric Analytics Engineer (DP-600) · Google Cloud Generative AI Leader*
