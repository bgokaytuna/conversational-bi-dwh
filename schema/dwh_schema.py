"""
dwh_schema.py
=============
Insurance DWH — Star Schema (SQLite in-memory)
Grain, SCD ve surrogate key mantığı gerçek bir DWH'ı yansıtır.

Tables
------
dim_date        → Zaman boyutu (no SCD)
dim_customer    → SCD Type 2  (tarihsel müşteri kaydı)
dim_product     → SCD Type 1  (her zaman güncel)
dim_agent       → SCD Type 1
fact_policy     → Grain: 1 row per policy per effective month
fact_claim      → Grain: 1 row per claim event
"""

import sqlite3
import random
from datetime import date, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_conn: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """Singleton in-memory SQLite bağlantısı döndürür."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(":memory:", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _bootstrap(_conn)
    return _conn


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
-- ── dim_date ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_date (
    date_key        INTEGER PRIMARY KEY,   -- YYYYMMDD
    full_date       TEXT NOT NULL,
    year            INTEGER NOT NULL,
    quarter         INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    month_name      TEXT NOT NULL,
    week_of_year    INTEGER NOT NULL,
    day_of_week     TEXT NOT NULL,
    is_weekend      INTEGER NOT NULL       -- 0/1
);

-- ── dim_customer (SCD Type 2) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_customer (
    customer_sk         INTEGER PRIMARY KEY AUTOINCREMENT,  -- surrogate key
    customer_nk         TEXT NOT NULL,                      -- natural / business key
    first_name          TEXT NOT NULL,
    last_name           TEXT NOT NULL,
    gender              TEXT,
    birth_date          TEXT,
    city                TEXT,
    region              TEXT,
    country             TEXT DEFAULT 'TR',
    customer_segment    TEXT,    -- 'Individual' | 'Corporate' | 'SME'
    credit_score        INTEGER,
    is_current          INTEGER NOT NULL DEFAULT 1,   -- SCD2 flag
    valid_from          TEXT NOT NULL,
    valid_to            TEXT,                         -- NULL = current record
    dw_insert_date      TEXT NOT NULL
);

-- ── dim_product ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_product (
    product_sk      INTEGER PRIMARY KEY AUTOINCREMENT,
    product_nk      TEXT NOT NULL UNIQUE,
    product_name    TEXT NOT NULL,
    product_line    TEXT NOT NULL,  -- 'Life' | 'Non-Life' | 'Health'
    product_type    TEXT NOT NULL,  -- 'Motor' | 'Home' | 'Life' | 'Health' | 'Travel'
    coverage_type   TEXT,
    base_premium    REAL,
    risk_category   TEXT,           -- 'Low' | 'Medium' | 'High'
    is_active       INTEGER DEFAULT 1
);

-- ── dim_agent ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_agent (
    agent_sk        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_nk        TEXT NOT NULL UNIQUE,
    agent_name      TEXT NOT NULL,
    agency_name     TEXT,
    region          TEXT,
    channel         TEXT,   -- 'Direct' | 'Broker' | 'Bancassurance' | 'Digital'
    is_active       INTEGER DEFAULT 1
);

-- ── fact_policy ──────────────────────────────────────────────────────────────
-- Grain: 1 satır = 1 poliçe x 1 ay (aylık snapshot)
CREATE TABLE IF NOT EXISTS fact_policy (
    policy_sk           INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_nk           TEXT NOT NULL,          -- doğal anahtar (poliçe no)
    customer_sk         INTEGER NOT NULL REFERENCES dim_customer(customer_sk),
    product_sk          INTEGER NOT NULL REFERENCES dim_product(product_sk),
    agent_sk            INTEGER NOT NULL REFERENCES dim_agent(agent_sk),
    start_date_key      INTEGER NOT NULL REFERENCES dim_date(date_key),
    end_date_key        INTEGER REFERENCES dim_date(date_key),
    snapshot_date_key   INTEGER NOT NULL REFERENCES dim_date(date_key),
    -- Measures
    gross_premium       REAL NOT NULL,   -- Brüt prim (TRY)
    net_premium         REAL NOT NULL,   -- Net prim (TRY)
    commission_amount   REAL NOT NULL,
    policy_count        INTEGER NOT NULL DEFAULT 1,
    policy_status       TEXT NOT NULL,   -- 'Active' | 'Cancelled' | 'Expired' | 'Renewed'
    payment_frequency   TEXT             -- 'Monthly' | 'Quarterly' | 'Annual'
);

-- ── fact_claim ───────────────────────────────────────────────────────────────
-- Grain: 1 satır = 1 hasar bildirimi
CREATE TABLE IF NOT EXISTS fact_claim (
    claim_sk            INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_nk            TEXT NOT NULL,
    policy_nk           TEXT NOT NULL,
    customer_sk         INTEGER NOT NULL REFERENCES dim_customer(customer_sk),
    product_sk          INTEGER NOT NULL REFERENCES dim_product(product_sk),
    agent_sk            INTEGER NOT NULL REFERENCES dim_agent(agent_sk),
    report_date_key     INTEGER NOT NULL REFERENCES dim_date(date_key),
    close_date_key      INTEGER REFERENCES dim_date(date_key),
    -- Measures
    claimed_amount      REAL NOT NULL,   -- Bildirilen hasar tutarı
    paid_amount         REAL,            -- Ödenen tutar (NULL = açık)
    reserve_amount      REAL,            -- Rezerv
    claim_status        TEXT NOT NULL,   -- 'Open' | 'Closed' | 'Rejected' | 'Reopened'
    claim_type          TEXT,            -- 'Accident' | 'Theft' | 'Fire' | 'Health' | 'Liability'
    days_to_close       INTEGER          -- NULL = henüz kapanmadı
);
"""


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

random.seed(42)

_FIRST_NAMES = ["Ahmet", "Mehmet", "Ayşe", "Fatma", "Ali", "Zeynep",
                "Mustafa", "Emine", "Hüseyin", "Hatice", "İbrahim", "Elif",
                "Hasan", "Meryem", "Ömer", "Büşra", "Yusuf", "Esra"]
_LAST_NAMES  = ["Yılmaz", "Kaya", "Demir", "Çelik", "Şahin", "Yıldız",
                "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Aydın"]

# Shuffle separately — first_name and last_name pools are decoupled
# so no real person can be inferred from the combination
_SHUFFLED_FIRST = _FIRST_NAMES.copy()
_SHUFFLED_LAST  = _LAST_NAMES.copy()
random.shuffle(_SHUFFLED_FIRST)
random.shuffle(_SHUFFLED_LAST)

# Agent name pool — separate from customer names
_AGENT_FIRST = ["Serkan", "Burak", "Selin", "Derya", "Emre",
                "Canan", "Tolga", "Pınar", "Murat", "Gül"]
_AGENT_LAST  = ["Öztürk", "Bulut", "Erdoğan", "Karaca", "Yıldırım",
                "Aktaş", "Güneş", "Koç", "Polat", "Keskin"]
random.shuffle(_AGENT_FIRST)
random.shuffle(_AGENT_LAST)
_CITIES      = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya",
                "Konya", "Adana", "Gaziantep", "Kayseri", "Mersin"]
_REGIONS     = {"İstanbul": "Marmara", "Ankara": "İç Anadolu",
                "İzmir": "Ege", "Bursa": "Marmara", "Antalya": "Akdeniz",
                "Konya": "İç Anadolu", "Adana": "Akdeniz",
                "Gaziantep": "Güneydoğu Anadolu", "Kayseri": "İç Anadolu",
                "Mersin": "Akdeniz"}
_SEGMENTS    = ["Individual", "Individual", "Individual", "Corporate", "SME"]
_CHANNELS    = ["Direct", "Broker", "Bancassurance", "Digital"]


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _date_key(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def _month_name(m: int) -> str:
    return ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
            "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"][m - 1]


def _seed_dim_date(conn: sqlite3.Connection):
    start = date(2021, 1, 1)
    end   = date(2024, 12, 31)
    rows  = []
    for d in _date_range(start, end):
        rows.append((
            _date_key(d),
            d.isoformat(),
            d.year,
            (d.month - 1) // 3 + 1,
            d.month,
            _month_name(d.month),
            d.isocalendar()[1],
            d.strftime("%A"),
            1 if d.weekday() >= 5 else 0,
        ))
    conn.executemany(
        "INSERT OR IGNORE INTO dim_date VALUES (?,?,?,?,?,?,?,?,?)", rows
    )


def _seed_dim_product(conn: sqlite3.Connection):
    products = [
        ("PRD-001", "Zorunlu Trafik Sigortası", "Non-Life", "Motor",   "Third-Party Liability", 2800,  "Low"),
        ("PRD-002", "Kasko",                    "Non-Life", "Motor",   "Comprehensive",         9500,  "Medium"),
        ("PRD-003", "Konut Sigortası",           "Non-Life", "Home",    "All-Risk",              1200,  "Low"),
        ("PRD-004", "Dask",                      "Non-Life", "Home",    "Earthquake",             400,  "Low"),
        ("PRD-005", "Hayat Sigortası",           "Life",     "Life",    "Term Life",             3600,  "Medium"),
        ("PRD-006", "Bireysel Emeklilik",        "Life",     "Life",    "Unit-Linked",           6000,  "Low"),
        ("PRD-007", "Sağlık Sigortası",          "Health",   "Health",  "Inpatient + Outpatient",12000, "High"),
        ("PRD-008", "Tamamlayıcı Sağlık",        "Health",   "Health",  "Supplemental",          4500,  "Medium"),
        ("PRD-009", "Seyahat Sigortası",         "Non-Life", "Travel",  "Annual Multi-Trip",      800,  "Low"),
        ("PRD-010", "İşyeri Sigortası",          "Non-Life", "Home",    "Commercial Property",   5500,  "High"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO dim_product "
        "(product_nk,product_name,product_line,product_type,coverage_type,base_premium,risk_category) "
        "VALUES (?,?,?,?,?,?,?)", products
    )


def _seed_dim_agent(conn: sqlite3.Connection):
    agencies = [
        ("AGT-001", "Berk Sigorta Aracılık",   "İstanbul", "Broker"),
        ("AGT-002", "Güven Sigorta Acentesi",   "Ankara",   "Direct"),
        ("AGT-003", "Akdeniz Aracılık",         "Antalya",  "Broker"),
        ("AGT-004", "Ege Sigorta Hizmetleri",   "İzmir",    "Broker"),
        ("AGT-005", "Dijital Poliçe",           "İstanbul", "Digital"),
        ("AGT-006", "Marmara Acentesi",         "Bursa",    "Direct"),
        ("AGT-007", "Banka Kanalı İstanbul",    "İstanbul", "Bancassurance"),
        ("AGT-008", "Banka Kanalı Ankara",      "Ankara",   "Bancassurance"),
    ]
    # agent_name: shuffled first+last — decoupled from agency_name
    rows = []
    for i, (nk, agency_name, region, channel) in enumerate(agencies):
        fn = _AGENT_FIRST[i % len(_AGENT_FIRST)]
        ln = _AGENT_LAST[i % len(_AGENT_LAST)]
        agent_name = f"{fn} {ln}"
        rows.append((nk, agent_name, agency_name, region, channel))
    conn.executemany(
        "INSERT OR IGNORE INTO dim_agent "
        "(agent_nk,agent_name,agency_name,region,channel) VALUES (?,?,?,?,?)", rows
    )


def _seed_dim_customer(conn: sqlite3.Connection, n: int = 120):
    today = date(2024, 12, 31)
    rows = []
    for i in range(1, n + 1):
        nk      = f"CST-{i:05d}"
        fn      = random.choice(_SHUFFLED_FIRST)
        ln      = random.choice(_SHUFFLED_LAST)
        gender  = random.choice(["M", "F"])
        birth   = date(random.randint(1960, 2000), random.randint(1, 12), random.randint(1, 28))
        city    = random.choice(_CITIES)
        segment = random.choice(_SEGMENTS)
        score   = random.randint(500, 900)
        vf      = date(2021, 1, 1).isoformat()
        rows.append((nk, fn, ln, gender, birth.isoformat(), city,
                     _REGIONS[city], "TR", segment, score,
                     1, vf, None, today.isoformat()))
        # ~15% müşteri için SCD2 geçmiş kayıt
        if random.random() < 0.15:
            old_city  = random.choice(_CITIES)
            old_score = score - random.randint(30, 100)
            rows.append((nk, fn, ln, gender, birth.isoformat(), old_city,
                         _REGIONS[old_city], "TR", segment, max(400, old_score),
                         0, date(2020, 1, 1).isoformat(),
                         date(2020, 12, 31).isoformat(), today.isoformat()))
    conn.executemany(
        "INSERT INTO dim_customer "
        "(customer_nk,first_name,last_name,gender,birth_date,city,region,country,"
        "customer_segment,credit_score,is_current,valid_from,valid_to,dw_insert_date) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )


def _seed_fact_policy(conn: sqlite3.Connection):
    cur_customers = conn.execute(
        "SELECT customer_sk FROM dim_customer WHERE is_current=1"
    ).fetchall()
    products = conn.execute("SELECT product_sk, base_premium FROM dim_product").fetchall()
    agents   = conn.execute("SELECT agent_sk FROM dim_agent").fetchall()

    # Snapshot ayları: 2022-01 → 2024-12
    snapshot_months = []
    d = date(2022, 1, 1)
    while d <= date(2024, 12, 1):
        snapshot_months.append(d)
        m = d.month + 1
        y = d.year + (1 if m > 12 else 0)
        d = date(y, m % 12 or 12, 1)

    statuses = ["Active", "Active", "Active", "Active", "Cancelled", "Expired", "Renewed"]
    freqs    = ["Annual", "Annual", "Quarterly", "Monthly"]
    rows = []
    pol_counter = 1

    for cust in cur_customers:
        # Her müşteri 1–3 poliçe
        n_policies = random.randint(1, 3)
        chosen_products = random.sample(products, min(n_policies, len(products)))
        for prod in chosen_products:
            pol_nk   = f"POL-{pol_counter:06d}"
            pol_counter += 1
            agent    = random.choice(agents)
            start_d  = date(random.randint(2022, 2023),
                            random.randint(1, 12), 1)
            end_d    = date(start_d.year + 1, start_d.month, 1) - timedelta(days=1)
            base_p   = prod["base_premium"]
            gross_p  = round(base_p * random.uniform(0.85, 1.25), 2)
            comm_pct = random.uniform(0.08, 0.18)
            net_p    = round(gross_p * (1 - comm_pct), 2)
            comm_a   = round(gross_p * comm_pct, 2)
            status   = random.choice(statuses)
            freq     = random.choice(freqs)

            for snap in snapshot_months:
                if snap < start_d or snap > end_d + timedelta(days=31):
                    continue
                rows.append((
                    pol_nk,
                    cust["customer_sk"],
                    prod["product_sk"],
                    agent["agent_sk"],
                    _date_key(start_d),
                    _date_key(end_d),
                    _date_key(snap),
                    gross_p, net_p, comm_a, 1,
                    status, freq,
                ))

    conn.executemany(
        "INSERT INTO fact_policy "
        "(policy_nk,customer_sk,product_sk,agent_sk,start_date_key,end_date_key,"
        "snapshot_date_key,gross_premium,net_premium,commission_amount,policy_count,"
        "policy_status,payment_frequency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )


def _seed_fact_claim(conn: sqlite3.Connection):
    policies = conn.execute(
        "SELECT DISTINCT policy_nk, customer_sk, product_sk, agent_sk "
        "FROM fact_policy WHERE policy_status='Active'"
    ).fetchall()

    claim_types   = ["Accident", "Theft", "Fire", "Health", "Liability", "Natural Disaster"]
    claim_statuses = ["Closed", "Closed", "Closed", "Open", "Rejected"]
    rows = []
    clm_counter = 1

    # Aktif poliçelerin ~30%'u hasar bildirmiş
    sampled = random.sample(policies, int(len(policies) * 0.30))
    for pol in sampled:
        n_claims = random.randint(1, 2)
        for _ in range(n_claims):
            clm_nk     = f"CLM-{clm_counter:06d}"
            clm_counter += 1
            rep_year   = random.randint(2022, 2024)
            rep_month  = random.randint(1, 12)
            rep_day    = random.randint(1, 28)
            rep_date   = date(rep_year, rep_month, rep_day)
            status     = random.choice(claim_statuses)
            claimed    = round(random.uniform(500, 80000), 2)
            paid       = None
            reserve    = None
            days_close = None
            close_key  = None

            if status == "Closed":
                days_close = random.randint(5, 180)
                close_d    = rep_date + timedelta(days=days_close)
                if close_d.year <= 2024:
                    close_key = _date_key(close_d)
                paid    = round(claimed * random.uniform(0.5, 0.95), 2)
                reserve = 0.0
            elif status == "Open":
                reserve = round(claimed * random.uniform(0.7, 1.0), 2)
            elif status == "Rejected":
                paid    = 0.0
                reserve = 0.0

            rows.append((
                clm_nk, pol["policy_nk"],
                pol["customer_sk"], pol["product_sk"], pol["agent_sk"],
                _date_key(rep_date), close_key,
                claimed, paid, reserve, status,
                random.choice(claim_types), days_close,
            ))

    conn.executemany(
        "INSERT INTO fact_claim "
        "(claim_nk,policy_nk,customer_sk,product_sk,agent_sk,"
        "report_date_key,close_date_key,claimed_amount,paid_amount,"
        "reserve_amount,claim_status,claim_type,days_to_close) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _bootstrap(conn: sqlite3.Connection):
    conn.executescript(_DDL)
    _seed_dim_date(conn)
    _seed_dim_product(conn)
    _seed_dim_agent(conn)
    _seed_dim_customer(conn, n=120)
    _seed_fact_policy(conn)
    _seed_fact_claim(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def run_query(sql: str) -> tuple[list[str], list[tuple]]:
    """SQL çalıştırır; (columns, rows) döner. Hata için exception fırlatır."""
    conn = get_connection()
    cur  = conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    return cols, [tuple(r) for r in rows]


def get_table_stats() -> dict:
    """Her tablodaki satır sayısını döner."""
    tables = ["dim_date", "dim_customer", "dim_product", "dim_agent",
              "fact_policy", "fact_claim"]
    conn = get_connection()
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in tables}


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    stats = get_table_stats()
    print("=== DWH Table Row Counts ===")
    for t, n in stats.items():
        print(f"  {t:<20} {n:>6} rows")

    print("\n=== Sample: fact_policy (5 rows) ===")
    cols, rows = run_query("SELECT * FROM fact_policy LIMIT 5")
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(x) for x in r))

    print("\n=== Sample: fact_claim (5 rows) ===")
    cols, rows = run_query("SELECT * FROM fact_claim LIMIT 5")
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(x) for x in r))
