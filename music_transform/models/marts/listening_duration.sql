WITH scrobbles AS (
    SELECT * FROM {{ ref('stg_scrobbles') }}
)

SELECT
    played_date,
    COUNT(*)                                        AS play_count,
    DAYNAME(played_date)                            AS day_of_week,
    WEEKOFYEAR(played_date)                         AS week_number,
    DATE_TRUNC('week', played_date)                 AS week_start
FROM scrobbles
GROUP BY played_date
ORDER BY played_date DESC