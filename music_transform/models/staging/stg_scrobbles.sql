WITH lastfm AS (
    SELECT
        track_name,
        artist_name,
        album_name,
        played_at_ts,
        TO_TIMESTAMP(played_at_ts)                      AS played_at,
        DATE_TRUNC('day', TO_TIMESTAMP(played_at_ts))   AS played_date,
        NULL::BIGINT                                     AS ms_played,
        'lastfm'                                         AS source
    FROM {{ source('main', 'raw_scrobbles') }}
    WHERE played_at_ts IS NOT NULL
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
),

combined AS (
    SELECT * FROM lastfm
    UNION ALL
    SELECT * FROM spotify
)

SELECT * FROM combined