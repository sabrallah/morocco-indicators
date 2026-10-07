"""Extraction des indicateurs du Maroc depuis TradingEconomics vers SQLite/CSV.

Source : https://tradingeconomics.com/morocco/indicators
Sorties : data/morocco_latest.csv + data/morocco.db
          (tables `indicators_latest` ecrasee, `indicators_history` cumulee)

Utilisation :
  python pipeline/fetch_te.py              # un seul passage
  python pipeline/fetch_te.py --loop 300   # repete toutes les 300 s
"""
import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    # Console Windows (cp1252) : evite les crashs sur caracteres speciaux.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd
import requests

URL = "https://tradingeconomics.com/morocco/indicators"
HEADERS = {"User-Agent": "Mozilla/5.0 (Morocco-Streamlit-Project)"}

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DB_PATH = DATA_DIR / "morocco.db"
CSV_LATEST = DATA_DIR / "morocco_latest.csv"

# Mots-cles des tableaux d'indicateurs (filtre anti-faux-positifs de read_html).
MOTS_CLES = ["gdp", "rate", "inflation", "unemploy", "trade", "mad", "percent", "usd"]

# Releve de secours si le site bloque le scraping (valeurs du 2026-10-07).
# Noms en anglais comme le live : la traduction FR se fait dans l'app.
SECOURS = [
    ("Currency", 9.98, 9.96, "", "Oct/26"),
    ("Stock Market", 17132, 16893, "points", "Oct/26"),
    ("GDP Annual Growth Rate", 4, 4.6, "percent", "Jun/26"),
    ("Unemployment Rate", 9.5, 10.8, "percent", "Jun/26"),
    ("Inflation Rate", -0.3, -0.6, "percent", "Aug/26"),
    ("Interest Rate", 2.25, 2.25, "percent", "Sep/26"),
    ("Balance of Trade", -37920, -46315, "MAD Million", "Aug/26"),
    ("Current Account", -5028, -13390, "MAD Million", "Mar/26"),
    ("Current Account to GDP", -2.4, -1.6, "percent of GDP", "Dec/25"),
    ("Government Debt to GDP", 67.1, 67.7, "percent of GDP", "Dec/25"),
    ("Government Budget", -3.6, -3.9, "percent of GDP", "Dec/25"),
    ("Consumer Confidence", 60.1, 64.4, "points", "Jun/26"),
    ("GDP", 182, 161, "USD Billion", "Dec/25"),
    ("GDP per Capita", 3644, 3516, "USD", "Dec/25"),
    ("Tourist Arrivals", 19800000, 17411949, "", "Dec/25"),
    ("Foreign Exchange Reserves", 500065, 496761, "MAD Million", "Aug/26"),
    ("Minimum Wages", 3423, 3045, "MAD/Month", "Jan/26"),
    ("Youth Unemployment Rate", 22.9, 23.4, "percent", "Jun/26"),
    ("Food Inflation", -3.9, -3.7, "percent", "Aug/26"),
    ("Industrial Production", -4.5, -1.4, "percent", "Jun/26"),
]


def parse_nombre(valeur):
    """Convertit une cellule de tableau en float, None si illisible."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = re.sub(r"[^\d.\-]", "", str(valeur).strip().replace(",", ""))
    if texte in ("", "-", "."):
        return None
    try:
        return float(texte)
    except ValueError:
        return None


def fetch_live() -> pd.DataFrame:
    """Scrape live : toutes les tables d'indicateurs de la page."""
    reponse = requests.get(URL, headers=HEADERS, timeout=30)
    reponse.raise_for_status()
    reponse.encoding = "utf-8"
    import io

    lignes = []
    for table in pd.read_html(io.StringIO(reponse.text), flavor="lxml"):
        if table.shape[1] < 6 or table.shape[0] < 3:
            continue
        if not any(mot in str(table.to_string()).lower() for mot in MOTS_CLES):
            continue
        table = table.iloc[:, :7]
        table.columns = ["indicator", "last", "previous", "highest", "lowest", "unit", "date"]
        for _, rang in table.iterrows():
            nom = str(rang.get("indicator", "")).strip()
            if not nom or nom.lower() in ("nan", "last") or len(nom) > 60:
                continue
            lignes.append(
                {
                    "indicator": nom,
                    "last": parse_nombre(rang.get("last")),
                    "previous": parse_nombre(rang.get("previous")),
                    "unit": str(rang.get("unit", "")).strip()[:30],
                    "date": str(rang.get("date", "")).strip()[:20],
                }
            )
    if len(lignes) < 10:
        raise ValueError(f"extraction incomplete : {len(lignes)} lignes")
    return pd.DataFrame(lignes).drop_duplicates("indicator")


def fetch_secours() -> pd.DataFrame:
    """Releve fige utilise quand le site est injoignable."""
    return pd.DataFrame(
        [
            {"indicator": nom, "last": v, "previous": p, "unit": u, "date": d}
            for nom, v, p, u, d in SECOURS
        ]
    )


def fetch_with_status() -> tuple:
    """Comme fetch(), plus (direct_ok, detail). direct_ok=False = site bloque."""
    try:
        df = fetch_live()
        print(f"[pipeline] scrape direct OK : {len(df)} indicateurs")
        direct_ok, detail = True, ""
    except Exception as exc:
        detail = str(exc).encode("ascii", "ignore").decode()[:200]
        print(f"[pipeline] echec direct ({detail}), releve de secours")
        df, direct_ok = fetch_secours(), False
    df["fetched_at"] = datetime.now(timezone.utc).isoformat()
    df["source"] = URL
    return df, direct_ok, detail


def fetch() -> pd.DataFrame:
    """Tente le live, sinon le secours. Ajoute horodatage + source."""
    df, _, _ = fetch_with_status()
    return df


def save(df: pd.DataFrame) -> None:
    """Ecrit le CSV + SQLite (dernier releve + historique cumulatif)."""
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(CSV_LATEST, index=False)
    with sqlite3.connect(DB_PATH) as con:
        df.to_sql("indicators_latest", con, if_exists="replace", index=False)
        df.to_sql("indicators_history", con, if_exists="append", index=False)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_hist ON indicators_history(indicator, fetched_at)"
        )
    print(f"[pipeline] {len(df)} lignes -> {CSV_LATEST} + {DB_PATH}")


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--loop", type=int, default=0, help="secondes entre passages, 0 = une fois")
    intervalle = args.parse_args().loop
    while True:
        save(fetch())
        if not intervalle:
            break
        print(f"[pipeline] prochain passage dans {intervalle}s...")
        time.sleep(intervalle)


if __name__ == "__main__":
    main()
