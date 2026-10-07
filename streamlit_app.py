"""Point d'entree par defaut pour Streamlit Community Cloud.

L'application vit dans app.py (source unique, voir sa docstring).
Ce fichier ne fait que l'executer, pour que le chemin par defaut
`streamlit_app.py` fonctionne sans dupliquer le code.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
