"""Application Streamlit en francais - Indicateurs du Maroc via TradingEconomics.
Lancement :
  streamlit run app.py
Pipeline :
  python pipeline/fetch_te.py --loop 300
"""
import sqlite3
import time
from pathlib import Path
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "morocco.db"
CSV_LATEST = BASE / "data" / "morocco_latest.csv"
SOURCE_URL = "https://tradingeconomics.com/morocco/indicators"

st.set_page_config(page_title="Indicateurs Maroc en direct", layout="wide")
st.title("Indicateurs du Maroc — Pipeline en continu")
st.caption(f"Source des donnees : {SOURCE_URL}")

@st.cache_data(ttl=10)
def load_latest():
    if DB_PATH.exists():
        con = sqlite3.connect(DB_PATH)
        try:
            df = pd.read_sql("SELECT * FROM indicators_latest", con)
        finally:
            con.close()
        if not df.empty:
            return df
    if CSV_LATEST.exists():
        return pd.read_csv(CSV_LATEST)
    from pipeline.fetch_te import fetch
    return fetch()

@st.cache_data(ttl=30)
def load_history(indicator: str, limit: int = 100):
    if not DB_PATH.exists():
        return pd.DataFrame()
    con = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql(
            "SELECT fetched_at, last FROM indicators_history WHERE indicator=? ORDER BY fetched_at DESC LIMIT ?",
            con, params=(indicator, limit),
        )
    finally:
        con.close()

# --- controles ---
col_a, col_b, col_c, col_d = st.columns(4)
with col_a:
    interval = st.selectbox("Intervalle d'actualisation (s)", [15, 60, 300, 900], index=1)
with col_b:
    auto = st.toggle("Actualisation auto", value=True)
with col_c:
    if st.button("Rafraichir"):
        st.rerun()
with col_d:
    if st.button("Mettre a jour", type="primary"):
        with st.spinner("Recuperation depuis TradingEconomics..."):
            from pipeline.fetch_te import fetch, save
            df_new = fetch()
            save(df_new)
            load_latest.clear()
            load_history.clear()
        st.success(f"{len(df_new)} indicateurs mis a jour")
        time.sleep(1)
        st.rerun()

try:
    df = load_latest()
except Exception:
    st.error("Pipeline vide / recuperation impossible.")
    st.info("Lancez : `python pipeline/fetch_te.py` puis relancez l'application.")
    st.stop()

if df.empty:
    st.warning("Aucune donnee. Lancez `python pipeline/fetch_te.py`.")
    st.stop()

# --- traduction EN -> FR pour l'affichage ---
from pipeline.traduction import traduire_indicateur, traduire_unite
df["indicateur_fr"] = df["indicator"].apply(traduire_indicateur)
df["unite_fr"] = df["unit"].apply(lambda u: traduire_unite(u) if pd.notna(u) else u)
FR_VERS_EN = dict(zip(df["indicateur_fr"], df["indicator"]))

# --- indicateurs cles ---
LIBELLES = {
    "GDP Annual Growth Rate": "Croissance du PIB",
    "Inflation Rate": "Inflation",
    "Unemployment Rate": "Chomage",
    "Interest Rate": "Taux d'interet",
}

def kpi(nom_te):
    r = df[df.indicator == nom_te]
    if r.empty:
        return None
    r = r.iloc[0]
    delta = (r["last"] - r["previous"]) if pd.notna(r.get("previous")) else None
    return r, delta

k1, k2, k3, k4 = st.columns(4)
for col, nom_te in zip([k1, k2, k3, k4], LIBELLES.keys()):
    with col:
        res = kpi(nom_te)
        if res is None:
            st.metric(LIBELLES[nom_te], "N/D")
        else:
            r, delta = res
            unite_fr = traduire_unite(r.get('unite_fr', r.get('unit','')))
            st.metric(
                f"{LIBELLES[nom_te]} ({unite_fr})",
                f"{r['last']}",
                delta=f"{round(delta,2)}" if delta is not None else None,
            )

# --- tableau en francais ---
st.subheader(f"Dernier releve — {len(df)} indicateurs")
q = st.text_input("Filtrer (ex : PIB, chomage, inflation)")
vue = df[df.indicateur_fr.str.contains(q, case=False, na=False)] if q else df
vue_aff = pd.DataFrame({
    "Indicateur": vue["indicateur_fr"],
    "Valeur": vue["last"],
    "Precedent": vue["previous"],
    "Unite": vue["unite_fr"],
    "Date": vue["date"],
}).sort_values("Indicateur")
st.dataframe(vue_aff, use_container_width=True, hide_index=True)

# --- historique ---
st.subheader("Historique (base SQLite)")
ind_fr = st.selectbox("Indicateur", sorted(df["indicateur_fr"].unique().tolist()))
ind_en = FR_VERS_EN.get(ind_fr, ind_fr)
hist = load_history(ind_en)
if not hist.empty:
    hist["fetched_at"] = pd.to_datetime(hist["fetched_at"])
    hist = hist.sort_values("fetched_at")
    st.line_chart(hist.set_index("fetched_at")["last"])
    st.caption(f"{len(hist)} points enregistres dans l'historique")
else:
    st.info("Pas encore d'historique — lancez la pipeline en boucle : `python pipeline/fetch_te.py --loop 300`")

st.caption(f"Derniere mise a jour : {df['fetched_at'].max() if 'fetched_at' in df else 'N/D'}")

if auto:
    time.sleep(interval)
    st.rerun()
