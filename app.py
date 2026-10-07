"""Indicateurs du Maroc - application Streamlit organisee (doc officielle).
Patterns doc : st.sidebar (controles persistants), st.tabs, st.columns(gap),
st.container(border=True), st.expander, st.dataframe(width/column_config/on_select),
theme via .streamlit/config.toml.
Donnees : TradingEconomics - affichage 100% francais.
"""
import sqlite3
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

# ---------- donnees ----------
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

# ---------- barre laterale : controles persistants (doc layouts) ----------
with st.sidebar:
    st.header("Controles")
    if st.button("Mettre a jour", type="primary", use_container_width=True):
        with st.spinner("Recuperation depuis TradingEconomics..."):
            from pipeline.fetch_te import fetch, save
            df_new = fetch()
            save(df_new)
            load_latest.clear()
            load_history.clear()
        st.toast(f"{len(df_new)} indicateurs mis a jour")
        st.rerun()
    if st.button("Rafraichir l'affichage", use_container_width=True):
        load_latest.clear()
        st.rerun()

# ---------- chargement + traduction ----------
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


def _nb_hist_points():
    if not DB_PATH.exists():
        return "0"
    try:
        con = sqlite3.connect(DB_PATH)
        try:
            return str(con.execute("SELECT COUNT(*) FROM indicators_history").fetchone()[0])
        finally:
            con.close()
    except Exception:
        return "N/D"

# ---------- en-tete ----------
with st.container():
    st.title("Indicateurs economiques du Maroc")
    st.caption(f"Source : {SOURCE_URL} - donnees traduites en francais")
    maj = df["fetched_at"].max() if "fetched_at" in df else "N/D"
    c1, c2, c3 = st.columns(3, gap="small")
    c1.metric("Indicateurs suivis", f"{len(df)}")
    c2.metric("Derniere mise a jour", str(maj)[:16])
    c3.metric("Points d'historique", _nb_hist_points())

# ---------- cartes KPI ----------
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

with st.container():
    st.subheader("Chiffres cles")
    k1, k2, k3, k4 = st.columns(4, gap="medium")
    for col, nom_te in zip([k1, k2, k3, k4], LIBELLES.keys()):
        with col:
            with st.container(border=True):
                res = kpi(nom_te)
                if res is None:
                    st.metric(LIBELLES[nom_te], "N/D")
                else:
                    r, delta = res
                    st.metric(
                        f"{LIBELLES[nom_te]} ({traduire_unite(r.get('unite_fr', r.get('unit', '')))})",
                        f"{r['last']}",
                        delta=f"{round(delta, 2)}" if delta is not None else None,
                    )
                    st.caption(f"Date : {r.get('date', 'N/D')}")

# ---------- onglets ----------
tab_tableau, tab_histo, tab_methode = st.tabs(["Tableau", "Historique", "Methode"])

with tab_tableau:
    with st.container():
        q = st.text_input("Filtrer", placeholder="Ex : PIB, chomage, inflation")
        vue = df[df.indicateur_fr.str.contains(q, case=False, na=False)] if q else df
        vue_aff = pd.DataFrame({
            "Indicateur": vue["indicateur_fr"],
            "Valeur": vue["last"],
            "Precedent": vue["previous"],
            "Unite": vue["unite_fr"],
            "Date": vue["date"],
        }).sort_values("Indicateur")
        event = st.dataframe(
            vue_aff,
            width="stretch",
            hide_index=True,
            column_order=("Indicateur", "Valeur", "Precedent", "Unite", "Date"),
            column_config={
                "Indicateur": st.column_config.TextColumn("Indicateur", width="large"),
                "Valeur": st.column_config.NumberColumn("Valeur", format="%.2f"),
                "Precedent": st.column_config.NumberColumn("Precedent", format="%.2f"),
                "Unite": st.column_config.TextColumn("Unite", width="medium"),
                "Date": st.column_config.TextColumn("Date", width="small"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="tableau",
        )
        st.caption(f"{len(vue_aff)} lignes. Cliquez une ligne pour l'envoyer vers l'onglet Historique.")

with tab_histo:
    with st.container():
        st.subheader("Historique")
        # priorite a la ligne selectionnee dans le tableau (doc dataframe selections)
        sel_fr = None
        try:
            rows = event.selection.get("rows", []) if event is not None else []
            if rows:
                sel_fr = vue_aff.iloc[rows[0]]["Indicateur"]
        except Exception:
            sel_fr = None
        choix = sel_fr if sel_fr in df["indicateur_fr"].tolist() else None
        ind_fr = st.selectbox(
            "Indicateur",
            sorted(df["indicateur_fr"].unique().tolist()),
            index=sorted(df["indicateur_fr"].unique().tolist()).index(choix) if choix else 0,
        )
        ind_en = FR_VERS_EN.get(ind_fr, ind_fr)
        hist = load_history(ind_en)
        if hist.empty:
            st.info("Pas encore d'historique. Lancez : `python pipeline/fetch_te.py --loop 300`.")
        else:
            hist["fetched_at"] = pd.to_datetime(hist["fetched_at"])
            hist = hist.sort_values("fetched_at")
            st.line_chart(hist.set_index("fetched_at")["last"], use_container_width=True)
            st.caption(f"{len(hist)} points enregistres pour « {ind_fr} ».")

with tab_methode:
    with st.expander("Pipeline et traduction", expanded=True):
        st.markdown(
            "- **Extraction** : `pipeline/fetch_te.py` lit les tableaux de la page TradingEconomics.\n"
            "- **Stockage** : `data/morocco.db` (`indicators_latest`, `indicators_history`) + CSV.\n"
            "- **Traduction** : `pipeline/traduction.py` (73 libelles + unites).\n"
            "- **Organisation UI** : sidebar, onglets, conteneurs a bordure, colonnes (doc officielle Streamlit)."
        )
