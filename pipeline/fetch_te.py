"""Streaming pipeline source: TradingEconomics Morocco Indicators -> SQLite/CSV.
URL: https://tradingeconomics.com/morocco/indicators
Usage:
  python pipeline/fetch_te.py              # one shot
  python pipeline/fetch_te.py --loop 300   # streaming: every 300s
"""
import argparse
import sqlite3
import sys
import time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from datetime import datetime, timezone
from pathlib import Path
import re

import requests
import pandas as pd

URL = "https://tradingeconomics.com/morocco/indicators"
HEADERS = {"User-Agent": "Mozilla/5.0 (Morocco-Streamlit-Project)"}

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DB_PATH = DATA_DIR / "morocco.db"
CSV_LATEST = DATA_DIR / "morocco_latest.csv"

# Fallback snapshot (2026-10-07) if site blocks scraping
FALLBACK = [
 ("Currency",9.98,9.96,"","", "Oct/26"),
 ("Stock Market",17132,16893,"points","", "Oct/26"),
 ("GDP Annual Growth Rate",4,4.6,"percent","GDP", "Jun/26"),
 ("Unemployment Rate",9.5,10.8,"percent","Labour", "Jun/26"),
 ("Inflation Rate",-0.3,-0.6,"percent","Prices", "Aug/26"),
 ("Interest Rate",2.25,2.25,"percent","Money", "Sep/26"),
 ("Balance of Trade",-37920,-46315,"MAD Million","Trade", "Aug/26"),
 ("Current Account",-5028,-13390,"MAD Million","Trade", "Mar/26"),
 ("Current Account to GDP",-2.4,-1.6,"percent of GDP","Trade", "Dec/25"),
 ("Government Debt to GDP",67.1,67.7,"percent of GDP","Government", "Dec/25"),
 ("Government Budget",-3.6,-3.9,"percent of GDP","Government", "Dec/25"),
 ("Consumer Confidence",60.1,64.4,"points","Consumer", "Jun/26"),
 ("GDP",182,161,"USD Billion","GDP", "Dec/25"),
 ("GDP per Capita",3644,3516,"USD","GDP", "Dec/25"),
 ("Tourist Arrivals",19800000,17411949,"","Trade", "Dec/25"),
 ("Foreign Exchange Reserves",500065,496761,"MAD Million","Money", "Aug/26"),
 ("Minimum Wages",3423,3045,"MAD/Month","Labour", "Jan/26"),
 ("Youth Unemployment Rate",22.9,23.4,"percent","Labour", "Jun/26"),
 ("Food Inflation",-3.9,-3.7,"percent","Prices", "Aug/26"),
 ("Industrial Production",-4.5,-1.4,"percent","Business", "Jun/26"),
]

def parse_value(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip().replace(",", "")
    s = re.sub(r"[^\d\.\-]", "", s)
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None

def fetch_live():
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    import io
    tables = pd.read_html(io.StringIO(r.text), flavor="lxml")
    rows = []
    for t in tables:
        # Expected cols: Indicator | Last | Previous | Highest | Lowest | ... | Date
        if t.shape[1] < 6 or t.shape[0] < 3:
            continue
        t = t.iloc[:, :7]
        t.columns = ["indicator", "last", "previous", "highest", "lowest", "unit", "date"][: len(t.columns)]
        if "indicator" not in t.columns:
            continue
        # keep only tables that look like indicators (contain GDP / Rate / etc or percent/MAD)
        sample = " ".join(t["indicator"].astype(str).tolist()[:5])
        blob = str(t.to_string()).lower()
        if not any(k in blob for k in ["gdp", "rate", "inflation", "unemploy", "trade", "mad", "percent", "usd"]):
            continue
        for _, row in t.iterrows():
            name = str(row.get("indicator", "")).strip()
            if not name or name.lower() in ("nan", "last"):
                continue
            if len(name) > 60:
                continue
            rows.append({
                "indicator": name,
                "last": parse_value(row.get("last")),
                "previous": parse_value(row.get("previous")),
                "unit": str(row.get("unit", "")).strip()[:30],
                "date": str(row.get("date", "")).strip()[:20],
            })
    if len(rows) < 10:
        raise ValueError(f"parse failed, only {len(rows)} rows")
    return pd.DataFrame(rows).drop_duplicates("indicator")

def fetch_fallback():
    return pd.DataFrame([{
        "indicator": n, "last": l, "previous": p, "unit": u, "date": d
    } for n, l, p, u, _, d in FALLBACK])

def fetch():
    try:
        df = fetch_live()
        print(f"[pipeline] live scrape OK: {len(df)} indicators")
    except Exception as e:
        msg = str(e).encode("ascii", "ignore").decode()[:200]
        print(f"[pipeline] live failed ({msg}), using fallback snapshot")
        df = fetch_fallback()
    df["fetched_at"] = datetime.now(timezone.utc).isoformat()
    df["source"] = URL
    return df

def save(df: pd.DataFrame):
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(CSV_LATEST, index=False)
    con = sqlite3.connect(DB_PATH)
    df.to_sql("indicators_latest", con, if_exists="replace", index=False)
    df.to_sql("indicators_history", con, if_exists="append", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS idx_hist ON indicators_history(indicator, fetched_at)")
    con.commit()
    con.close()
    print(f"[pipeline] saved {len(df)} rows -> {CSV_LATEST} + {DB_PATH}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="seconds between fetches, 0=once")
    args = ap.parse_args()
    while True:
        df = fetch()
        save(df)
        if not args.loop:
            break
        print(f"[pipeline] next fetch in {args.loop}s...")
        time.sleep(args.loop)

if __name__ == "__main__":
    main()
