"""Indicateurs economiques du Maroc.

Application Streamlit (francais) alimentee par un pipeline qui scrape les
tableaux de TradingEconomics vers SQLite/CSV, avec libelles traduits.

Structure du repo :
  app.py                  -> cette application (code source unique)
  streamlit_app.py        -> simple point d'entree exige par Streamlit Cloud
  pipeline/fetch_te.py    -> extraction + stockage SQLite/CSV
  pipeline/traduction.py  -> dictionnaires anglais -> francais
  data/morocco_latest.csv -> snapshot embarque (demarrage instantane sur Cloud)
  .streamlit/config.toml  -> theme + barre d'outils minimale

Lancement local :
  pip install -r requirements.txt
  streamlit run app.py                 # ou : streamlit run streamlit_app.py
  python pipeline/fetch_te.py --loop 300   # optionnel : accumule l'historique

Patterns Streamlit suivis (https://docs.streamlit.io) :
  mise en page   : st.sidebar, st.tabs, st.columns(gap=...), st.container(border=True)
  tableau        : st.dataframe(width, hide_index, column_order, column_config,
                   on_select + selection_mode) avec retour de selection
  donnees        : @st.cache_data(ttl=...) pour SQLite/CSV
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from st_keyup import st_keyup  # filtrage a chaque frappe (sinon text_input)
except ImportError:  # pragma: no cover - repli si composant absent
    st_keyup = None

from pipeline.traduction import traduire_indicateur, traduire_unite

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "morocco.db"
CSV_SNAPSHOT = BASE / "data" / "morocco_latest.csv"

# Libelles francais des 4 chiffres cles (cles = noms anglais sources).
CHIFFRES_CLES = {
    "GDP Annual Growth Rate": "Croissance du PIB",
    "Inflation Rate": "Inflation",
    "Unemployment Rate": "Chomage",
    "Interest Rate": "Taux d'interet",
}


# ----------------------------------------------------------------------------
# Couche donnees (mise en cache, cf. doc "Caching and state")
# ----------------------------------------------------------------------------
@st.cache_data(ttl=10)
def load_latest() -> pd.DataFrame:
    """Dernier releve : SQLite d'abord, sinon snapshot CSV, sinon scrape live."""
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as con:
            df = pd.read_sql("SELECT * FROM indicators_latest", con)
        if not df.empty:
            return df
    if CSV_SNAPSHOT.exists():
        return pd.read_csv(CSV_SNAPSHOT)
    from pipeline.fetch_te import fetch

    return fetch()


@st.cache_data(ttl=30)
def load_history(indicator: str, limit: int = 200) -> pd.DataFrame:
    """Historique d'un indicateur (nom anglais), vide si pas de SQLite."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT fetched_at, last FROM indicators_history "
            "WHERE indicator=? ORDER BY fetched_at DESC LIMIT ?",
            con,
            params=(indicator, limit),
        )


def franciser(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Ajoute les colonnes francaises + table de correspondance FR -> EN."""
    df = df.copy()
    df["indicateur_fr"] = df["indicator"].apply(traduire_indicateur)
    df["unite_fr"] = df["unit"].apply(lambda u: traduire_unite(u) if pd.notna(u) else u)
    return df, dict(zip(df["indicateur_fr"], df["indicator"]))


# ----------------------------------------------------------------------------
# Interface : sidebar, en-tete, KPI (doc "layouts and containers")
# ----------------------------------------------------------------------------
def render_sidebar() -> None:
    """Controles persistants dans la sidebar."""
    with st.sidebar:
        st.header("Controles")
        if st.button("Mettre a jour", type="primary", use_container_width=True):
            with st.spinner("Recuperation depuis TradingEconomics..."):
                from pipeline.fetch_te import fetch_with_status, save

                df_new, direct_ok, detail = fetch_with_status()
                save(df_new)
                load_latest.clear()
                load_history.clear()
            if direct_ok:
                st.session_state["avis_maj"] = ("ok", f"{len(df_new)} indicateurs mis a jour")
            else:
                st.session_state["avis_maj"] = (
                    "alerte",
                    "TradingEconomics a bloque la recuperation en direct. "
                    f"Releve de secours affiche ({len(df_new)} indicateurs). "
                    f"Detail : {detail or 'site injoignable'}",
                )
            st.rerun()
        if st.button("Rafraichir l'affichage", use_container_width=True):
            load_latest.clear()
            st.rerun()


def render_header(df: pd.DataFrame) -> None:
    """Titre + 2 compteurs (indicateurs suivis, derniere mise a jour)."""
    with st.container():
        st.title("Indicateurs economiques du Maroc")
        maj = df["fetched_at"].max() if "fetched_at" in df else "N/D"
        c1, c2 = st.columns(2, gap="small")
        c1.metric("Indicateurs suivis", f"{len(df)}")
        c2.metric("Derniere mise a jour", str(maj)[:16])


def render_kpi_cards(df: pd.DataFrame) -> None:
    """4 cartes KPI avec variation vs releve precedent."""

    def lookup(nom_en: str):
        lignes = df[df.indicator == nom_en]
        if lignes.empty:
            return None
        ligne = lignes.iloc[0]
        delta = (
            ligne["last"] - ligne["previous"]
            if pd.notna(ligne.get("previous"))
            else None
        )
        return ligne, delta

    with st.container():
        st.subheader("Chiffres cles")
        colonnes = st.columns(len(CHIFFRES_CLES), gap="medium")
        for col, nom_en in zip(colonnes, CHIFFRES_CLES):
            with col:
                with st.container(border=True):
                    res = lookup(nom_en)
                    if res is None:
                        st.metric(CHIFFRES_CLES[nom_en], "N/D")
                        continue
                    ligne, delta = res
                    unite = traduire_unite(ligne.get("unite_fr", ligne.get("unit", "")))
                    st.metric(
                        f"{CHIFFRES_CLES[nom_en]} ({unite})",
                        f"{ligne['last']}",
                        delta=f"{round(delta, 2)}" if delta is not None else None,
                    )
                    st.caption(f"Date : {ligne.get('date', 'N/D')}")


# ----------------------------------------------------------------------------
# Interface : onglets Tableau / Historique
# ----------------------------------------------------------------------------
def render_table(df: pd.DataFrame):
    """Tableau filtrable et selectionnable (doc st.dataframe + column_config).

    Retourne (tableau affiche, evenement de selection) pour l'onglet Historique.
    """
    with st.container():
        if st_keyup is not None:
            saisie = st_keyup(
                "Filtrer",
                placeholder="Ex : PIB, chomage, inflation",
                debounce=300,
                key="filtre_live",
            )
        else:
            saisie = st.text_input("Filtrer", placeholder="Ex : PIB, chomage, inflation")
        recherche = (saisie or "").strip()
        vue = (
            df[df.indicateur_fr.str.contains(recherche, case=False, na=False, regex=False)]
            if recherche
            else df
        )
        tableau = pd.DataFrame(
            {
                "Indicateur": vue["indicateur_fr"],
                "Valeur": vue["last"],
                "Precedent": vue["previous"],
                "Unite": vue["unite_fr"],
                "Date": vue["date"],
            }
        ).sort_values("Indicateur")
        event = st.dataframe(
            tableau,
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
        st.caption(
            f"{len(tableau)} lignes. Cliquez une ligne pour l'envoyer vers l'onglet Historique."
        )
        return tableau, event


def selected_indicator(df: pd.DataFrame, tableau: pd.DataFrame, event) -> str:
    """Nom francais preselectionne : ligne cliquee d'abord, sinon 1er choix."""
    try:
        lignes = event.selection.get("rows", []) if event is not None else []
        if lignes:
            candidat = tableau.iloc[lignes[0]]["Indicateur"]
            if candidat in df["indicateur_fr"].tolist():
                return candidat
    except Exception:
        pass
    return sorted(df["indicateur_fr"].unique().tolist())[0]


def render_history(df: pd.DataFrame, fr_vers_en: dict, tableau: pd.DataFrame, event) -> None:
    """Courbe d'historique (si SQLite) + variations dernier vs precedent (toujours).

    Doc graphiques : st.line_chart / st.bar_chart avec donnees tidy
    (colonnes x / y explicites) et width="stretch".
    """
    with st.container():
        st.subheader("Historique")
        presel = selected_indicator(df, tableau, event)
        choix = st.selectbox(
            "Indicateur",
            sorted(df["indicateur_fr"].unique().tolist()),
            index=sorted(df["indicateur_fr"].unique().tolist()).index(presel),
        )
        hist = load_history(fr_vers_en.get(choix, choix))
        if hist.empty:
            st.info(
                "Pas encore de courbe : cliquez « Mettre a jour » au moins 2 fois "
                "(ou `python pipeline/fetch_te.py --loop 300` en local) pour accumuler des points."
            )
        else:
            courbe = hist.assign(fetched_at=pd.to_datetime(hist["fetched_at"])).sort_values(
                "fetched_at"
            )
            st.line_chart(courbe, x="fetched_at", y="last", width="stretch")
            st.caption(f"{len(courbe)} points enregistres pour « {choix} ».")

        st.divider()
        st.subheader("Variations (dernier releve vs precedent)")
        variations = df.dropna(subset=["last", "previous"]).copy()
        variations["variation"] = variations["last"] - variations["previous"]
        top = variations.reindex(
            variations["variation"].abs().sort_values(ascending=False).index
        ).head(10)
        st.bar_chart(top, x="indicateur_fr", y="variation", width="stretch")
        st.caption("Top 10 des plus fortes variations absolues du dernier releve.")


# ----------------------------------------------------------------------------
# Point d'entree
# ----------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Indicateurs du Maroc",
        page_icon=":chart_with_upwards_trend:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_sidebar()

    try:
        df = load_latest()
    except Exception:
        st.error("Pipeline vide / recuperation impossible.")
        st.info("Lancez : `python pipeline/fetch_te.py` puis relancez l'application.")
        st.stop()
    if df.empty:
        st.warning("Aucune donnee. Lancez `python pipeline/fetch_te.py`.")
        st.stop()

    df, fr_vers_en = franciser(df)

    avis = st.session_state.pop("avis_maj", None)
    if avis:
        nature, message = avis
        if nature == "ok":
            st.success(message)
        else:
            st.warning(message)

    render_header(df)
    render_kpi_cards(df)

    onglet_tableau, onglet_histo = st.tabs(["Tableau", "Historique"])
    with onglet_tableau:
        tableau, event = render_table(df)
    with onglet_histo:
        render_history(df, fr_vers_en, tableau, event)


main()
