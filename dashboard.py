import duckdb
import streamlit as st
import plotly.express as px
from datetime import date

con = duckdb.connect("/Users/jakubmarczak/python/music-etl-project/music_pipeline.duckdb")

st.title("Music Listening Dashboard")

# --- Sidebar Filter ---
st.sidebar.header("Filter")

min_date, max_date = con.execute("""
    SELECT MIN(played_date), MAX(played_date) FROM stg_scrobbles
""").fetchone()

date_range = st.sidebar.date_input(
    "Zeitraum",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

# Sicherheitscheck falls nur ein Datum ausgewählt
if len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

# --- Top Artists ---
st.header("Top Artists")
top_artists = con.execute(f"""
    SELECT artist_name, COUNT(*) AS play_count
    FROM stg_scrobbles
    WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY artist_name
    ORDER BY play_count DESC
    LIMIT 20
""").fetchdf()

fig = px.bar(
    top_artists,
    x="play_count",
    y="artist_name",
    orientation="h",
    labels={"play_count": "Plays", "artist_name": "Artist"}
)
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)

# --- Top Tracks ---
st.header("Top Tracks")
top_tracks = con.execute(f"""
    SELECT track_name, artist_name, COUNT(*) AS play_count
    FROM stg_scrobbles
    WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY track_name, artist_name
    ORDER BY play_count DESC
    LIMIT 20
""").fetchdf()
st.dataframe(top_tracks, use_container_width=True)

# --- Listening Activity ---
st.header("Höraktivität über Zeit")
activity = con.execute(f"""
    SELECT played_date, COUNT(*) AS play_count, DAYNAME(played_date) AS day_of_week
    FROM stg_scrobbles
    WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY played_date
    ORDER BY played_date
""").fetchdf()

fig2 = px.bar(
    activity,
    x="played_date",
    y="play_count",
    labels={"played_date": "Datum", "play_count": "Tracks gehört"},
    color="day_of_week"
)
st.plotly_chart(fig2, use_container_width=True)

con.close()