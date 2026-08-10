"""
Pusht die lokale music_pipeline.duckdb in ein privates Hugging Face
Dataset-Repo, damit dashboard.py sie auf Streamlit Cloud herunterladen kann.

Nach jedem lokalen ETL-Lauf (extract.py -> load_spotify.py/load_to_duckdb.py
-> dbt run) einfach ausführen:

    python upload_db_to_hf.py

Voraussetzungen:
    pip install huggingface_hub
    huggingface-cli login        # einmalig, oder HF_TOKEN als env var setzen

Env vars (oder .env, wird via python-dotenv geladen):
    HF_TOKEN    = dein Hugging Face Access Token (Write-Rechte, https://huggingface.co/settings/tokens)
    HF_REPO_ID  = z.B. "kubaamarczak/music-pipeline-db"
"""

import os

from dotenv import load_dotenv
from huggingface_hub import HfApi

load_dotenv()

DB_FILENAME = "music_pipeline.duckdb"
DB_PATH = os.path.join(os.path.dirname(__file__), DB_FILENAME)

HF_TOKEN = os.environ["HF_TOKEN"]
HF_REPO_ID = os.environ["HF_REPO_ID"]

api = HfApi(token=HF_TOKEN)

# Legt das Dataset-Repo beim ersten Mal privat an, falls es noch nicht existiert
api.create_repo(
    repo_id=HF_REPO_ID,
    repo_type="dataset",
    private=True,
    exist_ok=True,
)

api.upload_file(
    path_or_fileobj=DB_PATH,
    path_in_repo=DB_FILENAME,
    repo_id=HF_REPO_ID,
    repo_type="dataset",
)

print(f"Hochgeladen: {DB_FILENAME} -> {HF_REPO_ID}")
