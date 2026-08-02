# Music Listening Pipeline

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Airflow](https://img.shields.io/badge/Airflow-2.9-017CEE?logo=apacheairflow&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?logo=duckdb&logoColor=black)
![dbt](https://img.shields.io/badge/dbt-FF694B?logo=dbt&logoColor=white)
![Last.fm](https://img.shields.io/badge/Last.fm-D51007?logo=lastdotfm&logoColor=white)


A personal ELT pipeline that collects, transforms, and visualizes my music listening history from **Last.fm** and **Spotify**. Built as a hands-on data engineering learning project.

---

## Dashboard

<!-- Add screenshot here -->

---

## Architecture

```
Last.fm API (daily incremental)         Spotify Export (one-time historical)
        |                                           |
        v                                           v
   extract.py                               load_spotify.py
        |                                           |
        v                                           v
  raw_scrobbles                             raw_spotify
        |                                           |
        +-------------------+-----------------------+
                            |
                            v
                     dbt (Transformations)
                            |
              +-------------+-------------+
              |             |             |
              v             v             v
         stg_scrobbles  top_artists   top_tracks
                                         |
                                  listening_duration
                            |
                            v
                   Streamlit Dashboard
                            ^
                            |
                        Airflow
                  (daily at 08:00 UTC)
```

---

## Stack

| Layer | Tool | Purpose |
|---|---|---|
| Extract | Python + requests | Last.fm API pagination |
| Load | Python + DuckDB | Raw data storage |
| Transform | dbt + DuckDB | Staging & mart models |
| Orchestration | Apache Airflow | Daily scheduling via Docker |
| Visualization | Streamlit + Plotly | Interactive dashboard |

---

## Project Structure

```
music-etl-project/
├── extract.py               # Last.fm API extract (incremental)
├── load_to_duckdb.py        # Load raw scrobbles into DuckDB
├── load_spotify.py          # One-time Spotify history load
├── dashboard.py             # Streamlit dashboard
├── music_transform/         # dbt project
│   ├── models/
│   │   ├── staging/
│   │   │   ├── sources.yml
│   │   │   └── stg_scrobbles.sql   # Combines Last.fm + Spotify
│   │   └── marts/
│   │       ├── top_artists.sql
│   │       ├── top_tracks.sql
│   │       └── listening_duration.sql
│   └── dbt_project.yml
└── airflow/
    └── dags/
        └── music_pipeline_dag.py
```

---

## Setup

### Prerequisites

- Python 3.9+
- Docker Desktop
- A [Last.fm account](https://www.last.fm) with scrobbling enabled
- A Last.fm API key ([apply here](https://www.last.fm/api/account/create))

### 1. Clone & install dependencies

```bash
git clone https://github.com/kubaamarczak/music-etl-project
cd music-etl-project
python -m venv venv
source venv/bin/activate
pip install requests python-dotenv duckdb pandas dbt-core dbt-duckdb streamlit plotly
```

### 2. Configure environment

Create a `.env` file in the project root:

```
LASTFM_API_KEY=your_api_key_here
LASTFM_USERNAME=your_lastfm_username
```

### 3. Configure dbt

Create `~/.dbt/profiles.yml`:

```yaml
music_transform:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: /absolute/path/to/music_pipeline.duckdb
      schema: main
```

### 4. Run the pipeline manually

```bash
# Extract & load Last.fm data
python extract.py
python load_to_duckdb.py

# (Optional) Load Spotify history
# Place StreamingHistory_music_*.json files in spotify_history/
python load_spotify.py

# Run dbt transformations
cd music_transform
dbt run

# Start the dashboard
cd ..
streamlit run dashboard.py
```

### 5. Start Airflow (automated daily runs)

```bash
cd airflow
docker compose up -d
```

Then open [http://localhost:8080](http://localhost:8080) (login: `airflow` / `airflow`) and enable the `music_pipeline` DAG.

---

## dbt Models

### Staging
- **`stg_scrobbles`** — Combines and cleans raw Last.fm and Spotify data into a unified view. Filters out skipped tracks and now-playing entries without timestamps.

### Marts
- **`top_artists`** — Play count per artist, with first/last listen dates
- **`top_tracks`** — Play count per track
- **`listening_duration`** — Daily listening activity with day-of-week breakdown

---

## Key Concepts Practiced

- **Incremental loading** — Only fetching new scrobbles since the last run using Last.fm's `from` timestamp parameter
- **ELT pattern** — Raw data lands in DuckDB first, transformations happen after
- **dbt source testing** — `not_null` and `unique` tests on staging models
- **Multi-source integration** — Combining API data (Last.fm) with file exports (Spotify)
- **Orchestration** — Dockerized Airflow DAG with task dependencies
