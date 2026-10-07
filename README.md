# Indicateurs economiques du Maroc

Application Streamlit (francais) : 73 indicateurs TradingEconomics,
traductions FR, tableau filtrable + historique.

## Lancer en local

```powershell
pip install -r requirements.txt
streamlit run app.py
python pipeline/fetch_te.py --loop 300   # optionnel : accumule l'historique
```

## Fichiers

| Fichier | Role |
|---|---|
| `app.py` | Application (source unique). `streamlit_app.py` ne fait que l'executer pour Streamlit Cloud |
| `pipeline/fetch_te.py` | Scrape TradingEconomics -> `data/morocco.db` + `data/morocco_latest.csv` |
| `pipeline/traduction.py` | Dictionnaires anglais -> francais (73 libelles + unites) |
| `data/morocco_latest.csv` | Snapshot embarque (demarrage instantane sur Cloud) |
| `.streamlit/config.toml` | Theme clair + barre d'outils minimale |

## Deploiement

Push sur `main` -> Streamlit Community Cloud redéploie seul
(repo `sabrallah/morocco-indicators`, fichier `streamlit_app.py`).
