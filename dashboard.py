import os

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "music_pipeline.duckdb")


@st.cache_resource(show_spinner="Loading database…", ttl="10m")
def get_connection():
    if os.path.exists(LOCAL_DB_PATH):
        return duckdb.connect(LOCAL_DB_PATH, read_only=True)

    from huggingface_hub import hf_hub_download

    db_path = hf_hub_download(
        repo_id=st.secrets["HF_REPO_ID"],
        repo_type="dataset",
        filename="music_pipeline.duckdb",
        token=st.secrets["HF_TOKEN"],
        force_download=True,
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
    "Time range", value=(min_date, max_date), min_value=min_date, max_value=max_date
)

if len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

# --- KPIs ---
kpis = con.execute(
    """
    SELECT
        COUNT(*)                                                                AS total_plays,
        COUNT(DISTINCT artist_key)                                              AS unique_artists,
        COUNT(DISTINCT (artist_key, LOWER(TRIM(track_name))))                   AS unique_tracks,
        COUNT(DISTINCT played_date)                                             AS active_days,
        ROUND(COUNT(*) / (CAST(? AS DATE) - CAST(? AS DATE) + 1), 1)            AS avg_per_day,
        ROUND(COUNT(*) / ((CAST(? AS DATE) - CAST(? AS DATE) + 1) / 30.44), 1)  AS avg_per_month
    FROM stg_scrobbles
    WHERE played_date BETWEEN ? AND ?
""",
    [end_date, start_date, end_date, start_date, start_date, end_date],
).fetchone()

total_plays, unique_artists, unique_tracks, active_days, avg_per_day, avg_per_month = (
    kpis
)

with st.container(border=True):
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Total plays", f"{total_plays:,}")
    col2.metric("Total artists", f"{unique_artists:,}")
    col3.metric("Total tracks", f"{unique_tracks:,}")
    col4.metric("Active days", f"{active_days:,}")
    col5.metric("⌀ Tracks / Day", f"{avg_per_day:,}")
    col6.metric("⌀ Tracks / Month", f"{avg_per_month:,}")

# --- Top artists ---
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
    labels={"play_count": "Plays", "artist_name": "Artist"},
)
fig.update_layout(yaxis={"categoryorder": "total ascending"})

# --- Top tracks / Top albums ---
with st.container(border=True):
    col1, col2 = st.columns(2)
    with col1:
        st.header("Top artists")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        header_placeholder = st.empty()

        view_type = st.radio(
            "",
            ["Top tracks", "Top albums"],
            horizontal=True,
            label_visibility="collapsed",
        )

        header_placeholder.header(view_type)

        if view_type == "Top tracks":
            data = con.execute(f"""
                SELECT 
                    track_name  AS "Track",
                    artist_name AS "Artist",
                    COUNT(*)    AS "Plays"
                FROM stg_scrobbles
                WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY track_name, artist_name
                ORDER BY "Plays" DESC
                LIMIT 20
            """).fetchdf()
            data.index = data.index + 1
            st.dataframe(data, use_container_width=True)

        else:
            st.caption("Album data recorded from 29/06/2026 onwards")
            data = con.execute(f"""
                SELECT 
                    album_name  AS "Album",
                    artist_name AS "Artist",
                    COUNT(*)    AS "Plays"
                FROM stg_scrobbles
                WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
                AND album_name IS NOT NULL
                AND source = 'lastfm'
                GROUP BY album_name, artist_name
                ORDER BY "Plays" DESC
                LIMIT 20
            """).fetchdf()
            data.index = data.index + 1
            st.dataframe(data, use_container_width=True)

# --- Listening activity ---
with st.container(border=True):
    st.header("Listening activity")

    activity = con.execute(
        """ 
        WITH calendar AS (
            SELECT CAST(d AS DATE) AS played_date
            FROM generate_series(CAST(? AS DATE) - INTERVAL 7 DAY,
                                CAST(? AS DATE),
                                INTERVAL 1 DAY) AS t(d)
        ),
        daily AS (
            SELECT played_date, COUNT(*) AS play_count
            FROM stg_scrobbles
            GROUP BY played_date
        ),
        filled AS (
            SELECT c.played_date,
                COALESCE(d.play_count, 0) AS play_count
            FROM calendar c
            LEFT JOIN daily d USING (played_date)
        )
        SELECT played_date,
           play_count,
           DAYNAME(played_date) AS "Day",
           LAG(play_count, 1) OVER (ORDER BY played_date) AS played_last_day,
           LAG(play_count, 7) OVER (ORDER BY played_date) AS played_last_week
        FROM filled
        QUALIFY played_date >= CAST(? AS DATE)
        ORDER BY played_date
    """,
        [start_date, end_date, start_date],
    ).fetchdf()

    played_last_day, played_last_week = activity[
        ["played_last_day", "played_last_week"]
    ].iloc[-1]

    with st.container(border=True):
        col1, col2 = st.columns(2)

        col1.metric("Total plays yesterday", f"{played_last_day:,}")
        col2.metric("Total plays last week same day", f"{played_last_week:,}")

    chart_type = st.radio(
        "Diagram type",
        ["Bar chart", "Line chart"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if chart_type == "Bar chart":
        fig = px.bar(
            activity,
            x="played_date",
            y="play_count",
            labels={"played_date": "Date", "play_count": "Played tracks"},
            color="Day",
            category_orders={
                "Day": [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ]
            },
        )
    else:
        fig = px.line(
            activity,
            x="played_date",
            y="play_count",
            labels={"played_date": "Date", "play_count": "Played tracks"},
            markers=False,
        )
        import plotly.graph_objects as go

        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker={"color": "rgba(0,0,0,0)"},  # invisible
                showlegend=True,
                name=" ",  # empty name
            )
        )
    st.plotly_chart(fig, use_container_width=True)

# --- Prediction: next 7 days ---
with st.container(border=True):
    st.header("Prediction: next 7 days")

    try:
        fc = con.execute("""
            SELECT * FROM forecast_daily
            WHERE run_date = (SELECT MAX(run_date) FROM forecast_daily)
            ORDER BY target_date
        """).fetchdf()
    except duckdb.CatalogException:  # handling missing table
        fc = pd.DataFrame()

    if fc.empty:
        st.info("No prediction available.")
    else:
        train_end = pd.Timestamp(fc["train_end"].iloc[0]).normalize()
        start = train_end - pd.Timedelta(weeks=8) + pd.Timedelta(days=1)

        hist = con.execute(
            """
            SELECT CAST(played_date AS DATE) AS d, COUNT(*) AS plays
            FROM stg_scrobbles
            WHERE CAST(played_date AS DATE) BETWEEN ? AND ?
            GROUP BY d
        """,
            [start.date(), train_end.date()],
        ).fetchdf()

        # days w/o plays are 0 plays
        days = pd.date_range(start, train_end, freq="D")
        hist["d"] = pd.to_datetime(hist["d"])
        hist = hist.set_index("d").reindex(days, fill_value=0)

        fc["target_date"] = pd.to_datetime(fc["target_date"])

        with st.container(border=True):
            first = fc.iloc[0]
            col1, col2 = st.columns(2)
            col1.metric(
                f"Expected plays for {first['target_date'].strftime('%d/%m/%Y')}",
                f"{first['mu']:.0f} Plays",
            )
            col2.metric(
                f"80-%-interval for {first['target_date'].strftime('%d/%m/%Y')}",
                f"{first['lo']:.0f} - {first['hi']:.0f} Plays",
            )

        fig = go.Figure()
        fig.add_trace(
            go.Bar(x=hist.index, y=hist["plays"], name="is", marker_color="#2979ff")
        )
        fig.add_trace(
            go.Scatter(
                x=fc["target_date"],
                y=fc["mu"],
                mode="markers",
                name="expected",
                marker={"color": "#ff9100", "size": 9},
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": (fc["hi"] - fc["mu"]).tolist(),
                    "arrayminus": (fc["mu"] - fc["lo"]).tolist(),
                    "color": "#ff9100",
                },
            )
        )
        fig.update_layout(
            xaxis_title="date",
            yaxis_title="plays",
            legend={"orientation": "h", "y": 1.1},
        )
        st.plotly_chart(fig, use_container_width=True)

        zero_rate = fc["zero_rate"].iloc[0]
        st.caption(
            f"Model: negative binomial w/ weekday-effect, trained on {int(fc['n_train'].iloc[0])} days "
            f"(Until {train_end.date()}). Whiskers show the 80-%-interval per day. "
            f"The interval is valid for days with play counts over 0. "
            f"At approx. {zero_rate:.0%} of the days no music is listened to."
        )

# --- Heatmap: Weekday × Hour ---
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

    # Pivot: Rows = Weekdays, Columns = Hours
    heatmap_pivot = heatmap_data.pivot_table(
        index="day_of_week", columns="hour_of_day", values="play_count", fill_value=0
    )

    day_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    heatmap_pivot = heatmap_pivot.reindex(
        index=day_order, columns=range(24), fill_value=0
    )

    fig3 = px.imshow(
        heatmap_pivot,
        labels={"x": "Time", "y": "Day", "color": "Plays"},
        color_continuous_scale=["#0f1117", "#131386", "#3b3bd7", "#2979ff", "#64b5f6"],
        aspect="equal",
    )
    fig3.update_xaxes(
        tickvals=list(range(24)), ticktext=[f"{h:02d}:00" for h in range(24)]
    )
    st.plotly_chart(fig3, use_container_width=True)

# --- Artist popularity over time ---
with st.container(border=True):
    st.header("Artist popularity over time")

    # Top N artists
    top_n = st.slider("Amount of artists", min_value=3, max_value=15, value=5)

    # Top artists in selected timeframe
    top_artists_list = (
        con.execute(f"""
        SELECT artist_name
        FROM stg_scrobbles
        WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY artist_name
        ORDER BY COUNT(*) DESC
        LIMIT {top_n}
    """)
        .fetchdf()["artist_name"]
        .tolist()
    )

    # Monthly plays per artist
    placeholders = ",".join(["?" for _ in top_artists_list])
    artist_trend = con.execute(
        f"""
        SELECT
            DATE_TRUNC('month', played_at)  AS month,
            artist_name,
            COUNT(*)                         AS play_count
        FROM stg_scrobbles
        WHERE played_date BETWEEN '{start_date}' AND '{end_date}'
        AND artist_name IN ({placeholders})
        GROUP BY month, artist_name
        ORDER BY month
    """,
        top_artists_list,
    ).fetchdf()

    fig4 = px.line(
        artist_trend,
        x="month",
        y="play_count",
        color="artist_name",
        labels={"month": "Month", "play_count": "Plays", "artist_name": "Artist"},
        markers=False,
    )
    st.plotly_chart(fig4, use_container_width=True)

# --- Bar Chart Race ---
with st.container(border=True):
    st.header("Top artists over time")

    top_n_race = st.slider("Amount of artists", min_value=3, max_value=10, value=5)

    # Monthly cumulated plays per artist
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

    # Top N artists in total
    top_artists_race = (
        race_data.groupby("artist_name")["cumulative_plays"]
        .max()
        .nlargest(top_n_race)
        .index.tolist()
    )

    race_data = race_data[race_data["artist_name"].isin(top_artists_race)]

    # Frames pro Monat bauen
    months = sorted(race_data["month"].unique())
    frames = []

    for month in months:
        frame_data = race_data[race_data["month"] == month].sort_values(
            "cumulative_plays", ascending=True
        )

        frames.append(
            {
                "data": [
                    {
                        "type": "bar",
                        "orientation": "h",
                        "x": frame_data["cumulative_plays"].tolist(),
                        "y": frame_data["artist_name"].tolist(),
                        "marker": {"color": "#2979ff"},
                    }
                ],
                "name": str(month)[:7],
                "layout": {"title": {"text": f"Cumulative plays – {str(month)[:7]}"}},
            }
        )

    max_plays = race_data["cumulative_plays"].max()

    fig5 = go.Figure(
        data=frames[0]["data"],
        layout=go.Layout(
            title=f"Cumulative plays – {str(months[0])[:7]}",
            xaxis={"title": "Cumulative plays", "range": [0, max_plays * 1.15]},
            yaxis={"title": "Artist"},
            height=400,
            updatemenus=[
                {
                    "type": "buttons",
                    "showactive": False,
                    "buttons": [
                        {
                            "label": "▶",
                            "method": "animate",
                            "args": [
                                None,
                                {
                                    "frame": {"duration": 800, "redraw": True},
                                    "fromcurrent": True,
                                    "transition": {"duration": 600},
                                },
                            ],
                        },
                        {
                            "label": "⏸",
                            "method": "animate",
                            "args": [
                                [None],
                                {"frame": {"duration": 0}, "mode": "immediate"},
                            ],
                        },
                    ],
                }
            ],
            sliders=[
                {
                    "steps": [
                        {
                            "method": "animate",
                            "args": [
                                [f["name"]],
                                {"frame": {"duration": 800}, "mode": "immediate"},
                            ],
                            "label": f["name"],
                        }
                        for f in frames
                    ],
                    "currentvalue": {"prefix": "Month: "},
                }
            ],
        ),
        frames=[
            go.Frame(data=f["data"], name=f["name"], layout=f["layout"]) for f in frames
        ],
    )

    st.plotly_chart(fig5, use_container_width=True)
