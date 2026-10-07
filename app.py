"""Indicateurs du Maroc - application Streamlit en francais.
Donnees : TradingEconomics (pipeline) - affichage 100% francais.
Lancement : streamlit run app.py
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

st.set_page_config(
    page_title="Indicateurs du Maroc",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- style moderne et clair ---
st.markdown(
    """
    <style>
    .main { background-color: #f6f8fb; }
    .block-container { padding-top: 1.2rem; max-width: 1200px; }
    h1 { font-size: 1.9rem !important; font-weight: 700 !important; color: #0f2a44 !important; }
    .sous-titre { color: #5b6b7c; font-size: 0.95rem; margin-top: -0.6rem; }
    .badge { display: inline-block; background: #e8eef6; color: #0f2a44;
              border-radius: 999px; padding: 0.2rem 0.7rem; font-size: 0.8rem; margin-right: 0.4rem; }
    [data-testid="stMetric"] { background: #ffffff; border: 1px solid #e3e9f1;
        border-radius: 14px; padding: 0.9rem 1rem; box-shadow: 0 1px 3px rgba(15,42,68,0.06); }
    [data-testid="stMetricLabel"] { color: #5b6b7c !important; font-size: 0.82rem !important; }
    [data-testid="stMetricValue"] { color: #0f2a44 !important; }
    section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e3e9f1; }
    .stDataFrame { background: #ffffff; border-radius: 14px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Indicateurs economiques du Maroc")
st.markdown(
    f"<div class='sous-titre'>Pipeline TradingEconomics vers Streamlit - donnees traduites en francais. "
    f"Source : <a href='{SOURCE_URL}' target='_blank'>tradingeconomics.com/morocco</a></div>",
    unsafe_allow_html=True,
)

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
def load_history(indicator: str, limit: int = 200):
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

# --- barre laterale : controles ---
with st.sidebar:
    st.header("Controles")
    if st.button("Mettre a jour", type="primary", use_container_width=True):
        with st.spinner("Recuperation depuis TradingEconomics..."):
            from pipeline.fetch_te import fetch, save
            df_new = fetch()
            save(df_new)
            load_latest.clear()
            load_history.clear()
        st.success(f"{len(df_new)} indicateurs mis a jour")
        time.sleep(1)
        st.rerun()
    if st.button("Rafraichir l'affichage", use_container_width=True):
        st.rerun()
    interval = st.selectbox("Intervalle d'actualisation (s)", [15, 60, 300, 900], index=1)
    auto = st.toggle("Actualisation auto", value=False)
    st.divider()
    st.caption("Astuce : laissez la pipeline tourner en boucle avec `python pipeline/fetch_te.py --loop 300` pour accumuler l'historique.")

try:
    df = load_latest()
except Exception:
    st.error("Pipeline vide / recuperation impossible.")
    st.info("Lancez : `python pipeline/fetch_te.py` puis relancez l'application.")
    st.stop()

if df.empty:
    st.warning("Aucune donnee. Lancez `python pipeline/fetch_te.py`.")
    st.stop()

from pipeline.traduction import traduire_indicateur, traduire_unite
df["indicateur_fr"] = df["indicator"].apply(traduire_indicateur)
df["unite_fr"] = df["unit"].apply(lambda u: traduire_unite(u) if pd.notna(u) else u)
FR_VERS_EN = dict(zip(df["indicateur_fr"], df["indicator"]))

maj = df["fetched_at"].max() if "fetched_at" in df else "N/D"
st.markdown(
    f"<span class='badge'>{len(df)} indicateurs</span>"
    f"<span class='badge'>Derniere mise a jour : {maj}</span>",
    unsafe_allow_html=True,
)

# --- cartes KPI ---
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
        with st.container(border=True):
            res = kpi(nom_te)
            if res is None:
                st.metric(LIBELLES[nom_te], "N/D")
            else:
                r, delta = res
                unite = traduire_unite(r.get("unite_fr", r.get("unit", "")))
                st.metric(
                    f"{LIBELLES[nom_te]} ({unite})",
                    f"{r['last']}",
                    delta=f"{round(delta, 2)}" if delta is not None else None,
                )
                st.caption(f"Date : {r.get('date', 'N/D')}")

onglets = st.tabs(["Tableau", "Historique", "A propos"])

with onglets[0]:
    q = st.text_input("Filtrer", placeholder="Ex : PIB, chomage, inflation")
    vue = df[df.indicateur_fr.str.contains(q, case=False, na=False)] if q else df
    vue_aff = pd.DataFrame({
        "Indicateur": vue["indicateur_fr"],
        "Valeur": vue["last"],
        "Precedent": vue["previous"],
        "Unite": vue["unite_fr"],
        "Date": vue["date"],
    }).sort_values("Indicateur")
    st.dataframe(vue_aff, use_container_width=True, hide_index=True)
    st.caption(f"{len(vue_aff)} lignes affichees.")

with onglets[1]:
    col_g, col_d = st.columns([1, 2])
    with col_g:
        ind_fr = st.selectbox("Indicateur", sorted(df["indicateur_fr"].unique().tolist()))
        ind_en = FR_VERS_EN.get(ind_fr, ind_fr)
        ligne = df[df["indicator"] == ind_en].iloc[0] if (df["indicator"] == ind_en).any() else None
        if ligne is not None:
            st.metric("Valeur", f"{ligne['last']} {traduire_unite(ligne.get('unit',''))}")
            st.metric("Precedent", f"{ligne.get('previous', 'N/D')}")
            st.caption(f"Date : {ligne.get('date', 'N/D')}")
    with col_d:
        hist = load_history(ind_en)
        if hist.empty:
            st.info("Pas encore d'historique. Lancez la pipeline en boucle : `python pipeline/fetch_te.py --loop 300`.")
        else:
            hist["fetched_at"] = pd.to_datetime(hist["fetched_at"])
            hist = hist.sort_values("fetched_at")
            st.line_chart(hist.set_index("fetched_at")["last"], use_container_width=True)
            st.caption(f"{len(hist)} points enregistres.")

with onglets[2]:
    st.markdown(
        "- **Source** : TradingEconomics Maroc, scrapee par `pipeline/fetch_te.py` vers SQLite/CSV.\n"
        "- **Traduction** : `pipeline/traduction.py` (73 indicateurs + unites en francais).\n"
        "- **Streaming** : bouton Mettre a jour, boucle `--loop`, actualisation auto."
    )

if auto:
    time.sleep(interval)
    st.rerun()
