import json
import os
import sys

import duckdb

con = duckdb.connect(os.path.join(os.path.dirname(__file__), "music_pipeline.duckdb"))

# Prüfen ob Tabelle überhaupt schon existiert
table_exists = con.execute("""
    SELECT COUNT(*) FROM information_schema.tables 
    WHERE table_name = 'raw_scrobbles'
""").fetchone()[0]

if table_exists:
    result = con.execute("SELECT MAX(played_at_ts) FROM raw_scrobbles").fetchone()
    last_ts = result[0]
    print(f"Letzter bekannter Timestamp: {last_ts} – hole nur neuere Scrobbles")
else:
    last_ts = None
    print("Tabelle existiert noch nicht – lade alles")

with open(os.path.join(os.path.dirname(__file__), "raw_scrobbles.json"), "r") as f:
    tracks = json.load(f)

if not tracks:
    print("Keine neuen Tracks")
    con.close()
    sys.exit()

if table_exists:
    con.execute("""
        INSERT INTO raw_scrobbles
        SELECT
            json->>'name'                        AS track_name,
            json->'artist'->>'#text'             AS artist_name,
            json->'artist'->>'mbid'              AS artist_mbid,
            json->'album'->>'#text'              AS album_name,
            json->'album'->>'mbid'               AS album_mbid,
            CAST(json->'date'->>'uts' AS BIGINT) AS played_at_ts,
            json->>'url'                         AS url
        FROM (SELECT UNNEST(?::JSON[]) AS json)
        WHERE CAST(json->'date'->>'uts' AS BIGINT) > ?
    """, [json.dumps(tracks), last_ts])
else:
    con.execute("""
        CREATE TABLE raw_scrobbles AS
        SELECT
            json->>'name'                        AS track_name,
            json->'artist'->>'#text'             AS artist_name,
            json->'artist'->>'mbid'              AS artist_mbid,
            json->'album'->>'#text'              AS album_name,
            json->'album'->>'mbid'               AS album_mbid,
            CAST(json->'date'->>'uts' AS BIGINT) AS played_at_ts,
            json->>'url'                         AS url
        FROM (SELECT UNNEST(?::JSON[]) AS json)
        WHERE json->'date'->>'uts' IS NOT NULL
    """, [json.dumps(tracks)])

count = con.execute("SELECT COUNT(*) FROM raw_scrobbles").fetchone()[0]
print(f"Fertig – Tabelle hat jetzt {count} Rows")

con.close()