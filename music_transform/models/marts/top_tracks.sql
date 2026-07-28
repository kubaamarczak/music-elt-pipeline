WITH scrobbles AS (
    SELECT * FROM {{ ref('stg_scrobbles') }}
)

SELECT
    track_name,
    artist_name,
    COUNT(*)                                    AS play_count,
    COUNT(DISTINCT played_date)                 AS days_listened,
    MIN(played_at)                              AS first_listened,
    MAX(played_at)                              AS last_listened
FROM scrobbles
GROUP BY track_name, artist_name
ORDER BY play_count DESC