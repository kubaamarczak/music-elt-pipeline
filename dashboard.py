import duckdb
import plotly.express as px
import streamlit as st
from dateutil.relativedelta import relativedelta
from huggingface_hub import hf_hub_download


@st.cache_resource(show_spinner="Loading database…", ttl="1h")
def get_connection():
    db_path = hf_hub_download(
        repo_id=st.secrets["HF_REPO_ID"],
        repo_type="dataset",
        filename="music_pipeline.duckdb",
        token=st.secrets["HF_TOKEN"],
    )
    return duckdb.connect(db_path, read_only=True)

con = get_connection()

st.set_page_config(layout="wide")

st.title("Music listening dashboard")

# --- Sidebar Filter ---
st.sidebar.header("Filter")

if st.sidebar.button("Reload data"):
    get_connection.clear()
    st.rerun()

min_date, max_date = con.execute("""
    SELECT MIN(played_date), MAX(played_date) FROM stg_scrobbles
""").fetchone()

date_range = st.sidebar.date_input(
    "Timespan",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

# Sicherheitscheck falls nur ein Datum ausgewählt
if len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

# --- KPIs ---
kpis = con.execute(f"""
    SELECT
        COUNT(*)                                                    AS total_plays,
        COUNT(DISTINCT artist_name)                                 AS unique_artists,
        COUNT(DISTINCT track_name)                                  AS unique_tracks,
        COUNT(DISTINCT played_date)                                 AS active_days,
        ROUND(COUNT(*) / COUNT(DISTINCT played_date), 1)            AS avg_per_day,
        ROUND(COUNT(*) / COUNT(DISTINCT DATE_TRUNC('month', played_at)), 1) AS avg_per_month
    FROM stg_scrobbles
    WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
""").fetchone()

total_plays, unique_artists, unique_tracks, active_days, avg_per_day, avg_per_month = kpis

with st.container(border=True): 

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Total plays", f"{total_plays:,}")
    col2.metric("Total artists", f"{unique_artists:,}")
    col3.metric("Total tracks", f"{unique_tracks:,}")
    col4.metric("Active days", f"{active_days:,}")
    col5.metric("⌀ Tracks / Day", f"{avg_per_day:,}")
    col6.metric("⌀ Tracks / Month", f"{avg_per_month:,}")

# --- Top Artists ---
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

# --- Top Tracks ---
top_tracks = con.execute(f"""
    SELECT 
        track_name  AS "Track",
        artist_name AS "Artist",
        COUNT(*)    AS "Plays"
    FROM stg_scrobbles
    WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY track_name, artist_name
    ORDER BY "Plays" DESC
    LIMIT 50
""").fetchdf()
top_tracks.index = top_tracks.index + 1

with st.container(border=True): 
    col1, col2 = st.columns(2)
    with col1:
        st.header("Top artists")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.header("Top tracks")

        track_period = st.radio(
            "Time range",
            ["Last week", "Last month", "Last year", "Selected time range"],
            index=3,
            horizontal=True,
            label_visibility="collapsed",
        )
 
        if track_period == "Last week":
            track_start_date = max(min_date, max_date - relativedelta(weeks=1))
            track_end_date = max_date
        elif track_period == "Last month":
            track_start_date = max(min_date, max_date - relativedelta(months=1))
            track_end_date = max_date
        elif track_period == "Last year":
            track_start_date = max(min_date, max_date - relativedelta(years=1))
            track_end_date = max_date
        else:
            track_start_date, track_end_date = start_date, end_date

        st.dataframe(top_tracks, use_container_width=True)

# --- Listening Activity ---
with st.container(border=True): 
    st.header("Listening activity")
    chart_type = st.radio(
        "Diagram type",
        ["Bar chart", "Line chart"],
        horizontal=True
    )

    activity = con.execute(f"""
        SELECT played_date, COUNT(*) AS play_count, DAYNAME(played_date) AS "Day"
        FROM stg_scrobbles
        WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY played_date
        ORDER BY played_date
    """).fetchdf()

    if chart_type == "Bar chart":
        fig = px.bar(
            activity,
            x="played_date",
            y="play_count",
            labels={"played_date": "Date", "play_count": "Played tracks"},
            color="Day",
            category_orders={"Day": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
        )
    else:
        fig = px.line(
            activity,
            x="played_date",
            y="play_count",
            labels={"played_date": "Date", "play_count": "Played tracks"},
            markers=False
        )
        import plotly.graph_objects as go

        fig.add_trace(go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker={"color": "rgba(0,0,0,0)"},  # unsichtbar
            showlegend=True,
            name=" "  # leerer Name
        ))
    st.plotly_chart(fig, use_container_width=True)

# --- Heatmap: Wochentag × Uhrzeit ---
with st.container(border=True): 
    st.header("When do you listen to music?")

    heatmap_data = con.execute(f"""
        SELECT 
            DAYNAME(played_at)                    AS day_of_week,
            DATEPART('hour', played_at)           AS hour_of_day,
            COUNT(*)                              AS play_count
        FROM stg_scrobbles
        WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY day_of_week, hour_of_day
        ORDER BY hour_of_day
    """).fetchdf()

    # Pivot: Zeilen = Wochentage, Spalten = Stunden
    heatmap_pivot = heatmap_data.pivot_table(
        index="day_of_week",
        columns="hour_of_day",
        values="play_count",
        fill_value=0
    )

    # Wochentage in richtiger Reihenfolge
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    heatmap_pivot = heatmap_pivot.reindex(
        [d for d in day_order if d in heatmap_pivot.index]
    )

    fig3 = px.imshow(
        heatmap_pivot,
        labels={"x": "Time", "y": "Day", "color": "Plays"},
        color_continuous_scale=["#0f1117", "#131386", "#3b3bd7", "#2979ff", "#64b5f6"],
        aspect="equal"
    )
    fig3.update_xaxes(
        tickvals=list(range(24)),
        ticktext=[f"{h:02d}:00" for h in range(24)]
    )
    st.plotly_chart(fig3, use_container_width=True)

# --- Artist Popularität über Zeit ---
with st.container(border=True): 
    st.header("Artist popularity over time")

    # Top N Artists auswählen
    top_n = st.slider("Amount of artists", min_value=3, max_value=15, value=5)

    # Top Artists im gewählten Zeitraum bestimmen
    top_artists_list = con.execute(f"""
        SELECT artist_name
        FROM stg_scrobbles
        WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY artist_name
        ORDER BY COUNT(*) DESC
        LIMIT {top_n}
    """).fetchdf()["artist_name"].tolist()

    # Monatliche Plays pro Artist
    placeholders = ','.join(['?' for _ in top_artists_list])
    artist_trend = con.execute(f"""
        SELECT
            DATE_TRUNC('month', played_at)  AS month,
            artist_name,
            COUNT(*)                         AS play_count
        FROM stg_scrobbles
        WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
        AND artist_name IN ({placeholders})
        GROUP BY month, artist_name
        ORDER BY month
    """, top_artists_list).fetchdf()

    fig4 = px.line(
        artist_trend,
        x="month",
        y="play_count",
        color="artist_name",
        labels={
            "month": "Month",
            "play_count": "Plays",
            "artist_name": "Artist"
        },
        markers=False
    )
    st.plotly_chart(fig4, use_container_width=True)

# --- Bar Chart Race ---
with st.container(border=True): 
    st.header("Top artists over time")

    top_n_race = st.slider("Amount of artists", min_value=3, max_value=10, value=5)

    # Monatliche kumulierte Plays pro Artist
    race_data = con.execute(f"""
        WITH monthly AS (
            SELECT
                DATE_TRUNC('month', played_at)  AS month,
                artist_name,
                COUNT(*)                         AS play_count
            FROM stg_scrobbles
            WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY month, artist_name
        ),
        -- Kreuzprodukt: jeder Artist × jeden Monat
        all_months AS (
            SELECT DISTINCT month FROM monthly
        ),
        all_artists AS (
            SELECT DISTINCT artist_name FROM monthly
        ),
        cross_joined AS (
            SELECT m.month, a.artist_name
            FROM all_months m CROSS JOIN all_artists a
        ),
        filled AS (
            SELECT
                c.month,
                c.artist_name,
                COALESCE(m.play_count, 0) AS play_count
            FROM cross_joined c
            LEFT JOIN monthly m
                ON c.month = m.month AND c.artist_name = m.artist_name
        ),
        cumulative AS (
            SELECT
                month,
                artist_name,
                SUM(play_count) OVER (
                    PARTITION BY artist_name
                    ORDER BY month
                ) AS cumulative_plays
            FROM filled
        )
        SELECT * FROM cumulative
        ORDER BY month, cumulative_plays DESC
    """).fetchdf()

    # Top N Artists insgesamt bestimmen
    top_artists_race = race_data.groupby("artist_name")["cumulative_plays"].max() \
        .nlargest(top_n_race).index.tolist()

    race_data = race_data[race_data["artist_name"].isin(top_artists_race)]

    # Frames pro Monat bauen
    months = sorted(race_data["month"].unique())
    frames = []

    for month in months:
        frame_data = race_data[race_data["month"] == month] \
            .sort_values("cumulative_plays", ascending=True)
    
        frames.append({
            "data": [{
                "type": "bar",
                "orientation": "h",
                "x": frame_data["cumulative_plays"].tolist(),
                "y": frame_data["artist_name"].tolist(),
                "marker": {"color": "#2979ff"}
            }],
            "name": str(month)[:7],
            "layout": {
                "title": {"text": f"Cumulative plays – {str(month)[:7]}"}
            }
        })

    import plotly.graph_objects as go

    max_plays = race_data["cumulative_plays"].max()

    fig5 = go.Figure(
        data=frames[0]["data"],
        layout=go.Layout(
            title=f"Cumulative plays – {str(months[0])[:7]}",
            xaxis={"title": "Cumulative plays", "range": [0, max_plays * 1.15]},
            yaxis={"title": "Artist"},
            height=400,
            updatemenus=[{
                "type": "buttons",
                "showactive": False,
                "buttons": [
                    {
                        "label": "▶",
                        "method": "animate",
                        "args": [None, {
                            "frame": {"duration": 800, "redraw": True},
                            "fromcurrent": True,
                            "transition": {"duration": 600}
                        }]
                    },
                    {
                        "label": "⏸",
                        "method": "animate",
                        "args": [[None], {
                            "frame": {"duration": 0},
                            "mode": "immediate"
                        }]
                    }
                ]
            }],
            sliders=[{
                "steps": [
                    {
                        "method": "animate",
                        "args": [[f["name"]], {"frame": {"duration": 800}, "mode": "immediate"}],
                        "label": f["name"]
                    }
                    for f in frames
                ],
                "currentvalue": {"prefix": "Month: "}
            }]
        ),
        frames=[go.Frame(data=f["data"], name=f["name"], layout=f["layout"]) for f in frames]
    )

    st.plotly_chart(fig5, use_container_width=True)