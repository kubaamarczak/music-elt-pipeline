{{ config(materialized='table') }}

WITH lastfm AS (
    SELECT
        track_name,
        artist_name,
        album_name,
        played_at_ts,
        TO_TIMESTAMP(played_at_ts) AT TIME ZONE 'Europe/Berlin'                     AS played_at,
        DATE_TRUNC('day', TO_TIMESTAMP(played_at_ts) AT TIME ZONE 'Europe/Berlin')  AS played_date,
        NULL::BIGINT                                                                AS ms_played,
        'lastfm'                                                                    AS source
    FROM {{ source('main', 'raw_scrobbles') }}
    WHERE played_at_ts IS NOT NULL
),

lastfm_start AS (
    SELECT MIN(played_at_ts) AS first_ts FROM lastfm
),

spotify AS (
    SELECT
        track_name,
        artist_name,
        NULL::VARCHAR                                    AS album_name,
        EPOCH(played_at)::BIGINT                        AS played_at_ts,
        played_at,
        played_date,
        ms_played,
        'spotify'                                        AS source
    FROM {{ source('main', 'raw_spotify') }}
    WHERE EPOCH(played_at)::BIGINT < (SELECT first_ts FROM lastfm_start)
),

combined AS (
    SELECT *,
           LOWER(TRIM(artist_name)) AS artist_key
    FROM (
        SELECT * FROM lastfm
        UNION ALL
        SELECT * FROM spotify
    )
),

display_names AS (
    -- häufigste Schreibweise pro Key; bei Gleichstand die alphabetisch erste
    SELECT artist_key, artist_name
    FROM combined
    GROUP BY artist_key, artist_name
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY artist_key
        ORDER BY COUNT(*) DESC, artist_name
    ) = 1
)

SELECT c.* EXCLUDE (artist_name), d.artist_name
FROM combined c
JOIN display_names d USING (artist_key)