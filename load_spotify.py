import json
import os

import duckdb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
con = duckdb.connect(os.path.join(BASE_DIR, "music_pipeline.duckdb"))

# Alle 4 Dateien laden
spotify_files = [
    "StreamingHistory_music_0.json",
    "StreamingHistory_music_1.json",
    "StreamingHistory_music_2.json",
    "StreamingHistory_music_3.json",
]

all_tracks = []
for filename in spotify_files:
    path = os.path.join(BASE_DIR, "spotify_history", filename)
    with open(path, "r") as f:
        tracks = json.load(f)
        all_tracks.extend(tracks)
        print(f"{filename}: {len(tracks)} Tracks geladen")

print(f"\nInsgesamt: {len(all_tracks)} Tracks")

# Tabelle erstellen
con.execute("DROP TABLE IF EXISTS raw_spotify")
con.execute("""
    CREATE TABLE raw_spotify AS
    SELECT
        json->>'artistName'                             AS artist_name,
        json->>'trackName'                              AS track_name,
        CAST(json->>'msPlayed' AS BIGINT)               AS ms_played,
        CAST(json->>'msPlayed' AS BIGINT) / 1000        AS seconds_played,
        STRPTIME(json->>'endTime', '%Y-%m-%d %H:%M')    AS played_at,
        DATE_TRUNC('day', STRPTIME(json->>'endTime', '%Y-%m-%d %H:%M')) AS played_date
    FROM (SELECT UNNEST(?::JSON[]) AS json)
    WHERE json->>'artistName' != 'Unknown Artist'
      AND CAST(json->>'msPlayed' AS BIGINT) > 30000
""", [json.dumps(all_tracks)])

count = con.execute("SELECT COUNT(*) FROM raw_spotify").fetchone()[0]
print(f"Fertig – {count} Rows in raw_spotify")

con.close()